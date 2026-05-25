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
from .core_runtime import core_state as core_state_runtime
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
from .core_runtime import startup as core_startup
from .core_runtime import stream_events as core_stream_events
from .core_runtime import streaming_state as core_streaming_state
from .core_runtime import system_diagnostics as core_system_diagnostics
from .core_runtime import token_usage_runtime as core_token_usage_runtime
from penguin.llm.stream_handler import (
    StreamingStateManager,
    AgentStreamingStateManager,
    StreamingConfig,
)
from penguin.multi import coordinator_runtime as multi_coordinator_runtime
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
        core_startup.ensure_tokenizers_parallelism()

        startup_timing = core_startup.StartupTiming()
        progress = None

        try:
            with profile_startup_phase("PenguinCore.create_total"):
                progress = core_startup.StartupProgress.create(
                    enable_cli=enable_cli,
                    show_progress=show_progress,
                    progress_callback=progress_callback,
                    tqdm_factory=tqdm,
                )

                # Step 1: Load environment
                with profile_startup_phase("Load environment"):
                    logger.info("STARTUP: Loading environment variables")
                    progress.start_step("Loading environment")
                    # load_dotenv() is already invoked centrally in config.py at import time.
                    # Calling it again here is redundant and can subtly override earlier values.
                    # Intentionally no-op.
                    progress.complete_step()
                    startup_timing.record_step("Load environment", logger=logger)

                # Step 2: Initialize logging
                with profile_startup_phase("Setup logging"):
                    logger.info("STARTUP: Setting up logging configuration")
                    progress.start_step("Setting up logging")
                    core_startup.configure_startup_logging()
                    progress.complete_step()
                    startup_timing.record_step("Setup logging", logger=logger)

                # Load configuration
                with profile_startup_phase("Load configuration"):
                    logger.info("STARTUP: Loading and parsing configuration")
                    progress.start_step("Loading configuration")
                    start_config_time = startup_timing.mark()
                    config = core_startup.load_startup_config(
                        config,
                        workspace_path=workspace_path,
                        config_loader=Config.load_config,
                    )

                    # Use fast_startup from config if not explicitly set
                    fast_startup = core_startup.resolve_fast_startup(
                        config,
                        fast_startup,
                    )

                    logger.info(
                        "STARTUP: Config loaded in %.4fs",
                        startup_timing.elapsed_since(start_config_time),
                    )
                    progress.complete_step()
                    startup_timing.record_step("Load configuration", logger=logger)

                # Initialize model configuration
                with profile_startup_phase("Create model config"):
                    logger.info("STARTUP: Creating model configuration")
                    progress.start_step("Creating model config")
                    model_config = core_startup.build_initial_model_config(
                        config,
                        model=model,
                        provider=provider,
                        default_model=DEFAULT_MODEL,
                        default_provider=DEFAULT_PROVIDER,
                        model_config_factory=ModelConfig,
                    )
                    logger.info(
                        f"STARTUP: Using model={model_config.model}, provider={model_config.provider}, client={model_config.client_preference}"
                    )
                    progress.complete_step()
                    startup_timing.record_step("Create model config", logger=logger)

                # Create API client
                with profile_startup_phase("Initialize API client"):
                    logger.info("STARTUP: Initializing API client")
                    progress.start_step("Initializing API client")
                    api_client_start = startup_timing.mark()
                    api_client = core_startup.build_api_client(
                        model_config,
                        system_prompt=SYSTEM_PROMPT,
                        api_client_factory=APIClient,
                        ensure_env_loaded=_ensure_env_loaded,
                    )
                    logger.info(
                        "STARTUP: API client initialized in %.4fs",
                        startup_timing.elapsed_since(api_client_start),
                    )
                    progress.complete_step()
                    startup_timing.record_step("Initialize API client", logger=logger)

                # Initialize tool manager
                with profile_startup_phase("Create tool manager"):
                    logger.info(
                        f"STARTUP: Creating tool manager (fast_startup={fast_startup})"
                    )
                    progress.start_step("Creating tool manager")
                    tool_manager_start = startup_timing.mark()
                    print("DEBUG: Creating ToolManager in PenguinCore...")
                    print(
                        f"DEBUG: Passing config of type {type(config)} to ToolManager."
                    )
                    print(
                        f"DEBUG: Passing log_error of type {type(log_error)} to ToolManager."
                    )
                    print(f"DEBUG: Fast startup mode: {fast_startup}")
                    tool_manager = core_startup.build_tool_manager(
                        config,
                        log_error=log_error,
                        fast_startup=fast_startup,
                        tool_manager_factory=ToolManager,
                    )
                    logger.info(
                        "STARTUP: Tool manager created in %.4fs with %s tools",
                        startup_timing.elapsed_since(tool_manager_start),
                        len(tool_manager.tools)
                        if hasattr(tool_manager, "tools")
                        else "unknown",
                    )
                    progress.complete_step()
                    startup_timing.record_step("Create tool manager", logger=logger)

                # Create core instance
                with profile_startup_phase("Create core instance"):
                    logger.info("STARTUP: Creating core instance")
                    progress.start_step("Creating core instance")
                    core_start = startup_timing.mark()
                    instance = cls(
                        config=config,
                        api_client=api_client,
                        tool_manager=tool_manager,
                        model_config=model_config,
                    )
                    logger.info(
                        "STARTUP: Core instance created in %.4fs",
                        startup_timing.elapsed_since(core_start),
                    )
                    progress.complete_step()
                    startup_timing.record_step("Create core instance", logger=logger)

                if enable_cli:
                    with profile_startup_phase("Initialize CLI"):
                        logger.info("STARTUP: Initializing CLI")
                        progress.start_step("Initializing CLI")
                        cli_start = startup_timing.mark()
                        from penguin.chat.cli import PenguinCLI

                        cli = PenguinCLI(instance)
                        logger.info(
                            "STARTUP: CLI initialized in %.4fs",
                            startup_timing.elapsed_since(cli_start),
                        )
                        progress.complete_step()
                        startup_timing.record_step("Initialize CLI", logger=logger)

                progress.finish()

                core_startup.log_startup_summary(
                    startup_timing,
                    fast_startup=fast_startup,
                    tool_manager=tool_manager,
                    logger=logger,
                )

                return instance if not enable_cli else (instance, cli)

        except Exception as e:
            if progress is not None:
                progress.close()
            error_msg = core_startup.log_startup_failure(
                startup_timing,
                e,
                logger=logger,
            )
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

        from penguin.config import RuntimeConfig

        core_startup.initialize_runtime_config(
            self,
            config=config,
            runtime_config=runtime_config,
            tool_manager=tool_manager,
            runtime_config_factory=RuntimeConfig,
        )

        from penguin.cli.events import EventBus, EventType
        from penguin.tui_adapter import PartEventAdapter

        core_startup.initialize_tui_bridge_state(
            self,
            event_bus_factory=EventBus.get_sync,
            event_type_enum=EventType,
            stream_lock_factory=asyncio.Lock,
            stream_manager_factory=AgentStreamingStateManager,
            part_event_adapter_factory=PartEventAdapter,
        )

        # Telemetry collector
        ensure_telemetry(self)
        core_startup.initialize_prompt_and_output_state(
            self,
            raw_config,
            get_system_prompt=get_system_prompt,
            fallback_system_prompt=SYSTEM_PROMPT,
        )

        # Initialize project manager with workspace path from config
        from penguin.config import WORKSPACE_PATH

        workspace_path = Path(getattr(self.config, "workspace_path", WORKSPACE_PATH))

        self.project_manager = ProjectManager(workspace_path=workspace_path)

        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()

        from penguin.system.checkpoint_manager import CheckpointConfig

        core_startup.initialize_conversation_action_state(
            self,
            workspace_path=workspace_path,
            checkpoint_config_factory=CheckpointConfig,
            conversation_manager_factory=ConversationManager,
            action_executor_factory=ActionExecutor,
            default_max_messages_per_session=DEFAULT_MAX_MESSAGES_PER_SESSION,
        )

        from penguin.engine import Engine, EngineSettings, TokenBudgetStop

        core_startup.initialize_engine_state(
            self,
            engine_factory=Engine,
            engine_settings_factory=EngineSettings,
            token_budget_stop_factory=TokenBudgetStop,
            logger=logger,
        )

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
        core_model_runtime.ensure_litellm_configured(self, log=logger)

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
        return multi_coordinator_runtime.get_core_coordinator(self, log=logger)

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
        core_state_runtime.validate_path(path)

    def register_progress_callback(
        self, callback: Callable[[int, int, Optional[str]], None]
    ) -> None:
        """Register a callback for progress updates during multi-step processing."""
        core_state_runtime.register_progress_callback(self, callback)

    def notify_progress(
        self, iteration: int, max_iterations: int, message: Optional[str] = None
    ) -> None:
        """Notify all registered callbacks about progress."""
        core_state_runtime.notify_progress(
            self,
            iteration,
            max_iterations,
            message,
        )

    def reset_context(self):
        """
        Reset conversation context and diagnostics.

        This method clears the current conversation state and resets all
        tools and diagnostics. Use this between different conversation
        sessions.
        """
        core_state_runtime.reset_context(self, diagnostics_manager=diagnostics)

    # ------------------------------------------------------------------
    # Multi-agent helpers
    # ------------------------------------------------------------------

    def get_persona_catalog(self) -> List[Dict[str, Any]]:
        """Return configured personas as serialisable dictionaries."""
        return core_agent_lifecycle.get_persona_catalog(self)

    def get_agent_roster(self) -> List[Dict[str, Any]]:
        """Return list of registered agents with their conversation metadata.

        Delegates to AgentManager for the actual implementation.
        """
        return core_agent_lifecycle.get_agent_roster(self)

    def get_agent_profile(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Return roster information for a single agent identifier.

        Delegates to AgentManager for the actual implementation.
        """
        return core_agent_lifecycle.get_agent_profile(self, agent_id)

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

    def delete_agent_conversation_guarded(
        self, agent_id: str, conversation_id: str, *, force: bool = False
    ) -> Dict[str, Any]:
        """Delete a conversation with safety checks for shared sessions.

        Returns a dict: {"success": bool, "warning": Optional[str]}
        """
        return core_agent_lifecycle.delete_agent_conversation_guarded(
            self,
            agent_id,
            conversation_id,
            force=force,
        )

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
        del kwargs
        core_agent_lifecycle.ensure_agent_conversation(
            self,
            agent_id,
            system_prompt=system_prompt,
        )

    def delete_agent_conversation(
        self,
        agent_id: str,
        conversation_id: Optional[str] = None,
    ) -> bool:
        """Delete an agent or a specific agent conversation.

        A ``conversation_id`` preserves the legacy explicit conversation-delete
        form; omitting it uses the conversation-centered agent lifecycle path.

        Args:
            agent_id: Agent to remove
            conversation_id: Optional concrete conversation/session id to delete

        Returns:
            True if agent was removed, False otherwise
        """
        return core_agent_lifecycle.delete_agent_conversation_compat(
            self,
            agent_id,
            conversation_id,
        )

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
        del kwargs
        core_agent_lifecycle.create_sub_agent(
            self,
            agent_id,
            parent_agent_id=parent_agent_id,
            system_prompt=system_prompt,
            share_session=share_session,
            share_context_window=share_context_window,
            shared_context_window_max_tokens=shared_context_window_max_tokens,
        )

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
        return core_agent_lifecycle.unregister_agent(
            self,
            agent_id,
            preserve_conversation=preserve_conversation,
        )

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
        return await core_system_diagnostics.get_telemetry_summary(self)

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
        return core_streaming_state.total_tokens_used(self)

    # ------------------------------------------------------------------
    # Streaming State Properties (delegate to AgentStreamingStateManager)
    # ------------------------------------------------------------------

    @property
    def streaming_active(self) -> bool:
        """Whether streaming is currently active for the default agent."""
        return core_streaming_state.streaming_active(self)

    @property
    def streaming_content(self) -> str:
        """Accumulated assistant content from default agent's stream."""
        return core_streaming_state.streaming_content(self)

    @property
    def streaming_reasoning_content(self) -> str:
        """Accumulated reasoning content from default agent's stream."""
        return core_streaming_state.streaming_reasoning_content(self)

    @property
    def streaming_stream_id(self) -> Optional[str]:
        """Unique ID of the default agent's stream, or None if not streaming."""
        return core_streaming_state.streaming_stream_id(self)

    # --- Agent-Specific Streaming Methods ---

    def is_agent_streaming(self, agent_id: str) -> bool:
        """Check if a specific agent is currently streaming.

        Args:
            agent_id: The agent identifier to check

        Returns:
            True if the agent is actively streaming
        """
        return core_streaming_state.is_agent_streaming(self, agent_id)

    def get_agent_streaming_content(self, agent_id: str) -> str:
        """Get accumulated streaming content for a specific agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Accumulated content string (empty if agent not found or not streaming)
        """
        return core_streaming_state.get_agent_streaming_content(self, agent_id)

    def get_agent_streaming_reasoning(self, agent_id: str) -> str:
        """Get accumulated reasoning content for a specific agent.

        Args:
            agent_id: The agent identifier

        Returns:
            Accumulated reasoning content string
        """
        return core_streaming_state.get_agent_streaming_reasoning(self, agent_id)

    def get_active_streaming_agents(self) -> List[str]:
        """Get list of agent IDs that are currently streaming.

        Returns:
            List of agent IDs with active streams
        """
        return core_streaming_state.get_active_streaming_agents(self)

    def cleanup_agent_streaming(self, agent_id: str) -> None:
        """Clean up streaming state for a terminated agent.

        Args:
            agent_id: The agent identifier to clean up
        """
        core_streaming_state.cleanup_agent_streaming(self, agent_id)

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
        core_prompt_settings.set_core_system_prompt(self, prompt)

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
        core_state_runtime.reset_state(self, diagnostics_manager=diagnostics)

    def list_context_files(self) -> List[Dict[str, Any]]:
        """List all available context files"""
        return core_state_runtime.list_context_files(self)

    # ------------------------------------------------------------------
    # Snapshot / Restore wrappers (Phase 3 integration)
    # ------------------------------------------------------------------

    def create_snapshot(self, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Persist current conversation state and return snapshot_id."""
        return core_state_runtime.create_snapshot(self, meta=meta)

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Load conversation from snapshot; returns success bool."""
        return core_state_runtime.restore_snapshot(self, snapshot_id)

    def branch_from_snapshot(
        self, snapshot_id: str, meta: Optional[Dict[str, Any]] = None
    ) -> Optional[str]:
        """Fork a snapshot into a new branch and load it."""
        return core_state_runtime.branch_from_snapshot(self, snapshot_id, meta=meta)

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
            return core_process_lifecycle.handle_process_cancelled(
                self,
                request_session_id,
            )

        except Exception as e:
            return await core_process_lifecycle.handle_process_error(
                self,
                e,
                input_data,
                log=logger,
                log_error_fn=log_error,
            )

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
        return await core_model_runtime.resolve_request_runtime(
            self,
            model_id,
            api_client_factory=APIClient,
        )

    async def load_model(self, model_id: str) -> bool:
        """Replace the active model at runtime.

        The *model_id* argument can be either:
        1. A key present in ``config.yml -> model_configs``
        2. A fully-qualified model string of the form ``<provider>/<model_name>``.

        Returns ``True`` on success, ``False`` otherwise.
        """
        return await core_model_runtime.load_model_for_core(
            self,
            model_id,
            log=logger,
        )

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
        return core_stream_events.prepare_runmode_stream_callback(
            callback,
            adapter_factory=adapt_stream_callback,
        )

    async def _invoke_runmode_stream_callback(
        self,
        chunk: str,
        message_type: str,
        callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
    ) -> None:
        await core_stream_events.invoke_runmode_stream_callback(
            self,
            chunk,
            message_type,
            callback=callback,
            logger=logger,
        )

    # Update token usage notification to use events
    def update_token_display(self) -> None:
        """Emit token usage event to UI subscribers."""
        core_token_usage_runtime.emit_token_display_update(self, log=logger)

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
        await core_opencode_bridge.apply_usage_to_core_latest_message(
            self,
            session_id,
            usage,
            logger=logger,
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
