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
from pathlib import Path
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
from penguin._version import __version__ as PENGUIN_VERSION

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig, fetch_model_specs
from .core_runtime import action_execution as core_action_execution
from .core_runtime import agent_lifecycle as core_agent_lifecycle
from .core_runtime import checkpoint_runtime as core_checkpoint_runtime
from .core_runtime import conversations as core_conversations
from .core_runtime import core_state as core_state_runtime
from .core_runtime import message_processing as core_message_processing
from .core_runtime import model_runtime as core_model_runtime
from .core_runtime import opencode_facade as core_opencode_facade
from .core_runtime import process_runtime as core_process_runtime
from .core_runtime import prompt_settings as core_prompt_settings
from .core_runtime import response_generation as core_response_generation
from .core_runtime import runmode_lifecycle as core_runmode_lifecycle
from .core_runtime import startup as core_startup
from .core_runtime import streaming_facade as core_streaming_facade
from .core_runtime import system_diagnostics as core_system_diagnostics
from .core_runtime import token_usage_runtime as core_token_usage_runtime
from penguin.llm.stream_handler import (
    AgentStreamingStateManager,
)
from penguin.multi import coordinator_runtime as multi_coordinator_runtime
from penguin.multi import routing as multi_routing

# Project manager
from penguin.project.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.diagnostics import (
    diagnostics,
    disable_diagnostics,
)
from penguin.utils.log_error import log_error
from penguin.utils.parser import (
    ActionExecutor,
)
from penguin.utils.profiling import (
    profile_startup_phase,
    profiler,
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
    core_streaming_facade.StreamingCoreFacade,
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
        return core_agent_lifecycle.create_agent_conversation(self, agent_id)

    def list_all_conversations(self, *, limit_per_agent: int = 1000, offset: int = 0):
        return core_agent_lifecycle.list_agent_conversations(
            self,
            limit_per_agent=limit_per_agent,
            offset=offset,
        )

    def load_agent_conversation(
        self, agent_id: str, conversation_id: str, *, activate: bool = True
    ) -> bool:
        return core_agent_lifecycle.load_agent_conversation(
            self, agent_id, conversation_id, activate=activate
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
        return core_agent_lifecycle.list_agents(self)

    def list_sub_agents(
        self, parent_agent_id: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """Return mapping of parent agents to sub-agents."""
        return core_agent_lifecycle.list_sub_agents(self, parent_agent_id)

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
