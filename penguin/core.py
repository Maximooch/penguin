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
    Config,
    _ensure_env_loaded,
    config as raw_config,
)
from penguin.constants import DEFAULT_MAX_MESSAGES_PER_SESSION

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
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

from .core_runtime import (
    agent_lifecycle_facade as core_agent_lifecycle_facade,
    checkpoint_facade as core_checkpoint_facade,
    conversation_facade as core_conversation_facade,
    diagnostics_facade as core_diagnostics_facade,
    model_facade as core_model_facade,
    opencode_facade as core_opencode_facade,
    process_facade as core_process_facade,
    prompt_facade as core_prompt_facade,
    runmode_facade as core_runmode_facade,
    startup as core_startup,
    state_facade as core_state_facade,
    streaming_facade as core_streaming_facade,
    token_usage_facade as core_token_usage_facade,
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


# ---------------------------------------------------------------------------
# PenguinCore
# ---------------------------------------------------------------------------
class PenguinCore(
    core_agent_lifecycle_facade.AgentLifecycleCoreFacade,
    core_checkpoint_facade.CheckpointCoreFacade,
    core_conversation_facade.ConversationCoreFacade,
    core_diagnostics_facade.DiagnosticsCoreFacade,
    core_model_facade.ModelCoreFacade,
    core_process_facade.ProcessCoreFacade,
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
        from penguin.cli.events import EventBus, EventType
        from penguin.config import WORKSPACE_PATH, RuntimeConfig
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

    # ------------------------------------------------------------------
    # Coordinator accessor (singleton per Core)
    # ------------------------------------------------------------------
    def get_coordinator(self):
        """Return a singleton MultiAgentCoordinator bound to this Core."""
        return multi_coordinator_runtime.get_core_coordinator(self, log=logger)
