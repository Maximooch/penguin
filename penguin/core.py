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
import logging
from typing import (
    TYPE_CHECKING,
    Any,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
)

from rich.console import Console  # type: ignore
from tqdm import tqdm

# Configuration
from penguin.config import (
    DEFAULT_MODEL,
    DEFAULT_PROVIDER,
    MAX_TASK_ITERATIONS,
    Config,
    _ensure_env_loaded,  # Lazy env loading for startup performance
)
from penguin.config import config as raw_config
from penguin.constants import DEFAULT_MAX_MESSAGES_PER_SESSION

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig, fetch_model_specs
from .core_runtime import action_execution as core_action_execution
from .core_runtime import agent_lifecycle_facade as core_agent_lifecycle_facade
from .core_runtime import checkpoint_facade as core_checkpoint_facade
from .core_runtime import conversation_facade as core_conversation_facade
from .core_runtime import conversations as core_conversations
from .core_runtime import diagnostics_facade as core_diagnostics_facade
from .core_runtime import message_processing as core_message_processing
from .core_runtime import model_runtime as core_model_runtime
from .core_runtime import opencode_facade as core_opencode_facade
from .core_runtime import process_runtime as core_process_runtime
from .core_runtime import prompt_facade as core_prompt_facade
from .core_runtime import response_generation as core_response_generation
from .core_runtime import runmode_facade as core_runmode_facade
from .core_runtime import state_facade as core_state_facade
from .core_runtime import startup as core_startup
from .core_runtime import streaming_facade as core_streaming_facade
from .core_runtime import token_usage_facade as core_token_usage_facade
from penguin.llm.stream_handler import (
    AgentStreamingStateManager,
)
from penguin.multi import coordinator_runtime as multi_coordinator_runtime

# Project manager
from penguin.project.manager import ProjectManager

# Core systems
from penguin.system.conversation_manager import ConversationManager

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.diagnostics import (
    disable_diagnostics,
)
from penguin.utils.log_error import log_error
from penguin.utils.parser import (
    ActionExecutor,
)
from penguin.utils.profiling import (
    profile_startup_phase,
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


def _trace_log_info(message: str, *args: Any) -> None:
    """Mirror core trace logs to uvicorn for live server debugging."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


# ---------------------------------------------------------------------------
# PenguinCore
# ---------------------------------------------------------------------------
class PenguinCore(
    core_agent_lifecycle_facade.AgentLifecycleCoreFacade,
    core_checkpoint_facade.CheckpointCoreFacade,
    core_conversation_facade.ConversationCoreFacade,
    core_diagnostics_facade.DiagnosticsCoreFacade,
    core_prompt_facade.PromptCoreFacade,
    core_runmode_facade.RunModeCoreFacade,
    core_state_facade.StateCoreFacade,
    core_streaming_facade.StreamingCoreFacade,
    core_token_usage_facade.TokenUsageCoreFacade,
    core_opencode_facade.OpenCodeCoreFacade,
):
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
        return await core_startup.create_core_instance(
            cls,
            config=config,
            model=model,
            provider=provider,
            workspace_path=workspace_path,
            enable_cli=enable_cli,
            show_progress=show_progress,
            progress_callback=progress_callback,
            fast_startup=fast_startup,
            default_model=DEFAULT_MODEL,
            default_provider=DEFAULT_PROVIDER,
            system_prompt=SYSTEM_PROMPT,
            config_loader=Config.load_config,
            model_config_factory=ModelConfig,
            api_client_factory=APIClient,
            tool_manager_factory=ToolManager,
            ensure_env_loaded=_ensure_env_loaded,
            log_error=log_error,
            tqdm_factory=tqdm,
            profile_phase=profile_startup_phase,
            logger=logger,
        )

    def __init__(
        self,
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        model_config: Optional[ModelConfig] = None,
        runtime_config: Optional["RuntimeConfig"] = None,
    ):
        """Initialize PenguinCore with required components."""
        from penguin.config import RuntimeConfig
        from penguin.cli.events import EventBus, EventType
        from penguin.config import WORKSPACE_PATH
        from penguin.engine import Engine, EngineSettings, TokenBudgetStop
        from penguin.system.checkpoint_manager import CheckpointConfig
        from penguin.tui_adapter import PartEventAdapter

        core_startup.initialize_core_instance_state(
            self,
            config=config,
            api_client=api_client,
            tool_manager=tool_manager,
            model_config=model_config,
            runtime_config=runtime_config,
            config_factory=Config.load_config,
            runtime_config_factory=RuntimeConfig,
            event_bus_factory=EventBus.get_sync,
            event_type_enum=EventType,
            stream_lock_factory=asyncio.Lock,
            stream_manager_factory=AgentStreamingStateManager,
            part_event_adapter_factory=PartEventAdapter,
            telemetry_ensurer=ensure_telemetry,
            raw_config=raw_config,
            get_system_prompt=get_system_prompt,
            fallback_system_prompt=SYSTEM_PROMPT,
            default_workspace_path=WORKSPACE_PATH,
            project_manager_factory=ProjectManager,
            diagnostics_disabler=disable_diagnostics,
            checkpoint_config_factory=CheckpointConfig,
            conversation_manager_factory=ConversationManager,
            action_executor_factory=ActionExecutor,
            default_max_messages_per_session=DEFAULT_MAX_MESSAGES_PER_SESSION,
            engine_factory=Engine,
            engine_settings_factory=EngineSettings,
            token_budget_stop_factory=TokenBudgetStop,
            logger=logger,
        )

    def _ensure_litellm_configured(self):
        """Configure LiteLLM on first use when the optional extra is installed."""
        core_model_runtime.ensure_litellm_runtime_state(self, log=logger)

    # ------------------------------------------------------------------
    # Coordinator accessor (singleton per Core)
    # ------------------------------------------------------------------
    def get_coordinator(self):
        """Return a singleton MultiAgentCoordinator bound to this Core."""
        return multi_coordinator_runtime.get_core_coordinator(self, log=logger)

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
        return await core_process_runtime.process_with_retry(
            self,
            input_data=input_data,
            context=context,
            conversation_id=conversation_id,
            agent_id=agent_id,
            max_iterations=max_iterations,
            context_files=context_files,
            streaming=streaming,
            stream_callback=stream_callback,
            multi_step=multi_step,
            api_client_override=api_client_override,
            model_config_override=model_config_override,
            log=logger,
            trace_log_info=_trace_log_info,
            log_error_fn=log_error,
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
