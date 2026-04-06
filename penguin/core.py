"""
PenguinCore acts as the central nervous system for Penguin, orchestrating interactions between various subsystems.


Architecture:
    PenguinCore orchestrates interactions between specialized subsystems, delegating
    functionality rather than implementing it directly. Key delegations:

    - Engine: Multi-step reasoning loops, agent registry, MessageBus integration
    - ConversationManager: Message history, context, persistence
    - StreamingStateManager: Streaming state machine, chunk coalescing (penguin/llm/stream_handler.py)
    - EventBus: UI event delivery (penguin/cli/events.py)
    - AgentManager: Agent roster queries (penguin/agent/manager.py)
    - ToolManager: Tool registration and execution
    - ActionExecutor: Action parsing and routing
    - RunMode: Autonomous task execution

Key Features:
    - Modular architecture with clear separation of concerns
    - Streaming-first design with chunk coalescing
    - Event-driven UI updates via EventBus
    - Multi-agent support with Engine registry
    - Checkpoint/snapshot management for conversation state
    - Flexible model loading and switching

API Specification:

Factory & Initialization:
    @classmethod async create(model, provider, workspace_path, enable_cli, fast_startup) -> PenguinCore
        Factory method - preferred way to instantiate PenguinCore

Message Processing:
    async process_message(message, context, streaming) -> str
        Single-turn chat - process user message and return response

    async process(input_data, max_iterations, streaming, multi_step) -> Dict
        Multi-step processing with tool execution and action handling

    async get_response(streaming, stream_callback) -> Tuple[Dict, bool]
        Generate response using current conversation context

RunMode (Autonomous Execution):
    async start_run_mode(name, description, context, continuous, time_limit) -> None
        Start autonomous task execution mode

Agent Management:
    ensure_agent_conversation(agent_id, system_prompt) -> None
        Create or get agent conversation (replaces deprecated register_agent)

    get_agent_roster() -> List[Dict]
        List all agents with metadata (delegates to AgentManager)

    set_active_agent(agent_id) -> None
        Switch active agent context

Messaging (via Engine):
    async route_message(recipient_id, content, message_type) -> bool
    async send_to_agent(agent_id, content) -> bool
    async send_to_human(content, message_type) -> bool
    async human_reply(agent_id, content) -> bool

Model Management:
    async load_model(model_id) -> bool
        Switch to a different model

    list_available_models() -> List[Dict]
        Get available models from provider

Conversation Management:
    list_conversations(limit, offset) -> List[Dict]
    create_conversation() -> str
    delete_conversation(conversation_id) -> bool

Checkpoints:
    async create_checkpoint(name, description) -> Optional[str]
    async rollback_to_checkpoint(checkpoint_id) -> bool
    list_checkpoints(session_id, limit) -> List[Dict]

UI Events:
    async emit_ui_event(event_type, data) -> None
        Emit event to all EventBus subscribers

Properties:
    total_tokens_used -> int
    get_token_usage() -> Dict[str, Dict[str, int]]

Design Principles:
    - Thin coordinator: Core delegates to specialized modules
    - Single source of truth: Engine owns agent state, CM owns conversations
    - Event-driven UI: All UI updates via EventBus.emit()
    - Streaming-first: StreamingStateManager handles all streaming state

Example:
    core = await PenguinCore.create(model="gpt-5")
    response = await core.process_message("Hello!")
    await core.start_run_mode(name="coding_task")

See Also:
    - penguin/engine.py: Engine class for multi-step reasoning
    - penguin/llm/stream_handler.py: StreamingStateManager
    - penguin/cli/events.py: EventBus for UI events
    - penguin/agent/manager.py: AgentManager for roster queries
    - context/architecture/core-refactor-plan.md: Refactoring documentation
"""

import asyncio
import inspect
import logging
import time
import traceback
import os
from dataclasses import asdict, fields
from pathlib import Path
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    Iterable,
    List,
    Mapping,
    Optional,
    Sequence,
    Set,
    Tuple,
    Union,
)
import asyncio
import json
from datetime import datetime

from dotenv import load_dotenv  # type: ignore
from rich.console import Console  # type: ignore
from tenacity import (  # type: ignore
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from tqdm import tqdm

# Configuration
from penguin.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    TASK_COMPLETION_PHRASE,
    MAX_TASK_ITERATIONS,
    AgentModelSettings,
    AgentPersonaConfig,
    Config,
    _ensure_env_loaded,  # Lazy env loading for startup performance
)
from penguin.config import config as raw_config
from penguin.constants import DEFAULT_MAX_MESSAGES_PER_SESSION
from penguin._version import __version__ as PENGUIN_VERSION

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig, safe_context_window, fetch_model_specs
from penguin.llm.stream_handler import (
    StreamingStateManager,
    AgentStreamingStateManager,
    StreamingConfig,
)

MODEL_CONFIG_FIELD_NAMES = {field.name for field in fields(ModelConfig)}

# Project manager
from penguin.project.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
    normalize_directory,
)
from penguin.system.state import MessageCategory, Message

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt

# Workflow Prompt
from penguin.prompt_workflow import PENGUIN_WORKFLOW

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.callbacks import adapt_stream_callback
from penguin.utils.diagnostics import (
    diagnostics,
    enable_diagnostics,
    disable_diagnostics,
)
from penguin.llm.litellm_support import load_litellm_module
from penguin.utils.log_error import log_error
from penguin.utils.parser import (
    ActionExecutor,
    parse_action,
    parse_patch_file_payload,
    parse_patch_files_payload,
    parse_read_file_payload,
    parse_write_file_payload,
)
from penguin.utils.profiling import (
    profile_startup_phase,
    profile_operation,
    profiler,
    print_startup_report,
)

try:
    from penguin.system.message_bus import MessageBus, ProtocolMessage
    from penguin.telemetry.collector import ensure_telemetry
except Exception:  # pragma: no cover
    MessageBus = None  # type: ignore
    ProtocolMessage = None  # type: ignore

    def ensure_telemetry(_: Any):  # type: ignore[nested-alias]
        return None


# Add the EventHandler type for type hinting
EventHandler = Callable[[str, Dict[str, Any]], Union[Awaitable[None], None]]

if TYPE_CHECKING:
    from penguin.chat.cli import PenguinCLI

logger = logging.getLogger(__name__)
console = Console()


# ---------------------------------------------------------------------------
# PenguinCore
# ---------------------------------------------------------------------------
class PenguinCore:
    """
    Central coordinator for the Penguin AI assistant.

    Acts as an integration point between:
    - ConversationManager: Handles messages, context, and conversation state
    - ToolManager: Provides access to available tools and actions
    - ActionExecutor: Executes actions from LLM responses
    - ProjectManager: Manages projects and tasks

    This class focuses on coordination rather than direct implementation,
    delegating most functionality to specialized components.

    Attributes:
        conversation_manager (ConversationManager): Manages conversations and context
        tool_manager (ToolManager): Manages available tools
        action_executor (ActionExecutor): Executes actions from LLM responses
        project_manager (ProjectManager): Manages projects and tasks
        api_client (APIClient): Handles API communication
        config (Config): System configuration
        model_config (ModelConfig): Model-specific configuration
    """

    @classmethod
    async def create(
        cls,
        config: Optional[Config] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None,
        enable_cli: bool = False,
        show_progress: bool = True,  # what is this again?
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        fast_startup: bool = True,  # Default True for faster startup (defers memory indexing)
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        """
        Factory method for creating PenguinCore instance.
        Returns either PenguinCore alone or with CLI if enable_cli=True

        Args:
            fast_startup: If True (default), defer heavy operations like memory indexing until first use
        """
        # Fix HuggingFace tokenizers parallelism warning early, before any model loading
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

        pbar = None  # Initialize pbar to None
        # Track detailed timing for profiling
        import time
        from collections import defaultdict

        timings = defaultdict(float)
        step_start_time = time.time()
        overall_start_time = step_start_time

        def log_step_time(step_name: str):
            nonlocal step_start_time
            step_end_time = time.time()
            elapsed = step_end_time - step_start_time
            timings[step_name] = elapsed
            logger.info(f"PROFILING: {step_name} took {elapsed:.4f} seconds")
            step_start_time = step_end_time

        try:
            with profile_startup_phase("PenguinCore.create_total"):
                # Initialize progress bar only if show_progress is True
                steps = [
                    "Loading environment",
                    "Setting up logging",
                    "Loading configuration",
                    "Creating model config",
                    "Initializing API client",
                    "Creating tool manager",
                    "Creating core instance",
                ]
                if enable_cli:
                    steps.append("Initializing CLI")

                total_steps = len(steps)
                if show_progress and progress_callback is None:
                    # Fall back to tqdm console only if no external callback provided
                    pbar = tqdm(steps, desc="Initializing Penguin", unit="step")
                # Internal helper to advance external progress callback if supplied
                current_step_index = 0

                # Step 1: Load environment
                with profile_startup_phase("Load environment"):
                    logger.info("STARTUP: Loading environment variables")
                    if pbar:
                        pbar.set_description("Loading environment")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Loading environment"
                        )
                    # load_dotenv() is already invoked centrally in config.py at import time.
                    # Calling it again here is redundant and can subtly override earlier values.
                    # Intentionally no-op.
                    if pbar:
                        pbar.update(1)
                    log_step_time("Load environment")

                # Step 2: Initialize logging
                with profile_startup_phase("Setup logging"):
                    logger.info("STARTUP: Setting up logging configuration")
                    if pbar:
                        pbar.set_description("Setting up logging")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Setting up logging"
                        )
                    logging.basicConfig(level=logging.WARNING)
                    for logger_name in [
                        "httpx",
                        "sentence_transformers",
                        "LiteLLM",
                        "tools",
                        "llm",
                    ]:
                        logging.getLogger(logger_name).setLevel(logging.WARNING)
                    logging.getLogger("chat").setLevel(logging.DEBUG)
                    if pbar:
                        pbar.update(1)
                    log_step_time("Setup logging")

                # Load configuration
                with profile_startup_phase("Load configuration"):
                    logger.info("STARTUP: Loading and parsing configuration")
                    if pbar:
                        pbar.set_description("Loading configuration")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Loading configuration"
                        )
                    start_config_time = time.time()
                    config = config or Config.load_config()

                    # Use fast_startup from config if not explicitly set
                    if fast_startup is False and hasattr(config, "fast_startup"):
                        fast_startup = config.fast_startup

                    logger.info(
                        f"STARTUP: Config loaded in {time.time() - start_config_time:.4f}s"
                    )
                    if pbar:
                        pbar.update(1)
                    log_step_time("Load configuration")

                # Initialize model configuration
                with profile_startup_phase("Create model config"):
                    logger.info("STARTUP: Creating model configuration")
                    if pbar:
                        pbar.set_description("Creating model config")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Creating model config"
                        )
                    # Source of truth for runtime model settings is the live Config.model_config.
                    # Allow explicit overrides via function args for tests/CLI.
                    model_config = ModelConfig(
                        model=(
                            model
                            or getattr(config.model_config, "model", DEFAULT_MODEL)
                        ),
                        provider=(
                            provider
                            or getattr(
                                config.model_config, "provider", DEFAULT_PROVIDER
                            )
                        ),
                        api_base=(
                            getattr(config.model_config, "api_base", None)
                            or (
                                config.api.base_url
                                if hasattr(config, "api")
                                and hasattr(config.api, "base_url")
                                else None
                            )
                        ),
                        use_assistants_api=bool(
                            getattr(config.model_config, "use_assistants_api", False)
                        ),
                        client_preference=getattr(
                            config.model_config, "client_preference", "openrouter"
                        ),
                        streaming_enabled=bool(
                            getattr(config.model_config, "streaming_enabled", True)
                        ),
                        # Generation cap should be the configured model's value; do not substitute context window here
                        max_output_tokens=getattr(
                            config.model_config,
                            "max_output_tokens",
                            getattr(
                                config.model_config,
                                "max_output_tokens",
                                getattr(config.model_config, "max_tokens", None),
                            ),  # Prefer new name
                        ),
                        max_context_window_tokens=getattr(
                            config.model_config, "max_context_window_tokens", None
                        ),
                    )
                    logger.info(
                        f"STARTUP: Using model={model_config.model}, provider={model_config.provider}, client={model_config.client_preference}"
                    )
                    if pbar:
                        pbar.update(1)
                    log_step_time("Create model config")

                # Create API client
                with profile_startup_phase("Initialize API client"):
                    logger.info("STARTUP: Initializing API client")
                    if pbar:
                        pbar.set_description("Initializing API client")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Initializing API client"
                        )
                    # Ensure .env files are loaded before API client needs API keys
                    _ensure_env_loaded()
                    api_client_start = time.time()
                    api_client = APIClient(model_config=model_config)
                    api_client.set_system_prompt(SYSTEM_PROMPT)
                    logger.info(
                        f"STARTUP: API client initialized in {time.time() - api_client_start:.4f}s"
                    )
                    if pbar:
                        pbar.update(1)
                    log_step_time("Initialize API client")

                # Initialize tool manager
                with profile_startup_phase("Create tool manager"):
                    logger.info(
                        f"STARTUP: Creating tool manager (fast_startup={fast_startup})"
                    )
                    if pbar:
                        pbar.set_description("Creating tool manager")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Creating tool manager"
                        )
                    tool_manager_start = time.time()
                    print("DEBUG: Creating ToolManager in PenguinCore...")
                    print(
                        f"DEBUG: Passing config of type {type(config)} to ToolManager."
                    )
                    print(
                        f"DEBUG: Passing log_error of type {type(log_error)} to ToolManager."
                    )
                    print(f"DEBUG: Fast startup mode: {fast_startup}")
                    # Provide ToolManager with a deterministic dict derived from the live Config
                    try:
                        config_dict = (
                            config.to_dict() if hasattr(config, "to_dict") else {}
                        )
                    except Exception:
                        config_dict = {}
                    tool_manager = ToolManager(
                        config_dict, log_error, fast_startup=fast_startup
                    )
                    logger.info(
                        f"STARTUP: Tool manager created in {time.time() - tool_manager_start:.4f}s with {len(tool_manager.tools) if hasattr(tool_manager, 'tools') else 'unknown'} tools"
                    )
                    if pbar:
                        pbar.update(1)
                    log_step_time("Create tool manager")

                # Create core instance
                with profile_startup_phase("Create core instance"):
                    logger.info("STARTUP: Creating core instance")
                    if pbar:
                        pbar.set_description("Creating core instance")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(
                            current_step_index, total_steps, "Creating core instance"
                        )
                    core_start = time.time()
                    instance = cls(
                        config=config,
                        api_client=api_client,
                        tool_manager=tool_manager,
                        model_config=model_config,
                    )
                    logger.info(
                        f"STARTUP: Core instance created in {time.time() - core_start:.4f}s"
                    )
                    if pbar:
                        pbar.update(1)
                    log_step_time("Create core instance")

                if enable_cli:
                    with profile_startup_phase("Initialize CLI"):
                        logger.info("STARTUP: Initializing CLI")
                        if pbar:
                            pbar.set_description("Initializing CLI")
                        if progress_callback:
                            current_step_index += 1
                            progress_callback(
                                current_step_index, total_steps, "Initializing CLI"
                            )
                        cli_start = time.time()
                        from penguin.chat.cli import PenguinCLI

                        cli = PenguinCLI(instance)
                        logger.info(
                            f"STARTUP: CLI initialized in {time.time() - cli_start:.4f}s"
                        )
                        if pbar:
                            pbar.update(1)
                        log_step_time("Initialize CLI")

                if pbar:
                    pbar.close()
                # Ensure external progress finishes
                if progress_callback and current_step_index < total_steps:
                    progress_callback(
                        total_steps, total_steps, "Initialization complete"
                    )

                total_time = time.time() - overall_start_time
                logger.info(
                    f"STARTUP COMPLETE: Total initialization time: {total_time:.4f} seconds"
                )

                # Log summary of all timing measurements
                logger.info("STARTUP TIMING SUMMARY:")
                for step, duration in timings.items():
                    percentage = (duration / total_time) * 100
                    logger.info(f"  - {step}: {duration:.4f}s ({percentage:.1f}%)")

                # Print comprehensive profiling report if enabled
                if fast_startup:
                    logger.info(
                        "FAST STARTUP enabled - memory indexing deferred to first use"
                    )

                # Log tool manager stats
                tool_stats = tool_manager.get_startup_stats()
                logger.info(f"ToolManager startup stats: {tool_stats}")

                return instance if not enable_cli else (instance, cli)

        except Exception as e:
            error_time = time.time() - overall_start_time
            logger.error(f"STARTUP FAILED after {error_time:.4f}s: {str(e)}")
            if pbar:
                pbar.close()
            error_msg = f"Failed to initialize PenguinCore: {str(e)}"
            logger.error(error_msg)
            raise RuntimeError(error_msg) from e

    def __init__(
        self,
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        model_config: Optional[ModelConfig] = None,
        runtime_config: Optional["RuntimeConfig"] = None,
    ):
        """Initialize PenguinCore with required components."""
        self.config = config or Config.load_config()
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.model_config = model_config
        self._interrupted = False
        self.progress_callbacks = []
        self.token_callbacks = []
        self._active_contexts = set()  # Track active execution contexts

        # Initialize runtime configuration (for dynamic config changes)
        from penguin.config import RuntimeConfig

        if runtime_config is None:
            # Create from current config
            config_dict = config.to_dict() if hasattr(config, "to_dict") else {}
            self.runtime_config = RuntimeConfig(config_dict)
        else:
            self.runtime_config = runtime_config

        # Register tool_manager as observer if it exists
        if tool_manager and hasattr(tool_manager, "on_runtime_config_change"):
            self.runtime_config.register_observer(tool_manager.on_runtime_config_change)

        # Initialize unified event system
        from penguin.cli.events import EventBus, EventType

        self.event_bus = EventBus.get_sync()
        self.event_types = {e.value for e in EventType}

        # Telemetry collector
        ensure_telemetry(self)

        output_config = getattr(self.config, "output", None)
        self.show_tool_results = True
        if output_config and hasattr(output_config, "show_tool_results"):
            self.show_tool_results = bool(output_config.show_tool_results)
        else:
            try:
                raw_output_config = (
                    raw_config.get("output", {}) if isinstance(raw_config, dict) else {}
                )
                show_tool_value = raw_output_config.get("show_tool_results", True)
                if isinstance(show_tool_value, str):
                    self.show_tool_results = show_tool_value.strip().lower() in {
                        "1",
                        "true",
                        "yes",
                        "on",
                    }
                else:
                    self.show_tool_results = bool(show_tool_value)
            except Exception:
                self.show_tool_results = True

        # Set system prompt from import
        # Initialize prompt mode from config if available
        try:
            initial_mode = (
                str(raw_config.get("prompt", {}).get("mode", "direct")).strip().lower()
            )
        except Exception:
            initial_mode = "direct"
        self.prompt_mode: str = initial_mode or "direct"

        # Apply initial output style from config before building prompt
        try:
            from penguin.prompt.builder import set_output_formatting

            if output_config and getattr(output_config, "prompt_style", None):
                prompt_style = str(output_config.prompt_style).strip().lower()
            else:
                prompt_style = (
                    str(raw_config.get("output", {}).get("prompt_style", "steps_final"))
                    .strip()
                    .lower()
                )
            self.output_style = prompt_style or "steps_final"
            set_output_formatting(self.output_style or "steps_final")
        except Exception:
            # If anything fails, fall back silently
            self.output_style = "steps_final"

        # Derive system prompt from builder for the selected mode
        try:
            self.system_prompt = get_system_prompt(self.prompt_mode)
        except Exception:
            self.system_prompt = SYSTEM_PROMPT

        # Initialize streaming primitives immediately (before Engine/handlers can use them)
        self.current_stream = None
        self.stream_lock = asyncio.Lock()

        # AgentStreamingStateManager handles per-agent streaming state, coalescing, and event generation
        # This allows multiple agents to stream simultaneously without interference
        self._stream_manager = AgentStreamingStateManager()

        # OpenCode TUI adapter for SSE event translation
        from penguin.tui_adapter import PartEventAdapter

        self._tui_adapter = PartEventAdapter(
            self.event_bus,
            persist_callback=self._persist_opencode_event,
            emit_session_status_events=False,
        )
        self._tui_adapters: Dict[str, Any] = {}
        self._opencode_abort_sessions: set[str] = set()
        self._opencode_active_requests: Dict[str, int] = {}
        self._opencode_process_tasks: Dict[str, Set[asyncio.Task[Any]]] = {}

        # Subscribe to stream events and translate to OpenCode format
        self._subscribe_to_stream_events()

        # RunMode state for UI streaming bridges
        self._runmode_stream_callback: Optional[
            Callable[[str, str], Awaitable[None]]
        ] = None
        self._runmode_active: bool = False
        self.run_mode = None

        # Initialize project manager with workspace path from config
        from penguin.config import WORKSPACE_PATH

        self.project_manager = ProjectManager(workspace_path=WORKSPACE_PATH)

        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()

        # Initialize conversation manager (replaces conversation system)
        from penguin.config import WORKSPACE_PATH
        from penguin.system.checkpoint_manager import CheckpointConfig

        # Create checkpoint configuration
        checkpoint_config = CheckpointConfig(
            enabled=True,
            frequency=1,  # Checkpoint every message
            planes={"conversation": True, "tasks": False, "code": False},
            retention={"keep_all_hours": 24, "keep_every_nth": 10, "max_age_days": 30},
            max_auto_checkpoints=1000,  # TODO: review magic numbers and at least put them into constants.py or parametrize them via Config
        )

        self.conversation_manager = ConversationManager(
            model_config=model_config,
            api_client=api_client,
            workspace_path=WORKSPACE_PATH,
            system_prompt=self.system_prompt,
            max_messages_per_session=DEFAULT_MAX_MESSAGES_PER_SESSION,
            max_sessions_in_memory=20,
            auto_save_interval=60,
            checkpoint_config=checkpoint_config,
        )
        # Attach a back-reference so Engine (and other helpers) can emit UI events
        # and finalize streaming messages via the Core.  Without this the Engine
        # silently skips those steps which caused tool results to be lost and
        # streaming panels to merge into a single message in the CLI.
        self.conversation_manager.core = self  # type: ignore[attr-defined]

        self.action_executor = ActionExecutor(
            self.tool_manager,
            self.project_manager,
            self.conversation_manager,
            ui_event_callback=self.emit_ui_event,
        )
        self.current_runmode_status_summary: str = "RunMode idle."  # New attribute

        # ------------------- Engine Initialization -------------------
        try:
            from penguin.engine import (
                Engine,
                EngineSettings,
                TokenBudgetStop,
                WallClockStop,
            )  # type: ignore

            # Propagate the model's streaming preference into the Engine so that
            # multi-step run modes (RunMode → Engine.run_task) inherit the same
            # behaviour as interactive chat.  Without this, Engine defaults to
            # non-streaming which for some providers (e.g. OpenRouter → Gemini)
            # often returns an *empty* completion causing blank responses in
            # RunMode even though regular chat works fine.

            streaming_pref = True
            try:
                # ``model_config.streaming_enabled`` may be None; coerce to bool
                streaming_pref = bool(self.model_config.streaming_enabled)
            except Exception:
                # Fall back to True which is the safer default for providers
                streaming_pref = True

            engine_settings = EngineSettings(streaming_default=streaming_pref)
            default_stops = [TokenBudgetStop()]
            self.engine = Engine(
                engine_settings,
                self.conversation_manager,
                self.api_client,
                self.tool_manager,
                self.action_executor,
                stop_conditions=default_stops,
            )
            try:
                self.engine.coordinator = self.get_coordinator()
                self.engine.telemetry = getattr(self, "telemetry", None)
                # Setup MessageBus integration for inter-agent communication
                self.engine.setup_message_bus(ui_event_callback=self.emit_ui_event)
            except Exception as coord_err:  # pragma: no cover
                logger.debug(f"Coordinator unavailable during engine init: {coord_err}")
        except Exception as e:
            logger.warning(
                "Failed to initialize Engine layer (fallback to legacy core processing): %s",
                e,
                exc_info=True,
            )
            self.engine = None

        # State
        self.initialized = True
        logger.info("PenguinCore initialized successfully")

        # Ensure error log directory exists
        from penguin.config import WORKSPACE_PATH

        self.validate_path(Path(WORKSPACE_PATH))

        # Add an accumulated token counter
        self.accumulated_tokens = {"prompt": 0, "completion": 0, "total": 0}

        # Defer LiteLLM configuration until first use to avoid import overhead
        self._litellm_configured = False
        self._last_model_load_error: Optional[str] = None

    def _ensure_litellm_configured(self):
        """Configure LiteLLM on first use when the optional extra is installed."""
        if not self._litellm_configured:
            try:
                litellm = load_litellm_module("LiteLLM optional runtime")
                _logging = litellm._logging
                _logging._disable_debugging()
                litellm.set_verbose = False
                litellm.drop_params = False
                self._litellm_configured = True
            except Exception as e:
                logger.debug(
                    "LiteLLM optional runtime unavailable or not configured: %s", e
                )
                self._litellm_configured = True  # Don't try again

        # Streaming primitives are initialized in __init__ now
        self.current_runmode_status_summary: str = "RunMode idle."

        # Inject core reference into tool_manager for sub-agent tools
        if self.tool_manager and hasattr(self.tool_manager, "set_core"):
            self.tool_manager.set_core(self)

    # ------------------------------------------------------------------
    # Coordinator accessor (singleton per Core)
    # ------------------------------------------------------------------
    def get_coordinator(self):
        """Return a singleton MultiAgentCoordinator bound to this Core."""
        try:
            if (
                not hasattr(self, "_coordinator")
                or getattr(self, "_coordinator") is None
            ):
                # Use a relative import to avoid path issues in both repo and installed layouts
                from .multi.coordinator import MultiAgentCoordinator  # type: ignore

                self._coordinator = MultiAgentCoordinator(self)
            return self._coordinator
        except Exception as e:
            logger.error(f"Failed to get coordinator: {e}")
        raise

    # ------------------------------------------------------------------
    # Prompt mode control
    # ------------------------------------------------------------------
    def set_prompt_mode(self, mode: str) -> str:
        """Rebuild and set the system prompt using the prompt builder mode.

        Modes: direct, review, implement, test, bench_minimal, terse, explain
        """
        try:
            mode_normalized = str(mode).strip().lower()
            prompt = get_system_prompt(mode_normalized)
            self.system_prompt = prompt
            # Replace on the active conversation as well
            try:
                if hasattr(self.conversation_manager, "set_system_prompt"):
                    self.conversation_manager.set_system_prompt(prompt)
            except Exception:
                pass
            self.prompt_mode = mode_normalized
            return f"Prompt mode set to '{mode_normalized}'."
        except Exception as e:
            msg = f"Failed to set prompt mode '{mode}': {e}"
            logger.warning(msg)
            return msg

    def get_prompt_mode(self) -> str:
        """Return current prompt mode name."""
        try:
            return getattr(self, "prompt_mode", "direct")
        except Exception:
            return "direct"

    # ------------------------------------------------------------------
    # Output style control
    # ------------------------------------------------------------------
    def set_output_style(self, style: str) -> str:
        """Set output formatting style and rebuild system prompt.

        Styles: steps_final, plain, json_guided
        """
        try:
            style_normalized = str(style).strip().lower()
            from penguin.prompt.builder import set_output_formatting

            set_output_formatting(style_normalized)
            self.output_style = style_normalized
            # Rebuild prompt with current mode
            try:
                if hasattr(self, "conversation_manager") and hasattr(
                    self.conversation_manager, "set_system_prompt"
                ):
                    prompt = get_system_prompt(self.prompt_mode)
                    self.system_prompt = prompt
                    self.conversation_manager.set_system_prompt(prompt)
                else:
                    self.system_prompt = get_system_prompt(self.prompt_mode)
            except Exception:
                pass
            return f"Output style set to '{style_normalized}'."
        except Exception as e:
            msg = f"Failed to set output style '{style}': {e}"
            logger.warning(msg)
            return msg

    def get_output_style(self) -> str:
        try:
            return getattr(self, "output_style", "steps_final")
        except Exception:
            return "steps_final"

    def validate_path(self, path: Path):
        """Validate and create a directory path if needed."""
        if not path.exists():
            path.mkdir(parents=True, exist_ok=True)
        if not os.access(path, os.W_OK):
            raise PermissionError(f"No write access to {path}")

    def register_progress_callback(
        self, callback: Callable[[int, int, Optional[str]], None]
    ) -> None:
        """Register a callback for progress updates during multi-step processing."""
        self.progress_callbacks.append(callback)

    def notify_progress(
        self, iteration: int, max_iterations: int, message: Optional[str] = None
    ) -> None:
        """Notify all registered callbacks about progress."""
        for callback in self.progress_callbacks:
            callback(iteration, max_iterations, message)

    def reset_context(self):
        """
        Reset conversation context and diagnostics.

        This method clears the current conversation state and resets all
        tools and diagnostics. Use this between different conversation
        sessions.
        """
        diagnostics.reset()
        self._interrupted = False

        # Reset conversation via manager
        self.conversation_manager.reset()

        # Reset tools
        # if self.tool_manager: # ToolManager does not have a reset method currently
        #     self.tool_manager.reset()
        # if self.action_executor: # ActionExecutor does not have a reset method currently
        #     self.action_executor.reset()

    # ------------------------------------------------------------------
    # Multi-agent helpers
    # ------------------------------------------------------------------

    def get_persona_catalog(self) -> List[Dict[str, Any]]:
        """Return configured personas as serialisable dictionaries."""

        personas = getattr(self.config, "agent_personas", {}) or {}
        catalog: List[Dict[str, Any]] = []
        for name, persona in personas.items():
            try:
                data = persona.to_dict()
            except Exception:
                data = {
                    "name": name,
                    "description": getattr(persona, "description", None),
                }
            data.setdefault("name", name)
            catalog.append(data)
        catalog.sort(key=lambda item: item.get("name", ""))
        return catalog

    def get_agent_roster(self) -> List[Dict[str, Any]]:
        """Return list of registered agents with their conversation metadata.

        Delegates to AgentManager for the actual implementation.
        """
        from penguin.agent.manager import AgentManager

        manager = AgentManager(
            conversation_manager=getattr(self, "conversation_manager", None),
            config=self.config,
            runtime_config=getattr(self, "runtime_config", None),
            is_paused_fn=self.is_agent_paused,
        )
        return manager.get_roster()

    def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return roster information for a single agent identifier.

        Delegates to AgentManager for the actual implementation.
        """
        from penguin.agent.manager import AgentManager

        manager = AgentManager(
            conversation_manager=getattr(self, "conversation_manager", None),
            config=self.config,
            runtime_config=getattr(self, "runtime_config", None),
            is_paused_fn=self.is_agent_paused,
        )
        return manager.get_profile(agent_id)

    def register_agent(self, *args, **kwargs) -> None:
        """REMOVED: Use ensure_agent_conversation() instead.

        This method has been removed as part of the core.py refactoring.
        See context/architecture/core-refactor-plan.md for migration guide.

        Migration:
            # Old:
            core.register_agent("analyzer", system_prompt="...", persona="code_analyzer")

            # New:
            core.ensure_agent_conversation("analyzer", system_prompt="...")
        """
        raise NotImplementedError(
            "register_agent() has been removed. Use ensure_agent_conversation() instead.\n"
            "See context/architecture/core-refactor-plan.md for migration guide.\n\n"
            "Quick migration:\n"
            "  OLD: core.register_agent(agent_id, system_prompt=..., persona=...)\n"
            "  NEW: core.ensure_agent_conversation(agent_id, system_prompt=...)"
        )

    def set_active_agent(self, agent_id: str) -> None:
        """Switch the active agent across ConversationManager and Engine."""
        # Switch CM
        try:
            self.conversation_manager.set_current_agent(agent_id)
        except Exception as e:
            logger.error(
                f"Failed to switch ConversationManager to agent '{agent_id}': {e}"
            )
            raise

        # Switch Engine default routing
        try:
            if getattr(self, "engine", None):
                self.engine.set_default_agent(agent_id)
        except Exception as e:
            logger.error(f"Failed to set Engine default agent '{agent_id}': {e}")
            raise

    # Thin wrappers for agent-scoped conversations
    def create_agent_conversation(self, agent_id: str) -> str:
        return self.conversation_manager.create_agent_conversation(agent_id)

    def list_all_conversations(self, *, limit_per_agent: int = 1000, offset: int = 0):
        return self.conversation_manager.list_all_conversations(
            limit_per_agent=limit_per_agent, offset=offset
        )

    def load_agent_conversation(
        self, agent_id: str, conversation_id: str, *, activate: bool = True
    ) -> bool:
        return self.conversation_manager.load_agent_conversation(
            agent_id, conversation_id, activate=activate
        )

    def delete_agent_conversation(self, agent_id: str, conversation_id: str) -> bool:
        return self.conversation_manager.delete_agent_conversation(
            agent_id, conversation_id
        )

    def delete_agent_conversation_guarded(
        self, agent_id: str, conversation_id: str, *, force: bool = False
    ) -> Dict[str, Any]:
        """Delete a conversation with safety checks for shared sessions.

        Returns a dict: {"success": bool, "warning": Optional[str]}
        """
        cm = self.conversation_manager
        warning = None

        try:
            # Determine if the target conversation is currently shared
            shared_agents = cm.agents_sharing_session(agent_id)
            if len(shared_agents) > 1:
                # Confirm this shared group is pointing at the same session id
                conv = cm.get_agent_conversation(agent_id)
                current_id = getattr(conv.session, "id", None)
                if current_id == conversation_id and not force:
                    warning = (
                        f"Conversation {conversation_id} is shared by agents {shared_agents}. "
                        f"Deletion aborted. Use force=True to delete anyway."
                    )
                    return {"success": False, "warning": warning}
        except Exception:
            # Best-effort safeguard only; continue with delete
            pass

        ok = cm.delete_agent_conversation(agent_id, conversation_id)
        return {"success": ok, "warning": None}

    def list_agents(self) -> List[str]:
        """Return all registered agent identifiers."""
        return self.conversation_manager.list_agents()

    def list_sub_agents(
        self, parent_agent_id: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """Return mapping of parent agents to sub-agents."""
        return self.conversation_manager.list_sub_agents(parent_agent_id)

    # ------------------------------
    # Sub-agent paused state helpers
    # ------------------------------
    def set_agent_paused(self, agent_id: str, paused: bool = True) -> None:
        """Mark an agent as paused/resumed using conversation metadata."""
        conv = self.conversation_manager.get_agent_conversation(agent_id)
        if conv and hasattr(conv, "session") and conv.session:
            conv.session.metadata["paused"] = bool(paused)
        # Also add system note for visibility
        try:
            note = "Paused" if paused else "Resumed"
            self.conversation_manager.add_system_note(
                agent_id,
                f"Agent state: {note}",
                metadata={"type": "agent_state", "paused": bool(paused)},
            )
        except Exception:
            pass

    def is_agent_paused(self, agent_id: str) -> bool:
        """Check if agent is paused via conversation metadata."""
        conv = self.conversation_manager.get_agent_conversation(agent_id)
        if conv and hasattr(conv, "session") and conv.session:
            return bool(conv.session.metadata.get("paused", False))
        return False

    # ------------------------------
    # Agent conversation management (NEW API)
    # ------------------------------
    def ensure_agent_conversation(
        self,
        agent_id: str,
        system_prompt: Optional[str] = None,
        **kwargs,  # Accept legacy params but ignore them
    ) -> None:
        """Ensure a conversation exists for an agent.

        This is the new simplified API that replaces register_agent().
        Only the conversation is persistent - all other agent state
        (model config, API clients) is derived at runtime.

        Args:
            agent_id: Unique identifier for the agent
            system_prompt: Optional system prompt for the agent
            **kwargs: Ignored (for backward compatibility with legacy callers)
        """
        conv = self.conversation_manager.get_agent_conversation(
            agent_id, create_if_missing=True
        )
        if system_prompt and conv:
            conv.set_system_prompt(system_prompt)

        # Register with Engine if available (just conversation, no API client)
        if getattr(self, "engine", None):
            try:
                # Create a minimal action executor for this agent
                action_executor = ActionExecutor(
                    self.tool_manager,
                    self.project_manager,
                    conv,
                    ui_event_callback=self.emit_ui_event,
                )
                self.engine.register_agent(
                    agent_id=agent_id,
                    conversation_manager=self.conversation_manager,
                    action_executor=action_executor,
                )
            except Exception as e:
                logger.debug(f"Engine registration for '{agent_id}' failed: {e}")

    def delete_agent_conversation(self, agent_id: str) -> bool:
        """Delete an agent's conversation.

        This is the new simplified API that replaces unregister_agent().

        Args:
            agent_id: Agent to remove

        Returns:
            True if agent was removed, False otherwise
        """
        if agent_id == "default":
            raise ValueError("Cannot delete the default agent")

        removed = self.conversation_manager.remove_agent(agent_id)

        if getattr(self, "engine", None):
            try:
                self.engine.unregister_agent(agent_id)
            except Exception as e:
                logger.debug(f"Engine unregister_agent failed for '{agent_id}': {e}")

        if self.conversation_manager.current_agent_id == agent_id:
            self.set_active_agent("default")

        return removed

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        system_prompt: Optional[str] = None,
        share_session: bool = True,
        share_context_window: bool = True,
        shared_context_window_max_tokens: Optional[int] = None,
        **kwargs,  # Accept but ignore legacy params
    ) -> None:
        """Create a sub-agent linked to a parent agent."""
        # Create sub-agent via conversation manager
        self.conversation_manager.create_sub_agent(
            agent_id,
            parent_agent_id=parent_agent_id,
            share_session=share_session,
            share_context_window=share_context_window,
            shared_context_window_max_tokens=shared_context_window_max_tokens,
        )
        # Ensure conversation exists
        self.ensure_agent_conversation(agent_id, system_prompt=system_prompt)

    async def publish_sub_agent_session_created(
        self,
        agent_id: str,
        *,
        parent_agent_id: Optional[str] = None,
        share_session: bool = False,
    ) -> Optional[Dict[str, Any]]:
        """Bind isolated sub-agent session directory and emit session.created."""
        if share_session:
            return None

        conversation_manager = getattr(self, "conversation_manager", None)
        if conversation_manager is None:
            return None

        conversation = conversation_manager.get_agent_conversation(agent_id)
        session = getattr(conversation, "session", None)
        session_id = getattr(session, "id", None)
        if not isinstance(session_id, str) or not session_id:
            return None

        resolved_directory = None
        metadata = getattr(session, "metadata", None)
        if isinstance(metadata, dict):
            existing = metadata.get("directory")
            if isinstance(existing, str) and existing.strip():
                resolved_directory = existing.strip()

        if not resolved_directory and parent_agent_id:
            try:
                parent_conv = conversation_manager.get_agent_conversation(
                    parent_agent_id
                )
                parent_session = getattr(parent_conv, "session", None)
                parent_metadata = getattr(parent_session, "metadata", None)
                if isinstance(parent_metadata, dict):
                    mapped = parent_metadata.get("directory")
                    if isinstance(mapped, str) and mapped.strip():
                        resolved_directory = mapped.strip()
                if not resolved_directory:
                    parent_session_id = getattr(parent_session, "id", None)
                    session_dirs = getattr(self, "_opencode_session_directories", None)
                    if isinstance(parent_session_id, str) and isinstance(
                        session_dirs, dict
                    ):
                        mapped = session_dirs.get(parent_session_id)
                        if isinstance(mapped, str) and mapped.strip():
                            resolved_directory = mapped.strip()
            except Exception:
                logger.debug(
                    "Failed to resolve parent directory for sub-agent '%s'",
                    agent_id,
                    exc_info=True,
                )

        if not resolved_directory:
            context = get_current_execution_context()
            if context and context.directory:
                resolved_directory = context.directory

        if not resolved_directory:
            runtime = getattr(self, "runtime_config", None)
            runtime_dir = getattr(runtime, "active_root", None) or getattr(
                runtime, "project_root", None
            )
            if isinstance(runtime_dir, str) and runtime_dir.strip():
                resolved_directory = runtime_dir.strip()

        if not resolved_directory:
            env_dir = os.getenv("PENGUIN_CWD")
            if isinstance(env_dir, str) and env_dir.strip():
                resolved_directory = env_dir.strip()

        if not resolved_directory:
            resolved_directory = os.getcwd()

        session_dirs = getattr(self, "_opencode_session_directories", None)
        if not isinstance(session_dirs, dict):
            session_dirs = {}
            self._opencode_session_directories = session_dirs
        session_dirs[session_id] = resolved_directory

        if not isinstance(metadata, dict):
            metadata = {}
            session.metadata = metadata
        if metadata.get("directory") != resolved_directory:
            metadata["directory"] = resolved_directory
            try:
                conversation._modified = True
                conversation.save()
            except Exception:
                logger.debug(
                    "Failed to persist sub-agent session directory for '%s'",
                    agent_id,
                    exc_info=True,
                )

        try:
            from penguin.web.services.session_view import get_session_info

            info = get_session_info(self, session_id)
        except Exception:
            logger.debug(
                "Failed to build session info for sub-agent '%s'",
                agent_id,
                exc_info=True,
            )
            return None

        if not isinstance(info, dict):
            return None

        emit = getattr(getattr(self, "event_bus", None), "emit", None)
        if callable(emit):
            await emit(
                "opencode_event",
                {
                    "type": "session.created",
                    "properties": {
                        "sessionID": session_id,
                        "info": info,
                    },
                },
            )
        return info

    def resolve_agent_execution_scope(
        self,
        agent_id: str,
        *,
        session_id: Optional[str] = None,
        directory: Optional[str] = None,
        agent_mode: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Resolve session-scoped execution context for an agent run."""
        resolved_session_id = session_id if isinstance(session_id, str) else None
        resolved_directory = directory if isinstance(directory, str) else None
        resolved_agent_mode = agent_mode if isinstance(agent_mode, str) else None

        conversation_manager = getattr(self, "conversation_manager", None)
        session = None
        if conversation_manager is not None:
            try:
                conversation = conversation_manager.get_agent_conversation(agent_id)
                session = getattr(conversation, "session", None)
            except Exception:
                logger.debug(
                    "Failed to resolve agent conversation for '%s'",
                    agent_id,
                    exc_info=True,
                )

        metadata = getattr(session, "metadata", None)
        if not resolved_session_id:
            candidate = getattr(session, "id", None)
            if isinstance(candidate, str) and candidate.strip():
                resolved_session_id = candidate.strip()

        if isinstance(metadata, dict):
            if not resolved_directory:
                candidate_directory = metadata.get("directory")
                if isinstance(candidate_directory, str) and candidate_directory.strip():
                    resolved_directory = candidate_directory.strip()
            if not resolved_agent_mode:
                candidate_mode = metadata.get(
                    "_opencode_agent_mode_v1"
                ) or metadata.get("agent_mode")
                if isinstance(candidate_mode, str) and candidate_mode.strip():
                    resolved_agent_mode = candidate_mode.strip().lower()

        if not resolved_directory and resolved_session_id:
            session_dirs = getattr(self, "_opencode_session_directories", None)
            if isinstance(session_dirs, dict):
                mapped = session_dirs.get(resolved_session_id)
                if isinstance(mapped, str) and mapped.strip():
                    resolved_directory = mapped.strip()

        inherited_context = get_current_execution_context()
        if not resolved_directory and inherited_context and inherited_context.directory:
            resolved_directory = inherited_context.directory
        if (
            not resolved_agent_mode
            and inherited_context
            and inherited_context.agent_mode
        ):
            resolved_agent_mode = inherited_context.agent_mode

        resolved_directory = (
            normalize_directory(resolved_directory) or resolved_directory
        )
        project_root = (
            inherited_context.project_root
            if inherited_context and inherited_context.project_root
            else resolved_directory
        )
        workspace_root = (
            inherited_context.workspace_root
            if inherited_context and inherited_context.workspace_root
            else resolved_directory
        )

        return {
            "session_id": resolved_session_id,
            "conversation_id": resolved_session_id,
            "directory": resolved_directory,
            "project_root": project_root,
            "workspace_root": workspace_root,
            "agent_mode": resolved_agent_mode,
        }

    async def run_agent_prompt_in_session(
        self,
        agent_id: str,
        prompt: str,
        *,
        session_id: Optional[str] = None,
        directory: Optional[str] = None,
        agent_mode: Optional[str] = None,
        streaming: Optional[bool] = None,
    ) -> Dict[str, Any]:
        """Run an agent prompt inside that agent's session-scoped execution context."""
        scope = self.resolve_agent_execution_scope(
            agent_id,
            session_id=session_id,
            directory=directory,
            agent_mode=agent_mode,
        )
        execution_context = ExecutionContext(
            session_id=scope.get("session_id"),
            conversation_id=scope.get("conversation_id"),
            agent_id=agent_id,
            agent_mode=scope.get("agent_mode"),
            directory=scope.get("directory"),
            project_root=scope.get("project_root"),
            workspace_root=scope.get("workspace_root"),
            request_id=f"subagent:{agent_id}:{scope.get('conversation_id') or 'unknown'}",
        )
        with execution_context_scope(execution_context):
            return await self.process(
                input_data={"text": prompt},
                conversation_id=scope.get("conversation_id"),
                agent_id=agent_id,
                streaming=streaming,
            )

    def unregister_agent(
        self, agent_id: str, *, preserve_conversation: bool = False
    ) -> bool:
        """Unregister an agent. Delegates to delete_agent_conversation()."""
        if preserve_conversation:
            # Just unregister from Engine, keep conversation
            if getattr(self, "engine", None):
                try:
                    self.engine.unregister_agent(agent_id)
                except Exception as e:
                    logger.debug(
                        f"Engine unregister_agent failed for '{agent_id}': {e}"
                    )
            return True
        return self.delete_agent_conversation(agent_id)

    # ------------------------------
    # Message routing via Engine
    # ------------------------------
    async def route_message(
        self,
        recipient_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Route a message via Engine's MessageBus integration."""
        if self.engine:
            return await self.engine.route_message(
                recipient_id,
                content,
                message_type=message_type,
                metadata=metadata,
                agent_id=agent_id,
                channel=channel,
            )
        logger.warning("Engine not available for message routing")
        return False

    async def send_to_agent(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a message to an agent via Engine."""
        if self.engine:
            return await self.engine.send_to_agent(
                agent_id,
                content,
                message_type=message_type,
                metadata=metadata,
                channel=channel,
            )
        return False

    async def send_to_human(
        self,
        content: Any,
        *,
        message_type: str = "status",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a message to the human (UI) via Engine."""
        if self.engine:
            return await self.engine.send_to_human(
                content,
                message_type=message_type,
                metadata=metadata,
                channel=channel,
            )
        return False

    async def human_reply(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a reply from human to an agent via Engine."""
        if self.engine:
            return await self.engine.human_reply(
                agent_id,
                content,
                message_type=message_type,
                metadata=metadata,
                channel=channel,
            )
        return False

    async def get_telemetry_summary(self) -> Dict[str, Any]:
        telemetry = getattr(self, "telemetry", None)
        if telemetry is None:
            return {}
        return await telemetry.snapshot()

    # ------------------------------------------------------------------
    # Diagnostics: Smoke test for agent wiring
    # ------------------------------------------------------------------
    def smoke_check_agents(self) -> Dict[str, Any]:
        """Return a diagnostic snapshot of agent wiring and context windows.

        Includes per-agent session, conversation object identity, context window
        limits and usage, and Engine registry presence.
        """
        cm = self.conversation_manager
        summary: Dict[str, Any] = {
            "active_agent": getattr(cm, "current_agent_id", "default"),
            "agents": [],
            "shared_conversations": [],
            "engine_registry": {},
        }

        # Build per-agent info and detect shared ConversationSystem groups
        conv_to_agents: Dict[int, list] = {}
        for aid, conv in getattr(cm, "agent_sessions", {}).items():
            try:
                session_id = getattr(conv.session, "id", None)
                cw = (
                    cm.agent_context_windows.get(aid)
                    if hasattr(cm, "agent_context_windows")
                    else getattr(cm, "context_window", None)
                )
                cw_usage = {}
                cw_max = None
                if cw and hasattr(cw, "get_token_usage"):
                    try:
                        u = cw.get_token_usage()
                        # Normalize usage fields
                        cw_usage = {
                            "total": u.get("total", u.get("current_total_tokens")),
                            "available": u.get("available", u.get("available_tokens")),
                        }
                        cw_max = u.get(
                            "max",
                            u.get("max_context_window_tokens", u.get("max_tokens")),
                        )  # max_context_window_tokens is the canonical key
                    except Exception:
                        pass
                # Record agent info
                summary["agents"].append(
                    {
                        "agent_id": aid,
                        "session_id": session_id,
                        "conversation_obj": id(conv),
                        "context_window_max": cw_max,
                        "context_window_usage": cw_usage,
                    }
                )
                conv_to_agents.setdefault(id(conv), []).append(aid)
            except Exception:
                continue

        # Shared conversation groups
        summary["shared_conversations"] = [
            {"conversation_obj": k, "agents": v}
            for k, v in conv_to_agents.items()
            if len(v) > 1
        ]

        # Engine registry presence
        try:
            engine_agents = (
                set(self.engine.list_agents())
                if getattr(self, "engine", None)
                else set()
            )
        except Exception:
            engine_agents = set()
        for a in [a.get("agent_id") for a in summary["agents"]]:
            summary["engine_registry"][a] = a in engine_agents

        return summary

    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used via conversation manager"""
        try:
            token_usage = self.conversation_manager.get_token_usage()
            return token_usage.get("total", 0)
        except Exception:
            return 0

    # ------------------------------------------------------------------
    # Streaming State Properties (delegate to AgentStreamingStateManager)
    # ------------------------------------------------------------------

    @property
    def streaming_active(self) -> bool:
        """Whether streaming is currently active for the default agent."""
        return self._stream_manager.is_active

    @property
    def streaming_content(self) -> str:
        """Accumulated assistant content from default agent's stream."""
        return self._stream_manager.content

    @property
    def streaming_reasoning_content(self) -> str:
        """Accumulated reasoning content from default agent's stream."""
        return self._stream_manager.reasoning_content

    @property
    def streaming_stream_id(self) -> Optional[str]:
        """Unique ID of the default agent's stream, or None if not streaming."""
        return self._stream_manager.stream_id

    # --- Agent-Specific Streaming Methods ---

    def is_agent_streaming(self, agent_id: str) -> bool:
        """Check if a specific agent is currently streaming.

        Args:
            agent_id: The agent identifier to check

        Returns:
            True if the agent is actively streaming
        """
        return self._stream_manager.is_agent_active(agent_id)

    def get_agent_streaming_content(self, agent_id: str) -> str:
        """Get accumulated streaming content for a specific agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Accumulated content string (empty if agent not found or not streaming)
        """
        return self._stream_manager.get_agent_content(agent_id)

    def get_agent_streaming_reasoning(self, agent_id: str) -> str:
        """Get accumulated reasoning content for a specific agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Accumulated reasoning content string
        """
        return self._stream_manager.get_agent_reasoning(agent_id)

    def get_active_streaming_agents(self) -> List[str]:
        """Get list of agent IDs that are currently streaming.

        Returns:
            List of agent IDs with active streams
        """
        return self._stream_manager.get_active_agents()

    def cleanup_agent_streaming(self, agent_id: str) -> None:
        """Clean up streaming state for a terminated agent.

        Args:
            agent_id: The agent identifier to clean up
        """
        self._stream_manager.cleanup_agent(agent_id)

    async def _emit_opencode_session_status(
        self,
        session_id: str,
        status_type: str,
        info: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Emit OpenCode session.status event for a session."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        if not sid:
            return

        properties: Dict[str, Any] = {
            "sessionID": sid,
            "status": {"type": status_type},
        }
        if info:
            properties["info"] = info

        await self.event_bus.emit(
            "opencode_event",
            {
                "type": "session.status",
                "properties": properties,
            },
        )

    async def abort_session(self, session_id: str) -> bool:
        """Abort active streaming/tool state for a session."""
        sid = session_id.strip() if isinstance(session_id, str) else ""
        if not sid:
            return False

        self._opencode_abort_sessions.add(sid)
        aborted = False

        adapter = self._get_tui_adapter(sid)
        adapter_abort = getattr(adapter, "abort", None)
        if callable(adapter_abort):
            try:
                adapter_aborted = await adapter_abort(
                    reason="Tool execution was interrupted"
                )
                aborted = bool(adapter_aborted) or aborted
            except Exception:
                logger.debug("Failed to abort active TUI parts", exc_info=True)

        tasks_map = getattr(self, "_opencode_process_tasks", None)
        if isinstance(tasks_map, dict):
            active_tasks = list(tasks_map.get(sid, set()))
            for task in active_tasks:
                if task.done():
                    continue
                task.cancel()
                aborted = True

        states = getattr(self, "_opencode_stream_states", None)
        state = states.get(sid) if isinstance(states, dict) else None
        if isinstance(state, dict):
            message_id = state.get("message_id")
            part_id = state.get("part_id")
            if (
                not callable(adapter_abort)
                and isinstance(message_id, str)
                and isinstance(part_id, str)
            ):
                try:
                    await adapter.on_stream_end(message_id, part_id)
                    aborted = True
                except Exception:
                    logger.debug(
                        "Failed to force-finalize aborted stream", exc_info=True
                    )
            state["active"] = False
            state["stream_id"] = None
            state["part_id"] = None

        tool_parts = getattr(self, "_opencode_tool_parts", None)
        if isinstance(tool_parts, dict):
            for key in [
                k for k in tool_parts if isinstance(k, str) and k.startswith(f"{sid}:")
            ]:
                tool_parts.pop(key, None)

        tool_info = getattr(self, "_opencode_tool_info", None)
        if isinstance(tool_info, dict):
            for key in [
                k for k in tool_info if isinstance(k, str) and k.startswith(f"{sid}:")
            ]:
                tool_info.pop(key, None)

        for scope in list(self._stream_manager.get_active_agents()):
            if scope != sid and not scope.startswith(f"{sid}:"):
                continue
            for event in self._stream_manager.abort(agent_id=scope):
                event_data = dict(event.data) if isinstance(event.data, dict) else {}
                event_data["session_id"] = sid
                event_data["conversation_id"] = sid
                await self.emit_ui_event(event.event_type, event_data)
                aborted = True

        await self._emit_opencode_session_status(sid, "idle")
        return aborted

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Get token usage via conversation manager"""
        try:
            if not self.conversation_manager:
                return {
                    "total": {"input": 0, "output": 0},
                    "session": {"input": 0, "output": 0},
                }

            usage = self.conversation_manager.get_token_usage()

            # Emit UI event for token update (only if event loop is running)
            try:
                token_event_data = usage.copy()
                # Only create task if we have a real emit_ui_event method (not a mock)
                if hasattr(self, "emit_ui_event") and not hasattr(
                    self.emit_ui_event, "_mock_name"
                ):
                    asyncio.create_task(
                        self.emit_ui_event("token_update", token_event_data)
                    )
            except (RuntimeError, AttributeError):
                # No event loop running or method is a mock, skip event emission
                pass

            return usage
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            return {
                "total": {"input": 0, "output": 0},
                "session": {"input": 0, "output": 0},
            }

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt for both core and API client."""
        self.system_prompt = prompt
        if self.api_client:
            self.api_client.set_system_prompt(prompt)
        self.conversation_manager.set_system_prompt(prompt)

    def set_llm_config(
        self,
        base_url: Optional[str] = None,
        link_user_id: Optional[str] = None,
        link_session_id: Optional[str] = None,
        link_agent_id: Optional[str] = None,
        link_workspace_id: Optional[str] = None,
        link_api_key: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Configure LLM endpoint and Link integration at runtime.

        This method is typically called by Link when starting a Penguin session
        to route LLM requests through Link's inference proxy for billing.

        Args:
            base_url: LLM API endpoint (e.g., "http://localhost:3001/api/v1")
            link_user_id: Link user ID for billing attribution
            link_session_id: Link session ID for tracking
            link_agent_id: Link agent ID for multi-agent scenarios
            link_workspace_id: Link workspace ID for org billing
            link_api_key: Link API key for production auth

        Returns:
            Dict with current LLM client status
        """
        from penguin.llm.client import LLMClient, LLMClientConfig, LinkConfig

        if not hasattr(self, "_llm_client") or self._llm_client is None:
            config = LLMClientConfig(
                base_url=base_url,
                link=LinkConfig(
                    user_id=link_user_id,
                    session_id=link_session_id,
                    agent_id=link_agent_id,
                    workspace_id=link_workspace_id,
                    api_key=link_api_key,
                ),
            )
            self._llm_client = LLMClient(self.model_config, config)
        else:
            self._llm_client.update_config(
                base_url=base_url,
                link_user_id=link_user_id,
                link_session_id=link_session_id,
                link_agent_id=link_agent_id,
                link_workspace_id=link_workspace_id,
                link_api_key=link_api_key,
            )

        return self._llm_client.get_status()

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        streaming: bool = False,
    ) -> str:
        """
        Process a message with optional conversation support.

        Args:
            message: The user message to process
            context: Optional additional context for processing
            conversation_id: Optional ID to continue an existing conversation
            agent_id: Optional agent identifier to scope the request
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses
        """
        try:
            # Resolve the active conversation manager for the agent (if provided)
            conversation_manager = self.conversation_manager
            if self.engine:
                try:
                    candidate_cm = self.engine.get_conversation_manager(agent_id)
                    if candidate_cm is not None:
                        conversation_manager = candidate_cm
                except Exception as engine_err:
                    logger.warning(
                        f"Engine conversation manager lookup failed for agent '{agent_id}': {engine_err}"
                    )
            elif agent_id:
                # Legacy fallback only: activate agent on shared manager when Engine is unavailable.
                try:
                    if hasattr(conversation_manager, "set_current_agent"):
                        conversation_manager.set_current_agent(agent_id)
                except Exception as agent_err:
                    logger.warning(
                        f"Failed to activate agent '{agent_id}' on ConversationManager: {agent_err}"
                    )

            # Add context if provided
            if context:
                for key, value in context.items():
                    conversation_manager.add_context(f"{key}: {value}")
            # Process through conversation manager (handles context files)
            return await conversation_manager.process_message(
                message=message,
                conversation_id=conversation_id,
                streaming=streaming,
                context_files=context_files,
            )

        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_message",
                    "message": message,
                },
            )
            return error_msg

    async def get_response(
        self,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        streaming: Optional[bool] = None,
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate a response using the conversation context and execute any actions.

        Args:
            current_iteration: Current iteration number for multi-step processing
            max_iterations: Maximum iterations for multi-step processing
            stream_callback: Optional callback function for handling streaming output chunks.
            streaming: Whether to use streaming mode for responses

        Returns:
            Tuple of (response data, exit continuation flag)
        """
        try:
            # Add iteration marker if in multi-step processing
            if current_iteration is not None and max_iterations is not None:
                self.conversation_manager.conversation.add_iteration_marker(
                    current_iteration, max_iterations
                )

            # Get formatted messages from conversation manager
            messages = self.conversation_manager.conversation.get_formatted_messages()

            # Maximum retry attempts for empty responses
            max_retries = 2
            retry_count = 0

            while retry_count <= max_retries:
                # Start new stream, PASSING both streaming flag and callback
                logger.debug(
                    f"Calling API directly (Streaming: {streaming}, Callback provided: {stream_callback is not None})"
                )

                assistant_response = None
                try:
                    logger.debug(
                        json.dumps(
                            self.conversation_manager.conversation.get_formatted_messages(),
                            indent=2,
                        )
                    )
                    assistant_response = await self.api_client.get_response(
                        messages=messages,
                        stream=streaming,
                        stream_callback=stream_callback,
                    )
                except asyncio.CancelledError:
                    logger.warning("APIClient response retrieval was cancelled")
                except Exception as e:
                    logger.error(
                        f"Error during APIClient response retrieval: {str(e)}",
                        exc_info=True,
                    )

                # Validate response (retry logic remains the same)
                if not assistant_response or not assistant_response.strip():
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning(
                            f"Empty response from API (attempt {retry_count}/{max_retries}), retrying..."
                        )
                        # Small exponential backoff
                        await asyncio.sleep(1 * retry_count)
                        continue
                    else:
                        logger.warning(
                            f"Empty response from API after {max_retries} attempts"
                        )
                        assistant_response = "I apologize, but I encountered an issue generating a response. Please try again."
                        break
                else:
                    # We got a valid response, break the retry loop
                    break

                # Let's return it as is for now, core needs adjustment later if this is the case.

            # Process response and execute actions regardless of streaming mode
            logger.debug(
                f"[Core.get_response] Processing response and executing actions. Streaming={streaming}"
            )

            # Add assistant response to conversation (only happens *after* the stream task is fully complete)
            if assistant_response:
                # Add assistant response to conversation
                # Ensure we add the complete response, even if it was streamed.
                # The APIClient should return the full string after streaming completes.
                # Note: add_assistant_message automatically strips action tags
                self.conversation_manager.conversation.add_assistant_message(
                    assistant_response
                )

            # Parse actions and continue with action handling
            actions = parse_action(assistant_response)

            # Check for task/response completion via finish_task or finish_response tools
            # NOTE: Phrase-based detection is deprecated. Use finish_task/finish_response tools.
            exit_continuation = any(
                action.action_type.value
                in ("finish_response", "finish_task", "task_completed")
                for action in actions
            )

            # Execute actions with interrupt checking
            action_results = []
            for action in actions:
                if self._check_interrupt():
                    action_results.append(
                        {
                            "action": action.action_type.value,
                            "result": "Action skipped due to interrupt",
                            "status": "interrupted",
                        }
                    )
                    continue

                try:
                    result = await self.action_executor.execute_action(action)
                    if result is not None:
                        action_results.append(
                            {
                                "action": action.action_type.value,
                                "result": str(result),
                                "status": "completed",
                            }
                        )

                        # Update conversation with action result
                        self.conversation_manager.add_action_result(
                            action_type=action.action_type.value,
                            result=str(result),
                            status="completed",
                        )
                except Exception as e:
                    error_result = {
                        "action": action.action_type.value,
                        "result": f"Error executing action: {str(e)}",
                        "status": "error",
                    }
                    action_results.append(error_result)
                    self.conversation_manager.add_action_result(
                        action_type=action.action_type.value,
                        result=f"Error executing action: {str(e)}",
                        status="error",
                    )
                    logger.error(f"Action execution error: {str(e)}")

            # Save the updated conversation state
            self.conversation_manager.save()

            # Construct the final response payload
            full_response = {
                "assistant_response": assistant_response,
                "actions": actions,
                "action_results": action_results,
                "metadata": {
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            }

            logger.debug(
                f"ACTION RESULT TEST: System outputs visible to LLM: {[msg for msg in messages if 'system' in msg.get('role', '') and 'Action executed' in str(msg.get('content', ''))]}"
            )

            return full_response, exit_continuation

        except Exception as e:
            error_data = log_error(
                e,
                context={
                    "component": "core",
                    "method": "get_response",
                    "iteration": current_iteration,
                    "max_iterations": max_iterations,
                },
            )
            return {
                "assistant_response": f"I apologize, but an error occurred: {str(e)}",
                "action_results": [],
            }, False

    async def execute_action(self, action) -> Dict[str, Any]:
        """Execute an action and return structured result"""
        try:
            # result = await super().execute_action(action)
            result = await self.action_executor.execute_action(action)
            return {
                "action": action.action_type.value,
                "result": str(result) if result is not None else "",
                "status": "completed",
            }
        except Exception as e:
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "execute_action",
                    "action": action.action_type.value,
                },
            )
            return {
                "action": action.action_type.value,
                "result": f"Error: {str(e)}",
                "status": "error",
            }

    async def reset_state(self):
        """
        Reset the core state completely.

        This method performs a more comprehensive reset than reset_context:
        - Resets all conversation state
        - Clears interrupt flags
        - Closes external resources like browser instances

        Use this when switching between entirely different tasks or at
        application shutdown.
        """
        self.reset_context()
        self._interrupted = False

        # Close browser if it was initialized
        from penguin.tools.browser_tools import browser_manager

        asyncio.create_task(browser_manager.close())

    def list_context_files(self) -> List[Dict[str, Any]]:
        """List all available context files"""
        return self.conversation_manager.list_context_files()

    # ------------------------------------------------------------------
    # Snapshot / Restore wrappers (Phase 3 integration)
    # ------------------------------------------------------------------

    def create_snapshot(self, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Persist current conversation state and return snapshot_id."""
        return self.conversation_manager.create_snapshot(meta=meta)

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Load conversation from snapshot; returns success bool."""
        return self.conversation_manager.restore_snapshot(snapshot_id)

    def branch_from_snapshot(
        self, snapshot_id: str, meta: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Fork a snapshot into a new branch and load it."""
        return self.conversation_manager.branch_from_snapshot(snapshot_id, meta=meta)

    # ------------------------------------------------------------------
    # Checkpoint Management API (NEW - V2.1 Conversation Plane)
    # ------------------------------------------------------------------

    async def create_checkpoint(
        self, name: Optional[str] = None, description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a manual checkpoint of the current conversation state.

        Args:
            name: Optional name for the checkpoint
            description: Optional description

        Returns:
            Checkpoint ID if successful, None otherwise
        """
        return await self.conversation_manager.create_manual_checkpoint(
            name=name, description=description
        )

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Rollback conversation to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            True if successful, False otherwise
        """
        return await self.conversation_manager.rollback_to_checkpoint(checkpoint_id)

    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new conversation branch from a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to branch from
            name: Optional name for the branch
            description: Optional description

        Returns:
            New branch checkpoint ID if successful, None otherwise
        """
        return await self.conversation_manager.branch_from_checkpoint(
            checkpoint_id, name=name, description=description
        )

    def list_checkpoints(
        self, session_id: Optional[str] = None, limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List available checkpoints with optional filtering.

        Args:
            session_id: Filter by session ID (None for current session)
            limit: Maximum number of checkpoints to return

        Returns:
            List of checkpoint information
        """
        # If no session_id specified, use current session
        if session_id is None:
            current_session = self.conversation_manager.get_current_session()
            if current_session:
                session_id = current_session.id

        return self.conversation_manager.list_checkpoints(
            session_id=session_id, limit=limit
        )

    async def cleanup_old_checkpoints(self) -> int:
        """
        Clean up old checkpoints according to retention policy.

        Returns:
            Number of checkpoints cleaned up
        """
        return await self.conversation_manager.cleanup_old_checkpoints()

    def get_checkpoint_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the checkpointing system.

        Returns:
            Dictionary with checkpoint statistics
        """
        if (
            not self.conversation_manager
            or not self.conversation_manager.checkpoint_manager
        ):
            return {
                "enabled": False,
                "total_checkpoints": 0,
                "auto_checkpoints": 0,
                "manual_checkpoints": 0,
                "branch_checkpoints": 0,
            }

        checkpoints = self.conversation_manager.list_checkpoints(limit=1000)

        stats = {
            "enabled": True,
            "total_checkpoints": len(checkpoints),
            "auto_checkpoints": len(
                [cp for cp in checkpoints if cp.get("auto", False)]
            ),
            "manual_checkpoints": len(
                [cp for cp in checkpoints if cp.get("type") == "manual"]
            ),
            "branch_checkpoints": len(
                [cp for cp in checkpoints if cp.get("type") == "branch"]
            ),
            "config": {
                "frequency": self.conversation_manager.checkpoint_manager.config.frequency,
                "retention_hours": self.conversation_manager.checkpoint_manager.config.retention[
                    "keep_all_hours"
                ],
                "max_age_days": self.conversation_manager.checkpoint_manager.config.retention[
                    "max_age_days"
                ],
            },
        }

        return stats

    # System Diagnostics and Information API
    # ------------------------------------------------------------------

    def get_system_info(self) -> Dict[str, Any]:
        """
        Get comprehensive system information.

        Returns:
            Dictionary containing system information including model config,
            component status, and capabilities
        """
        try:
            info = {
                "penguin_version": PENGUIN_VERSION,
                "engine_available": hasattr(self, "engine") and self.engine is not None,
                "checkpoints_enabled": self.get_checkpoint_stats().get(
                    "enabled", False
                ),
                "current_model": None,
                "conversation_manager": {
                    "active": hasattr(self, "conversation_manager")
                    and self.conversation_manager is not None,
                    "current_session_id": None,
                    "total_messages": 0,
                },
                "tool_manager": {
                    "active": hasattr(self, "tool_manager")
                    and self.tool_manager is not None,
                    "total_tools": 0,
                },
                "memory_provider": {"initialized": False, "provider_type": None},
            }

            # Add current model info
            if hasattr(self, "model_config") and self.model_config:
                info["current_model"] = {
                    "model": self.model_config.model,
                    "provider": self.model_config.provider,
                    "streaming_enabled": self.model_config.streaming_enabled,
                    "vision_enabled": bool(
                        getattr(self.model_config, "vision_enabled", False)
                    ),
                }

            # Add conversation manager details
            if hasattr(self, "conversation_manager") and self.conversation_manager:
                try:
                    current_session = self.conversation_manager.get_current_session()
                    if current_session:
                        info["conversation_manager"]["current_session_id"] = (
                            current_session.id
                        )
                        info["conversation_manager"]["total_messages"] = len(
                            current_session.messages
                        )
                except Exception:
                    pass  # Ignore errors getting session info

            # Add tool manager details
            if hasattr(self, "tool_manager") and self.tool_manager:
                info["tool_manager"]["total_tools"] = len(
                    getattr(self.tool_manager, "tools", {})
                )

                # Add memory provider info
                if (
                    hasattr(self.tool_manager, "_memory_provider")
                    and self.tool_manager._memory_provider
                ):
                    info["memory_provider"]["initialized"] = True
                    info["memory_provider"]["provider_type"] = type(
                        self.tool_manager._memory_provider
                    ).__name__

            return info

        except Exception as e:
            logger.error(f"Error getting system info: {e}")
            return {"error": f"Failed to get system info: {str(e)}"}

    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current system status including runtime state.

        Returns:
            Dictionary containing current system status and runtime information
        """
        try:
            from datetime import datetime

            status = {
                "status": "active",
                "runmode_status": getattr(
                    self, "current_runmode_status_summary", "RunMode idle."
                ),
                "continuous_mode": getattr(self, "_continuous_mode", False),
                "streaming_active": getattr(self, "streaming_active", False),
                "token_usage": self.get_token_usage(),
                "timestamp": datetime.now().isoformat(),
                "initialization": {
                    "core_initialized": getattr(self, "initialized", False),
                    "fast_startup_enabled": (
                        getattr(self.tool_manager, "fast_startup", False)
                        if hasattr(self, "tool_manager")
                        else False
                    ),
                },
            }

            # Add memory provider status if available
            if hasattr(self, "get_memory_provider_status"):
                status["memory_provider"] = self.get_memory_provider_status()

            return status

        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {
                "status": "error",
                "error": f"Failed to get system status: {str(e)}",
                "timestamp": datetime.now().isoformat(),
            }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
        retry=retry_if_exception_type(Exception),
        retry_error_callback=lambda retry_state: (
            None
            if isinstance(retry_state.outcome.exception(), KeyboardInterrupt)
            else retry_state.outcome.exception()
        ),
    )
    async def process(
        self,
        input_data: Union[Dict[str, Any], str],
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
        max_iterations: int = MAX_TASK_ITERATIONS,  # Use config value (default 5000)
        context_files: Optional[List[str]] = None,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        multi_step: bool = True,
    ) -> Dict[str, Any]:
        """
        Process a message with Penguin.

        This method serves as the primary interface for external systems
        (CLI, API, etc.) to interact with Penguin's capabilities. It handles:
        - Input preprocessing
        - Conversation loading/management
        - Delegating to multi-step processing
        - Error handling and retries

        Args:
            input_data: Either a dictionary with a 'text' key or a string message directly
            context: Optional additional context for processing
            conversation_id: Optional ID for conversation continuity
            agent_id: Optional agent identifier to scope the request
            max_iterations: Maximum reasoning-action cycles (default: 5)
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses.
            stream_callback: Optional callback function for handling streaming output chunks.
            multi_step: If True, use the multi-step `run_task` engine. Defaults to True.

        Returns:
            Dict containing assistant response and action results
        """
        # Handle flexible input format
        if isinstance(input_data, str):
            message = input_data
            image_paths = None
        else:
            message = input_data.get("text", "")
            image_paths = input_data.get("image_paths")
            if not image_paths:
                legacy_path = input_data.get("image_path")
                if isinstance(legacy_path, str) and legacy_path.strip():
                    image_paths = [legacy_path.strip()]

            # Handle string input and filter out empty/whitespace-only paths
            if isinstance(image_paths, str):
                image_paths = [image_paths.strip()] if image_paths.strip() else None
            elif isinstance(image_paths, list):
                image_paths = [
                    p.strip() for p in image_paths if isinstance(p, str) and p.strip()
                ]
                if not image_paths:
                    image_paths = None

        if not message and not image_paths:
            return {"assistant_response": "No input provided", "action_results": []}
        conversation_manager = self.conversation_manager
        if self.engine:
            try:
                candidate_cm = self.engine.get_conversation_manager(agent_id)
                if candidate_cm is not None:
                    conversation_manager = candidate_cm
            except Exception as engine_err:
                logger.warning(
                    f"Engine conversation manager lookup failed for agent '{agent_id}': {engine_err}"
                )
        elif agent_id:
            # Legacy fallback only: activate agent on shared manager when Engine is unavailable.
            try:
                if hasattr(conversation_manager, "set_current_agent"):
                    conversation_manager.set_current_agent(agent_id)
            except Exception as agent_err:
                logger.warning(
                    f"Failed to activate agent '{agent_id}' on ConversationManager: {agent_err}"
                )

        execution_context = get_current_execution_context()
        request_session_id = (
            execution_context.session_id
            if execution_context and execution_context.session_id
            else conversation_id
        )
        request_task = asyncio.current_task()
        request_tracked = False
        if isinstance(request_session_id, str) and request_session_id:
            self._opencode_abort_sessions.discard(request_session_id)
            if request_task is not None:
                tasks = self._opencode_process_tasks.get(request_session_id)
                if not isinstance(tasks, set):
                    tasks = set()
                    self._opencode_process_tasks[request_session_id] = tasks
                tasks.add(request_task)
                request_tracked = True

                next_count = (
                    self._opencode_active_requests.get(request_session_id, 0) + 1
                )
                self._opencode_active_requests[request_session_id] = next_count
                if next_count == 1:
                    await self._emit_opencode_session_status(request_session_id, "busy")

        try:
            # Load conversation if ID provided
            if conversation_id:
                scoped_conversation = getattr(
                    conversation_manager, "conversation", None
                )
                if scoped_conversation is not None and hasattr(
                    scoped_conversation, "load"
                ):
                    if not scoped_conversation.load(conversation_id):
                        logger.warning(f"Failed to load conversation {conversation_id}")
                elif not conversation_manager.load(conversation_id):
                    logger.warning(f"Failed to load conversation {conversation_id}")

            # Load context files if specified
            if context_files:
                scoped_conversation = getattr(
                    conversation_manager, "conversation", None
                )
                for file_path in context_files:
                    if scoped_conversation is not None and hasattr(
                        scoped_conversation, "load_context_file"
                    ):
                        scoped_conversation.load_context_file(file_path)
                    else:
                        conversation_manager.load_context_file(file_path)

            # Add user message to conversation explicitly
            user_message_dict = {
                "role": "user",
                "content": message,
                "category": MessageCategory.DIALOG,
            }
            if agent_id:
                user_message_dict["agent_id"] = agent_id

            # Emit user message event before processing
            logger.debug(f"Emitting user message event: {message[:30]}...")
            await self.emit_ui_event("message", user_message_dict)

            # Use new Engine layer if available
            if self.engine:
                execution_context = get_current_execution_context()
                stream_scope_id = self._resolve_stream_scope_id(
                    execution_context,
                    agent_id,
                )
                scoped_conversation_id = conversation_id
                scoped_session_id = conversation_id
                if execution_context is not None:
                    scoped_conversation_id = (
                        execution_context.conversation_id
                        or execution_context.session_id
                        or scoped_conversation_id
                    )
                    scoped_session_id = (
                        execution_context.session_id
                        or scoped_conversation_id
                        or scoped_session_id
                    )
                if not scoped_session_id:
                    try:
                        active_session = conversation_manager.get_current_session()
                        scoped_session_id = (
                            active_session.id if active_session else None
                        )
                    except Exception:
                        scoped_session_id = None
                if not scoped_conversation_id:
                    scoped_conversation_id = scoped_session_id

                async def _scoped_stream_callback(
                    chunk: str,
                    message_type: str = "assistant",
                ) -> None:
                    await self._handle_stream_chunk(
                        chunk,
                        message_type=message_type,
                        agent_id=agent_id,
                        stream_scope_id=stream_scope_id,
                        session_id=scoped_session_id,
                        conversation_id=scoped_conversation_id,
                    )

                # Build streaming callback for Engine that first updates internal streaming
                # state via _handle_stream_chunk and then forwards chunks to any external
                # stream_callback supplied by callers (e.g., WebSocket).
                if streaming:
                    if stream_callback:

                        async def _combined_stream_callback(
                            chunk: str, message_type: str = "assistant"
                        ):
                            # Update internal streaming handling
                            await _scoped_stream_callback(chunk, message_type)
                            # Forward to external callback, preserving message_type when supported
                            try:
                                import inspect

                                params = []
                                try:
                                    params = list(
                                        inspect.signature(
                                            stream_callback
                                        ).parameters.keys()
                                    )
                                except Exception:
                                    params = []
                                if asyncio.iscoroutinefunction(stream_callback):
                                    if len(params) >= 2:
                                        await stream_callback(chunk, message_type)
                                    else:
                                        await stream_callback(chunk)
                                else:
                                    if len(params) >= 2:
                                        await asyncio.to_thread(
                                            stream_callback, chunk, message_type
                                        )
                                    else:
                                        await asyncio.to_thread(stream_callback, chunk)
                            except Exception as cb_err:
                                logger.error(
                                    f"Error in external stream_callback: {cb_err}"
                                )

                        engine_stream_callback = _combined_stream_callback
                    else:
                        engine_stream_callback = _scoped_stream_callback
                else:
                    engine_stream_callback = None

                if multi_step:
                    # Check if this is a formal task (RunMode) or conversational multi-step
                    is_formal_task = context and context.get("task_mode", False)

                    if is_formal_task:
                        # Bridge the simple stream_callback to the Engine's richer message_callback
                        engine_message_callback = None
                        if stream_callback:
                            # The engine expects an async callback that takes (message, type, **kwargs)
                            async def bridged_callback(
                                message: str,
                                msg_type: str,
                                action_name: Optional[str] = None,
                                **kwargs,
                            ):
                                # We only care about streaming assistant thoughts for this callback
                                if msg_type == "assistant":
                                    # Create a task to run the potentially non-async callback
                                    # This ensures we don't block the engine's event loop.
                                    asyncio.create_task(
                                        asyncio.to_thread(stream_callback, message)
                                    )

                            engine_message_callback = bridged_callback

                        # Use the task-oriented engine for formal tasks
                        response = await self.engine.run_task(
                            task_prompt=message,
                            image_paths=image_paths,
                            max_iterations=max_iterations,
                            task_context=context,
                            message_callback=engine_message_callback,
                            agent_id=agent_id,
                        )
                    else:
                        # Use the new conversational multi-step engine
                        response = await self.engine.run_response(
                            prompt=message,
                            image_paths=image_paths,
                            max_iterations=max_iterations,
                            streaming=streaming,
                            stream_callback=engine_stream_callback,
                            agent_id=agent_id,
                        )
                else:
                    # Use the single-turn conversational engine
                    response = await self.engine.run_single_turn(
                        message,
                        image_paths=image_paths,
                        streaming=streaming,
                        stream_callback=engine_stream_callback,
                        agent_id=agent_id,
                    )
            else:
                # ---------- Legacy path (fallback) ----------
                # Prepare conversation and call get_response directly
                conversation_manager.conversation.prepare_conversation(
                    message, image_paths=image_paths
                )

                # FIX: Set the callback for event-based streaming, even in legacy mode
                internal_stream_callback = (
                    self._handle_stream_chunk if streaming else None
                )

                response, _ = await self.get_response(
                    stream_callback=internal_stream_callback,  # Pass the correct callback
                    streaming=streaming,
                )

            # NOTE: Empty-response retry logic removed - engine._llm_step handles this.
            # Engine retries once with stream=False, then raises LLMEmptyResponseError.
            # WALLET_GUARD in finalize_streaming_message injects placeholder for empty streams.

            token_data = conversation_manager.get_token_usage()
            latest_usage: Dict[str, Any] = {}
            try:
                if isinstance(response, dict):
                    response_usage = response.get("usage")
                    if isinstance(response_usage, dict):
                        latest_usage = response_usage
                if not latest_usage:
                    latest_usage = self._latest_model_usage()

                if isinstance(token_data, dict) and latest_usage:
                    current_total_tokens = int(
                        token_data.get("current_total_tokens", 0) or 0
                    )
                    if current_total_tokens <= 0:
                        usage_total_tokens = int(
                            latest_usage.get("total_tokens", 0) or 0
                        )
                        if usage_total_tokens <= 0:
                            usage_total_tokens = (
                                int(latest_usage.get("input_tokens", 0) or 0)
                                + int(latest_usage.get("output_tokens", 0) or 0)
                                + int(latest_usage.get("reasoning_tokens", 0) or 0)
                                + int(latest_usage.get("cache_read_tokens", 0) or 0)
                                + int(latest_usage.get("cache_write_tokens", 0) or 0)
                            )
                        if usage_total_tokens > 0:
                            token_data = dict(token_data)
                            token_data["current_total_tokens"] = usage_total_tokens
                            max_tokens_value = token_data.get(
                                "max_context_window_tokens"
                            )
                            if max_tokens_value is None:
                                max_tokens_value = token_data.get("max_tokens")
                            if isinstance(max_tokens_value, (int, float)):
                                max_tokens_int = int(max_tokens_value)
                                if max_tokens_int > 0:
                                    token_data["max_context_window_tokens"] = (
                                        max_tokens_int
                                    )
                                    token_data["max_tokens"] = max_tokens_int
                                    token_data["available_tokens"] = max(
                                        max_tokens_int - usage_total_tokens,
                                        0,
                                    )
                                    token_data["percentage"] = (
                                        usage_total_tokens / max_tokens_int
                                    ) * 100

                try:
                    current_session = conversation_manager.get_current_session()
                    if current_session and isinstance(
                        getattr(current_session, "metadata", None), dict
                    ):
                        current_session.metadata["_opencode_usage_v1"] = {
                            "current_total_tokens": token_data.get(
                                "current_total_tokens", 0
                            ),
                            "max_context_window_tokens": token_data.get(
                                "max_context_window_tokens",
                                token_data.get("max_tokens"),
                            ),
                            "available_tokens": token_data.get("available_tokens", 0),
                            "percentage": token_data.get("percentage", 0),
                            "truncations": token_data.get("truncations", {}),
                        }
                except Exception:
                    logger.debug("Unable to persist usage snapshot", exc_info=True)

                if latest_usage:
                    await self._apply_opencode_usage_to_latest_message(
                        request_session_id,
                        latest_usage,
                    )
            except Exception:
                logger.debug("Unable to emit OpenCode usage metadata", exc_info=True)

            # Ensure conversation is saved after processing
            conversation_manager.save()

            # Emit assistant message event after processing.
            # Streaming paths usually update UI via chunk events; however, some
            # provider failures return only a final error/note string with zero
            # chunks. In that case emit a message event so users can see it.
            if response and "assistant_response" in response:
                assistant_message = response["assistant_response"]
                if assistant_message:
                    emit_assistant_event = not streaming
                    if streaming:
                        stripped = assistant_message.lstrip()
                        if stripped.startswith("[Error:") or stripped.startswith(
                            "[Note:"
                        ):
                            emit_assistant_event = True
                    if emit_assistant_event:
                        logger.debug(
                            "Emitting assistant message event: %s…",
                            assistant_message[:30],
                        )
                        await self.emit_ui_event(
                            "message",
                            {
                                "role": "assistant",
                                "content": assistant_message,
                                "category": MessageCategory.DIALOG,
                                "metadata": {},
                                **({"agent_id": agent_id} if agent_id else {}),
                            },
                        )

            # Ensure token usage is emitted after processing
            await self.emit_ui_event("token_update", token_data)

            return response

        except asyncio.CancelledError:
            if isinstance(request_session_id, str) and request_session_id:
                self._opencode_abort_sessions.discard(request_session_id)
            return {
                "assistant_response": "",
                "action_results": [],
                "aborted": True,
            }

        except Exception as e:
            error_msg = f"Error in process method: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            log_error(e, context={"method": "process", "input_data": input_data})

            # Emit error event
            await self.emit_ui_event(
                "error",
                {
                    "message": "Error processing your request",
                    "source": "core.process",
                    "details": str(e),
                },
            )

            return {
                "assistant_response": "I apologize, but an error occurred while processing your request.",
                "action_results": [],
                "error": str(e),
            }

        finally:
            if (
                request_tracked
                and isinstance(request_session_id, str)
                and request_session_id
            ):
                tasks = self._opencode_process_tasks.get(request_session_id)
                if isinstance(tasks, set) and request_task is not None:
                    tasks.discard(request_task)
                    if not tasks:
                        self._opencode_process_tasks.pop(request_session_id, None)

                current_count = self._opencode_active_requests.get(
                    request_session_id, 0
                )
                if current_count > 1:
                    self._opencode_active_requests[request_session_id] = (
                        current_count - 1
                    )
                else:
                    self._opencode_active_requests.pop(request_session_id, None)
                    self._opencode_abort_sessions.discard(request_session_id)
                    await self._emit_opencode_session_status(request_session_id, "idle")

    def list_conversations(
        self,
        limit: int = 20,
        offset: int = 0,
        search_term: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        List available conversations.

        Args:
            limit: Maximum number of conversations to return
            offset: Offset for pagination

        Returns:
            List of conversations with metadata
        """
        return self.conversation_manager.list_conversations(
            limit=limit, offset=offset, search_term=search_term
        )

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific conversation by ID.

        Args:
            conversation_id: ID of the conversation to retrieve

        Returns:
            Conversation data or None if not found
        """
        if self.conversation_manager.load(conversation_id):
            session = self.conversation_manager.get_current_session()
            if not session:
                return None

            return {
                "id": session.id,
                "messages": [
                    {
                        "role": msg.role,
                        "content": msg.content,
                        "timestamp": msg.timestamp,
                        "agent_id": msg.agent_id,
                        "recipient_id": msg.recipient_id,
                        "message_type": msg.message_type,
                        "metadata": msg.metadata,
                    }
                    for msg in session.messages
                ],
                "created_at": session.created_at,
                "last_active": session.last_active,
                "metadata": session.metadata,
            }
        return None

    def get_conversation_history(
        self,
        conversation_id: str,
        *,
        include_system: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return self.conversation_manager.get_conversation_history(
            conversation_id,
            include_system=include_system,
            limit=limit,
        )

    def create_conversation(self) -> str:
        """
        Create a new conversation.

        Returns:
            ID of the new conversation
        """
        return self.conversation_manager.create_new_conversation()

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            conversation_id: ID of the conversation to delete

        Returns:
            True if successful, False otherwise
        """
        return self.conversation_manager.delete_conversation(conversation_id)

    def get_conversation_stats(self) -> Dict[str, Any]:
        """
        Get statistics about conversations.

        Returns:
            Dictionary with conversation statistics
        """
        return self.conversation_manager.get_session_stats()

    async def start_run_mode(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        continuous: bool = False,
        time_limit: Optional[int] = None,
        mode_type: str = "task",
        stream_callback_for_cli: Optional[Callable[[str], Awaitable[None]]] = None,
        ui_update_callback_for_cli: Optional[Callable[[], Awaitable[None]]] = None,
    ) -> None:
        """
        Start autonomous run mode for executing a task.

        Args:
            name: Name of the task (existing or new)
            description: Optional description if creating a new task
            context: Optional additional context or parameters
            continuous: Whether to run in continuous mode
            time_limit: Optional time limit in minutes
            mode_type: Type of mode (task or project)
            stream_callback_for_cli: Async callback for streaming LLM responses to UI.
            ui_update_callback_for_cli: Async callback for UI updates based on RunMode events.
        """
        # Store UI update callback for _handle_run_mode_event to use
        self._ui_update_callback = ui_update_callback_for_cli
        self._runmode_stream_callback = self._prepare_runmode_stream_callback(
            stream_callback_for_cli
        )
        self._runmode_active = True

        # Initialize status
        self.current_runmode_status_summary = "Starting RunMode..."

        try:
            run_mode = RunMode(
                self,  # core instance
                time_limit=time_limit,
                event_callback=self._handle_run_mode_event,
            )
            self.run_mode = run_mode
            self._continuous_mode = continuous

            if continuous:
                # RunMode's start_continuous will manage its internal continuous_mode flag
                await run_mode.start_continuous(
                    specified_task_name=name, task_description=description
                )
            else:
                await run_mode.start(
                    name=name, description=description, context=context
                )

        except Exception as e:
            # Reset continuous mode flag if starting run_mode itself fails
            self._continuous_mode = False

            # Log the error
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "start_run_mode",
                    "task_name": name,
                    "description": description,
                },
            )

            # Update error status
            self.current_runmode_status_summary = f"Error starting RunMode: {str(e)}"

            # Final UI update with error
            if self._ui_update_callback:
                try:
                    await self._ui_update_callback()
                except Exception as callback_err:
                    logger.error(f"Error in UI update callback: {callback_err}")

            raise  # Re-raise the exception so the caller knows starting run_mode failed

        finally:
            self._runmode_active = False
            self._runmode_stream_callback = None
            self.run_mode = None
            # Clear the UI update callback reference when finished
            self._ui_update_callback = None

            # Ensure state is cleaned up if run mode was not continuous or if continuous mode exited
            if hasattr(run_mode, "continuous_mode") and not run_mode.continuous_mode:
                self._continuous_mode = False

            logger.info(
                f"Exiting start_run_mode. Core _continuous_mode: {self._continuous_mode}"
            )

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------

    def refresh_api_client(self) -> None:
        """Recreate the active API client using the current model config."""
        self.api_client = APIClient(model_config=self.model_config)
        self.api_client.set_system_prompt(self.system_prompt)

        if self.conversation_manager:
            self.conversation_manager.api_client = self.api_client
            try:
                if hasattr(self.conversation_manager, "context_window"):
                    cw = self.conversation_manager.context_window
                    cw.api_client = self.api_client  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(
                    f"Failed to propagate refreshed API client to ContextWindowManager: {e}"
                )

        if getattr(self, "engine", None) is not None:
            try:
                self.engine.api_client = self.api_client  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(
                    f"Failed to propagate refreshed API client to Engine: {e}"
                )

    def _apply_new_model_config(
        self, new_model_config: ModelConfig, context_window_tokens: Optional[int] = None
    ) -> None:
        """Internal helper that swaps the model configuration and re-wires dependent components.

        This keeps the public ``load_model`` method concise and focused on
        validation / construction of the ``ModelConfig``.  All mutation of
        run-time state happens here so that we only need to test it in one
        place.

        Args:
            new_model_config: The new ModelConfig to apply
            context_window_tokens: The safe context window size (85% of raw) to apply
        """
        # Swap the model_config reference first so that any downstream logic
        # reads the up-to-date values.
        self.model_config = new_model_config

        # 1. Re-create API client with new settings so that every subsequent
        #    call uses the correct base URL / API key / etc.
        self.refresh_api_client()

        # 2. Propagate to ConversationManager components so token budgeting and
        #    streaming limits are accurate.
        if self.conversation_manager:
            self.conversation_manager.model_config = new_model_config
            # Update nested helpers if they expose the attributes we need.
            try:
                # ContextWindowManager lives under conversation_manager.context_window
                if hasattr(self.conversation_manager, "context_window"):
                    cw = self.conversation_manager.context_window
                    cw.model_config = new_model_config  # type: ignore[attr-defined]
                    # Update context window budget with safe window (85% of raw)
                    if context_window_tokens:
                        old_budget = cw.max_context_window_tokens
                        cw.max_context_window_tokens = context_window_tokens
                        cw._initialize_token_budgets()  # Re-compute category budgets
                        logger.info(
                            f"Updated context window: {old_budget} -> {context_window_tokens} tokens"
                        )
            except Exception as e:
                logger.warning(
                    f"Failed to propagate new model config to ContextWindowManager: {e}"
                )

    async def load_model(self, model_id: str) -> bool:
        """Replace the active model at runtime.

        The *model_id* argument can be either:
        1. A key present in ``config.yml -> model_configs``
        2. A fully-qualified model string of the form ``<provider>/<model_name>``.

        Returns ``True`` on success, ``False`` otherwise.
        """
        self._last_model_load_error = None

        def _coerce_optional_int(value: Any) -> Optional[int]:
            try:
                parsed = int(value)
            except Exception:
                return None
            return parsed if parsed > 0 else None

        try:
            # Resolve provider and client preference
            provider, client_pref = self._resolve_model_provider(model_id)
            if not provider:
                self._last_model_load_error = (
                    f"Could not resolve provider for model '{model_id}'"
                )
                return False

            provider_value = provider.strip().lower()
            client_value = client_pref.strip().lower()
            runtime_model_id = self._canonicalize_runtime_model_id(
                model_id,
                provider_value,
                client_value,
            )

            model_configs = getattr(self.config, "model_configs", None)
            if not isinstance(model_configs, dict):
                model_configs = {}
            model_lookup_id = (
                runtime_model_id
                if runtime_model_id in model_configs and model_id not in model_configs
                else model_id
            )

            requires_openrouter_specs = bool(
                provider_value == "openrouter" or client_value == "openrouter"
            )
            model_specs: Dict[str, Any] = {}
            spec_model_id = (
                runtime_model_id if provider_value == "openrouter" else model_id
            )

            if requires_openrouter_specs:
                model_specs = await fetch_model_specs(spec_model_id)
                if not model_specs:
                    self._last_model_load_error = (
                        f"Could not fetch specifications for model '{spec_model_id}'"
                    )
                    logger.error(self._last_model_load_error)
                    return False
                logger.info(f"Fetched specs for {spec_model_id}: {model_specs}")

            model_specific = model_configs.get(model_lookup_id, {})
            if not isinstance(model_specific, dict):
                model_specific = {}

            context_length = _coerce_optional_int(model_specs.get("context_length"))
            if context_length is None:
                context_length = _coerce_optional_int(
                    model_specific.get("context_window")
                    or model_specific.get("max_context_window_tokens")
                )

            safe_window = safe_context_window(context_length)
            max_output = _coerce_optional_int(model_specs.get("max_output_tokens"))
            if max_output is None:
                max_output = _coerce_optional_int(
                    model_specific.get("max_output_tokens")
                    or model_specific.get("max_tokens")
                )
            if max_output is None:
                max_output = safe_window

            # Build and apply new ModelConfig
            new_model_config = ModelConfig.for_model(
                model_name=model_lookup_id,
                provider=provider,
                client_preference=client_pref,
                model_configs=model_configs,
            )

            new_model_config.model = runtime_model_id
            if context_length is not None:
                new_model_config.max_context_window_tokens = context_length
                new_model_config.max_history_tokens = safe_window
            if max_output is not None:
                new_model_config.max_output_tokens = max_output

            # Apply vision support from actual model specs, but respect explicit user config.
            # Only auto-enable if user hasn't explicitly set vision_enabled in model_configs.
            user_explicit_vision = model_specific.get("vision_enabled")
            if user_explicit_vision is not None:
                # User explicitly configured vision - respect their choice
                new_model_config.vision_enabled = bool(user_explicit_vision)
                logger.info(
                    f"Model '{runtime_model_id}' vision set to {new_model_config.vision_enabled} (user config)"
                )
            elif model_specs.get("supports_vision"):
                # No explicit user config, auto-enable based on model capability
                new_model_config.vision_enabled = True
                logger.info(
                    f"Model '{runtime_model_id}' supports vision (auto-detected)"
                )

            self._apply_new_model_config(
                new_model_config, context_window_tokens=safe_window
            )

            logger.info(
                f"Switched to model '{runtime_model_id}' (context: {safe_window} tokens, vision: {new_model_config.vision_enabled})"
            )
            return True

        except Exception as e:
            self._last_model_load_error = str(e)
            logger.error(f"Failed to switch to model '{model_id}': {e}")
            return False

    def _canonicalize_runtime_model_id(
        self,
        model_id: str,
        provider: str,
        client_preference: str,
    ) -> str:
        """Canonicalize model IDs into provider-local form for runtime adapters."""
        value = str(model_id or "").strip()
        if not value:
            return value

        provider_value = str(provider or "").strip().lower()
        client_value = str(client_preference or "").strip().lower()

        # Native SDK adapters expect provider-local IDs (e.g. `gpt-5`, not `openai/gpt-5`).
        if client_value == "native" and provider_value in {"openai", "anthropic"}:
            if "/" in value:
                prefix, remainder = value.split("/", 1)
                if prefix.strip().lower() == provider_value and remainder.strip():
                    return remainder.strip()
            return value

        # OpenRouter runtime model IDs should not include an extra `openrouter/` prefix.
        if provider_value == "openrouter" and "/" in value:
            prefix, remainder = value.split("/", 1)
            if prefix.strip().lower() == "openrouter" and remainder.strip():
                return remainder.strip()

        return value

    def _resolve_model_provider(self, model_id: str) -> tuple[Optional[str], str]:
        """Resolve provider and client preference for a model ID.

        Returns:
            Tuple of (provider, client_preference), or (None, "") on error.
        """
        # Check explicit model_configs first
        if hasattr(self.config, "model_configs") and isinstance(
            self.config.model_configs, dict
        ):
            model_conf = self.config.model_configs.get(model_id)
            if model_conf:
                provider = model_conf.get("provider")
                client_pref = model_conf.get("client_preference", "openrouter")
                return provider, client_pref

        # Infer from fully-qualified model ID
        if "/" not in model_id:
            logger.error(
                f"Model '{model_id}' not in model_configs and not fully-qualified"
            )
            return None, ""

        provider_part = model_id.split("/", 1)[0]
        provider_part = provider_part.strip().lower()

        if provider_part == "openrouter":
            client_pref = "openrouter"
            provider = "openrouter"
            return provider, client_pref

        native_providers = {"openai", "anthropic", "google", "ollama"}
        if provider_part in native_providers:
            return provider_part, "native"

        client_pref = (
            self.model_config.client_preference if self.model_config else "openrouter"
        )
        provider = "openrouter" if client_pref == "openrouter" else provider_part
        return provider, client_pref

    def list_available_models(self) -> List[Dict[str, Any]]:
        """Return a list of model metadata derived from ``config.yml``.

        This helper is intentionally lightweight so it can be called at any
        time without additional network requests.  Richer model discovery (e.g.
        OpenRouter catalogue) is handled in *PenguinInterface*.
        """
        models: List[Dict[str, Any]] = []
        current_model_name = self.model_config.model if self.model_config else None

        if not (
            hasattr(self.config, "model_configs")
            and isinstance(self.config.model_configs, dict)
        ):
            return models

        for model_id, conf in self.config.model_configs.items():
            if not isinstance(conf, dict):
                continue
            entry = {
                "id": model_id,
                "name": conf.get("model", model_id),
                "provider": conf.get("provider", "unknown"),
                "client_preference": conf.get("client_preference", "openrouter"),
                "vision_enabled": conf.get("vision_enabled", False),
                "max_output_tokens": conf.get(
                    "max_output_tokens", conf.get("max_tokens")
                ),  # Accept both keys
                "temperature": conf.get("temperature"),
                "current": model_id == current_model_name
                or conf.get("model") == current_model_name,
            }
            models.append(entry)

        # Bring the current model to the top for convenience.
        models.sort(key=lambda m: (not m["current"], m["id"]))
        return models

    def get_current_model(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the currently loaded model.

        Returns:
            Dictionary with current model information, or None if no model is loaded
        """
        if not self.model_config:
            return None

        return {
            "model": self.model_config.model,
            "provider": self.model_config.provider,
            "client_preference": self.model_config.client_preference,
            "max_output_tokens": getattr(self.model_config, "max_output_tokens", None),
            "temperature": getattr(self.model_config, "temperature", None),
            "streaming_enabled": self.model_config.streaming_enabled,
            "vision_enabled": bool(getattr(self.model_config, "vision_enabled", False)),
            "api_base": getattr(self.model_config, "api_base", None),
        }

    async def emit_ui_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event through the unified event bus.

        Filters internal markers from content before emitting to UI.

        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update", etc.)
            data: Event data relevant to the event type
        """
        data_keys = list(data.keys()) if isinstance(data, dict) else []
        logger.debug(
            "emit_ui_event called: %s keys=%s bus=%s",
            event_type,
            data_keys,
            id(self.event_bus),
        )

        # Filter internal markers from content before emitting
        if isinstance(data, dict):
            data = self._filter_internal_markers_from_event(data)

        execution_context = get_current_execution_context()

        # Tag with agent_id when available so UI can label sources
        try:
            if isinstance(data, dict):
                # Tag missing or empty agent_id with the current active agent
                if not data.get("agent_id"):
                    context_agent = (
                        execution_context.agent_id if execution_context else None
                    )
                    if context_agent:
                        data = dict(data)
                        data["agent_id"] = context_agent
                    else:
                        cm = getattr(self, "conversation_manager", None)
                        if cm and hasattr(cm, "current_agent_id"):
                            data = dict(data)
                            data["agent_id"] = cm.current_agent_id
        except Exception:
            pass

        # Inject conversation/session ids for SSE filtering
        if isinstance(data, dict):
            scoped_conversation_id = None
            scoped_session_id = None
            if execution_context:
                scoped_conversation_id = (
                    execution_context.conversation_id or execution_context.session_id
                )
                scoped_session_id = (
                    execution_context.session_id or scoped_conversation_id
                )

            if scoped_conversation_id and not data.get("conversation_id"):
                data = dict(data)
                data["conversation_id"] = scoped_conversation_id
            if scoped_session_id and not data.get("session_id"):
                data = dict(data)
                data["session_id"] = scoped_session_id

            if not data.get("conversation_id") or not data.get("session_id"):
                fallback_conversation_id = getattr(
                    self, "_current_conversation_id", None
                )
                if fallback_conversation_id:
                    data = dict(data)  # shallow copy to avoid mutating caller dict
                    data.setdefault("conversation_id", fallback_conversation_id)
                    data.setdefault("session_id", fallback_conversation_id)

        # Emit through unified event bus
        try:
            await self.event_bus.emit(event_type, data)

            if event_type == "status" and isinstance(data, dict):
                status_type = data.get("status_type")
                session_id = data.get("session_id") or data.get("conversation_id")
                if isinstance(status_type, str) and isinstance(session_id, str):
                    # Clarification status originates as plain UI status events, but SSE clients only
                    # subscribe to `opencode_event`. Bridge the session-scoped status here so web clients
                    # see the same waiting/resume truth instead of silently missing it.
                    if status_type in {"clarification_needed", "clarification_answered"}:
                        await self._emit_opencode_session_status(
                            session_id,
                            status_type,
                            info=data.get("data") if isinstance(data.get("data"), dict) else None,
                        )
        except Exception as e:
            logger.error(f"[TUI_ADAPTER] ERROR in event_bus.emit: {e}", exc_info=True)

    def _filter_internal_markers_from_event(
        self, data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Filter internal implementation markers from event data.

        Removes tags like <execute>, <system-reminder>, <internal> from content fields.

        Args:
            data: Event data dictionary

        Returns:
            Filtered event data (shallow copy if modified)
        """
        import re

        # Patterns for internal markers
        internal_patterns = [
            r"<execute>.*?</execute>",
            r"<system-reminder>.*?</system-reminder>",
            r"<internal>.*?</internal>",
            r"</?finish_response\b[^>]*>?",
        ]

        # Fields that may contain content to filter
        content_fields = ["content", "chunk", "content_so_far", "message"]

        modified = False
        filtered_data = data

        for field in content_fields:
            if field in data and isinstance(data[field], str):
                original_content = data[field]
                filtered_content = original_content

                # Apply all filter patterns
                for pattern in internal_patterns:
                    filtered_content = re.sub(
                        pattern, "", filtered_content, flags=re.DOTALL
                    )

                # Only create copy if content changed
                if filtered_content != original_content:
                    if not modified:
                        filtered_data = dict(data)  # Shallow copy
                        modified = True
                    filtered_data[field] = filtered_content.strip()

        return filtered_data

    def _resolve_stream_scope_id(
        self,
        execution_context: Optional[Any],
        agent_id: Optional[str],
    ) -> str:
        """Resolve stream-state key for concurrent session isolation."""
        resolved_agent = agent_id
        if not resolved_agent and execution_context is not None:
            resolved_agent = getattr(execution_context, "agent_id", None)
        if not resolved_agent:
            resolved_agent = getattr(
                self.conversation_manager,
                "current_agent_id",
                None,
            )
        resolved_agent = resolved_agent or "default"
        if execution_context is None:
            return resolved_agent
        session_scope = (
            execution_context.session_id or execution_context.conversation_id
        )
        if not session_scope:
            return resolved_agent
        return f"{session_scope}:{resolved_agent}"

    async def _handle_stream_chunk(
        self,
        chunk: str,
        message_type: Optional[str] = None,
        role: str = "assistant",
        agent_id: Optional[str] = None,
        stream_scope_id: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
    ) -> None:
        """
        Central handler for all streaming content chunks from any source.
        Delegates to AgentStreamingStateManager and emits events.

        Args:
            chunk: The content chunk to add
            message_type: Type of message - "assistant", "reasoning", "tool_output", etc.
            role: The role of the message (default: "assistant")
            agent_id: Optional agent identifier for per-agent streaming (default: current agent)
        """
        # Resolve agent_id from conversation_manager if not provided
        execution_context = get_current_execution_context()
        if agent_id is None:
            if execution_context and execution_context.agent_id:
                agent_id = execution_context.agent_id
            else:
                agent_id = getattr(
                    self.conversation_manager, "current_agent_id", "default"
                )
        resolved_scope_id = stream_scope_id or self._resolve_stream_scope_id(
            execution_context, agent_id
        )
        resolved_session_id = session_id or conversation_id
        if execution_context:
            resolved_session_id = (
                execution_context.session_id
                or execution_context.conversation_id
                or resolved_session_id
            )

        abort_sessions = getattr(self, "_opencode_abort_sessions", None)
        if not isinstance(abort_sessions, set):
            abort_sessions = set()
            setattr(self, "_opencode_abort_sessions", abort_sessions)

        if (
            isinstance(resolved_session_id, str)
            and resolved_session_id in abort_sessions
        ):
            raise asyncio.CancelledError(f"Session {resolved_session_id} aborted")

        # Delegate to AgentStreamingStateManager
        filtered = self._filter_internal_markers_from_event({"chunk": chunk})
        if filtered.get("chunk") is not None:
            chunk = filtered.get("chunk", "")
        events = self._stream_manager.handle_chunk(
            chunk,
            agent_id=resolved_scope_id,
            message_type=message_type,
            role=role,
        )

        # Emit events and invoke RunMode callback
        for event in events:
            # Inject session_id into event data for SSE filtering
            event_data = (
                dict(event.data)
                if isinstance(event.data, dict)
                else {"data": event.data}
            )
            scoped_conversation_id = conversation_id
            scoped_session_id = session_id or conversation_id
            if execution_context:
                scoped_conversation_id = (
                    execution_context.conversation_id
                    or execution_context.session_id
                    or scoped_conversation_id
                )
                scoped_session_id = (
                    execution_context.session_id
                    or scoped_conversation_id
                    or scoped_session_id
                )

            if scoped_conversation_id:
                event_data["conversation_id"] = scoped_conversation_id
                event_data["session_id"] = scoped_session_id or scoped_conversation_id
            else:
                try:
                    session = self.conversation_manager.get_current_session()
                    sid = session.id if session else "unknown"
                    event_data["session_id"] = sid
                    event_data["conversation_id"] = sid
                except Exception:
                    event_data["session_id"] = "unknown"
                    event_data["conversation_id"] = "unknown"

            event_data["agent_id"] = agent_id
            event_data = self._filter_internal_markers_from_event(event_data)
            await self.emit_ui_event(event.event_type, event_data)
            # Forward to RunMode stream callback if active
            if event_data.get("chunk") and not event_data.get("is_reasoning"):
                await self._invoke_runmode_stream_callback(
                    event_data["chunk"],
                    event_data.get("message_type", "assistant"),
                )

    def finalize_streaming_message(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        stream_scope_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Finalizes the current streaming message for a specific agent, adds it to
        ConversationManager, and resets the streaming state. Emits a final event
        with is_final=True.

        Args:
            agent_id: Optional agent identifier (defaults to current agent)

        Returns:
            The finalized message dict or None if no streaming was active
        """
        # Resolve agent_id from conversation_manager if not provided
        execution_context = get_current_execution_context()
        if agent_id is None:
            if execution_context and execution_context.agent_id:
                agent_id = execution_context.agent_id
            else:
                agent_id = getattr(
                    self.conversation_manager, "current_agent_id", "default"
                )
        resolved_agent_id = agent_id
        if (
            resolved_agent_id is None
            and execution_context
            and execution_context.agent_id
        ):
            resolved_agent_id = execution_context.agent_id
        if resolved_agent_id is None:
            resolved_agent_id = getattr(
                self.conversation_manager,
                "current_agent_id",
                "default",
            )
        resolved_agent_id = resolved_agent_id or "default"

        resolved_conversation_id = conversation_id
        resolved_session_id = session_id or conversation_id
        if execution_context:
            resolved_conversation_id = (
                execution_context.conversation_id
                or execution_context.session_id
                or resolved_conversation_id
            )
            resolved_session_id = (
                execution_context.session_id
                or resolved_conversation_id
                or resolved_session_id
            )

        resolved_stream_scope_id = stream_scope_id
        if not resolved_stream_scope_id and resolved_session_id:
            resolved_stream_scope_id = f"{resolved_session_id}:{resolved_agent_id}"
        if not resolved_stream_scope_id:
            resolved_stream_scope_id = self._resolve_stream_scope_id(
                execution_context,
                resolved_agent_id,
            )

        # Delegate to AgentStreamingStateManager
        message, events = self._stream_manager.finalize(
            agent_id=resolved_stream_scope_id
        )
        if message is None:
            logical_agent_id = resolved_agent_id
            if resolved_stream_scope_id != logical_agent_id:
                message, events = self._stream_manager.finalize(
                    agent_id=logical_agent_id
                )
            if message is None:
                active_scopes = self._stream_manager.get_active_agents()
                if len(active_scopes) == 1:
                    message, events = self._stream_manager.finalize(
                        agent_id=active_scopes[0]
                    )

        if message is None:
            return None

        # Log WALLET_GUARD warning if empty
        if message.was_empty:
            logger.warning(
                f"[WALLET_GUARD] Empty response from LLM for agent '{resolved_agent_id}', forcing context advance."
            )

        # Determine message category
        if message.role == "assistant":
            category = MessageCategory.DIALOG
        elif message.role == "system":
            category = MessageCategory.SYSTEM
        else:
            category = MessageCategory.DIALOG

        # Add to the correct agent's conversation
        if hasattr(self, "conversation_manager") and self.conversation_manager:
            try:
                # Try to get agent-specific conversation if available
                conv = self.conversation_manager.get_agent_conversation(
                    resolved_agent_id
                )
                conv.add_message(
                    role=message.role,
                    content=message.content,
                    category=category,
                    metadata=message.metadata,
                )
            except (KeyError, AttributeError):
                # Fallback to current conversation
                self.conversation_manager.conversation.add_message(
                    role=message.role,
                    content=message.content,
                    category=category,
                    metadata=message.metadata,
                )

            # For WebSocket streaming (RunMode), emit a message event
            if hasattr(self, "_temp_ws_callback") and self._temp_ws_callback:
                asyncio.create_task(
                    self._temp_ws_callback(
                        {
                            "type": "message",
                            "role": message.role,
                            "content": message.content,
                            "category": category,
                            "metadata": message.metadata,
                            "agent_id": resolved_agent_id,
                        }
                    )
                )

        # Emit events from manager
        callback_ref = self._runmode_stream_callback
        for event in events:
            event_data = (
                dict(event.data)
                if isinstance(event.data, dict)
                else {"data": event.data}
            )
            scoped_conversation_id = resolved_conversation_id
            scoped_session_id = resolved_session_id
            if execution_context:
                scoped_conversation_id = (
                    execution_context.conversation_id
                    or execution_context.session_id
                    or scoped_conversation_id
                )
                scoped_session_id = (
                    execution_context.session_id
                    or scoped_conversation_id
                    or scoped_session_id
                )

            if scoped_conversation_id:
                event_data["session_id"] = scoped_session_id or scoped_conversation_id
                event_data["conversation_id"] = scoped_conversation_id
            else:
                try:
                    session = self.conversation_manager.get_current_session()
                    sid = session.id if session else "unknown"
                    event_data["session_id"] = sid
                    event_data["conversation_id"] = sid
                except Exception:
                    event_data["session_id"] = "unknown"
                    event_data["conversation_id"] = "unknown"

            event_data["agent_id"] = resolved_agent_id
            event_data = self._filter_internal_markers_from_event(event_data)
            asyncio.create_task(self.emit_ui_event(event.event_type, event_data))
            # Forward final event to RunMode callback
            if callback_ref and event_data.get("is_final"):
                asyncio.create_task(
                    self._invoke_runmode_stream_callback("", "assistant", callback_ref)
                )

        return message.to_dict()

    def _prepare_runmode_stream_callback(
        self,
        callback: Optional[Callable[..., Any]],
    ) -> Optional[Callable[[str, str], Awaitable[None]]]:
        """Normalize run mode stream callbacks to a common async signature."""
        return adapt_stream_callback(callback, suppress_errors=True)

    async def _invoke_runmode_stream_callback(
        self,
        chunk: str,
        message_type: str,
        callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> None:
        cb = callback or self._runmode_stream_callback
        if not cb:
            return
        try:
            await cb(chunk, message_type)
        except Exception as exc:
            logger.debug(
                "RunMode stream callback execution failed: %s", exc, exc_info=True
            )

    # Update token usage notification to use events
    def update_token_display(self) -> None:
        """Emit token usage event to UI subscribers."""
        token_data = self.get_token_usage()
        asyncio.create_task(self.emit_ui_event("token_update", token_data))

        # Legacy callback support
        for callback in self.token_callbacks:
            try:
                callback(token_data)
            except Exception as e:
                logger.error(f"Error in token callback: {e}")

    # Keep existing register_stream_callback for backward compatibility

    async def _handle_run_mode_event(self, event: Dict[str, Any]) -> None:
        """
        Central handler for all events emitted by RunMode.

        This method is the bridge between RunMode's headless operation and the rest of the system.
        It processes events from RunMode and updates ConversationManager appropriately.

        Args:
            event: Dictionary containing event data with at least a 'type' key
        """
        try:
            logger.debug(f"Core received RunMode event: {event}")
            event_type = event.get("type")

            # Handle message events
            if event_type == "message":
                # Extract message data
                msg_data = {
                    "role": event.get("role", "system"),
                    "content": event.get("content", ""),
                    "category": event.get("category", MessageCategory.SYSTEM),
                    "metadata": event.get("metadata", {}),
                }

                # Ensure category is a MessageCategory enum if provided as string
                if isinstance(msg_data["category"], str):
                    try:
                        msg_data["category"] = MessageCategory[
                            msg_data["category"].upper()
                        ]
                    except KeyError:
                        logger.warning(
                            f"Invalid message category string '{msg_data['category']}' from RunMode event. Defaulting to SYSTEM."
                        )
                        msg_data["category"] = MessageCategory.SYSTEM

                # Add to conversation
                self.conversation_manager.conversation.add_message(**msg_data)
                self.conversation_manager.save()
                logger.debug(
                    f"Core added message to ConversationManager from RunMode event: {msg_data['role']} - {msg_data['content'][:50]}..."
                )

            # Handle status events
            elif event_type == "status":
                status_type = event.get("status_type", "unknown")
                status_data = event.get("data", {})
                logger.info(
                    f"RunMode status update: {status_type} - Data: {status_data}"
                )

                # Update status summary based on event type
                if (
                    status_type == "task_started"
                    or status_type == "task_started_legacy"
                ):
                    task_name = status_data.get(
                        "task_name", status_data.get("task_prompt", "Unknown task")
                    )
                    self.current_runmode_status_summary = f"Task: {task_name} - Running"
                elif status_type == "task_progress":
                    iteration = status_data.get("iteration", "?")
                    max_iter = status_data.get("max_iterations", "?")
                    progress = status_data.get("progress", 0)
                    self.current_runmode_status_summary = (
                        f"Progress: {progress}% (Iter: {iteration}/{max_iter})"
                    )
                elif (
                    status_type == "task_completed"
                    or status_type == "task_completed_legacy"
                    or status_type == "task_completed_eventbus"
                ):
                    task_name = status_data.get("task_name", "Last task")
                    self.current_runmode_status_summary = (
                        f"Task: {task_name} - Completed"
                    )
                elif (
                    status_type == "run_mode_ended"
                    or status_type == "shutdown_completed"
                ):
                    self.current_runmode_status_summary = "RunMode ended."
                elif (
                    status_type == "clarification_needed"
                    or status_type == "clarification_needed_eventbus"
                ):
                    self.current_runmode_status_summary = "Awaiting user clarification."
                elif status_type == "awaiting_user_input_after_task":
                    self.current_runmode_status_summary = (
                        "Task complete. Awaiting input."
                    )

            # Handle error events
            elif event_type == "error":
                err_msg = event.get("message", "Unknown error from RunMode")
                err_source = event.get("source", "runmode")
                err_details = event.get("details", {})
                logger.error(
                    f"RunMode Error Event (Source: {err_source}): {err_msg} | Details: {err_details}"
                )

                # Update status with error
                self.current_runmode_status_summary = f"Error: {err_msg}"

            # Handle unknown event types
            else:
                logger.warning(
                    f"Core received unknown RunMode event type: {event_type} | Event: {event}"
                )

            # After processing any event, signal the UI to update if callback is registered
            if hasattr(self, "_ui_update_callback") and self._ui_update_callback:
                try:
                    await self._ui_update_callback()
                except Exception as e:
                    logger.error(f"Error in UI update callback: {e}", exc_info=True)

            # Also send to WebSocket if temporary callback exists (for streaming)
            if hasattr(self, "_temp_ws_callback") and self._temp_ws_callback:
                try:
                    await self._temp_ws_callback(event)
                except Exception as e:
                    logger.error(f"Error in WebSocket callback: {e}", exc_info=True)

        except Exception as e:
            logger.error(
                f"Error in PenguinCore._handle_run_mode_event: {str(e)}", exc_info=True
            )

    def get_startup_stats(self) -> Dict[str, Any]:
        """Get comprehensive startup performance statistics."""
        stats = {
            "profiling_summary": profiler.get_summary(),
            "tool_manager_stats": (
                self.tool_manager.get_startup_stats()
                if hasattr(self.tool_manager, "get_startup_stats")
                else {}
            ),
            "memory_provider_initialized": hasattr(
                self.tool_manager, "_memory_provider"
            )
            and self.tool_manager._memory_provider is not None,
            "core_initialized": self.initialized,
        }
        return stats

    def print_startup_report(self) -> None:
        """Print a comprehensive startup performance report."""
        print("\n" + "=" * 60)
        print("PENGUIN STARTUP PERFORMANCE REPORT")
        print("=" * 60)

        # Get tool manager stats
        if hasattr(self.tool_manager, "get_startup_stats"):
            tool_stats = self.tool_manager.get_startup_stats()
            print(f"\nTool Manager Configuration:")
            print(f"  Fast startup mode: {tool_stats.get('fast_startup', 'Unknown')}")
            print(
                f"  Memory provider initialized: {tool_stats.get('memory_provider_exists', 'Unknown')}"
            )
            print(
                f"  Indexing completed: {tool_stats.get('indexing_completed', 'Unknown')}"
            )

            lazy_init = tool_stats.get("lazy_initialized", {})
            print(f"\nLazy-loaded components:")
            for component, initialized in lazy_init.items():
                status = "✓ Loaded" if initialized else "○ Deferred"
                print(f"  {component}: {status}")

        # Print profiling report
        print(f"\nDetailed Performance Breakdown:")
        profiler_report = profiler.get_startup_report()
        print(profiler_report)

        print("=" * 60)

    def enable_fast_startup_globally(self) -> None:
        """Enable fast startup mode for future operations."""
        if hasattr(self.tool_manager, "fast_startup"):
            self.tool_manager.fast_startup = True
            logger.info("Fast startup mode enabled globally")

    def get_memory_provider_status(self) -> Dict[str, Any]:
        """Get current status of memory provider and indexing."""
        if not hasattr(self.tool_manager, "_memory_provider"):
            return {"status": "not_initialized", "provider": None}

        provider = self.tool_manager._memory_provider
        if provider is None:
            return {"status": "disabled", "provider": None}

        status = {
            "status": "initialized" if provider else "not_initialized",
            "provider": type(provider).__name__ if provider else None,
            "indexing_completed": getattr(
                self.tool_manager, "_indexing_completed", False
            ),
            "indexing_task_running": False,
        }

        # Check indexing task status
        if (
            hasattr(self.tool_manager, "_indexing_task")
            and self.tool_manager._indexing_task
        ):
            task = self.tool_manager._indexing_task
            status["indexing_task_running"] = not task.done()
            status["indexing_task_status"] = {
                "done": task.done(),
                "cancelled": task.cancelled(),
                "exception": (
                    str(task.exception()) if task.done() and task.exception() else None
                ),
            }

        return status

    def _subscribe_to_stream_events(self):
        """Subscribe to Penguin stream events and translate to OpenCode format."""
        self._opencode_stream_states: Dict[str, Dict[str, Any]] = {}
        self._opencode_message_adapters: Dict[str, Any] = {}
        self._opencode_tool_parts: Dict[str, str] = {}
        self._opencode_tool_info: Dict[str, Dict[str, Any]] = {}

        # Store reference to handler so it doesn't get garbage collected
        self._tui_stream_handler = self._on_tui_stream_chunk
        self.event_bus.subscribe("stream_chunk", self._tui_stream_handler)

        self._tui_action_handler = self._on_tui_action
        self._tui_action_result_handler = self._on_tui_action_result
        self.event_bus.subscribe("action", self._tui_action_handler)
        self.event_bus.subscribe("action_result", self._tui_action_result_handler)

        self._tui_lsp_updated_handler = self._on_tui_lsp_updated
        self._tui_lsp_diagnostics_handler = self._on_tui_lsp_diagnostics
        self.event_bus.subscribe("lsp.updated", self._tui_lsp_updated_handler)
        self.event_bus.subscribe(
            "lsp.client.diagnostics", self._tui_lsp_diagnostics_handler
        )

        self._tui_todo_updated_handler = self._on_tui_todo_updated
        self.event_bus.subscribe("todo.updated", self._tui_todo_updated_handler)

    def _get_tui_adapter(self, session_id: Optional[str]) -> Any:
        """Return a session-scoped TUI adapter to avoid cross-session bleed."""
        sid = session_id or "unknown"

        resolved_directory = None
        session_dirs = getattr(self, "_opencode_session_directories", None)
        if isinstance(session_dirs, dict):
            mapped = session_dirs.get(sid)
            if isinstance(mapped, str) and mapped.strip():
                resolved_directory = mapped.strip()
        if not resolved_directory:
            execution_context = get_current_execution_context()
            if execution_context and execution_context.directory:
                resolved_directory = execution_context.directory
        if not resolved_directory:
            runtime = getattr(self, "runtime_config", None)
            runtime_dir = getattr(runtime, "active_root", None) or getattr(
                runtime, "project_root", None
            )
            if isinstance(runtime_dir, str) and runtime_dir.strip():
                resolved_directory = runtime_dir.strip()
        if not resolved_directory:
            env_dir = os.getenv("PENGUIN_CWD")
            if isinstance(env_dir, str) and env_dir.strip():
                resolved_directory = env_dir.strip()
        if not resolved_directory:
            resolved_directory = os.getcwd()

        adapters = getattr(self, "_tui_adapters", None)
        if not isinstance(adapters, dict):
            adapters = {}
            self._tui_adapters = adapters
        adapter = adapters.get(sid)
        if adapter is not None:
            if hasattr(adapter, "set_directory"):
                adapter.set_directory(resolved_directory)
            return adapter

        from penguin.tui_adapter import PartEventAdapter

        adapter = PartEventAdapter(
            self.event_bus,
            persist_callback=self._persist_opencode_event,
            emit_session_status_events=False,
        )
        adapter.set_session(sid)
        if hasattr(adapter, "set_directory"):
            adapter.set_directory(resolved_directory)
        adapters[sid] = adapter
        return adapter

    async def _on_tui_stream_chunk(self, event_type: str, data: Dict[str, Any]):
        """Handle stream chunk - manages stream lifecycle and emits with delta."""
        if event_type != "stream_chunk":
            return

        chunk = data.get("chunk", "")
        message_type = data.get("message_type", "assistant")
        stream_id = data.get("stream_id", "unknown")
        session_id = (
            data.get("session_id")
            or data.get("conversation_id")
            or data.get("sessionID")
            or "unknown"
        )
        agent_id = data.get("agent_id") or data.get("agentID") or "default"
        adapter = self._get_tui_adapter(session_id)
        stream_states = getattr(self, "_opencode_stream_states", None)
        if not isinstance(stream_states, dict):
            stream_states = {}
            self._opencode_stream_states = stream_states
        state = stream_states.get(session_id)
        if not isinstance(state, dict):
            state = {
                "active": False,
                "stream_id": None,
                "message_id": None,
                "part_id": None,
            }
            stream_states[session_id] = state

        is_final = bool(data.get("is_final"))
        is_aborted = bool(data.get("aborted"))
        if is_aborted and is_final and not state.get("active") and not chunk:
            state["stream_id"] = None
            state["part_id"] = None
            return

        # Auto-detect stream start (first chunk or new stream_id)
        if (not state.get("active")) or state.get("stream_id") != stream_id:
            # Finalize previous stream if exists
            message_id = state.get("message_id")
            part_id = state.get("part_id")
            if state.get("active") and message_id and part_id:
                try:
                    await adapter.on_stream_end(message_id, part_id)
                except Exception:
                    pass

            # Start new stream
            state["active"] = True
            state["stream_id"] = stream_id

            # Create message and text part
            try:
                message_id, part_id = await adapter.on_stream_start(
                    agent_id=agent_id,
                    model_id=getattr(self.model_config, "model", None),
                    provider_id=getattr(self.model_config, "provider", None),
                )
                state["message_id"] = message_id
                state["part_id"] = part_id
                self._opencode_message_adapters[message_id] = adapter
            except Exception as e:
                logger.error(f"Failed to start OpenCode stream: {e}")
                state["active"] = False
                return

        # Emit the chunk
        message_id = state.get("message_id")
        part_id = state.get("part_id")
        if message_id and part_id:
            try:
                await adapter.on_stream_chunk(message_id, part_id, chunk, message_type)
            except Exception as e:
                logger.error(f"Failed to emit OpenCode chunk: {e}")

        # Fallback: when provider streaming yields no assistant chunk events but
        # finalize includes full assistant content, synthesize one part update so
        # Penguin-mode SSE clients render the response.
        if is_final and message_id and part_id and not chunk:
            final_content = data.get("content")
            if isinstance(final_content, str) and final_content.strip():
                should_emit_fallback = True
                try:
                    active_parts = getattr(adapter, "_active_parts", {})
                    active_part = (
                        active_parts.get(part_id)
                        if isinstance(active_parts, dict)
                        else None
                    )
                    if isinstance(active_part, dict):
                        existing_text = active_part.get("content", {}).get("text", "")
                    else:
                        existing_content = (
                            getattr(active_part, "content", {}) if active_part else {}
                        )
                        existing_text = (
                            existing_content.get("text", "")
                            if isinstance(existing_content, dict)
                            else ""
                        )
                    should_emit_fallback = not bool(
                        isinstance(existing_text, str) and existing_text
                    )
                except Exception:
                    should_emit_fallback = True

                if should_emit_fallback:
                    try:
                        await adapter.on_stream_chunk(
                            message_id,
                            part_id,
                            final_content,
                            "assistant",
                        )
                    except Exception as e:
                        logger.error(
                            "Failed to emit fallback OpenCode final chunk: %s",
                            e,
                        )

        if data.get("is_final"):
            if message_id and part_id:
                try:
                    await adapter.on_stream_end(message_id, part_id)
                except Exception as e:
                    logger.error(f"Failed to finalize OpenCode stream: {e}")
            state["active"] = False
            state["stream_id"] = None
            # Keep latest message id so post-stream tool events can attach
            # to the same assistant response when possible.
            state["message_id"] = message_id
            state["part_id"] = None

    def _strip_diff_fences(self, diff_content: str) -> str:
        if not diff_content:
            return diff_content
        stripped = diff_content.strip()
        if not stripped.startswith("```"):
            return diff_content
        lines = stripped.splitlines()
        if len(lines) < 2:
            return diff_content
        if not lines[-1].startswith("```"):
            return diff_content
        return "\n".join(lines[1:-1])

    def _ensure_unified_diff(self, file_path: str, diff_content: str) -> str:
        if not diff_content:
            return diff_content
        cleaned = self._strip_diff_fences(diff_content)
        stripped = cleaned.lstrip()
        if stripped.startswith("--- ") or stripped.startswith("*** "):
            return cleaned
        rel = (file_path or "").lstrip("./")
        if not rel:
            return cleaned
        header = f"--- a/{rel}\n+++ b/{rel}\n"
        body = cleaned.lstrip("\n")
        return f"{header}{body}"

    def _extract_unified_diff_from_result(self, result: Any) -> str:
        if result is None:
            return ""
        text = str(result)
        if not text:
            return ""

        lines = text.strip().splitlines()
        start_index = -1
        for index, line in enumerate(lines):
            if line.startswith("--- "):
                start_index = index
                break
        if start_index < 0:
            return ""

        diff_lines = lines[start_index:]
        if not any(line.startswith("+++ ") for line in diff_lines):
            return ""
        return "\n".join(diff_lines).strip()

    def _extract_tool_file_path(self, tool_input: Any) -> str:
        if not isinstance(tool_input, dict):
            return ""
        for key in ("filePath", "file_path", "path", "file", "target"):
            value = tool_input.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        return ""

    def _normalize_todo_items(self, value: Any) -> list[Dict[str, str]]:
        if isinstance(value, dict):
            value = value.get("todos")
        if not isinstance(value, list):
            return []

        statuses = {"pending", "in_progress", "completed", "cancelled"}
        priorities = {"high", "medium", "low"}
        normalized: list[Dict[str, str]] = []
        seen_ids: set[str] = set()
        for index, item in enumerate(value):
            if not isinstance(item, dict):
                continue

            content_raw = item.get("content")
            if isinstance(content_raw, str):
                content = content_raw.strip()
            elif content_raw is None:
                content = ""
            else:
                content = str(content_raw).strip()
            if not content:
                continue

            status_raw = item.get("status", "pending")
            status = (
                status_raw.strip().lower()
                if isinstance(status_raw, str)
                else str(status_raw).strip().lower()
            )
            if status not in statuses:
                status = "pending"

            priority_raw = item.get("priority", "medium")
            priority = (
                priority_raw.strip().lower()
                if isinstance(priority_raw, str)
                else str(priority_raw).strip().lower()
            )
            if priority not in priorities:
                priority = "medium"

            todo_id_raw = item.get("id")
            todo_id = (
                todo_id_raw.strip()
                if isinstance(todo_id_raw, str) and todo_id_raw.strip()
                else f"todo_{index + 1}"
            )
            if todo_id in seen_ids:
                suffix = 2
                candidate = f"{todo_id}_{suffix}"
                while candidate in seen_ids:
                    suffix += 1
                    candidate = f"{todo_id}_{suffix}"
                todo_id = candidate
            seen_ids.add(todo_id)

            normalized.append(
                {
                    "id": todo_id,
                    "content": content,
                    "status": status,
                    "priority": priority,
                }
            )

        return normalized

    def _extract_todos_from_result(self, result: Any) -> list[Dict[str, str]]:
        if isinstance(result, list):
            return self._normalize_todo_items(result)
        if isinstance(result, dict):
            return self._normalize_todo_items(result)
        if result is None:
            return []

        text = str(result).strip()
        if not text:
            return []
        try:
            parsed = json.loads(text)
        except Exception:
            return []
        return self._normalize_todo_items(parsed)

    def _parse_action_payload(self, params: Any) -> Dict[str, Any]:
        if isinstance(params, dict):
            return dict(params)
        if not isinstance(params, str):
            return {}
        text = params.strip()
        if not text.startswith("{"):
            return {}
        try:
            parsed = json.loads(text)
        except Exception:
            return {}
        if isinstance(parsed, dict):
            return parsed
        return {}

    def _extract_result_file_paths(self, result: Any) -> list[str]:
        payload = self._parse_action_payload(result)
        if not payload:
            return []

        files: list[str] = []
        single_file = payload.get("file")
        if isinstance(single_file, str) and single_file.strip():
            files.append(single_file.strip())

        for key in ("files", "created", "files_edited"):
            value = payload.get(key)
            if not isinstance(value, list):
                continue
            files.extend(
                str(item).strip()
                for item in value
                if isinstance(item, str) and item.strip()
            )

        deduped: list[str] = []
        seen: set[str] = set()
        for path in files:
            if path in seen:
                continue
            seen.add(path)
            deduped.append(path)
        return deduped

    def _humanize_subagent_name(self, value: Any) -> str:
        text = str(value or "subagent").strip() or "subagent"
        return text.replace("_", " ").replace("-", " ")

    def _summarize_subagent_description(self, value: Any, fallback: str) -> str:
        text = " ".join(str(value or "").split()).strip()
        if not text:
            return fallback
        if len(text) <= 120:
            return text
        return text[:117].rstrip() + "..."

    def _build_task_card_summary(
        self,
        label: str,
        status: str,
        *,
        item_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        state: Dict[str, Any] = {"status": status}
        if isinstance(title, str) and title.strip():
            state["title"] = title.strip()
        return [
            {
                "id": item_id or f"task_{label.lower().replace(' ', '_')}",
                "tool": label,
                "state": state,
            }
        ]

    def _summary_status(self, metadata: Dict[str, Any], default: str) -> str:
        summary = metadata.get("summary")
        if not isinstance(summary, list) or not summary:
            return default
        first = summary[0]
        if not isinstance(first, dict):
            return default
        state = first.get("state")
        if not isinstance(state, dict):
            return default
        value = state.get("status")
        if isinstance(value, str) and value.strip():
            return value.strip()
        return default

    def _build_spawn_subagent_task_card(
        self, params: Any
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        payload = self._parse_action_payload(params)
        share_session = bool(payload.get("share_session", False))
        if share_session:
            if isinstance(params, dict):
                return dict(params), {}
            return {"params": params}, {}

        raw_agent = payload.get("persona") or payload.get("id") or "subagent"
        subagent_type = self._humanize_subagent_name(raw_agent)
        description = self._summarize_subagent_description(
            payload.get("description") or payload.get("initial_prompt"),
            f"Subagent session for {subagent_type}",
        )
        tool_input = {
            "description": description,
            "prompt": payload.get("initial_prompt") or "",
            "subagent_type": subagent_type,
        }
        metadata = {
            "summary": self._build_task_card_summary(
                "subagent",
                "running",
                item_id=str(payload.get("id") or "subagent"),
            )
        }
        return tool_input, metadata

    def _map_action_to_tool(
        self, action: str, params: Any
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        action_name = (action or "").strip().lower()
        tool_input: Dict[str, Any] = {}
        metadata: Dict[str, Any] = {}
        raw = params if isinstance(params, str) else ""
        if isinstance(params, dict):
            raw = (
                params.get("code")
                or params.get("command")
                or params.get("params")
                or ""
            )

        if action_name == "execute":
            tool_input = {"command": raw, "description": "IPython"}
            return "bash", tool_input, metadata

        if action_name == "execute_command":
            tool_input = {"command": raw, "description": "Shell"}
            return "bash", tool_input, metadata

        if action_name == "todowrite":
            todos = self._normalize_todo_items(params)
            if not todos and isinstance(params, str):
                try:
                    parsed = json.loads(params)
                    todos = self._normalize_todo_items(parsed)
                except Exception:
                    todos = []
            tool_input = {"todos": todos}
            return "todowrite", tool_input, metadata

        if action_name == "todoread":
            return "todoread", {}, metadata

        if action_name == "question":
            questions: list[dict[str, Any]] = []
            if isinstance(params, dict):
                raw_questions = params.get("questions")
                if isinstance(raw_questions, list):
                    questions = [
                        item for item in raw_questions if isinstance(item, dict)
                    ]
            elif isinstance(raw, str) and raw.strip():
                try:
                    parsed = json.loads(raw)
                    if isinstance(parsed, dict):
                        raw_questions = parsed.get("questions")
                        if isinstance(raw_questions, list):
                            questions = [
                                item for item in raw_questions if isinstance(item, dict)
                            ]
                    elif isinstance(parsed, list):
                        questions = [item for item in parsed if isinstance(item, dict)]
                except Exception:
                    questions = []
            tool_input = {"questions": questions}
            return "question", tool_input, metadata

        if action_name == "spawn_sub_agent":
            tool_input, metadata = self._build_spawn_subagent_task_card(params)
            if metadata:
                return "task", tool_input, metadata
            return action_name, tool_input, metadata

        if action_name == "apply_diff":
            if isinstance(params, dict):
                file_path = params.get("file_path") or params.get("path") or ""
                diff_content = params.get("diff_content") or params.get("diff") or ""
            else:
                first_sep = raw.find(":")
                if first_sep != -1:
                    file_path = raw[:first_sep].strip()
                    remainder = raw[first_sep + 1 :]
                else:
                    file_path = ""
                    remainder = raw
                diff_content = remainder
                if ":" in remainder:
                    diff_part, flag = remainder.rsplit(":", 1)
                    flag_stripped = flag.strip().lower()
                    if (
                        flag_stripped in {"true", "false"}
                        and "\n" not in flag
                        and "\r" not in flag
                    ):
                        diff_content = diff_part
            tool_input = {"filePath": file_path}
            metadata["diff"] = self._ensure_unified_diff(file_path, diff_content)
            return "edit", tool_input, metadata

        if action_name == "patch_file":
            parsed = parse_patch_file_payload(params)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, str):
                return "edit", {"filePath": ""}, metadata
            tool_input = {"filePath": parsed.get("path", "")}
            operation = parsed.get("operation") if isinstance(parsed, dict) else None
            if isinstance(operation, dict):
                operation_type = operation.get("type")
                if operation_type == "unified_diff":
                    diff_content = operation.get("diff_content") or ""
                    metadata["diff"] = self._ensure_unified_diff(
                        tool_input.get("filePath", ""),
                        str(diff_content),
                    )
                elif operation_type == "replace_lines":
                    if isinstance(operation.get("start_line"), int):
                        tool_input["startLine"] = operation["start_line"]
                    if isinstance(operation.get("end_line"), int):
                        tool_input["endLine"] = operation["end_line"]
                    if isinstance(operation.get("new_content"), str):
                        tool_input["newContent"] = operation["new_content"]
                elif operation_type == "insert_lines":
                    if isinstance(operation.get("after_line"), int):
                        tool_input["afterLine"] = operation["after_line"]
                    if isinstance(operation.get("new_content"), str):
                        tool_input["newContent"] = operation["new_content"]
                elif operation_type == "delete_lines":
                    if isinstance(operation.get("start_line"), int):
                        tool_input["startLine"] = operation["start_line"]
                    if isinstance(operation.get("end_line"), int):
                        tool_input["endLine"] = operation["end_line"]
                elif operation_type == "regex_replace":
                    tool_input["pattern"] = operation.get("search_pattern")
                    tool_input["replacement"] = operation.get("replacement")
            return "edit", tool_input, metadata

        if action_name == "replace_lines":
            if isinstance(params, dict):
                path = params.get("path") or params.get("file_path") or ""
                start_line = params.get("start_line")
                end_line = params.get("end_line")
                tool_input = {"filePath": path}
                if isinstance(start_line, int):
                    tool_input["startLine"] = start_line
                if isinstance(end_line, int):
                    tool_input["endLine"] = end_line
                if isinstance(params.get("new_content"), str):
                    tool_input["newContent"] = params.get("new_content")
            else:
                parts = raw.split(":", 3)
                if len(parts) >= 4:
                    path = parts[0].strip()
                    try:
                        start_line = int(parts[1].strip())
                        end_line = int(parts[2].strip())
                        content = parts[3]
                        verify = True
                        if ":" in content:
                            content_part, flag = content.rsplit(":", 1)
                            flag_stripped = flag.strip().lower()
                            if (
                                flag_stripped in {"true", "false"}
                                and "\n" not in flag
                                and "\r" not in flag
                            ):
                                verify = flag_stripped == "true"
                                content = content_part
                        tool_input = {
                            "filePath": path,
                            "startLine": start_line,
                            "endLine": end_line,
                            "newContent": content,
                            "verify": verify,
                        }
                    except ValueError:
                        tool_input = {"filePath": path}
            return "edit", tool_input, metadata

        if action_name == "insert_lines":
            if isinstance(params, dict):
                tool_input = {
                    "filePath": params.get("path") or params.get("file_path") or "",
                    "newContent": params.get("new_content") or "",
                }
                after_line = params.get("after_line")
                if isinstance(after_line, int):
                    tool_input["afterLine"] = after_line
            else:
                parts = raw.split(":", 2)
                if len(parts) >= 3:
                    tool_input = {
                        "filePath": parts[0].strip(),
                        "newContent": parts[2],
                    }
                    try:
                        tool_input["afterLine"] = int(parts[1].strip())
                    except ValueError:
                        pass
            return "edit", tool_input, metadata

        if action_name == "delete_lines":
            if isinstance(params, dict):
                tool_input = {
                    "filePath": params.get("path") or params.get("file_path") or "",
                }
                start_line = params.get("start_line")
                end_line = params.get("end_line")
                if isinstance(start_line, int):
                    tool_input["startLine"] = start_line
                if isinstance(end_line, int):
                    tool_input["endLine"] = end_line
            else:
                parts = raw.split(":", 2)
                if len(parts) >= 3:
                    tool_input = {
                        "filePath": parts[0].strip(),
                    }
                    try:
                        tool_input["startLine"] = int(parts[1].strip())
                        tool_input["endLine"] = int(parts[2].strip())
                    except ValueError:
                        pass
            return "edit", tool_input, metadata

        if action_name == "edit_with_pattern":
            if isinstance(params, dict):
                tool_input = {
                    "filePath": params.get("file_path") or params.get("path") or "",
                    "pattern": params.get("search_pattern") or params.get("pattern"),
                    "replacement": params.get("replacement"),
                }
                if isinstance(params.get("backup"), bool):
                    tool_input["backup"] = params.get("backup")
            else:
                content = raw
                backup: Optional[bool] = None
                parts = raw.rsplit(":", 1)
                if len(parts) == 2 and parts[1].strip().lower() in ("true", "false"):
                    content = parts[0]
                    backup = parts[1].strip().lower() == "true"
                fields = content.split(":", 2)
                if len(fields) >= 3:
                    tool_input = {
                        "filePath": fields[0].strip(),
                        "pattern": fields[1],
                        "replacement": fields[2],
                    }
                    if backup is not None:
                        tool_input["backup"] = backup
            return "edit", tool_input, metadata

        if action_name == "enhanced_write":
            if isinstance(params, dict):
                tool_input = {
                    "filePath": params.get("path") or params.get("file_path") or "",
                    "content": params.get("content") or "",
                }
                if isinstance(params.get("backup"), bool):
                    tool_input["backup"] = params.get("backup")
            else:
                first_sep = raw.find(":")
                if first_sep != -1:
                    file_path = raw[:first_sep].strip()
                    remainder = raw[first_sep + 1 :]
                    backup = True
                    content = remainder
                    if ":" in remainder:
                        content_part, flag = remainder.rsplit(":", 1)
                        flag_stripped = flag.strip().lower()
                        if (
                            flag_stripped in {"true", "false"}
                            and "\n" not in flag
                            and "\r" not in flag
                        ):
                            backup = flag_stripped == "true"
                            content = content_part
                    tool_input = {
                        "filePath": file_path,
                        "content": content,
                        "backup": backup,
                    }
            return "write", tool_input, metadata

        if action_name == "write_file":
            parsed = parse_write_file_payload(params)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, str):
                return "write", {"filePath": ""}, metadata
            tool_input = {
                "filePath": parsed.get("path") or "",
                "content": parsed.get("content") or "",
                "backup": parsed.get("backup", True),
            }
            return "write", tool_input, metadata

        if action_name == "multiedit":
            apply_flag: Optional[bool] = None
            content = raw
            if isinstance(params, dict):
                content = str(params.get("content") or "")
                if isinstance(params.get("apply"), bool):
                    apply_flag = params.get("apply")
            else:
                first_line = content.split("\n", 1)[0].strip().lower()
                if first_line.startswith("apply=") or first_line.startswith("apply:"):
                    maybe_value = first_line.split("=", 1)[-1].split(":", 1)[-1].strip()
                    if maybe_value in {"true", "false"}:
                        apply_flag = maybe_value == "true"
            tool_input = {
                "filePath": "(multiple files)",
                "content": content,
            }
            if apply_flag is not None:
                tool_input["apply"] = apply_flag
            return "edit", tool_input, metadata

        if action_name == "patch_files":
            parsed = parse_patch_files_payload(params)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, str):
                return "edit", {"filePath": "(multiple files)"}, metadata
            tool_input = {"filePath": "(multiple files)"}
            if isinstance(parsed.get("operations"), list):
                files = []
                for item in parsed["operations"]:
                    if not isinstance(item, dict):
                        continue
                    path = item.get("path")
                    if isinstance(path, str) and path.strip():
                        files.append(path.strip())
                if files:
                    metadata["files"] = files
            if isinstance(parsed.get("content"), str):
                tool_input["content"] = parsed["content"]
            if isinstance(parsed.get("apply"), bool):
                tool_input["apply"] = parsed["apply"]
            return "edit", tool_input, metadata

        if action_name == "enhanced_diff":
            if isinstance(params, dict):
                tool_input = {
                    "filePath": params.get("file1") or params.get("path1") or "",
                    "comparePath": params.get("file2") or params.get("path2") or "",
                }
                if isinstance(params.get("semantic"), bool):
                    tool_input["semantic"] = params.get("semantic")
            else:
                parts = raw.split(":", 2)
                tool_input = {
                    "filePath": parts[0].strip() if len(parts) > 0 else "",
                    "comparePath": parts[1].strip() if len(parts) > 1 else "",
                }
                if len(parts) > 2 and parts[2].strip().lower() in {"true", "false"}:
                    tool_input["semantic"] = parts[2].strip().lower() == "true"
            return "read", tool_input, metadata

        if action_name == "workspace_search":
            if isinstance(params, dict):
                tool_input = {
                    "pattern": params.get("query") or params.get("pattern") or "",
                    "path": params.get("path") or ".",
                }
            else:
                parts = raw.split(":", 1)
                tool_input = {
                    "pattern": parts[0].strip() if len(parts) > 0 else "",
                    "path": ".",
                }
            return "grep", tool_input, metadata

        if action_name in {"enhanced_read", "read_file"}:
            parsed = parse_read_file_payload(params)
            error = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(error, str):
                return "read", {"filePath": ""}, metadata
            tool_input = {"filePath": parsed.get("path", "")}
            if parsed.get("max_lines") is not None:
                tool_input["limit"] = parsed.get("max_lines")
            return "read", tool_input, metadata

        if action_name == "list_files_filtered":
            if isinstance(params, dict):
                tool_input = {
                    "path": params.get("path") or params.get("directory") or "."
                }
            else:
                parts = raw.split(":")
                path = parts[0].strip() if parts and parts[0].strip() else "."
                tool_input = {"path": path}
            return "list", tool_input, metadata

        if action_name == "find_files_enhanced":
            if isinstance(params, dict):
                tool_input = {
                    "pattern": params.get("pattern") or params.get("filename") or "",
                    "path": params.get("search_path") or params.get("path") or ".",
                }
            else:
                parts = raw.split(":")
                pattern = parts[0].strip() if parts and parts[0].strip() else ""
                search_path = (
                    parts[1].strip() if len(parts) > 1 and parts[1].strip() else "."
                )
                tool_input = {"pattern": pattern, "path": search_path}
            return "glob", tool_input, metadata

        if action_name == "search":
            if isinstance(params, dict):
                tool_input = {
                    "pattern": params.get("pattern") or params.get("query") or ""
                }
            else:
                tool_input = {"pattern": raw}
            return "grep", tool_input, metadata

        if isinstance(params, dict):
            tool_input = params
        else:
            tool_input = {"params": params}
        return action_name or "unknown", tool_input, metadata

    def _map_action_result_metadata(
        self,
        action: str,
        result: Any,
        existing: Optional[Dict[str, Any]] = None,
        tool_input: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        metadata = dict(existing or {})
        if isinstance(event_metadata, dict):
            metadata.update(event_metadata)
        action_name = (action or "").strip().lower()
        if status == "error" and action_name in {
            "patch_file",
            "patch_files",
            "apply_diff",
            "replace_lines",
            "edit_with_pattern",
            "write_file",
            "enhanced_write",
            "insert_lines",
            "delete_lines",
            "multiedit",
        }:
            raw_diff = metadata.pop("diff", None)
            if isinstance(raw_diff, str) and raw_diff.strip():
                metadata["attemptedDiff"] = raw_diff

        if action_name in {"execute", "execute_command"}:
            metadata.setdefault("output", "" if result is None else str(result))
        if status != "error" and action_name in {"todowrite", "todoread"}:
            todos = self._extract_todos_from_result(result)
            if todos:
                metadata["todos"] = todos
        if status != "error" and action_name in {
            "patch_file",
            "replace_lines",
            "edit_with_pattern",
            "write_file",
            "enhanced_write",
            "insert_lines",
            "delete_lines",
            "patch_files",
            "multiedit",
        }:
            file_path = self._extract_tool_file_path(tool_input)
            if file_path:
                metadata.setdefault("filePath", file_path)
            diff_text = self._extract_unified_diff_from_result(result)
            if diff_text:
                metadata["diff"] = self._ensure_unified_diff(file_path, diff_text)
            result_files = self._extract_result_file_paths(result)
            if result_files:
                metadata["files"] = result_files
                if len(result_files) == 1:
                    metadata.setdefault("filePath", result_files[0])
        if action_name == "spawn_sub_agent":
            payload = self._parse_action_payload(result)
            if (
                isinstance(payload.get("session_id"), str)
                and payload["session_id"].strip()
            ):
                metadata.setdefault("sessionId", payload["session_id"].strip())
            if (
                isinstance(payload.get("session_title"), str)
                and payload["session_title"].strip()
            ):
                metadata.setdefault("title", payload["session_title"].strip())
            label = "subagent"
            item_id = None
            if (
                isinstance(metadata.get("sessionId"), str)
                and metadata["sessionId"].strip()
            ):
                item_id = metadata["sessionId"].strip()
            title = (
                metadata.get("title")
                if isinstance(metadata.get("title"), str)
                else None
            )
            summary_status = (
                "error"
                if status == "error"
                else self._summary_status(
                    metadata,
                    "completed",
                )
            )
            if status != "error":
                summary_status = "completed"
            metadata["summary"] = self._build_task_card_summary(
                label,
                summary_status,
                item_id=item_id,
                title=title if status != "error" else "Subagent session failed",
            )
        return metadata

    async def _on_tui_action(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type != "action":
            return

        session_id = (
            data.get("session_id")
            or data.get("conversation_id")
            or data.get("sessionID")
            or "unknown"
        )
        adapter = self._get_tui_adapter(session_id)

        tool_name = data.get("type") or data.get("action") or "unknown"
        params = data.get("params")
        if isinstance(params, str) and params.strip().startswith(("{", "[")):
            try:
                import json

                params = json.loads(params)
            except Exception:
                pass

        mapped_tool, tool_input, metadata = self._map_action_to_tool(tool_name, params)

        stream_state: Dict[str, Any] = {}
        states = getattr(self, "_opencode_stream_states", None)
        if isinstance(states, dict):
            maybe_state = states.get(session_id)
            if isinstance(maybe_state, dict):
                stream_state = maybe_state
        message_id_hint = stream_state.get("message_id")
        agent_id_hint = data.get("agent_id") or data.get("agentID") or "default"

        call_id = data.get("id") or data.get("call_id") or data.get("callID")
        if not call_id:
            call_id = f"call_{int(time.time() * 1000)}"
        tool_key = f"{session_id}:{call_id}"

        part_id = await adapter.on_tool_start(
            mapped_tool,
            tool_input,
            tool_call_id=call_id,
            metadata=metadata,
            message_id=message_id_hint,
            agent_id=agent_id_hint,
        )
        self._opencode_tool_parts[tool_key] = part_id
        self._opencode_tool_info[tool_key] = {
            "tool": mapped_tool,
            "input": tool_input,
            "metadata": metadata,
            "action": tool_name,
        }

    async def _on_tui_action_result(
        self, event_type: str, data: Dict[str, Any]
    ) -> None:
        if event_type != "action_result":
            return

        session_id = (
            data.get("session_id")
            or data.get("conversation_id")
            or data.get("sessionID")
            or "unknown"
        )
        adapter = self._get_tui_adapter(session_id)

        call_id = data.get("id") or data.get("call_id") or data.get("callID")
        if not call_id:
            return
        tool_key = f"{session_id}:{call_id}"

        info = self._opencode_tool_info.get(tool_key, {})
        part_id = self._opencode_tool_parts.get(tool_key)
        action_name = (
            data.get("action") or data.get("type") or info.get("action") or "unknown"
        )
        if not part_id:
            mapped_tool, tool_input, metadata = self._map_action_to_tool(
                action_name, {}
            )

            stream_state: Dict[str, Any] = {}
            states = getattr(self, "_opencode_stream_states", None)
            if isinstance(states, dict):
                maybe_state = states.get(session_id)
                if isinstance(maybe_state, dict):
                    stream_state = maybe_state
            message_id_hint = stream_state.get("message_id")
            agent_id_hint = data.get("agent_id") or data.get("agentID") or "default"

            part_id = await adapter.on_tool_start(
                mapped_tool,
                tool_input,
                tool_call_id=call_id,
                metadata=metadata,
                message_id=message_id_hint,
                agent_id=agent_id_hint,
            )
            self._opencode_tool_parts[tool_key] = part_id
            info = {"tool": mapped_tool, "input": tool_input, "metadata": metadata}

        status = data.get("status")
        result = data.get("result")
        if (
            status != "error"
            and isinstance(result, str)
            and result.lstrip().lower().startswith("error")
        ):
            status = "error"
        error = result if status == "error" else None
        merged_meta = self._map_action_result_metadata(
            action_name,
            result,
            info.get("metadata") if isinstance(info, dict) else None,
            info.get("input") if isinstance(info, dict) else None,
            status,
            data.get("metadata") if isinstance(data.get("metadata"), dict) else None,
        )
        await adapter.on_tool_end(part_id, result, error=error, metadata=merged_meta)
        self._opencode_tool_parts.pop(tool_key, None)
        self._opencode_tool_info.pop(tool_key, None)

    async def _on_tui_todo_updated(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type != "todo.updated":
            return

        properties = dict(data or {})
        context = get_current_execution_context()
        session_id = (
            properties.get("sessionID")
            or properties.get("session_id")
            or properties.get("conversation_id")
        )
        if not session_id and context is not None:
            session_id = context.session_id or context.conversation_id
        if not session_id:
            return

        properties.setdefault("sessionID", session_id)
        properties.setdefault("conversation_id", session_id)

        normalized_todos = self._normalize_todo_items(properties.get("todos"))
        try:
            from penguin.web.services.session_view import update_session_todo

            persisted = update_session_todo(self, str(session_id), normalized_todos)
            if isinstance(persisted, list):
                normalized_todos = persisted
        except Exception:
            pass
        properties["todos"] = normalized_todos

        if "directory" not in properties:
            directory = context.directory if context is not None else None
            if not directory:
                session_dirs = getattr(self, "_opencode_session_directories", None)
                if isinstance(session_dirs, dict):
                    mapped = session_dirs.get(str(session_id))
                    if isinstance(mapped, str) and mapped.strip():
                        directory = mapped
            if directory:
                properties["directory"] = directory

        await self.event_bus.emit(
            "opencode_event",
            {
                "type": "todo.updated",
                "properties": properties,
            },
        )

    async def _on_tui_lsp_updated(self, event_type: str, data: Dict[str, Any]) -> None:
        if event_type != "lsp.updated":
            return
        properties = dict(data or {})
        context = get_current_execution_context()
        session_id = (
            properties.get("sessionID")
            or properties.get("session_id")
            or properties.get("conversation_id")
        )
        if not session_id and context is not None:
            session_id = context.session_id or context.conversation_id
        if session_id:
            properties.setdefault("sessionID", session_id)
            properties.setdefault("conversation_id", session_id)

        if "directory" not in properties:
            directory = context.directory if context is not None else None
            if not directory and session_id:
                session_dirs = getattr(self, "_opencode_session_directories", None)
                if isinstance(session_dirs, dict):
                    mapped = session_dirs.get(str(session_id))
                    if isinstance(mapped, str) and mapped.strip():
                        directory = mapped
            if directory:
                properties["directory"] = directory

        await self.event_bus.emit(
            "opencode_event",
            {
                "type": "lsp.updated",
                "properties": properties,
            },
        )

    async def _on_tui_lsp_diagnostics(
        self, event_type: str, data: Dict[str, Any]
    ) -> None:
        if event_type != "lsp.client.diagnostics":
            return
        properties = dict(data or {})
        context = get_current_execution_context()
        session_id = (
            properties.get("sessionID")
            or properties.get("session_id")
            or properties.get("conversation_id")
        )
        if not session_id and context is not None:
            session_id = context.session_id or context.conversation_id
        if session_id:
            properties.setdefault("sessionID", session_id)
            properties.setdefault("conversation_id", session_id)

        if "directory" not in properties:
            directory = context.directory if context is not None else None
            if not directory and session_id:
                session_dirs = getattr(self, "_opencode_session_directories", None)
                if isinstance(session_dirs, dict):
                    mapped = session_dirs.get(str(session_id))
                    if isinstance(mapped, str) and mapped.strip():
                        directory = mapped
            if directory:
                properties["directory"] = directory

        await self.event_bus.emit(
            "opencode_event",
            {
                "type": "lsp.client.diagnostics",
                "properties": properties,
            },
        )

    def _find_session_store(
        self, session_id: str
    ) -> tuple[Optional[Any], Optional[Any]]:
        """Locate session and owning session manager for a given session id."""
        if not session_id:
            return None, None

        manager_candidates: list[Any] = []
        conversation_manager = getattr(self, "conversation_manager", None)
        if conversation_manager is None:
            return None, None

        default_manager = getattr(conversation_manager, "session_manager", None)
        if default_manager is not None:
            manager_candidates.append(default_manager)

        agent_managers = getattr(conversation_manager, "agent_session_managers", {})
        if isinstance(agent_managers, dict):
            manager_candidates.extend(agent_managers.values())

        seen: set[int] = set()
        for manager in manager_candidates:
            manager_id = id(manager)
            if manager_id in seen:
                continue
            seen.add(manager_id)

            cached = getattr(manager, "sessions", {})
            if isinstance(cached, dict) and session_id in cached:
                session = cached[session_id][0]
                return session, manager

            index = getattr(manager, "session_index", {})
            if isinstance(index, dict) and session_id in index:
                try:
                    session = manager.load_session(session_id)
                except Exception:
                    session = None
                if session is not None:
                    return session, manager

        return None, None

    async def _persist_opencode_event(
        self, event_type: str, properties: Dict[str, Any]
    ) -> None:
        """Persist OpenCode message/part events for replay via session history."""
        if event_type not in {
            "message.updated",
            "message.part.updated",
            "message.part.removed",
            "message.removed",
        }:
            return

        session_id = properties.get("sessionID")
        if not session_id and isinstance(properties.get("part"), dict):
            session_id = properties["part"].get("sessionID")
        if not session_id or session_id == "unknown":
            return

        session, manager = self._find_session_store(session_id)
        if session is None or manager is None:
            return

        metadata = getattr(session, "metadata", None)
        if not isinstance(metadata, dict):
            return

        key = "_opencode_transcript_v1"
        transcript = metadata.get(key)
        if not isinstance(transcript, dict):
            transcript = {"messages": {}, "order": []}
            metadata[key] = transcript

        messages = transcript.get("messages")
        if not isinstance(messages, dict):
            messages = {}
            transcript["messages"] = messages

        order = transcript.get("order")
        if not isinstance(order, list):
            order = []
            transcript["order"] = order

        should_save = False

        if event_type == "message.updated":
            message_id = properties.get("id")
            if not message_id:
                return
            entry = messages.get(message_id)
            if not isinstance(entry, dict):
                entry = {}
            parts = entry.get("parts")
            if not isinstance(parts, dict):
                parts = {}
            part_order = entry.get("part_order")
            if not isinstance(part_order, list):
                part_order = []
            entry["info"] = dict(properties)
            entry["parts"] = parts
            entry["part_order"] = part_order
            messages[message_id] = entry
            if message_id not in order:
                order.append(message_id)

            time_data = properties.get("time")
            if isinstance(time_data, dict) and time_data.get("completed"):
                should_save = True

        elif event_type == "message.part.updated":
            part = properties.get("part")
            if not isinstance(part, dict):
                return

            message_id = part.get("messageID")
            part_id = part.get("id")
            if not message_id or not part_id:
                return

            entry = messages.get(message_id)
            if not isinstance(entry, dict):
                session_dirs = getattr(self, "_opencode_session_directories", {})
                mapped_directory = (
                    session_dirs.get(session_id)
                    if isinstance(session_dirs, dict)
                    else None
                )
                context = get_current_execution_context()
                context_directory = context.directory if context else None
                runtime_directory = getattr(
                    getattr(self, "runtime_config", None),
                    "active_root",
                    None,
                )
                fallback_directory = (
                    mapped_directory
                    or context_directory
                    or runtime_directory
                    or os.getenv("PENGUIN_CWD")
                    or os.getcwd()
                )
                entry = {
                    "info": {
                        "id": message_id,
                        "sessionID": session_id,
                        "role": "assistant",
                        "time": {"created": int(time.time() * 1000)},
                        "parentID": "root",
                        "modelID": getattr(
                            self.model_config, "model", "penguin-default"
                        ),
                        "providerID": getattr(self.model_config, "provider", "penguin"),
                        "mode": "chat",
                        "agent": "default",
                        "path": {"cwd": fallback_directory, "root": fallback_directory},
                        "cost": 0,
                        "tokens": {
                            "input": 0,
                            "output": 0,
                            "reasoning": 0,
                            "cache": {"read": 0, "write": 0},
                        },
                    },
                    "parts": {},
                    "part_order": [],
                }
                messages[message_id] = entry
                if message_id not in order:
                    order.append(message_id)

            parts = entry.get("parts")
            if not isinstance(parts, dict):
                parts = {}
                entry["parts"] = parts
            part_order = entry.get("part_order")
            if not isinstance(part_order, list):
                part_order = []
                entry["part_order"] = part_order

            parts[part_id] = dict(part)
            if part_id not in part_order:
                part_order.append(part_id)

            if part.get("type") == "tool":
                state = part.get("state")
                if isinstance(state, dict) and state.get("status") in {
                    "completed",
                    "error",
                }:
                    should_save = True

        elif event_type == "message.part.removed":
            message_id = properties.get("messageID")
            part_id = properties.get("partID")
            if not message_id or not part_id:
                return
            entry = messages.get(message_id)
            if not isinstance(entry, dict):
                return
            parts = entry.get("parts")
            if isinstance(parts, dict):
                parts.pop(part_id, None)
            part_order = entry.get("part_order")
            if isinstance(part_order, list):
                entry["part_order"] = [item for item in part_order if item != part_id]

        elif event_type == "message.removed":
            message_id = properties.get("messageID")
            if not message_id:
                return
            messages.pop(message_id, None)
            transcript["order"] = [item for item in order if item != message_id]

        try:
            manager.mark_session_modified(session_id)
            if should_save:
                manager.save_session(session)
        except Exception:
            logger.debug("Unable to persist OpenCode transcript event", exc_info=True)

    # ------------------------------------------------------------------
    # OpenCode TUI Adapter Integration
    # ------------------------------------------------------------------

    async def _emit_opencode_stream_start(
        self,
        agent_id: str = "default",
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
    ) -> Tuple[str, str]:
        """Initialize OpenCode streaming - creates Message and TextPart."""
        execution_context = get_current_execution_context()
        session_id = None
        if execution_context:
            session_id = (
                execution_context.session_id or execution_context.conversation_id
            )
        if not session_id:
            current_session = self.conversation_manager.get_current_session()
            session_id = current_session.id if current_session else "unknown"
        adapter = self._get_tui_adapter(session_id)
        message_id, part_id = await adapter.on_stream_start(
            agent_id, model_id, provider_id
        )
        self._opencode_message_adapters[message_id] = adapter
        return message_id, part_id

    async def _emit_opencode_stream_chunk(
        self, message_id: str, part_id: str, chunk: str, message_type: str = "assistant"
    ):
        """Emit OpenCode-compatible stream chunk with delta."""
        adapter = self._opencode_message_adapters.get(message_id, self._tui_adapter)
        await adapter.on_stream_chunk(message_id, part_id, chunk, message_type)

    async def _emit_opencode_stream_end(self, message_id: str, part_id: str):
        """Finalize OpenCode streaming."""
        adapter = self._opencode_message_adapters.pop(message_id, self._tui_adapter)
        await adapter.on_stream_end(message_id, part_id)

    def _latest_model_usage(self) -> Dict[str, Any]:
        """Return normalized usage metadata from active model handler."""
        handler = getattr(getattr(self, "api_client", None), "client_handler", None)
        getter = getattr(handler, "get_last_usage", None)
        if not callable(getter):
            return {}
        try:
            data = getter()
        except Exception:
            return {}
        return data if isinstance(data, dict) else {}

    async def _apply_opencode_usage_to_latest_message(
        self,
        session_id: Optional[str],
        usage: Dict[str, Any],
    ) -> None:
        if not isinstance(session_id, str) or not session_id.strip():
            return
        if not isinstance(usage, dict) or not usage:
            return

        message_id: Optional[str] = None
        states = getattr(self, "_opencode_stream_states", None)
        if isinstance(states, dict):
            state = states.get(session_id)
            if isinstance(state, dict):
                state_message_id = state.get("message_id")
                if isinstance(state_message_id, str) and state_message_id:
                    message_id = state_message_id

            if not message_id:
                scoped_prefix = f"{session_id}:"
                for key, state_value in states.items():
                    if not isinstance(key, str) or not key.startswith(scoped_prefix):
                        continue
                    if not isinstance(state_value, dict):
                        continue
                    state_message_id = state_value.get("message_id")
                    if isinstance(state_message_id, str) and state_message_id:
                        message_id = state_message_id
                        break

        adapter = (
            self._opencode_message_adapters.get(message_id) if message_id else None
        )
        if adapter is None:
            adapter = self._get_tui_adapter(session_id)

        if not message_id:
            adapter_message_id = getattr(adapter, "_current_message_id", None)
            if isinstance(adapter_message_id, str) and adapter_message_id:
                message_id = adapter_message_id

        if not isinstance(message_id, str) or not message_id:
            return

        updater = getattr(adapter, "update_assistant_usage", None)
        if not callable(updater):
            return

        tokens = {
            "input": int(usage.get("input_tokens", 0) or 0),
            "output": int(usage.get("output_tokens", 0) or 0),
            "reasoning": int(usage.get("reasoning_tokens", 0) or 0),
            "cache": {
                "read": int(usage.get("cache_read_tokens", 0) or 0),
                "write": int(usage.get("cache_write_tokens", 0) or 0),
            },
        }
        cost = usage.get("cost")
        try:
            normalized_cost = float(cost) if cost is not None else 0.0
        except Exception:
            normalized_cost = 0.0

        try:
            await updater(message_id, tokens=tokens, cost=max(normalized_cost, 0.0))
            usage_log = (
                "opencode.usage.applied session=%s message=%s input=%s output=%s "
                "reasoning=%s cache_read=%s cache_write=%s total=%s cost=%s"
            )
            usage_args = (
                session_id,
                message_id,
                tokens["input"],
                tokens["output"],
                tokens["reasoning"],
                tokens["cache"]["read"],
                tokens["cache"]["write"],
                int(usage.get("total_tokens", 0) or 0),
                max(normalized_cost, 0.0),
            )
            logger.info(usage_log, *usage_args)
            uvicorn_logger = logging.getLogger("uvicorn.error")
            if uvicorn_logger is not logger:
                uvicorn_logger.info(usage_log, *usage_args)
        except Exception:
            logger.debug("Failed to apply OpenCode usage metadata", exc_info=True)

    async def _emit_opencode_user_message(self, content: str) -> str:
        """Emit user message in OpenCode format."""
        execution_context = get_current_execution_context()
        session_id = None
        if execution_context:
            session_id = (
                execution_context.session_id or execution_context.conversation_id
            )
        if not session_id:
            current_session = self.conversation_manager.get_current_session()
            session_id = current_session.id if current_session else "unknown"
        adapter = self._get_tui_adapter(session_id)
        return await adapter.on_user_message(content)
