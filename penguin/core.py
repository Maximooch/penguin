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
from penguin.llm.stream_handler import StreamingStateManager, StreamingConfig

MODEL_CONFIG_FIELD_NAMES = {field.name for field in fields(ModelConfig)}

# Project manager
from penguin.project.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory, Message

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt
# Workflow Prompt
from penguin.prompt_workflow import PENGUIN_WORKFLOW

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.callbacks import adapt_stream_callback
from penguin.utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
from penguin.utils.log_error import log_error
from penguin.utils.parser import ActionExecutor, parse_action
from penguin.utils.profiling import profile_startup_phase, profile_operation, profiler, print_startup_report

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
        show_progress: bool = True, # what is this again?
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        fast_startup: bool = True  # Default True for faster startup (defers memory indexing)
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        """
        Factory method for creating PenguinCore instance.
        Returns either PenguinCore alone or with CLI if enable_cli=True

        Args:
            fast_startup: If True (default), defer heavy operations like memory indexing until first use
        """
        # Fix HuggingFace tokenizers parallelism warning early, before any model loading
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        
        pbar = None # Initialize pbar to None
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
                    if pbar: pbar.set_description("Loading environment")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Loading environment")
                    # load_dotenv() is already invoked centrally in config.py at import time.
                    # Calling it again here is redundant and can subtly override earlier values.
                    # Intentionally no-op.
                    if pbar: pbar.update(1)
                    log_step_time("Load environment")

                # Step 2: Initialize logging
                with profile_startup_phase("Setup logging"):
                    logger.info("STARTUP: Setting up logging configuration")
                    if pbar: pbar.set_description("Setting up logging")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Setting up logging")
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
                    if pbar: pbar.update(1)
                    log_step_time("Setup logging")

                # Load configuration
                with profile_startup_phase("Load configuration"):
                    logger.info("STARTUP: Loading and parsing configuration")
                    if pbar: pbar.set_description("Loading configuration")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Loading configuration")
                    start_config_time = time.time()
                    config = config or Config.load_config()
                    
                    # Use fast_startup from config if not explicitly set
                    if fast_startup is False and hasattr(config, 'fast_startup'):
                        fast_startup = config.fast_startup
                        
                    logger.info(f"STARTUP: Config loaded in {time.time() - start_config_time:.4f}s")
                    if pbar: pbar.update(1)
                    log_step_time("Load configuration")

                # Initialize model configuration
                with profile_startup_phase("Create model config"):
                    logger.info("STARTUP: Creating model configuration")
                    if pbar: pbar.set_description("Creating model config")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Creating model config")
                    # Source of truth for runtime model settings is the live Config.model_config.
                    # Allow explicit overrides via function args for tests/CLI.
                    model_config = ModelConfig(
                        model=(
                            model
                            or getattr(config.model_config, 'model', DEFAULT_MODEL)
                        ),
                        provider=(
                            provider
                            or getattr(config.model_config, 'provider', DEFAULT_PROVIDER)
                        ),
                        api_base=(
                            getattr(config.model_config, 'api_base', None)
                            or (config.api.base_url if hasattr(config, 'api') and hasattr(config.api, 'base_url') else None)
                        ),
                        use_assistants_api=bool(getattr(config.model_config, 'use_assistants_api', False)),
                        client_preference=getattr(config.model_config, 'client_preference', 'native'),
                        streaming_enabled=bool(getattr(config.model_config, 'streaming_enabled', True)),
                        # Generation cap should be the configured model's value; do not substitute context window here
                        max_output_tokens=getattr(
                            config.model_config,
                            "max_output_tokens",
                            getattr(config.model_config, "max_output_tokens", getattr(config.model_config, "max_tokens", None)),  # Prefer new name
                        ),
                        max_context_window_tokens=getattr(
                            config.model_config, "max_context_window_tokens", None
                        ),
                    )
                    logger.info(f"STARTUP: Using model={model_config.model}, provider={model_config.provider}, client={model_config.client_preference}")
                    if pbar: pbar.update(1)
                    log_step_time("Create model config")

                # Create API client
                with profile_startup_phase("Initialize API client"):
                    logger.info("STARTUP: Initializing API client")
                    if pbar: pbar.set_description("Initializing API client")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Initializing API client")
                    # Ensure .env files are loaded before API client needs API keys
                    _ensure_env_loaded()
                    api_client_start = time.time()
                    api_client = APIClient(model_config=model_config)
                    api_client.set_system_prompt(SYSTEM_PROMPT)
                    logger.info(f"STARTUP: API client initialized in {time.time() - api_client_start:.4f}s")
                    if pbar: pbar.update(1)
                    log_step_time("Initialize API client")

                # Initialize tool manager
                with profile_startup_phase("Create tool manager"):
                    logger.info(f"STARTUP: Creating tool manager (fast_startup={fast_startup})")
                    if pbar: pbar.set_description("Creating tool manager")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Creating tool manager")
                    tool_manager_start = time.time()
                    print("DEBUG: Creating ToolManager in PenguinCore...")
                    print(f"DEBUG: Passing config of type {type(config)} to ToolManager.")
                    print(f"DEBUG: Passing log_error of type {type(log_error)} to ToolManager.")
                    print(f"DEBUG: Fast startup mode: {fast_startup}")
                    # Provide ToolManager with a deterministic dict derived from the live Config
                    try:
                        config_dict = config.to_dict() if hasattr(config, 'to_dict') else {}
                    except Exception:
                        config_dict = {}
                    tool_manager = ToolManager(config_dict, log_error, fast_startup=fast_startup)
                    logger.info(f"STARTUP: Tool manager created in {time.time() - tool_manager_start:.4f}s with {len(tool_manager.tools) if hasattr(tool_manager, 'tools') else 'unknown'} tools")
                    if pbar: pbar.update(1)
                    log_step_time("Create tool manager")

                # Create core instance
                with profile_startup_phase("Create core instance"):
                    logger.info("STARTUP: Creating core instance")
                    if pbar: pbar.set_description("Creating core instance")
                    if progress_callback:
                        current_step_index += 1
                        progress_callback(current_step_index, total_steps, "Creating core instance")
                    core_start = time.time()
                    instance = cls(
                        config=config, 
                        api_client=api_client, 
                        tool_manager=tool_manager, 
                        model_config=model_config
                    )
                    logger.info(f"STARTUP: Core instance created in {time.time() - core_start:.4f}s")
                    if pbar: pbar.update(1)
                    log_step_time("Create core instance")

                if enable_cli:
                    with profile_startup_phase("Initialize CLI"):
                        logger.info("STARTUP: Initializing CLI")
                        if pbar: pbar.set_description("Initializing CLI")
                        if progress_callback:
                            current_step_index += 1
                            progress_callback(current_step_index, total_steps, "Initializing CLI")
                        cli_start = time.time()
                        from penguin.chat.cli import PenguinCLI
                        cli = PenguinCLI(instance)
                        logger.info(f"STARTUP: CLI initialized in {time.time() - cli_start:.4f}s")
                        if pbar: pbar.update(1)
                        log_step_time("Initialize CLI")

                if pbar: pbar.close()
                # Ensure external progress finishes
                if progress_callback and current_step_index < total_steps:
                    progress_callback(total_steps, total_steps, "Initialization complete")

                total_time = time.time() - overall_start_time
                logger.info(f"STARTUP COMPLETE: Total initialization time: {total_time:.4f} seconds")
                
                # Log summary of all timing measurements
                logger.info("STARTUP TIMING SUMMARY:")
                for step, duration in timings.items():
                    percentage = (duration / total_time) * 100
                    logger.info(f"  - {step}: {duration:.4f}s ({percentage:.1f}%)")

                # Print comprehensive profiling report if enabled
                if fast_startup:
                    logger.info("FAST STARTUP enabled - memory indexing deferred to first use")
                
                # Log tool manager stats
                tool_stats = tool_manager.get_startup_stats()
                logger.info(f"ToolManager startup stats: {tool_stats}")

                return instance if not enable_cli else (instance, cli)

        except Exception as e:
            error_time = time.time() - overall_start_time
            logger.error(f"STARTUP FAILED after {error_time:.4f}s: {str(e)}")
            if pbar: pbar.close()
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
            config_dict = config.to_dict() if hasattr(config, 'to_dict') else {}
            self.runtime_config = RuntimeConfig(config_dict)
        else:
            self.runtime_config = runtime_config
        
        # Register tool_manager as observer if it exists
        if tool_manager and hasattr(tool_manager, 'on_runtime_config_change'):
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
                raw_output_config = raw_config.get("output", {}) if isinstance(raw_config, dict) else {}
                show_tool_value = raw_output_config.get("show_tool_results", True)
                if isinstance(show_tool_value, str):
                    self.show_tool_results = show_tool_value.strip().lower() in {"1", "true", "yes", "on"}
                else:
                    self.show_tool_results = bool(show_tool_value)
            except Exception:
                self.show_tool_results = True

        # Set system prompt from import
        # Initialize prompt mode from config if available
        try:
            initial_mode = str(raw_config.get("prompt", {}).get("mode", "direct")).strip().lower()
        except Exception:
            initial_mode = "direct"
        self.prompt_mode: str = initial_mode or "direct"

        # Apply initial output style from config before building prompt
        try:
            from penguin.prompt.builder import set_output_formatting
            if output_config and getattr(output_config, "prompt_style", None):
                prompt_style = str(output_config.prompt_style).strip().lower()
            else:
                prompt_style = str(raw_config.get("output", {}).get("prompt_style", "steps_final")).strip().lower()
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

        # StreamingStateManager handles all streaming state, coalescing, and event generation
        self._stream_manager = StreamingStateManager()

        # RunMode state for UI streaming bridges
        self._runmode_stream_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
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
            max_auto_checkpoints=1000 #TODO: review magic numbers and at least put them into constants.py or parametrize them via Config
        )
        
        self.conversation_manager = ConversationManager(
            model_config=model_config,
            api_client=api_client,
            workspace_path=WORKSPACE_PATH,
            system_prompt=self.system_prompt,
            max_messages_per_session=DEFAULT_MAX_MESSAGES_PER_SESSION,
            max_sessions_in_memory=20,
            auto_save_interval=60,
            checkpoint_config=checkpoint_config
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
        self.current_runmode_status_summary: str = "RunMode idle." # New attribute

        # ------------------- Engine Initialization -------------------
        try:
            from penguin.engine import Engine, EngineSettings, TokenBudgetStop, WallClockStop  # type: ignore
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
            logger.warning(f"Failed to initialize Engine layer (fallback to legacy core processing): {e}")
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

    def _ensure_litellm_configured(self):
        """Configure LiteLLM on first use to avoid import time overhead."""
        if not self._litellm_configured:
            try:
                from litellm import _logging # type: ignore
                _logging._disable_debugging()
                # Also set these to be safe
                import litellm # type: ignore
                litellm.set_verbose = False
                litellm.drop_params = False
                self._litellm_configured = True
            except Exception as e:
                logger.warning(f"Failed to disable LiteLLM debugging: {e}")
                self._litellm_configured = True  # Don't try again

        # Streaming primitives are initialized in __init__ now
        self.current_runmode_status_summary: str = "RunMode idle."

    # ------------------------------------------------------------------
    # Coordinator accessor (singleton per Core)
    # ------------------------------------------------------------------
    def get_coordinator(self):
        """Return a singleton MultiAgentCoordinator bound to this Core."""
        try:
            if not hasattr(self, "_coordinator") or getattr(self, "_coordinator") is None:
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
                if hasattr(self, "conversation_manager") and hasattr(self.conversation_manager, "set_system_prompt"):
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

    def register_progress_callback(self, callback: Callable[[int, int, Optional[str]], None]) -> None:
        """Register a callback for progress updates during multi-step processing."""
        self.progress_callbacks.append(callback)

    def notify_progress(self, iteration: int, max_iterations: int, message: Optional[str] = None) -> None:
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
            logger.error(f"Failed to switch ConversationManager to agent '{agent_id}': {e}")
            raise

        # Switch Engine default routing
        try:
            if getattr(self, 'engine', None):
                self.engine.set_default_agent(agent_id)
        except Exception as e:
            logger.error(f"Failed to set Engine default agent '{agent_id}': {e}")
            raise

    # Thin wrappers for agent-scoped conversations
    def create_agent_conversation(self, agent_id: str) -> str:
        return self.conversation_manager.create_agent_conversation(agent_id)

    def list_all_conversations(self, *, limit_per_agent: int = 1000, offset: int = 0):
        return self.conversation_manager.list_all_conversations(limit_per_agent=limit_per_agent, offset=offset)

    def load_agent_conversation(self, agent_id: str, conversation_id: str, *, activate: bool = True) -> bool:
        return self.conversation_manager.load_agent_conversation(agent_id, conversation_id, activate=activate)

    def delete_agent_conversation(self, agent_id: str, conversation_id: str) -> bool:
        return self.conversation_manager.delete_agent_conversation(agent_id, conversation_id)

    def delete_agent_conversation_guarded(self, agent_id: str, conversation_id: str, *, force: bool = False) -> Dict[str, Any]:
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

    def list_sub_agents(self, parent_agent_id: Optional[str] = None) -> Dict[str, List[str]]:
        """Return mapping of parent agents to sub-agents."""
        return self.conversation_manager.list_sub_agents(parent_agent_id)

    # ------------------------------
    # Sub-agent paused state helpers
    # ------------------------------
    def set_agent_paused(self, agent_id: str, paused: bool = True) -> None:
        """Mark an agent as paused/resumed using conversation metadata."""
        conv = self.conversation_manager.get_agent_conversation(agent_id)
        if conv and hasattr(conv, 'session') and conv.session:
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
        if conv and hasattr(conv, 'session') and conv.session:
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
        conv = self.conversation_manager.get_agent_conversation(agent_id, create_if_missing=True)
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

    def unregister_agent(self, agent_id: str, *, preserve_conversation: bool = False) -> bool:
        """Unregister an agent. Delegates to delete_agent_conversation()."""
        if preserve_conversation:
            # Just unregister from Engine, keep conversation
            if getattr(self, "engine", None):
                try:
                    self.engine.unregister_agent(agent_id)
                except Exception as e:
                    logger.debug(f"Engine unregister_agent failed for '{agent_id}': {e}")
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
                cw = cm.agent_context_windows.get(aid) if hasattr(cm, "agent_context_windows") else getattr(cm, "context_window", None)
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
                        cw_max = u.get("max", u.get("max_context_window_tokens", u.get("max_tokens")))  # max_context_window_tokens is the canonical key
                    except Exception:
                        pass
                # Record agent info
                summary["agents"].append({
                    "agent_id": aid,
                    "session_id": session_id,
                    "conversation_obj": id(conv),
                    "context_window_max": cw_max,
                    "context_window_usage": cw_usage,
                })
                conv_to_agents.setdefault(id(conv), []).append(aid)
            except Exception:
                continue

        # Shared conversation groups
        summary["shared_conversations"] = [
            {"conversation_obj": k, "agents": v}
            for k, v in conv_to_agents.items() if len(v) > 1
        ]

        # Engine registry presence
        try:
            engine_agents = set(self.engine.list_agents()) if getattr(self, "engine", None) else set()
        except Exception:
            engine_agents = set()
        for a in [a.get("agent_id") for a in summary["agents"]]:
            summary["engine_registry"][a] = (a in engine_agents)

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
    # Streaming State Properties (delegate to StreamingStateManager)
    # ------------------------------------------------------------------

    @property
    def streaming_active(self) -> bool:
        """Whether streaming is currently active."""
        return self._stream_manager.is_active

    @property
    def streaming_content(self) -> str:
        """Accumulated assistant content from current stream."""
        return self._stream_manager.content

    @property
    def streaming_reasoning_content(self) -> str:
        """Accumulated reasoning content from current stream."""
        return self._stream_manager.reasoning_content

    @property
    def streaming_stream_id(self) -> Optional[str]:
        """Unique ID of the current stream, or None if not streaming."""
        return self._stream_manager.stream_id

    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Get token usage via conversation manager"""
        try:
            if not self.conversation_manager:
                return {"total": {"input": 0, "output": 0}, "session": {"input": 0, "output": 0}}
            
            usage = self.conversation_manager.get_token_usage()
            
            # Emit UI event for token update (only if event loop is running)
            try:
                token_event_data = usage.copy()
                # Only create task if we have a real emit_ui_event method (not a mock)
                if hasattr(self, 'emit_ui_event') and not hasattr(self.emit_ui_event, '_mock_name'):
                    asyncio.create_task(self.emit_ui_event("token_update", token_event_data))
            except (RuntimeError, AttributeError):
                # No event loop running or method is a mock, skip event emission
                pass
            
            return usage
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            return {"total": {"input": 0, "output": 0}, "session": {"input": 0, "output": 0}}

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
        
        if not hasattr(self, '_llm_client') or self._llm_client is None:
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
        streaming: bool = False
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
            if agent_id:
                try:
                    if hasattr(conversation_manager, "set_current_agent"):
                        conversation_manager.set_current_agent(agent_id)
                except Exception as agent_err:
                    logger.warning(f"Failed to activate agent '{agent_id}' on ConversationManager: {agent_err}")
                if self.engine:
                    try:
                        candidate_cm = self.engine.get_conversation_manager(agent_id)
                        if candidate_cm is not None:
                            conversation_manager = candidate_cm
                            if hasattr(candidate_cm, "set_current_agent"):
                                candidate_cm.set_current_agent(agent_id)
                    except Exception as engine_err:
                        logger.warning(f"Engine conversation manager lookup failed for agent '{agent_id}': {engine_err}")

            # Add context if provided
            if context:
                for key, value in context.items():
                    conversation_manager.add_context(f"{key}: {value}")

            # Process through conversation manager (handles context files)
            return await conversation_manager.process_message(
                message=message,
                conversation_id=conversation_id,
                streaming=streaming,
                context_files=context_files
            )
            
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            log_error(
                e,
                context={
                    "component": "core",
                    "method": "process_message",
                    "message": message
                },
            )
            return error_msg

    async def get_response(
        self,
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        streaming: Optional[bool] = None
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
                logger.debug(f"Calling API directly (Streaming: {streaming}, Callback provided: {stream_callback is not None})")

                assistant_response = None
                try:
                    logger.debug(json.dumps(self.conversation_manager.conversation.get_formatted_messages(), indent=2))
                    assistant_response = await self.api_client.get_response(
                        messages=messages,
                        stream=streaming,
                        stream_callback=stream_callback
                    )
                except asyncio.CancelledError:
                    logger.warning("APIClient response retrieval was cancelled")
                except Exception as e:
                    logger.error(f"Error during APIClient response retrieval: {str(e)}", exc_info=True) 

                # Validate response (retry logic remains the same)
                if not assistant_response or not assistant_response.strip():
                    retry_count += 1
                    if retry_count <= max_retries:
                        logger.warning(f"Empty response from API (attempt {retry_count}/{max_retries}), retrying...")
                        # Small exponential backoff
                        await asyncio.sleep(1 * retry_count)
                        continue
                    else:
                        logger.warning(f"Empty response from API after {max_retries} attempts")
                        assistant_response = "I apologize, but I encountered an issue generating a response. Please try again."
                        break
                else:
                    # We got a valid response, break the retry loop
                    break
            
                # Let's return it as is for now, core needs adjustment later if this is the case.
    
            # Process response and execute actions regardless of streaming mode
            logger.debug(f"[Core.get_response] Processing response and executing actions. Streaming={streaming}")

            # Add assistant response to conversation (only happens *after* the stream task is fully complete)
            if assistant_response:
                # Add assistant response to conversation
                # Ensure we add the complete response, even if it was streamed.
                # The APIClient should return the full string after streaming completes.
                # Note: add_assistant_message automatically strips action tags
                self.conversation_manager.conversation.add_assistant_message(assistant_response)
            
            # Parse actions and continue with action handling
            actions = parse_action(assistant_response)
            
            # Check for task/response completion via finish_task or finish_response tools
            # NOTE: Phrase-based detection is deprecated. Use finish_task/finish_response tools.
            exit_continuation = any(
                action.action_type.value in ("finish_response", "finish_task", "task_completed")
                for action in actions
            )

            # Execute actions with interrupt checking
            action_results = []
            for action in actions:
                if self._check_interrupt():
                    action_results.append({
                        "action": action.action_type.value,
                        "result": "Action skipped due to interrupt",
                        "status": "interrupted",
                    })
                    continue

                try:
                    result = await self.action_executor.execute_action(action)
                    if result is not None:
                        action_results.append({
                            "action": action.action_type.value,
                            "result": str(result),
                            "status": "completed",
                        })
                        
                        # Update conversation with action result
                        self.conversation_manager.add_action_result(
                            action_type=action.action_type.value,
                            result=str(result),
                            status="completed"
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
                        status="error"
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

            logger.debug(f"ACTION RESULT TEST: System outputs visible to LLM: {[msg for msg in messages if 'system' in msg.get('role', '') and 'Action executed' in str(msg.get('content', ''))]}")
            print(f"ACTION RESULT TEST: System outputs visible to LLM: {[msg for msg in messages if 'system' in msg.get('role', '') and 'Action executed' in str(msg.get('content', ''))]}")

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

    def branch_from_snapshot(self, snapshot_id: str, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Fork a snapshot into a new branch and load it."""
        return self.conversation_manager.branch_from_snapshot(snapshot_id, meta=meta)

    # ------------------------------------------------------------------
    # Checkpoint Management API (NEW - V2.1 Conversation Plane)
    # ------------------------------------------------------------------

    async def create_checkpoint(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None
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
            name=name,
            description=description
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
        description: Optional[str] = None
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
            checkpoint_id,
            name=name,
            description=description
        )

    def list_checkpoints(
        self,
        session_id: Optional[str] = None,
        limit: int = 50
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
            session_id=session_id,
            limit=limit
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
        if not self.conversation_manager or not self.conversation_manager.checkpoint_manager:
            return {
                "enabled": False,
                "total_checkpoints": 0,
                "auto_checkpoints": 0,
                "manual_checkpoints": 0,
                "branch_checkpoints": 0
            }
            
        checkpoints = self.conversation_manager.list_checkpoints(limit=1000)
        
        stats = {
            "enabled": True,
            "total_checkpoints": len(checkpoints),
            "auto_checkpoints": len([cp for cp in checkpoints if cp.get("auto", False)]),
            "manual_checkpoints": len([cp for cp in checkpoints if cp.get("type") == "manual"]),
            "branch_checkpoints": len([cp for cp in checkpoints if cp.get("type") == "branch"]),
            "config": {
                "frequency": self.conversation_manager.checkpoint_manager.config.frequency,
                "retention_hours": self.conversation_manager.checkpoint_manager.config.retention["keep_all_hours"],
                "max_age_days": self.conversation_manager.checkpoint_manager.config.retention["max_age_days"]
            }
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
                "engine_available": hasattr(self, 'engine') and self.engine is not None,
                "checkpoints_enabled": self.get_checkpoint_stats().get('enabled', False),
                "current_model": None,
                "conversation_manager": {
                    "active": hasattr(self, 'conversation_manager') and self.conversation_manager is not None,
                    "current_session_id": None,
                    "total_messages": 0
                },
                "tool_manager": {
                    "active": hasattr(self, 'tool_manager') and self.tool_manager is not None,
                    "total_tools": 0
                },
                "memory_provider": {
                    "initialized": False,
                    "provider_type": None
                }
            }
            
            # Add current model info
            if hasattr(self, 'model_config') and self.model_config:
                info["current_model"] = {
                    "model": self.model_config.model,
                    "provider": self.model_config.provider,
                    "streaming_enabled": self.model_config.streaming_enabled,
                    "vision_enabled": bool(getattr(self.model_config, 'vision_enabled', False))
                }
            
            # Add conversation manager details
            if hasattr(self, 'conversation_manager') and self.conversation_manager:
                try:
                    current_session = self.conversation_manager.get_current_session()
                    if current_session:
                        info["conversation_manager"]["current_session_id"] = current_session.id
                        info["conversation_manager"]["total_messages"] = len(current_session.messages)
                except Exception:
                    pass  # Ignore errors getting session info
            
            # Add tool manager details
            if hasattr(self, 'tool_manager') and self.tool_manager:
                info["tool_manager"]["total_tools"] = len(getattr(self.tool_manager, 'tools', {}))
                
                # Add memory provider info
                if hasattr(self.tool_manager, '_memory_provider') and self.tool_manager._memory_provider:
                    info["memory_provider"]["initialized"] = True
                    info["memory_provider"]["provider_type"] = type(self.tool_manager._memory_provider).__name__
            
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
                "runmode_status": getattr(self, 'current_runmode_status_summary', 'RunMode idle.'),
                "continuous_mode": getattr(self, '_continuous_mode', False),
                "streaming_active": getattr(self, 'streaming_active', False),
                "token_usage": self.get_token_usage(),
                "timestamp": datetime.now().isoformat(),
                "initialization": {
                    "core_initialized": getattr(self, 'initialized', False),
                    "fast_startup_enabled": getattr(self.tool_manager, 'fast_startup', False) if hasattr(self, 'tool_manager') else False
                }
            }
            
            # Add memory provider status if available
            if hasattr(self, 'get_memory_provider_status'):
                status["memory_provider"] = self.get_memory_provider_status()
            
            return status
            
        except Exception as e:
            logger.error(f"Error getting system status: {e}")
            return {
                "status": "error",
                "error": f"Failed to get system status: {str(e)}",
                "timestamp": datetime.now().isoformat()
            }

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=4, max=10),
        reraise=True,
        retry=retry_if_exception_type(Exception),
        retry_error_callback=lambda retry_state: None 
            if isinstance(retry_state.outcome.exception(), KeyboardInterrupt) 
            else retry_state.outcome.exception()
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
            image_paths = input_data.get("image_paths")  # List of image paths

        if not message and not image_paths:
            return {"assistant_response": "No input provided", "action_results": []}

        conversation_manager = self.conversation_manager
        if agent_id:
            try:
                if hasattr(conversation_manager, "set_current_agent"):
                    conversation_manager.set_current_agent(agent_id)
            except Exception as agent_err:
                logger.warning(f"Failed to activate agent '{agent_id}' on ConversationManager: {agent_err}")
            if self.engine:
                try:
                    candidate_cm = self.engine.get_conversation_manager(agent_id)
                    if candidate_cm is not None:
                        conversation_manager = candidate_cm
                        if hasattr(candidate_cm, "set_current_agent"):
                            candidate_cm.set_current_agent(agent_id)
                except Exception as engine_err:
                    logger.warning(f"Engine conversation manager lookup failed for agent '{agent_id}': {engine_err}")

        try:
            # Load conversation if ID provided
            if conversation_id:
                if not conversation_manager.load(conversation_id):
                    logger.warning(f"Failed to load conversation {conversation_id}")

            # Load context files if specified
            if context_files:
                for file_path in context_files:
                    conversation_manager.load_context_file(file_path)

            # Add user message to conversation explicitly
            user_message_dict = {
                "role": "user",
                "content": message,
                "category": MessageCategory.DIALOG
            }
            if agent_id:
                user_message_dict["agent_id"] = agent_id

            # Emit user message event before processing
            logger.debug(f"Emitting user message event: {message[:30]}...")
            await self.emit_ui_event("message", user_message_dict)

            # Use new Engine layer if available
            if self.engine:
                # Build streaming callback for Engine that first updates internal streaming
                # state via _handle_stream_chunk and then forwards chunks to any external
                # stream_callback supplied by callers (e.g., WebSocket).
                if streaming:
                    if stream_callback:
                        async def _combined_stream_callback(chunk: str, message_type: str = "assistant"):
                            # Update internal streaming handling
                            await self._handle_stream_chunk(chunk, message_type=message_type)
                            # Forward to external callback, preserving message_type when supported
                            try:
                                import inspect
                                params = []
                                try:
                                    params = list(inspect.signature(stream_callback).parameters.keys())
                                except Exception:
                                    params = []
                                if asyncio.iscoroutinefunction(stream_callback):
                                    if len(params) >= 2:
                                        await stream_callback(chunk, message_type)
                                    else:
                                        await stream_callback(chunk)
                                else:
                                    if len(params) >= 2:
                                        await asyncio.to_thread(stream_callback, chunk, message_type)
                                    else:
                                        await asyncio.to_thread(stream_callback, chunk)
                            except Exception as cb_err:
                                logger.error(f"Error in external stream_callback: {cb_err}")
                        engine_stream_callback = _combined_stream_callback
                    else:
                        engine_stream_callback = self._handle_stream_chunk
                else:
                    engine_stream_callback = None

                if multi_step:
                    # Check if this is a formal task (RunMode) or conversational multi-step
                    is_formal_task = context and context.get('task_mode', False)
                    
                    if is_formal_task:
                        # Bridge the simple stream_callback to the Engine's richer message_callback
                        engine_message_callback = None
                        if stream_callback:
                            # The engine expects an async callback that takes (message, type, **kwargs)
                            async def bridged_callback(message: str, msg_type: str, action_name: Optional[str] = None, **kwargs):
                                # We only care about streaming assistant thoughts for this callback
                                if msg_type == 'assistant':
                                    # Create a task to run the potentially non-async callback
                                    # This ensures we don't block the engine's event loop.
                                    asyncio.create_task(asyncio.to_thread(stream_callback, message))

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
                conversation_manager.conversation.prepare_conversation(message, image_paths=image_paths)

                # FIX: Set the callback for event-based streaming, even in legacy mode
                internal_stream_callback = self._handle_stream_chunk if streaming else None

                response, _ = await self.get_response(
                    stream_callback=internal_stream_callback, # Pass the correct callback
                    streaming=streaming
                )

            # NOTE: Empty-response retry logic removed - engine._llm_step handles this.
            # Engine retries once with stream=False, then raises LLMEmptyResponseError.
            # WALLET_GUARD in finalize_streaming_message injects placeholder for empty streams.

            # Ensure conversation is saved after processing
            conversation_manager.save()

            # Emit assistant message event after processing (if not streamed)
            # When *streaming* was active we streamed the full message live and
            # `finalize_streaming_message` already handled persistence / UI
            # events.  Emitting another `message` here would duplicate the
            # assistant reply.  Therefore we only emit when streaming is **not**
            # enabled for this call.
            if not streaming and response and "assistant_response" in response:
                assistant_message = response["assistant_response"]
                if assistant_message:
                    logger.debug(
                        "Emitting assistant message event (non-streaming): %s…",
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
            token_data = conversation_manager.get_token_usage()
            await self.emit_ui_event("token_update", token_data)

            return response
            
        except Exception as e:
            error_msg = f"Error in process method: {str(e)}"
            logger.error(f"{error_msg}\n{traceback.format_exc()}")
            log_error(e, context={"method": "process", "input_data": input_data})
            
            # Emit error event
            await self.emit_ui_event("error", {
                "message": "Error processing your request",
                "source": "core.process",
                "details": str(e)
            })
            
            return {
                "assistant_response": "I apologize, but an error occurred while processing your request.",
                "action_results": [],
                "error": str(e)
            }

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
        return self.conversation_manager.list_conversations(limit=limit, offset=offset, search_term=search_term)
        
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
                "metadata": session.metadata
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
        ui_update_callback_for_cli: Optional[Callable[[], Awaitable[None]]] = None
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
                event_callback=self._handle_run_mode_event
            )
            self.run_mode = run_mode
            self._continuous_mode = continuous

            if continuous:
                # RunMode's start_continuous will manage its internal continuous_mode flag
                await run_mode.start_continuous(specified_task_name=name, task_description=description)
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
            
            raise # Re-raise the exception so the caller knows starting run_mode failed
        
        finally:
            self._runmode_active = False
            self._runmode_stream_callback = None
            self.run_mode = None
            # Clear the UI update callback reference when finished
            self._ui_update_callback = None
            
            # Ensure state is cleaned up if run mode was not continuous or if continuous mode exited
            if hasattr(run_mode, 'continuous_mode') and not run_mode.continuous_mode:
                self._continuous_mode = False
            
            logger.info(f"Exiting start_run_mode. Core _continuous_mode: {self._continuous_mode}")

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------

    def _apply_new_model_config(self, new_model_config: ModelConfig, context_window_tokens: Optional[int] = None) -> None:
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
        self.api_client = APIClient(model_config=new_model_config)
        self.api_client.set_system_prompt(self.system_prompt)

        # 2. Propagate to ConversationManager components so token budgeting and
        #    streaming limits are accurate.
        if self.conversation_manager:
            self.conversation_manager.model_config = new_model_config
            self.conversation_manager.api_client = self.api_client
            # Update nested helpers if they expose the attributes we need.
            try:
                # ContextWindowManager lives under conversation_manager.context_window
                if hasattr(self.conversation_manager, "context_window"):
                    cw = self.conversation_manager.context_window
                    cw.model_config = new_model_config  # type: ignore[attr-defined]
                    cw.api_client = self.api_client     # type: ignore[attr-defined]
                    # Update context window budget with safe window (85% of raw)
                    if context_window_tokens:
                        old_budget = cw.max_context_window_tokens
                        cw.max_context_window_tokens = context_window_tokens
                        cw._initialize_token_budgets()  # Re-compute category budgets
                        logger.info(f"Updated context window: {old_budget} -> {context_window_tokens} tokens")
            except Exception as e:
                logger.warning(f"Failed to propagate new model config to ContextWindowManager: {e}")

        # 3. Engine layer (optional – may not exist depending on install).
        if getattr(self, "engine", None) is not None:
            try:
                self.engine.api_client = self.api_client  # type: ignore[attr-defined]
            except Exception as e:
                logger.warning(f"Failed to propagate new API client to Engine: {e}")

    async def load_model(self, model_id: str) -> bool:
        """Replace the active model at runtime.

        The *model_id* argument can be either:
        1. A key present in ``config.yml -> model_configs``
        2. A fully-qualified model string of the form ``<provider>/<model_name>``.

        Returns ``True`` on success, ``False`` otherwise.
        """
        try:
            # Fetch model specs from cached service (fast, no API call if cached)
            model_specs = await fetch_model_specs(model_id)
            if not model_specs:
                logger.error(f"Could not fetch specifications for model '{model_id}'")
                return False
            logger.info(f"Fetched specs for {model_id}: {model_specs}")

            # Resolve provider and client preference
            provider, client_pref = self._resolve_model_provider(model_id)
            if not provider:
                return False

            # Calculate safe context window (85% of raw)
            context_length = model_specs.get("context_length")
            safe_window = safe_context_window(context_length)
            max_output = model_specs.get("max_output_tokens") or safe_window

            # Build and apply new ModelConfig
            new_model_config = ModelConfig.for_model(
                model_name=model_id,
                provider=provider,
                client_preference=client_pref,
                model_configs=getattr(self.config, 'model_configs', None),
            )
            self._apply_new_model_config(new_model_config, context_window_tokens=safe_window)

            logger.info(f"Switched to model '{model_id}' (context: {safe_window} tokens)")
            return True

        except Exception as e:
            logger.error(f"Failed to switch to model '{model_id}': {e}")
            return False

    def _resolve_model_provider(self, model_id: str) -> tuple[Optional[str], str]:
        """Resolve provider and client preference for a model ID.

        Returns:
            Tuple of (provider, client_preference), or (None, "") on error.
        """
        # Check explicit model_configs first
        if hasattr(self.config, "model_configs") and isinstance(self.config.model_configs, dict):
            model_conf = self.config.model_configs.get(model_id)
            if model_conf:
                provider = model_conf.get("provider")
                client_pref = model_conf.get("client_preference", "native")
                return provider, client_pref

        # Infer from fully-qualified model ID
        if "/" not in model_id:
            logger.error(f"Model '{model_id}' not in model_configs and not fully-qualified")
            return None, ""

        provider_part = model_id.split("/", 1)[0]
        client_pref = self.model_config.client_preference if self.model_config else "native"

        # OpenRouter routes all providers through its gateway
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

        if not (hasattr(self.config, "model_configs") and isinstance(self.config.model_configs, dict)):
            return models

        for model_id, conf in self.config.model_configs.items():
            if not isinstance(conf, dict):
                continue
            entry = {
                "id": model_id,
                "name": conf.get("model", model_id),
                "provider": conf.get("provider", "unknown"),
                "client_preference": conf.get("client_preference", "native"),
                "vision_enabled": conf.get("vision_enabled", False),
                "max_output_tokens": conf.get("max_output_tokens", conf.get("max_tokens")),  # Accept both keys
                "temperature": conf.get("temperature"),
                "current": model_id == current_model_name or conf.get("model") == current_model_name,
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
            "max_output_tokens": getattr(self.model_config, 'max_output_tokens', None),
            "temperature": getattr(self.model_config, 'temperature', None),
            "streaming_enabled": self.model_config.streaming_enabled,
            "vision_enabled": bool(getattr(self.model_config, 'vision_enabled', False)),
            "api_base": getattr(self.model_config, 'api_base', None)
        }

    async def emit_ui_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """
        Emit an event through the unified event bus.

        Filters internal markers from content before emitting to UI.

        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update", etc.)
            data: Event data relevant to the event type
        """
        logger.debug(f"Core emit_ui_event {event_type} keys={list(data.keys())}")

        # Filter internal markers from content before emitting
        if isinstance(data, dict):
            data = self._filter_internal_markers_from_event(data)

        # Tag with agent_id when available so UI can label sources
        try:
            if isinstance(data, dict):
                # Tag missing or empty agent_id with the current active agent
                if not data.get('agent_id'):
                    cm = getattr(self, 'conversation_manager', None)
                    if cm and hasattr(cm, 'current_agent_id'):
                        data = dict(data)  # shallow copy to avoid mutating caller dict
                        data['agent_id'] = cm.current_agent_id
        except Exception:
            pass

        # Emit through unified event bus
        await self.event_bus.emit(event_type, data)

    def _filter_internal_markers_from_event(self, data: Dict[str, Any]) -> Dict[str, Any]:
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
            r'<execute>.*?</execute>',
            r'<system-reminder>.*?</system-reminder>',
            r'<internal>.*?</internal>',
        ]

        # Fields that may contain content to filter
        content_fields = ['content', 'chunk', 'content_so_far', 'message']

        modified = False
        filtered_data = data

        for field in content_fields:
            if field in data and isinstance(data[field], str):
                original_content = data[field]
                filtered_content = original_content

                # Apply all filter patterns
                for pattern in internal_patterns:
                    filtered_content = re.sub(pattern, '', filtered_content, flags=re.DOTALL)

                # Only create copy if content changed
                if filtered_content != original_content:
                    if not modified:
                        filtered_data = dict(data)  # Shallow copy
                        modified = True
                    filtered_data[field] = filtered_content.strip()

        return filtered_data

    async def _handle_stream_chunk(self, chunk: str, message_type: Optional[str] = None, role: str = "assistant") -> None:
        """
        Central handler for all streaming content chunks from any source.
        Delegates to StreamingStateManager and emits events.

        Args:
            chunk: The content chunk to add
            message_type: Type of message - "assistant", "reasoning", "tool_output", etc.
            role: The role of the message (default: "assistant")
        """
        # Delegate to StreamingStateManager
        events = self._stream_manager.handle_chunk(chunk, message_type=message_type, role=role)

        # Emit events and invoke RunMode callback
        for event in events:
            await self.emit_ui_event(event.event_type, event.data)
            # Forward to RunMode stream callback if active
            if event.data.get("chunk") and not event.data.get("is_reasoning"):
                await self._invoke_runmode_stream_callback(
                    event.data["chunk"],
                    event.data.get("message_type", "assistant")
                )

    def finalize_streaming_message(self) -> Optional[Dict[str, Any]]:
        """
        Finalizes the current streaming message, adds it to ConversationManager,
        and resets the streaming state. Emits a final event with is_final=True.

        Returns:
            The finalized message dict or None if no streaming was active
        """
        # Delegate to StreamingStateManager
        message, events = self._stream_manager.finalize()

        if message is None:
            return None

        # Log WALLET_GUARD warning if empty
        if message.was_empty:
            logger.warning(
                f"[WALLET_GUARD] Empty response from LLM, forcing context advance."
            )

        # Determine message category
        if message.role == "assistant":
            category = MessageCategory.DIALOG
        elif message.role == "system":
            category = MessageCategory.SYSTEM
        else:
            category = MessageCategory.DIALOG

        # Add to conversation manager
        if hasattr(self, "conversation_manager") and self.conversation_manager:
            self.conversation_manager.conversation.add_message(
                role=message.role,
                content=message.content,
                category=category,
                metadata=message.metadata
            )

            # For WebSocket streaming (RunMode), emit a message event
            if hasattr(self, '_temp_ws_callback') and self._temp_ws_callback:
                asyncio.create_task(self._temp_ws_callback({
                    "type": "message",
                    "role": message.role,
                    "content": message.content,
                    "category": category,
                    "metadata": message.metadata
                }))

        # Emit events from manager
        callback_ref = self._runmode_stream_callback
        for event in events:
            asyncio.create_task(self.emit_ui_event(event.event_type, event.data))
            # Forward final event to RunMode callback
            if callback_ref and event.data.get("is_final"):
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
            logger.debug("RunMode stream callback execution failed: %s", exc, exc_info=True)

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
                    "metadata": event.get("metadata", {})
                }
                
                # Ensure category is a MessageCategory enum if provided as string
                if isinstance(msg_data["category"], str):
                    try:
                        msg_data["category"] = MessageCategory[msg_data["category"].upper()]
                    except KeyError:
                        logger.warning(f"Invalid message category string '{msg_data['category']}' from RunMode event. Defaulting to SYSTEM.")
                        msg_data["category"] = MessageCategory.SYSTEM
                
                # Add to conversation
                self.conversation_manager.conversation.add_message(**msg_data)
                self.conversation_manager.save()
                logger.debug(f"Core added message to ConversationManager from RunMode event: {msg_data['role']} - {msg_data['content'][:50]}...")
            
            # Handle status events
            elif event_type == "status":
                status_type = event.get("status_type", "unknown")
                status_data = event.get("data", {})
                logger.info(f"RunMode status update: {status_type} - Data: {status_data}")
                
                # Update status summary based on event type
                if status_type == "task_started" or status_type == "task_started_legacy":
                    task_name = status_data.get('task_name', status_data.get('task_prompt', 'Unknown task'))
                    self.current_runmode_status_summary = f"Task: {task_name} - Running"
                elif status_type == "task_progress":
                    iteration = status_data.get('iteration', '?')
                    max_iter = status_data.get('max_iterations', '?')
                    progress = status_data.get('progress', 0)
                    self.current_runmode_status_summary = f"Progress: {progress}% (Iter: {iteration}/{max_iter})"
                elif status_type == "task_completed" or status_type == "task_completed_legacy" or status_type == "task_completed_eventbus":
                    task_name = status_data.get('task_name', 'Last task')
                    self.current_runmode_status_summary = f"Task: {task_name} - Completed"
                elif status_type == "run_mode_ended" or status_type == "shutdown_completed":
                    self.current_runmode_status_summary = "RunMode ended."
                elif status_type == "clarification_needed" or status_type == "clarification_needed_eventbus":
                    self.current_runmode_status_summary = "Awaiting user clarification."
                elif status_type == "awaiting_user_input_after_task":
                    self.current_runmode_status_summary = "Task complete. Awaiting input."
            
            # Handle error events
            elif event_type == "error":
                err_msg = event.get("message", "Unknown error from RunMode")
                err_source = event.get("source", "runmode")
                err_details = event.get("details", {})
                logger.error(f"RunMode Error Event (Source: {err_source}): {err_msg} | Details: {err_details}")
                
                # Update status with error
                self.current_runmode_status_summary = f"Error: {err_msg}"
            
            # Handle unknown event types
            else:
                logger.warning(f"Core received unknown RunMode event type: {event_type} | Event: {event}")

            # After processing any event, signal the UI to update if callback is registered
            if hasattr(self, '_ui_update_callback') and self._ui_update_callback:
                try:
                    await self._ui_update_callback()
                except Exception as e:
                    logger.error(f"Error in UI update callback: {e}", exc_info=True)

            # Also send to WebSocket if temporary callback exists (for streaming)
            if hasattr(self, '_temp_ws_callback') and self._temp_ws_callback:
                try:
                    await self._temp_ws_callback(event)
                except Exception as e:
                    logger.error(f"Error in WebSocket callback: {e}", exc_info=True)

        except Exception as e:
            logger.error(f"Error in PenguinCore._handle_run_mode_event: {str(e)}", exc_info=True)

    def get_startup_stats(self) -> Dict[str, Any]:
        """Get comprehensive startup performance statistics."""
        stats = {
            "profiling_summary": profiler.get_summary(),
            "tool_manager_stats": self.tool_manager.get_startup_stats() if hasattr(self.tool_manager, 'get_startup_stats') else {},
            "memory_provider_initialized": hasattr(self.tool_manager, '_memory_provider') and self.tool_manager._memory_provider is not None,
            "core_initialized": self.initialized,
        }
        return stats

    def print_startup_report(self) -> None:
        """Print a comprehensive startup performance report."""
        print("\n" + "="*60)
        print("PENGUIN STARTUP PERFORMANCE REPORT")
        print("="*60)
        
        # Get tool manager stats
        if hasattr(self.tool_manager, 'get_startup_stats'):
            tool_stats = self.tool_manager.get_startup_stats()
            print(f"\nTool Manager Configuration:")
            print(f"  Fast startup mode: {tool_stats.get('fast_startup', 'Unknown')}")
            print(f"  Memory provider initialized: {tool_stats.get('memory_provider_exists', 'Unknown')}")
            print(f"  Indexing completed: {tool_stats.get('indexing_completed', 'Unknown')}")
            
            lazy_init = tool_stats.get('lazy_initialized', {})
            print(f"\nLazy-loaded components:")
            for component, initialized in lazy_init.items():
                status = "✓ Loaded" if initialized else "○ Deferred"
                print(f"  {component}: {status}")
        
        # Print profiling report
        print(f"\nDetailed Performance Breakdown:")
        profiler_report = profiler.get_startup_report()
        print(profiler_report)
        
        print("="*60)

    def enable_fast_startup_globally(self) -> None:
        """Enable fast startup mode for future operations."""
        if hasattr(self.tool_manager, 'fast_startup'):
            self.tool_manager.fast_startup = True
            logger.info("Fast startup mode enabled globally")

    def get_memory_provider_status(self) -> Dict[str, Any]:
        """Get current status of memory provider and indexing."""
        if not hasattr(self.tool_manager, '_memory_provider'):
            return {"status": "not_initialized", "provider": None}
        
        provider = self.tool_manager._memory_provider
        if provider is None:
            return {"status": "disabled", "provider": None}
        
        status = {
            "status": "initialized" if provider else "not_initialized",
            "provider": type(provider).__name__ if provider else None,
            "indexing_completed": getattr(self.tool_manager, '_indexing_completed', False),
            "indexing_task_running": False,
        }
        
        # Check indexing task status
        if hasattr(self.tool_manager, '_indexing_task') and self.tool_manager._indexing_task:
            task = self.tool_manager._indexing_task
            status["indexing_task_running"] = not task.done()
            status["indexing_task_status"] = {
                "done": task.done(),
                "cancelled": task.cancelled(),
                "exception": str(task.exception()) if task.done() and task.exception() else None
            }
        
        return status
