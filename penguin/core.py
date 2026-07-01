"""
PenguinCore acts as the central nervous system for Penguin, orchestrating
interactions between various subsystems.

Architecture:
    PenguinCore is the low-level public runtime object that assembles configuration,
    managers, provider clients, Engine, EventBus, TUI/OpenCode bridge state,
    and compatibility methods used by CLI, web/API, and Python callers.

    It wires long-lived collaborators and delegates behavior rather than
    implementing provider logic, conversation lineage, action mapping, token
    accounting, or orchestration rules directly.

Imported Systems:
    - Config and constants:
        Load runtime configuration, provider defaults, environment variables,
        workspace paths, and session/message limits.
    - APIClient and ModelConfig:
        Provide model/provider communication, streaming, reasoning support,
        provider-local model IDs, and runtime model configuration.
    - AgentStreamingStateManager:
        Tracks streaming state, assistant chunks, reasoning chunks, stream IDs,
        and per-agent stream isolation.
    - ProjectManager:
        Owns SQLite-backed project/task state used by RunMode and web/API
        orchestration surfaces.
    - ConversationManager:
        Owns sessions, messages, checkpoints, context-window trimming, and
        per-agent conversation state.
    - ToolManager and ActionExecutor:
        Register tools, parse model actions, execute tool calls, and return
        structured action results.
    - EventBus, MessageBus, and telemetry:
        Deliver UI/runtime events, route agent messages, and collect runtime
        diagnostics.
    - System prompt and startup helpers:
        Build the active prompt, initialize collaborators, profile startup, and
        apply fast-startup behavior.

Core Runtime Delegations:
    - Process methods:
        Exposes process(), process_message(), get_response(), and direct action
        execution while delegating to focused runtime helpers.
    - Model methods:
        Exposes model switching and current-model payloads backed by
        core_runtime.model_runtime.
    - Checkpoint methods:
        Exposes checkpoint, rollback, branch, cleanup, and checkpoint stats
        backed by core_runtime.checkpoint_runtime.
    - Token usage methods:
        Exposes runtime/session/agent token and context-window telemetry.
    - Streaming and OpenCode methods:
        Expose streaming state plus OpenCode/TUI event and transcript bridges.
    - Agent lifecycle, conversation, runmode, diagnostics, prompt, process,
      state, and coordinator methods:
        Preserve historical PenguinCore methods while keeping business logic in
        the owning runtime, manager, service, or domain module.

Design Principles:
    - Construction and delegation live here; business logic lives elsewhere.
    - Engine owns reasoning loops, tool execution flow, and task execution.
    - ConversationManager owns sessions, messages, checkpoints, and context.
    - Web routes stay thin; web-specific behavior belongs in web services.
    - Compatibility shims preserve public APIs without restoring deprecated
      architecture.
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
    coordinator_facade as core_coordinator_facade,
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
    core_coordinator_facade.CoordinatorCoreFacade,
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
    Construction, delegation, and compatibility surface for Penguin.

    `PenguinCore` wires long-lived collaborators and exposes the stable public
    methods that older callers still import from `penguin.core`. The actual
    behavior behind those methods lives in `penguin.core_runtime`, `Engine`,
    `RunMode`, `ConversationManager`, `ToolManager`, and web/service modules.
    New runtime or domain behavior should be implemented in the owning module,
    not directly on this class.

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
        # Default True for faster startup by deferring memory indexing.
        fast_startup: bool = True,
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        """
        Factory method for creating PenguinCore instance.
        Returns either PenguinCore alone or with CLI if enable_cli=True

        Args:
            fast_startup: If True (default), defer heavy operations like memory
                indexing until first use.
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
