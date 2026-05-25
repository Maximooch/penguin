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
import copy
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
from penguin.llm.model_config import ModelConfig, fetch_model_specs
from .core_runtime import action_execution as core_action_execution
from .core_runtime import action_events as core_action_events
from .core_runtime import action_mapping as core_action_mapping
from .core_runtime import agent_lifecycle as core_agent_lifecycle
from .core_runtime import checkpoint_runtime as core_checkpoint_runtime
from .core_runtime import conversations as core_conversations
from .core_runtime import message_processing as core_message_processing
from .core_runtime import model_runtime as core_model_runtime
from .core_runtime import opencode_adapters as core_opencode_adapters
from .core_runtime import opencode_bridge as core_opencode_bridge
from .core_runtime import opencode_persistence as core_opencode_persistence
from .core_runtime import process_engine as core_process_engine
from .core_runtime import process_input as core_process_input
from .core_runtime import process_lifecycle as core_process_lifecycle
from .core_runtime import process_streaming as core_process_streaming
from .core_runtime import prompt_settings as core_prompt_settings
from .core_runtime import response_generation as core_response_generation
from .core_runtime import runmode_events as core_runmode_events
from .core_runtime import runmode_lifecycle as core_runmode_lifecycle
from .core_runtime import session_lookup as core_session_lookup
from .core_runtime import stream_events as core_stream_events
from .core_runtime import system_diagnostics as core_system_diagnostics
from .core_runtime import token_usage_runtime as core_token_usage_runtime
from penguin.llm.stream_handler import (
    StreamingStateManager,
    AgentStreamingStateManager,
    StreamingConfig,
)
from penguin.multi import routing as multi_routing

MODEL_CONFIG_FIELD_NAMES = {field.name for field in fields(ModelConfig)}

# Project manager
from penguin.project.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager
from penguin.system.execution_context import get_current_execution_context
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
    from penguin.config import RuntimeConfig

logger = logging.getLogger(__name__)
console = Console()

_SESSION_MODEL_ID_KEY = core_opencode_bridge.SESSION_MODEL_ID_KEY
_SESSION_PROVIDER_ID_KEY = core_opencode_bridge.SESSION_PROVIDER_ID_KEY
_SESSION_VARIANT_KEY = core_opencode_bridge.SESSION_VARIANT_KEY


def _trace_log_info(message: str, *args: Any) -> None:
    """Mirror core trace logs to uvicorn for live server debugging."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


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
                    previous_workspace = os.environ.get("PENGUIN_WORKSPACE")
                    if workspace_path:
                        os.environ["PENGUIN_WORKSPACE"] = str(
                            Path(workspace_path).expanduser().resolve()
                        )
                    try:
                        config = config or Config.load_config()
                    finally:
                        if workspace_path:
                            if previous_workspace is None:
                                os.environ.pop("PENGUIN_WORKSPACE", None)
                            else:
                                os.environ["PENGUIN_WORKSPACE"] = previous_workspace
                    if workspace_path:
                        config.workspace_path = (
                            Path(workspace_path).expanduser().resolve()
                        )

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
                        service_tier=getattr(config.model_config, "service_tier", None),
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

        workspace_path = Path(getattr(self.config, "workspace_path", WORKSPACE_PATH))

        self.project_manager = ProjectManager(workspace_path=workspace_path)

        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()

        # Initialize conversation manager (replaces conversation system)
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
            workspace_path=workspace_path,
            system_prompt=self.system_prompt,
            max_messages_per_session=DEFAULT_MAX_MESSAGES_PER_SESSION,
            max_sessions_in_memory=20,
            auto_save_interval=60,
            checkpoint_config=checkpoint_config,
            skills_config=self.config.to_dict()
            if hasattr(self.config, "to_dict")
            else {},
            project_root=getattr(self.tool_manager, "project_root", None),
        )
        # Attach a back-reference so Engine (and other helpers) can emit UI events
        # and finalize streaming messages via the Core. Without this the Engine
        # silently skips those steps which caused tool results to be lost and
        # streaming panels to merge into a single message in the CLI.
        self.conversation_manager.core = self  # type: ignore[attr-defined]

        # Inject core reference into tool_manager now that ConversationManager exists.
        if self.tool_manager and hasattr(self.tool_manager, "set_core"):
            self.tool_manager.set_core(self)

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
                self.engine.model_config = self.model_config  # type: ignore[attr-defined]
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

        # Ensure the active workspace is writable.
        self.validate_path(workspace_path)

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
        return core_prompt_settings.set_prompt_mode(
            self,
            mode,
            get_system_prompt=get_system_prompt,
            logger=logger,
        )

    def get_prompt_mode(self) -> str:
        """Return current prompt mode name."""
        return core_prompt_settings.get_prompt_mode(self)

    # ------------------------------------------------------------------
    # Output style control
    # ------------------------------------------------------------------
    def set_output_style(self, style: str) -> str:
        """Set output formatting style and rebuild system prompt.

        Styles: steps_final, plain, json_guided
        """
        from penguin.prompt.builder import set_output_formatting

        return core_prompt_settings.set_output_style(
            self,
            style,
            get_system_prompt=get_system_prompt,
            set_output_formatting=set_output_formatting,
            logger=logger,
        )

    def get_output_style(self) -> str:
        return core_prompt_settings.get_output_style(self)

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
        from penguin.agent.manager import get_persona_catalog

        return get_persona_catalog(self.config)

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
        """Compatibility shim for legacy persona-based agent registration.

        New code should use ``ensure_agent_conversation()``. This shim keeps
        older deterministic callers working while deriving agent state from
        conversation metadata and Engine registry entries.
        """
        from penguin.core_runtime.agent_lifecycle import register_agent_compat

        register_agent_compat(self, *args, **kwargs)

    def set_active_agent(self, agent_id: str) -> None:
        """Switch the active agent across ConversationManager and Engine."""
        core_agent_lifecycle.set_active_agent(self, agent_id)

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
        core_agent_lifecycle.set_agent_paused(self, agent_id, paused)

    def is_agent_paused(self, agent_id: str) -> bool:
        """Check if agent is paused via conversation metadata."""
        return core_agent_lifecycle.is_agent_paused(self, agent_id)

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
        return await core_agent_lifecycle.publish_sub_agent_session_created(
            self,
            agent_id,
            parent_agent_id=parent_agent_id,
            share_session=share_session,
        )

    def resolve_agent_execution_scope(
        self,
        agent_id: str,
        *,
        session_id: Optional[str] = None,
        directory: Optional[str] = None,
        agent_mode: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Resolve session-scoped execution context for an agent run."""
        return core_agent_lifecycle.resolve_agent_execution_scope(
            self,
            agent_id,
            session_id=session_id,
            directory=directory,
            agent_mode=agent_mode,
        )

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
        return await core_agent_lifecycle.run_agent_prompt_in_session(
            self,
            agent_id,
            prompt,
            session_id=session_id,
            directory=directory,
            agent_mode=agent_mode,
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
        return await multi_routing.route_message(
            self,
            recipient_id,
            content,
            message_type=message_type,
            metadata=metadata,
            agent_id=agent_id,
            channel=channel,
            logger=logger,
        )

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
        return await multi_routing.send_to_agent(
            self,
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def send_to_human(
        self,
        content: Any,
        *,
        message_type: str = "status",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a message to the human (UI) via Engine."""
        return await multi_routing.send_to_human(
            self,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

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
        return await multi_routing.human_reply(
            self,
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

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
        return core_agent_lifecycle.smoke_check_agents(self)

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
        await core_stream_events.emit_opencode_session_status(
            self,
            session_id,
            status_type,
            info=info,
        )

    async def abort_session(self, session_id: str) -> bool:
        """Abort active streaming/tool state for a session."""
        return await core_stream_events.abort_session(self, session_id, logger=logger)

    def get_token_usage(
        self,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Return runtime or scoped token/context-window telemetry.

        Args:
            session_id: Optional session identifier to scope usage. Takes
                precedence over the runtime context window and never falls back
                to runtime usage when not found.
            conversation_id: Optional conversation identifier. Used as the
                lookup id when ``session_id`` is absent and echoed in scoped
                responses.
            agent_id: Optional agent identifier. When scoped usage is requested,
                filters messages by ``Message.agent_id`` or uses an isolated
                session whose metadata owner matches this id. Missing ownership
                returns ``scope="missing"`` instead of whole-session totals.

        Returns:
            Dict[str, Any]: Runtime calls return ``scope="runtime"`` plus the
            conversation manager's legacy usage fields. Scoped calls return
            ``scope="session"``, ``session_id``, ``conversation_id``, optional
            ``agent_id``, ``current_total_tokens``,
            ``max_context_window_tokens``, ``available_tokens``, ``percentage``,
            ``categories``, and ``truncations``. Missing scoped lookups return
            ``scope="missing"`` with identifiers and ``error`` for HTTP layers
            to translate to 404.

        Raises:
            None. Runtime telemetry failures are logged and return zeroed
            runtime usage; missing scoped lookups are returned as data.
        """

        return core_token_usage_runtime.get_token_usage(
            self,
            session_id=session_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )

    def _get_session_token_usage(
        self,
        session_id: str,
        *,
        conversation_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Return usage for one persisted session without global fallback."""

        return core_token_usage_runtime.get_session_token_usage(
            self,
            session_id,
            conversation_id=conversation_id,
            agent_id=agent_id,
        )

    def _usage_from_session_messages(
        self,
        session: Any,
        *,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Build a conservative session-scoped usage payload from messages."""

        return core_token_usage_runtime.usage_from_session_messages(
            self,
            session,
            agent_id=agent_id,
        )

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
        return core_model_runtime.configure_llm_client(
            self,
            base_url=base_url,
            link_user_id=link_user_id,
            link_session_id=link_session_id,
            link_agent_id=link_agent_id,
            link_workspace_id=link_workspace_id,
            link_api_key=link_api_key,
        )

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
        return await core_message_processing.process_message(
            self,
            message=message,
            context=context,
            conversation_id=conversation_id,
            agent_id=agent_id,
            context_files=context_files,
            streaming=streaming,
            resolve_conversation_manager=(
                core_conversations.resolve_conversation_manager
            ),
            log_error=log_error,
            log=logger,
        )

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
        return await core_response_generation.get_response(
            self,
            current_iteration=current_iteration,
            max_iterations=max_iterations,
            stream_callback=stream_callback,
            streaming=streaming,
            process_response_actions=core_action_execution.process_response_actions,
            sleep=asyncio.sleep,
            log_error=log_error,
            log=logger,
        )

    async def execute_action(self, action) -> Dict[str, Any]:
        """Execute an action and return structured result"""
        return await core_action_execution.execute_action(self, action)

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
        return await core_checkpoint_runtime.create_checkpoint(
            self.conversation_manager,
            name=name,
            description=description,
        )

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Rollback conversation to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            True if successful, False otherwise
        """
        return await core_checkpoint_runtime.rollback_to_checkpoint(
            self.conversation_manager,
            checkpoint_id,
        )

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
        return await core_checkpoint_runtime.branch_from_checkpoint(
            self.conversation_manager,
            checkpoint_id,
            name=name,
            description=description,
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
        return core_checkpoint_runtime.list_checkpoints(
            self.conversation_manager,
            session_id=session_id, limit=limit
        )

    async def cleanup_old_checkpoints(self) -> int:
        """
        Clean up old checkpoints according to retention policy.

        Returns:
            Number of checkpoints cleaned up
        """
        return await core_checkpoint_runtime.cleanup_old_checkpoints(
            self.conversation_manager
        )

    def get_checkpoint_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the checkpointing system.

        Returns:
            Dictionary with checkpoint statistics
        """
        return core_checkpoint_runtime.get_checkpoint_stats(
            self.conversation_manager
        )

    # System Diagnostics and Information API
    # ------------------------------------------------------------------

    def get_system_info(self) -> Dict[str, Any]:
        """
        Get comprehensive system information.

        Returns:
            Dictionary containing system information including model config,
            component status, and capabilities
        """
        return core_system_diagnostics.get_system_info(
            self,
            version=PENGUIN_VERSION,
            logger=logger,
        )

    def get_system_status(self) -> Dict[str, Any]:
        """
        Get current system status including runtime state.

        Returns:
            Dictionary containing current system status and runtime information
        """
        return core_system_diagnostics.get_system_status(self, logger=logger)

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
        max_iterations: int = MAX_TASK_ITERATIONS,  # Use config value (default 5000) #TODO:247 mode and other loops need to be infinite.
        context_files: Optional[List[str]] = None,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        multi_step: bool = True,
        api_client_override: Optional[APIClient] = None,
        model_config_override: Optional[ModelConfig] = None,
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
            max_iterations: Maximum reasoning-action cycles (default: 5) #TODO:247 mode and other loops need to be infinite.
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses.
            stream_callback: Optional callback function for handling streaming output chunks.
            multi_step: If True, use the multi-step `run_task` engine. Defaults to True.

        Returns:
            Dict containing assistant response and action results
        """
        process_input = core_process_input.normalize_process_input(input_data)
        message = process_input.message
        image_paths = process_input.image_paths
        client_message_id = process_input.client_message_id

        if process_input.is_empty:
            return {"assistant_response": "No input provided", "action_results": []}
        conversation_manager = core_conversations.resolve_conversation_manager(
            self,
            agent_id,
            log=logger,
        )

        execution_context = get_current_execution_context()
        request_session_id = (
            execution_context.session_id
            if execution_context and execution_context.session_id
            else conversation_id
        )
        scoped_conversation = getattr(conversation_manager, "conversation", None)
        scoped_session_before = getattr(
            getattr(scoped_conversation, "session", None), "id", None
        )
        _trace_log_info(
            "core.process.trace.start request=%s session=%s conversation=%s agent=%s cm=%s conv=%s conv_session=%s msg_len=%s context_files=%s images=%s streaming=%s multi_step=%s",
            execution_context.request_id if execution_context else "unknown",
            request_session_id or "unknown",
            conversation_id or "",
            agent_id or "default",
            hex(id(conversation_manager)),
            hex(id(scoped_conversation)) if scoped_conversation is not None else "none",
            scoped_session_before or "unknown",
            len(message or ""),
            len(context_files or []),
            len(image_paths or []),
            streaming,
            multi_step,
        )
        request_task = asyncio.current_task()
        request_tracked = (
            await core_process_lifecycle.register_opencode_process_request(
                self,
                request_session_id,
                request_task,
            )
        )

        try:
            if conversation_id:
                load_result = core_conversations.load_process_conversation(
                    conversation_manager,
                    conversation_id,
                    log=logger,
                )
                _trace_log_info(
                    "core.process.trace.load request=%s session=%s conversation=%s via=%s ok=%s conv_session=%s",
                    execution_context.request_id if execution_context else "unknown",
                    request_session_id or "unknown",
                    conversation_id,
                    load_result.via,
                    load_result.ok,
                    load_result.scoped_session_id or "unknown",
                )

            context_file_count = core_conversations.load_process_context_files(
                conversation_manager,
                context_files,
            )
            if context_file_count:
                _trace_log_info(
                    "core.process.trace.context request=%s session=%s conversation=%s count=%s",
                    execution_context.request_id if execution_context else "unknown",
                    request_session_id or "unknown",
                    conversation_id or "",
                    context_file_count,
                )

            await core_process_lifecycle.emit_process_user_message(
                self,
                message,
                message_category=MessageCategory.DIALOG,
                client_message_id=client_message_id,
                agent_id=agent_id,
                log=logger,
            )

            # Use new Engine layer if available
            if self.engine:
                execution_context = get_current_execution_context()
                engine_process_context = (
                    core_process_streaming.prepare_engine_process_context(
                        self,
                        conversation_manager=conversation_manager,
                        conversation_id=conversation_id,
                        agent_id=agent_id,
                        streaming=streaming,
                        stream_callback=stream_callback,
                        execution_context=execution_context,
                        log=logger,
                    )
                )
                engine_stream_callback = engine_process_context.stream_callback
                scoped_conversation_id = (
                    engine_process_context.scoped_conversation_id
                )
                response = await core_process_engine.run_engine_process(
                    self,
                    message=message,
                    image_paths=image_paths,
                    max_iterations=max_iterations,
                    context=context,
                    multi_step=multi_step,
                    streaming=streaming,
                    stream_callback=stream_callback,
                    engine_stream_callback=engine_stream_callback,
                    agent_id=agent_id,
                    api_client_override=api_client_override,
                    model_config_override=model_config_override,
                    conversation_manager=conversation_manager,
                    execution_context=execution_context,
                    request_session_id=request_session_id,
                    scoped_conversation_id=scoped_conversation_id,
                    trace_log_info=_trace_log_info,
                )
                _trace_log_info(
                    "core.process.trace.done request=%s session=%s conversation=%s status=%s iterations=%s actions=%s usage=%s response_len=%s",
                    execution_context.request_id if execution_context else "unknown",
                    request_session_id or "unknown",
                    scoped_conversation_id if self.engine else (conversation_id or ""),
                    response.get("status") if isinstance(response, dict) else None,
                    response.get("iterations") if isinstance(response, dict) else None,
                    len(response.get("action_results", []) or [])
                    if isinstance(response, dict)
                    else None,
                    response.get("usage") if isinstance(response, dict) else None,
                    len(response.get("assistant_response", "") or "")
                    if isinstance(response, dict)
                    else None,
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

            await core_process_lifecycle.finalize_process_response(
                self,
                conversation_manager,
                response,
                request_session_id,
                streaming=streaming,
                agent_id=agent_id,
                collect_token_usage=(
                    core_token_usage_runtime.collect_process_token_usage
                ),
                message_category=MessageCategory.DIALOG,
                log=logger,
            )

            return response

        except asyncio.CancelledError:
            core_process_lifecycle.discard_opencode_abort_session(
                self,
                request_session_id,
            )
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
            await core_process_lifecycle.finalize_opencode_process_request(
                self,
                request_session_id,
                request_task,
                request_tracked=request_tracked,
            )

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
        return core_conversations.list_conversations(
            self.conversation_manager,
            limit=limit,
            offset=offset,
            search_term=search_term,
        )

    def get_conversation(self, conversation_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific conversation by ID.

        Args:
            conversation_id: ID of the conversation to retrieve

        Returns:
            Conversation data or None if not found
        """
        return core_conversations.get_conversation(
            self.conversation_manager,
            conversation_id,
        )

    def get_conversation_history(
        self,
        conversation_id: str,
        *,
        include_system: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        return core_conversations.get_conversation_history(
            self.conversation_manager,
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
        return core_conversations.create_conversation(self.conversation_manager)

    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.

        Args:
            conversation_id: ID of the conversation to delete

        Returns:
            True if successful, False otherwise
        """
        return core_conversations.delete_conversation(
            self.conversation_manager,
            conversation_id,
        )

    def get_conversation_stats(self) -> Dict[str, Any]:
        """
        Get statistics about conversations.

        Returns:
            Dictionary with conversation statistics
        """
        return core_conversations.get_conversation_stats(self.conversation_manager)

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
        await core_runmode_lifecycle.start_run_mode(
            self,
            name=name,
            description=description,
            context=context,
            continuous=continuous,
            time_limit=time_limit,
            mode_type=mode_type,
            stream_callback_for_cli=stream_callback_for_cli,
            ui_update_callback_for_cli=ui_update_callback_for_cli,
            run_mode_factory=RunMode,
            log_error=log_error,
            logger=logger,
        )

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------

    def refresh_api_client(self) -> None:
        """Recreate the active API client using the current model config."""
        core_model_runtime.refresh_api_client(
            self,
            api_client_factory=APIClient,
            log=logger,
        )

    def _apply_new_model_config(
        self, new_model_config: ModelConfig, context_window_tokens: Optional[int] = None
    ) -> None:
        """Swap model configuration and rewire dependent runtime components.

        This keeps the public ``load_model`` method concise and focused on
        validation / construction of the ``ModelConfig``.  All mutation of
        run-time state happens here so that we only need to test it in one
        place.

        Args:
            new_model_config: The new ModelConfig to apply
            context_window_tokens: The safe context window size (85% of raw) to apply
        """
        core_model_runtime.apply_new_model_config(
            self,
            new_model_config,
            context_window_tokens=context_window_tokens,
            refresh_active_client=self.refresh_api_client,
            log=logger,
        )

    async def _build_model_config_for_model(
        self, model_id: str
    ) -> tuple[ModelConfig, Optional[int]]:
        """Resolve a runtime model id into a concrete ModelConfig without mutating global state."""
        return await core_model_runtime.build_model_config_for_model(
            model_id,
            model_configs=getattr(self.config, "model_configs", None),
            current_model_config=getattr(self, "model_config", None),
            fetch_specs=fetch_model_specs,
            resolve_provider=self._resolve_model_provider,
        )

    async def resolve_request_runtime(
        self,
        model_id: Optional[str] = None,
    ) -> tuple[ModelConfig, APIClient]:
        """Build a request-scoped model config and API client without mutating global state."""
        current_model = (
            self.get_current_model() if hasattr(self, "get_current_model") else {}
        )
        current_raw = (
            str(current_model.get("model") or "").strip()
            if isinstance(current_model, dict)
            else ""
        )
        current_provider = (
            str(current_model.get("provider") or "").strip()
            if isinstance(current_model, dict)
            else ""
        )
        current_qualified = (
            f"{current_provider}/{current_raw}"
            if current_provider and current_raw
            else ""
        )

        requested_model = model_id.strip() if isinstance(model_id, str) else ""
        if requested_model and requested_model not in {current_raw, current_qualified}:
            new_model_config, _ = await self._build_model_config_for_model(
                requested_model
            )
        else:
            new_model_config = copy.deepcopy(self.model_config)

        api_client = APIClient(model_config=new_model_config)
        api_client.set_system_prompt(self.system_prompt)
        return new_model_config, api_client

    async def load_model(self, model_id: str) -> bool:
        """Replace the active model at runtime.

        The *model_id* argument can be either:
        1. A key present in ``config.yml -> model_configs``
        2. A fully-qualified model string of the form ``<provider>/<model_name>``.

        Returns ``True`` on success, ``False`` otherwise.
        """
        self._last_model_load_error = None

        try:
            new_model_config, safe_window = await self._build_model_config_for_model(
                model_id
            )
            self._apply_new_model_config(
                new_model_config, context_window_tokens=safe_window
            )

            logger.info(
                f"Switched to model '{new_model_config.model}' (context: {safe_window} tokens, vision: {new_model_config.vision_enabled})"
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
        return core_model_runtime.canonicalize_runtime_model_id(
            model_id,
            provider,
            client_preference,
        )

    def _resolve_model_provider(self, model_id: str) -> tuple[Optional[str], str]:
        """Resolve provider and client preference for a model ID.

        Returns:
            Tuple of (provider, client_preference), or (None, "") on error.
        """
        return core_model_runtime.resolve_model_provider(
            model_id,
            getattr(self.config, "model_configs", None),
            current_client_preference=(
                self.model_config.client_preference if self.model_config else None
            ),
        )

    def list_available_models(self) -> List[Dict[str, Any]]:
        """Return a list of model metadata derived from ``config.yml``.

        This helper is intentionally lightweight so it can be called at any
        time without additional network requests.  Richer model discovery (e.g.
        OpenRouter catalogue) is handled in *PenguinInterface*.
        """
        current_model_name = self.model_config.model if self.model_config else None
        return core_model_runtime.list_available_models(
            getattr(self.config, "model_configs", None),
            current_model_name=current_model_name,
        )

    def get_current_model(self) -> Optional[Dict[str, Any]]:
        """
        Get information about the currently loaded model.

        Returns:
            Dictionary with current model information, or None if no model is loaded
        """
        if not self.model_config:
            return None

        return core_model_runtime.current_model_payload(self.model_config)

    async def emit_ui_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event through the unified event bus.

        Filters internal markers from content before emitting to UI.

        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update", etc.)
            data: Event data relevant to the event type
        """
        await core_stream_events.emit_ui_event(
            self,
            event_type,
            data,
            logger=logger,
        )

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
        return core_stream_events.filter_internal_markers_from_event(data)

    def _resolve_stream_scope_id(
        self,
        execution_context: Optional[Any],
        agent_id: Optional[str],
    ) -> str:
        """Resolve stream-state key for concurrent session isolation."""
        return core_stream_events.resolve_stream_scope_id(
            conversation_manager=getattr(self, "conversation_manager", None),
            execution_context=execution_context,
            agent_id=agent_id,
        )

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
        await core_stream_events.handle_stream_chunk(
            self,
            chunk,
            message_type=message_type,
            role=role,
            agent_id=agent_id,
            stream_scope_id=stream_scope_id,
            session_id=session_id,
            conversation_id=conversation_id,
            logger=logger,
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
        return core_stream_events.finalize_streaming_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            stream_scope_id=stream_scope_id,
            logger=logger,
            trace_log=_trace_log_info,
        )

    def abort_streaming_message(
        self,
        agent_id: Optional[str] = None,
        session_id: Optional[str] = None,
        conversation_id: Optional[str] = None,
        stream_scope_id: Optional[str] = None,
    ) -> bool:
        """Abort an uncommitted streaming message without persisting dialog."""
        return core_stream_events.abort_streaming_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            conversation_id=conversation_id,
            stream_scope_id=stream_scope_id,
            trace_log=_trace_log_info,
        )

    def _persist_finalized_message(
        self,
        *,
        agent_id: str,
        session_id: Optional[str],
        message: Message,
        category: MessageCategory,
    ) -> bool:
        """Persist a finalized streaming message without reloading shared conversations."""
        return core_stream_events.persist_finalized_message(
            self,
            agent_id=agent_id,
            session_id=session_id,
            message=message,
            category=category,
            trace_log=_trace_log_info,
        )

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
        await core_runmode_events.handle_run_mode_event(self, event, logger=logger)

    def get_startup_stats(self) -> Dict[str, Any]:
        """Get comprehensive startup performance statistics."""
        return core_system_diagnostics.get_startup_stats(self, profiler=profiler)

    def print_startup_report(self) -> None:
        """Print a comprehensive startup performance report."""
        core_system_diagnostics.print_startup_report(self, profiler=profiler)

    def enable_fast_startup_globally(self) -> None:
        """Enable fast startup mode for future operations."""
        core_system_diagnostics.enable_fast_startup_globally(self, logger=logger)

    def get_memory_provider_status(self) -> Dict[str, Any]:
        """Get current status of memory provider and indexing."""
        return core_system_diagnostics.get_memory_provider_status(self)

    def _subscribe_to_stream_events(self):
        """Subscribe to Penguin stream events and translate to OpenCode format."""
        core_stream_events.subscribe_to_stream_events(self)

    def _get_tui_adapter(self, session_id: Optional[str]) -> Any:
        """Return a session-scoped TUI adapter to avoid cross-session bleed."""
        return core_opencode_adapters.get_tui_adapter(
            self,
            session_id,
            execution_context=get_current_execution_context(),
        )

    async def _on_tui_stream_chunk(self, event_type: str, data: Dict[str, Any]):
        """Handle stream chunk - manages stream lifecycle and emits with delta."""
        await core_stream_events.handle_tui_stream_chunk(
            self,
            event_type,
            data,
            logger=logger,
        )

    def _strip_diff_fences(self, diff_content: str) -> str:
        return core_action_mapping.strip_diff_fences(diff_content)

    def _ensure_unified_diff(self, file_path: str, diff_content: str) -> str:
        return core_action_mapping.ensure_unified_diff(file_path, diff_content)

    def _extract_unified_diff_from_result(self, result: Any) -> str:
        return core_action_mapping.extract_unified_diff_from_result(result)

    def _extract_tool_file_path(self, tool_input: Any) -> str:
        return core_action_mapping.extract_tool_file_path(tool_input)

    def _normalize_todo_items(self, value: Any) -> list[Dict[str, str]]:
        return core_action_mapping.normalize_todo_items(value)

    def _extract_todos_from_result(self, result: Any) -> list[Dict[str, str]]:
        return core_action_mapping.extract_todos_from_result(result)

    def _parse_action_payload(self, params: Any) -> Dict[str, Any]:
        return core_action_mapping.parse_action_payload(params)

    def _extract_result_file_paths(self, result: Any) -> list[str]:
        return core_action_mapping.extract_result_file_paths(result)

    def _humanize_subagent_name(self, value: Any) -> str:
        return core_action_mapping.humanize_subagent_name(value)

    def _summarize_subagent_description(self, value: Any, fallback: str) -> str:
        return core_action_mapping.summarize_subagent_description(value, fallback)

    def _build_task_card_summary(
        self,
        label: str,
        status: str,
        *,
        item_id: Optional[str] = None,
        title: Optional[str] = None,
    ) -> list[Dict[str, Any]]:
        return core_action_mapping.build_task_card_summary(
            label,
            status,
            item_id=item_id,
            title=title,
        )

    def _summary_status(self, metadata: Dict[str, Any], default: str) -> str:
        return core_action_mapping.summary_status(metadata, default)

    def _build_spawn_subagent_task_card(
        self, params: Any
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        return core_action_mapping.build_spawn_subagent_task_card(params)

    def _map_action_to_tool(
        self, action: str, params: Any
    ) -> Tuple[str, Dict[str, Any], Dict[str, Any]]:
        return core_action_mapping.map_action_to_tool(action, params)

    def _map_action_result_metadata(
        self,
        action: str,
        result: Any,
        existing: Optional[Dict[str, Any]] = None,
        tool_input: Optional[Dict[str, Any]] = None,
        status: Optional[str] = None,
        event_metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        return core_action_mapping.map_action_result_metadata(
            action,
            result,
            existing=existing,
            tool_input=tool_input,
            status=status,
            event_metadata=event_metadata,
        )

    async def _on_tui_action(self, event_type: str, data: Dict[str, Any]) -> None:
        await core_action_events.handle_tui_action(self, event_type, data)

    async def _on_tui_action_result(
        self, event_type: str, data: Dict[str, Any]
    ) -> None:
        await core_action_events.handle_tui_action_result(self, event_type, data)

    async def _on_tui_todo_updated(self, event_type: str, data: Dict[str, Any]) -> None:
        await core_action_events.handle_tui_todo_updated(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    async def _on_tui_lsp_updated(self, event_type: str, data: Dict[str, Any]) -> None:
        await core_action_events.handle_tui_lsp_updated(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    async def _on_tui_lsp_diagnostics(
        self, event_type: str, data: Dict[str, Any]
    ) -> None:
        await core_action_events.handle_tui_lsp_diagnostics(
            self,
            event_type,
            data,
            execution_context=get_current_execution_context(),
            session_directories=getattr(self, "_opencode_session_directories", None),
        )

    def _find_session_store(
        self, session_id: str
    ) -> tuple[Optional[Any], Optional[Any]]:
        """Locate session and owning session manager for a given session id."""
        return core_session_lookup.find_session_store(self, session_id)

    def _resolve_opencode_model_state(
        self,
        *,
        session_id: Optional[str] = None,
        model_id: Optional[str] = None,
        provider_id: Optional[str] = None,
        variant: Optional[str] = None,
    ) -> Dict[str, Optional[str]]:
        """Resolve model/provider/variant for OpenCode event persistence."""
        return core_opencode_persistence.resolve_opencode_model_state(
            self,
            session_id=session_id,
            model_id=model_id,
            provider_id=provider_id,
            variant=variant,
        )

    async def _persist_opencode_event(
        self, event_type: str, properties: Dict[str, Any]
    ) -> None:
        """Persist OpenCode message/part events for replay via session history."""
        await core_opencode_persistence.persist_opencode_event(
            self,
            event_type=event_type,
            properties=properties,
            logger=logger,
            execution_context=get_current_execution_context(),
        )

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
        return await core_stream_events.emit_opencode_stream_start(
            self,
            agent_id=agent_id,
            model_id=model_id,
            provider_id=provider_id,
            execution_context=get_current_execution_context(),
        )

    async def _emit_opencode_stream_chunk(
        self, message_id: str, part_id: str, chunk: str, message_type: str = "assistant"
    ):
        """Emit OpenCode-compatible stream chunk with delta."""
        await core_stream_events.emit_opencode_stream_chunk(
            self,
            message_id,
            part_id,
            chunk,
            message_type,
        )

    async def _emit_opencode_stream_end(self, message_id: str, part_id: str):
        """Finalize OpenCode streaming."""
        await core_stream_events.emit_opencode_stream_end(self, message_id, part_id)

    def _latest_model_usage(self) -> Dict[str, Any]:
        """Return normalized usage metadata from active model handler."""
        return core_opencode_bridge.latest_model_usage(
            getattr(self, "api_client", None)
        )

    async def _apply_opencode_usage_to_latest_message(
        self,
        session_id: Optional[str],
        usage: Dict[str, Any],
    ) -> None:
        uvicorn_logger = logging.getLogger("uvicorn.error")
        extra_loggers = (uvicorn_logger,) if uvicorn_logger is not logger else ()
        await core_opencode_bridge.apply_usage_to_latest_message(
            session_id,
            usage,
            stream_states=getattr(self, "_opencode_stream_states", None),
            message_adapters=getattr(self, "_opencode_message_adapters", None),
            get_adapter=self._get_tui_adapter,
            logger=logger,
            extra_loggers=extra_loggers,
        )

    async def _emit_opencode_user_message(self, content: str) -> str:
        """Emit user message in OpenCode format."""
        return await self._emit_opencode_user_message_with_metadata(content)

    async def _emit_opencode_user_message_with_metadata(
        self,
        content: str,
        *,
        message_id: Optional[str] = None,
        agent_id: Optional[str] = None,
    ) -> str:
        """Emit user message in OpenCode format with stable message metadata."""
        return await core_stream_events.emit_opencode_user_message_with_metadata(
            self,
            content,
            message_id=message_id,
            agent_id=agent_id,
            execution_context=get_current_execution_context(),
        )
