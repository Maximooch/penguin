"""
PenguinCore acts as the central nervous system for the Penguin AI assistant, orchestrating interactions between various subsystems.

Key Systems:
- ConversationManager: Handles messages, context, conversation persistence, and formatting
- ToolManager: Manages available tools and capabilities
- ActionExecutor: Routes and executes actions using appropriate handlers
- ProjectManager: Handles project and task management
- Diagnostic System: Monitors performance and resource usage

The core acts as a coordinator rather than implementing functionality directly:
- Routes messages and actions between subsystems
- Manages initialization and cleanup
- Handles error conditions and recovery
- Provides unified interface for external interaction

Key Features:
- Modular architecture allowing easy extension
- Robust error handling and logging
- Configurable diagnostic tracking
- Support for multiple conversation modes
- Flexible tool integration system
- Project and task management capabilities

API Specification:

Core Methods:
    @classmethod
    async create(
        cls,
        config: Optional[Config] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None,
        enable_cli: bool = False,
        show_progress: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        fast_startup: bool = False
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        Factory method for creating PenguinCore instance with optional CLI

    __init__(
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        model_config: Optional[ModelConfig] = None
    ) -> None:
        Initialize PenguinCore with optional config and components

    async process_message(
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        streaming: bool = False
    ) -> str:
        Process a user message and return formatted response

    async process(
        input_data: Union[Dict[str, Any], str],
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        max_iterations: int = 5,
        context_files: Optional[List[str]] = None,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        multi_step: bool = False,
    ) -> Dict[str, Any]:
        Process input with multi-step reasoning and action execution

    async get_response(
        current_iteration: Optional[int] = None,
        max_iterations: Optional[int] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        streaming: Optional[bool] = None
    ) -> Tuple[Dict[str, Any], bool]:
        Generate response using conversation context
        Returns response data and continuation flag

    async start_run_mode(
        name: Optional[str] = None,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        continuous: bool = False,
        time_limit: Optional[int] = None,
        mode_type: str = "task",
        stream_callback_for_cli: Optional[Callable[[str], Awaitable[None]]] = None,
        ui_update_callback_for_cli: Optional[Callable[[], Awaitable[None]]] = None
    ) -> None:
        Start autonomous run mode for task execution

Conversation Management:
    list_conversations(limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        List available conversations with pagination

    get_conversation(conversation_id: str) -> Optional[Dict[str, Any]]:
        Get a specific conversation by ID

    create_conversation() -> str:
        Create a new conversation and return its ID

    delete_conversation(conversation_id: str) -> bool:
        Delete a conversation by ID

    get_conversation_stats() -> Dict[str, Any]:
        Get statistics about conversations

    list_context_files() -> List[Dict[str, Any]]:
        List all available context files

State Management:
    reset_context() -> None:
        Reset conversation context and diagnostics

    async reset_state() -> None:
        Reset core state including messages, tools, and external resources

    set_system_prompt(prompt: str) -> None:
        Set system prompt for conversation

    register_progress_callback(callback: Callable[[int, int, Optional[str]], None]) -> None:
        Register a callback for progress updates

Properties:
    total_tokens_used -> int:
        Get total tokens used in current session

    get_token_usage() -> Dict[str, Dict[str, int]]:
        Get detailed token usage statistics

Action Handling:
    async execute_action(action) -> Dict[str, Any]:
        Execute an action and return structured result

Usage:
The core should be initialized with required configuration and subsystems before use.
It provides high-level methods for message processing, task execution, and system control.

Example:
    core = await PenguinCore.create(config=config)
    response = await core.process_message("Hello!")
    await core.start_run_mode(name="coding_task")
"""

import asyncio
import logging
import time
import traceback
import os
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, Callable, Awaitable, Set
import asyncio
import json
from datetime import datetime
import uuid  # For unique stream IDs

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
    Config,
)

# LLM and API
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig

# Project manager
from penguin.project.manager import ProjectManager

# RunMode
from penguin.run_mode import RunMode

# Core systems
from penguin.system.conversation_manager import ConversationManager
from penguin.system.state import MessageCategory, Message

# System Prompt
from penguin.system_prompt import SYSTEM_PROMPT
# Workflow Prompt
from penguin.prompt_workflow import PENGUIN_WORKFLOW

# Tools and Processing
from penguin.tools import ToolManager
from penguin.utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
from penguin.utils.log_error import log_error
from penguin.utils.parser import ActionExecutor, parse_action
from penguin.utils.profiling import profile_startup_phase, profile_operation, profiler, print_startup_report
try:
    from penguin.system.message_bus import MessageBus, ProtocolMessage
except Exception:  # pragma: no cover
    MessageBus = None  # type: ignore
    ProtocolMessage = None  # type: ignore

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
        ui_subscribers (List[EventHandler]): UI components that receive events
    """
    
    @classmethod
    async def create(
        cls,
        config: Optional[Config] = None,
        model: Optional[str] = None,
        provider: Optional[str] = None,
        workspace_path: Optional[str] = None,
        enable_cli: bool = False,
        show_progress: bool = True,
        progress_callback: Optional[Callable[[int, int, str], None]] = None,
        fast_startup: bool = False
    ) -> Union["PenguinCore", Tuple["PenguinCore", "PenguinCLI"]]:
        """
        Factory method for creating PenguinCore instance.
        Returns either PenguinCore alone or with CLI if enable_cli=True
        
        Args:
            fast_startup: If True, defer heavy operations like memory indexing until first use
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
                        max_tokens=getattr(config.model_config, 'max_tokens', None),
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
        
        # Add event system
        self.ui_subscribers: List[EventHandler] = []
        # Allowed UI event types – expanded to include action/tool events emitted
        # by the Engine/RunMode so the TUI can consume them without warnings.
        self.event_types: Set[str] = {
            "stream_chunk",
            "token_update",
            "message",
            "status",
            "error",
            # Additional structured events used across the app
            "action",
            "action_result",
            "tool_call",
            "tool_result",
            # Human-in-the-loop adapter events
            "human_message",
        }

        # Set system prompt from import
        self.system_prompt = SYSTEM_PROMPT

        # Initialize streaming primitives immediately (before Engine/handlers can use them)
        self.current_stream = None
        self.stream_lock = asyncio.Lock()
        self._streaming_state = {
            "active": False,
            "content": "",
            "reasoning_content": "",
            "message_type": None,
            "role": None,
            "metadata": {},
            "started_at": None,
            "last_update": None,
            "empty_response_count": 0,
            "error": None,
            # Coalescing buffer to avoid per-token UI updates
            "emit_buffer": "",
            "last_emit_ts": 0.0,
        }

        # Initialize project manager with workspace path from config
        from penguin.config import WORKSPACE_PATH
        self.project_manager = ProjectManager(workspace_path=WORKSPACE_PATH)

        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()
        
        # Ensure model_config max_tokens is consistent – prefer context_window from config
        if model_config and not hasattr(model_config, 'max_tokens'):
            model_config.max_tokens = self.config.model.get("context_window") or self.config.model.get("max_tokens", 8000)
        elif model_config and model_config.max_tokens is None:
            model_config.max_tokens = self.config.model.get("context_window") or self.config.model.get("max_tokens", 8000)

        # Initialize conversation manager (replaces conversation system)
        from penguin.config import WORKSPACE_PATH
        from penguin.system.checkpoint_manager import CheckpointConfig
        
        # Create checkpoint configuration
        checkpoint_config = CheckpointConfig(
            enabled=True,
            frequency=1,  # Checkpoint every message
            planes={"conversation": True, "tasks": False, "code": False},
            retention={"keep_all_hours": 24, "keep_every_nth": 10, "max_age_days": 30},
            max_auto_checkpoints=1000
        )
        
        self.conversation_manager = ConversationManager(
            model_config=model_config,
            api_client=api_client,
            workspace_path=WORKSPACE_PATH,
            system_prompt=SYSTEM_PROMPT,
            max_messages_per_session=5000,
            max_sessions_in_memory=20,
            auto_save_interval=60,
            checkpoint_config=checkpoint_config
        )
        # Attach a back-reference so Engine (and other helpers) can emit UI events
        # and finalize streaming messages via the Core.  Without this the Engine
        # silently skips those steps which caused tool results to be lost and
        # streaming panels to merge into a single message in the CLI.
        self.conversation_manager.core = self  # type: ignore[attr-defined]

        # Initialize action executor with project manager and conversation manager
        print("DEBUG: Initializing ActionExecutor...")
        print(f"DEBUG: ToolManager type: {type(self.tool_manager)}")
        print(f"DEBUG: ProjectManager type: {type(self.project_manager)}")
        print(f"DEBUG: ConversationManager type: {type(self.conversation_manager)}")
        self.action_executor = ActionExecutor(
            self.tool_manager,
            self.project_manager,
            self.conversation_manager,
            ui_event_callback=self.emit_ui_event,
        )
        self.current_runmode_status_summary: str = "RunMode idle." # New attribute

        # Register MessageBus human adapter to forward to UI
        try:
            if MessageBus and ProtocolMessage:
                bus = MessageBus.get_instance()

                async def _human_handler(msg: ProtocolMessage):
                    payload = {
                        "agent_id": msg.sender,
                        "recipient_id": msg.recipient,
                        "content": msg.content,
                        "message_type": msg.message_type,
                        "metadata": msg.metadata,
                        "session_id": msg.session_id,
                        "message_id": msg.message_id,
                    }
                    await self.emit_ui_event("human_message", payload)

                bus.register_handler("human", _human_handler)
        except Exception as e:
            logger.debug(f"MessageBus human adapter not registered: {e}")

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
    # Multi-agent helpers (Core ↔ Engine wiring)
    # ------------------------------------------------------------------

    def register_agent(
        self,
        agent_id: str,
        *,
        system_prompt: Optional[str] = None,
        activate: bool = False,
        share_session_with: Optional[str] = None,
        share_context_window_with: Optional[str] = None,
        shared_cw_max_tokens: Optional[int] = None,
        model_max_tokens: Optional[int] = None,
    ) -> None:
        """Register an agent with a per-agent ActionExecutor bound to its conversation.

        - Ensures an agent-scoped ConversationSystem exists in ConversationManager
        - Creates an ActionExecutor that targets that agent's conversation
        - Registers the agent with Engine, overriding the action executor for that agent

        Args:
            agent_id: Unique agent identifier
            system_prompt: Optional system prompt override for the agent
            activate: If True, makes this the active/default agent for subsequent calls
        """
        if not getattr(self, 'engine', None):
            raise RuntimeError("Engine is not initialized; cannot register agents")

        # Provision agent or sub-agent
        # Determine effective clamp target for shared CW
        effective_cw_cap = None
        if shared_cw_max_tokens is not None and model_max_tokens is not None:
            effective_cw_cap = min(int(shared_cw_max_tokens), int(model_max_tokens))
        elif shared_cw_max_tokens is not None:
            effective_cw_cap = int(shared_cw_max_tokens)
        elif model_max_tokens is not None:
            effective_cw_cap = int(model_max_tokens)

        if share_session_with or share_context_window_with:
            parent = share_session_with or share_context_window_with  # prefer explicit share_session target
            self.conversation_manager.create_sub_agent(
                agent_id,
                parent_agent_id=parent,
                share_session=bool(share_session_with),
                share_context_window=True if (share_session_with or share_context_window_with) else False,
                shared_cw_max_tokens=effective_cw_cap,
            )
            conv = self.conversation_manager.get_agent_conversation(agent_id)
        else:
            # Ensure isolated agent conversation exists
            conv = self.conversation_manager.get_agent_conversation(agent_id, create_if_missing=True)
        if system_prompt:
            conv.set_system_prompt(system_prompt)

        # Create per-agent ActionExecutor targeting this agent's conversation
        agent_action_executor = ActionExecutor(
            self.tool_manager,
            self.project_manager,
            conv,  # Pass ConversationSystem so tools can add messages directly
            ui_event_callback=self.emit_ui_event,
        )

        # Register with Engine using the shared ConversationManager but per-agent executor
        try:
            self.engine.register_agent(
                agent_id=agent_id,
                conversation_manager=self.conversation_manager,
                action_executor=agent_action_executor,
            )
        except Exception as e:
            logger.error(f"Failed to register agent '{agent_id}' with Engine: {e}")
            raise

        if activate:
            self.set_active_agent(agent_id)

        # Register MessageBus inbox for this agent (route messages to conversation)
        try:
            if MessageBus and ProtocolMessage:
                bus = MessageBus.get_instance()

                async def _agent_inbox(msg: ProtocolMessage, *, _agent_id: str = agent_id):
                    try:
                        self.conversation_manager.set_current_agent(_agent_id)
                        conv_local = self.conversation_manager.get_agent_conversation(_agent_id)
                        conv_local.add_message(
                            role="user",
                            content=msg.content,
                            category=MessageCategory.DIALOG,
                            metadata={"via": "message_bus", "from": msg.sender, **(msg.metadata or {})},
                            message_type=msg.message_type or "message",
                        )
                        self.conversation_manager.save()
                        await self.emit_ui_event("message", {
                            "role": "user",
                            "content": msg.content,
                            "category": MessageCategory.DIALOG.name,
                            "message_type": msg.message_type or "message",
                            "metadata": {"via": "message_bus", "from": msg.sender}
                        })
                    except Exception as e:
                        logger.debug(f"Agent inbox handler failed: {e}")

                bus.register_handler(agent_id, _agent_inbox)
        except Exception as e:
            logger.debug(f"MessageBus agent inbox not registered: {e}")

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

    # ------------------------------
    # Message routing via MessageBus
    # ------------------------------
    async def route_message(
        self,
        recipient_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
    ) -> bool:
        try:
            if not (MessageBus and ProtocolMessage):
                return False
            sender = agent_id or getattr(self.conversation_manager, "current_agent_id", None)
            session_id = None
            try:
                session = self.conversation_manager.get_current_session()
                session_id = getattr(session, "id", None)
            except Exception:
                pass
            msg = ProtocolMessage(
                sender=sender,
                recipient=recipient_id,
                content=content,
                message_type=message_type,
                metadata=metadata or {},
                session_id=session_id,
            )
            await MessageBus.get_instance().send(msg)
            return True
        except Exception as e:
            logger.error(f"route_message failed: {e}")
            return False

    # Convenience wrappers
    async def send_to_agent(self, agent_id: str, content: Any, *, message_type: str = "message", metadata: Optional[Dict[str, Any]] = None) -> bool:
        return await self.route_message(agent_id, content, message_type=message_type, metadata=metadata)

    async def send_to_human(self, content: Any, *, message_type: str = "status", metadata: Optional[Dict[str, Any]] = None) -> bool:
        # Sender defaults to current agent; recipient is "human"
        return await self.route_message("human", content, message_type=message_type, metadata=metadata)

    async def human_reply(self, agent_id: str, content: Any, *, message_type: str = "message", metadata: Optional[Dict[str, Any]] = None) -> bool:
        """Convenience wrapper for human → agent directed replies via MessageBus.

        Semantically the same as send_to_agent, but forces the sender identity to
        "human" in the envelope.
        """
        try:
            if not (MessageBus and ProtocolMessage):
                # Fallback: treat as regular user message to the current conversation
                self.conversation_manager.conversation.add_message(
                    role="user",
                    content=content,
                    category=MessageCategory.DIALOG,
                    metadata={"via": "human_reply", **(metadata or {})},
                    message_type=message_type,
                )
                self.conversation_manager.save()
                await self.emit_ui_event("message", {
                    "role": "user",
                    "content": content,
                    "category": MessageCategory.DIALOG.name,
                    "message_type": message_type,
                    "metadata": {"via": "human_reply"}
                })
                return True

            # Build ProtocolMessage with sender="human"
            session_id = None
            try:
                session = self.conversation_manager.get_current_session()
                session_id = getattr(session, "id", None)
            except Exception:
                pass
            msg = ProtocolMessage(
                sender="human",
                recipient=agent_id,
                content=content,
                message_type=message_type,
                metadata=metadata or {},
                session_id=session_id,
            )
            await MessageBus.get_instance().send(msg)
            return True
        except Exception as e:
            logger.error(f"human_reply failed: {e}")
            return False

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
                        cw_max = u.get("max", u.get("max_tokens"))
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

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted

    async def process_message(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
        conversation_id: Optional[str] = None,
        context_files: Optional[List[str]] = None,
        streaming: bool = False
    ) -> str:
        """
        Process a message with optional conversation support.
        
        Args:
            message: The user message to process
            context: Optional additional context for processing
            conversation_id: Optional ID to continue an existing conversation
            context_files: Optional list of context files to load
            streaming: Whether to use streaming mode for responses
        """
        try:
            # Add context if provided
            if context:
                for key, value in context.items():
                    self.conversation_manager.add_context(f"{key}: {value}")
                    
            # Process through conversation manager (handles context files)
            return await self.conversation_manager.process_message(
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

                # --- MODIFIED PART: Directly await the API call --- 
                # self.current_stream = asyncio.create_task(...)
                assistant_response = None # Initialize
                try:
                    # Directly await the call, passing the callback
                    logger.debug(json.dumps(self.conversation_manager.conversation.get_formatted_messages(), indent=2))
                    assistant_response = await self.api_client.get_response(
                        messages=messages,
                        stream=streaming,
                        stream_callback=stream_callback
                    )
                except asyncio.CancelledError:
                    # This might happen if the outer request (e.g., websocket) is cancelled
                    logger.warning("APIClient response retrieval was cancelled")
                    # No specific stream task to cancel here
                except Exception as e:
                    logger.error(f"Error during APIClient response retrieval: {str(e)}", exc_info=True)
                # No finally block needed here for stream management
                # --- END MODIFIED PART --- 

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
                self.conversation_manager.conversation.add_assistant_message(assistant_response)
            
            # Parse actions and continue with action handling
            actions = parse_action(assistant_response)
            
            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in assistant_response
            
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
                "penguin_version": "0.3.1",  # TODO: Extract from __init__.py
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
                "streaming_active": getattr(self, '_streaming_state', {}).get('active', False),
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
        max_iterations: int = 5,
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
            image_path = None
        else:
            message = input_data.get("text", "")
            image_path = input_data.get("image_path")
            
        if not message and not image_path:
            return {"assistant_response": "No input provided", "action_results": []}
            
        try:
            # Load conversation if ID provided
            if conversation_id:
                if not self.conversation_manager.load(conversation_id):
                    logger.warning(f"Failed to load conversation {conversation_id}")
                    
            # Load context files if specified
            if context_files:
                for file_path in context_files:
                    self.conversation_manager.load_context_file(file_path)
            
            # Add user message to conversation explicitly
            user_message_dict = {
                "role": "user",
                "content": message,
                "category": MessageCategory.DIALOG
            }
            
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
                            image_path=image_path,
                            max_iterations=max_iterations,
                            task_context=context,
                            message_callback=engine_message_callback,
                        )
                    else:
                        # Use the new conversational multi-step engine
                        response = await self.engine.run_response(
                            prompt=message,
                            image_path=image_path,
                            max_iterations=max_iterations,
                            streaming=streaming,
                            stream_callback=engine_stream_callback
                        )
                else:
                    # Use the single-turn conversational engine
                    response = await self.engine.run_single_turn(
                        message, 
                        image_path=image_path, 
                        streaming=streaming, 
                        stream_callback=engine_stream_callback
                    )
            else:
                # ---------- Legacy path (fallback) ----------
                # Prepare conversation and call get_response directly
                self.conversation_manager.conversation.prepare_conversation(message, image_path)

                # FIX: Set the callback for event-based streaming, even in legacy mode
                internal_stream_callback = self._handle_stream_chunk if streaming else None
                
                response, _ = await self.get_response(
                    stream_callback=internal_stream_callback, # Pass the correct callback
                    streaming=streaming
                )

            # TODO: Should be at least 3 attempts. 
            # with exponential backoff?

            # ------------------------------------------------------------------
            # Empty-response fallback – if the assistant returned no content we
            # immediately retry once with *streaming disabled*.  This addresses
            # rare provider quirks where streaming yields an empty string.
            # ------------------------------------------------------------------
            if isinstance(response, dict) and not response.get("assistant_response", "").strip():
                try:
                    logger.warning("Assistant response was empty – retrying once without streaming…")
                    retry_data, _ = await self.get_response(streaming=False)
                    if retry_data and retry_data.get("assistant_response", "").strip():
                        response["assistant_response"] = retry_data["assistant_response"]
                        # Propagate any action results gathered during retry
                        response["action_results"] = retry_data.get("action_results", [])
                        logger.info("Non-streaming retry succeeded and produced a response.")
                except Exception as retry_err:
                    logger.warning(f"Non-streaming retry after empty response failed: {retry_err}")

            # Ensure conversation is saved after processing
            self.conversation_manager.save()
            
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
                        },
                    )

            # Ensure token usage is emitted after processing
            token_data = self.conversation_manager.get_token_usage()
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

    async def multi_step_process(
        self,
        message: str,
        image_path: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        max_iterations: int = 5,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None
    ) -> Dict[str, Any]:
        """
        Process a message with multi-step reasoning and action execution.

        DEPRECATED: This logic has moved to `Engine.run_task`. This method
        is now a compatibility wrapper. Please use `core.process(..., multi_step=True)`
        or call the engine directly.
        """
        logger.warning(
            "`PenguinCore.multi_step_process` is deprecated and will be removed. "
            "Use `core.process(..., multi_step=True)` instead."
        )
        if not self.engine:
            return {
                "assistant_response": "Multi-step processing requires the Engine, which is not available.",
                "action_results": [],
                "error": "Engine not initialized"
            }
        
        # This is now a simple wrapper around the new `process` method with the flag enabled.
        return await self.process(
            input_data={"text": message, "image_path": image_path},
            context=context,
            max_iterations=max_iterations,
            streaming=streaming,
            stream_callback=stream_callback,
            multi_step=True,
        )

    def list_conversations(self, limit: int = 20, offset: int = 0) -> List[Dict[str, Any]]:
        """
        List available conversations.
        
        Args:
            limit: Maximum number of conversations to return
            offset: Offset for pagination
            
        Returns:
            List of conversations with metadata
        """
        return self.conversation_manager.list_conversations(limit=limit, offset=offset)
        
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
                        "timestamp": msg.timestamp
                    }
                    for msg in session.messages
                ],
                "created_at": session.created_at,
                "last_active": session.last_active,
                "metadata": session.metadata
            }
        return None
        
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
        
        # Initialize status
        self.current_runmode_status_summary = "Starting RunMode..."
        
        try:
            run_mode = RunMode(
                self,  # core instance
                time_limit=time_limit,
                event_callback=self._handle_run_mode_event
            )
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
            # Clear the UI update callback reference when finished
            self._ui_update_callback = None
            
            # Ensure state is cleaned up if run mode was not continuous or if continuous mode exited
            if hasattr(run_mode, 'continuous_mode') and not run_mode.continuous_mode:
                self._continuous_mode = False
            
            logger.info(f"Exiting start_run_mode. Core _continuous_mode: {self._continuous_mode}")

    # ------------------------------------------------------------------
    # Model management helpers
    # ------------------------------------------------------------------

    def _apply_new_model_config(self, new_model_config: ModelConfig) -> None:
        """Internal helper that swaps the model configuration and re-wires dependent components.

        This keeps the public ``load_model`` method concise and focused on
        validation / construction of the ``ModelConfig``.  All mutation of
        run-time state happens here so that we only need to test it in one
        place.
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
            # Fetch model specifications first
            model_specs = await self._fetch_model_specifications(model_id)
            logger.info(f"Fetched specs for {model_id}: {model_specs}")
            
            # -----------------------------------------------------------------
            # 1. Locate configuration for the requested model
            # -----------------------------------------------------------------
            model_conf: Optional[Dict[str, Any]] = None
            if hasattr(self.config, "model_configs") and isinstance(self.config.model_configs, dict):
                model_conf = self.config.model_configs.get(model_id)

            # If not found in explicit configs attempt to infer from the id.
            if model_conf is None:
                if "/" not in model_id:
                    logger.error(f"Model id '{model_id}' not found in model_configs and does not appear to be fully-qualified.")
                    return False
                provider_part = model_id.split("/", 1)[0]
                # Decide on client preference – default to whatever the core is
                # currently using so that we remain consistent with the user's
                # environment (e.g. OpenRouter).
                client_pref = self.model_config.client_preference if self.model_config else "native"

                # If the current preference is OpenRouter we *override* the
                # provider to "openrouter" because the upstream ID still has
                # the real provider encoded in the model string (e.g.
                # "openai/gpt-4o").
                provider_for_config = "openrouter" if client_pref == "openrouter" else provider_part

                model_conf = {
                    "model": model_id,
                    "provider": provider_for_config,
                    "client_preference": client_pref,
                    "streaming_enabled": True,
                    # Prefer full context window when available; this is what
                    # ContextWindowManager and Interface use for budgeting.
                    "max_tokens": model_specs.get("context_length") or model_specs.get("max_output_tokens"),
                }

            # Sanity-check we have the minimum required keys.
            provider = model_conf.get("provider")
            if provider is None:
                logger.error(f"Invalid configuration for model '{model_id}': missing provider field.")
                return False

            # Update max_tokens with fetched specs – prefer context_length
            if "context_length" in model_specs:
                model_conf["max_tokens"] = model_specs["context_length"]
            elif "max_output_tokens" in model_specs:
                model_conf["max_tokens"] = model_specs["max_output_tokens"]
            else:
                # If we don't have real specs, error instead of guessing
                logger.error(f"Could not fetch context_length/max_output_tokens for model '{model_id}' from OpenRouter API")
                return False

            # -----------------------------------------------------------------
            # 2. Build a fresh ModelConfig object from the dict
            # -----------------------------------------------------------------
            new_mc_kwargs = {
                "model": model_conf.get("model", model_id),
                "provider": provider,
                "client_preference": model_conf.get("client_preference", "native"),
                "api_base": model_conf.get("api_base"),
                "max_tokens": model_conf.get("max_tokens"),
                "temperature": model_conf.get("temperature", 0.7),
                "use_assistants_api": model_conf.get("use_assistants_api", False),
                "streaming_enabled": model_conf.get("streaming_enabled", True),
                "vision_enabled": model_conf.get("vision_enabled"),
            }
            new_model_config = ModelConfig(**new_mc_kwargs)  # type: ignore[arg-type]

            # -----------------------------------------------------------------
            # 3. Apply it to running components
            # -----------------------------------------------------------------
            self._apply_new_model_config(new_model_config)
            
            # -----------------------------------------------------------------
            # 4. Update config.yml with new model specifications
            # -----------------------------------------------------------------
            self._update_config_file_with_model(model_id, model_specs)
            
            logger.info(f"Successfully switched to model '{model_id}' with context window {model_specs.get('context_length', 'unknown')} tokens.")
            return True
        except Exception as e:
            logger.error(f"Failed to switch to model '{model_id}': {e}")
            return False

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
                "max_tokens": conf.get("max_tokens"),
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
            "max_tokens": getattr(self.model_config, 'max_tokens', None),
            "temperature": getattr(self.model_config, 'temperature', None),
            "streaming_enabled": self.model_config.streaming_enabled,
            "vision_enabled": bool(getattr(self.model_config, 'vision_enabled', False)),
            "api_base": getattr(self.model_config, 'api_base', None)
        }

    # Add new event system methods
    def register_ui(self, handler: Callable[[str, Dict[str, Any]], Any]) -> None:
        """
        Register a UI component to receive events from the Core.
        
        Args:
            handler: A function or coroutine that accepts event_type and data parameters
        """
        if handler not in self.ui_subscribers:
            self.ui_subscribers.append(handler)
            logger.debug(f"Registered UI event handler: {handler.__qualname__ if hasattr(handler, '__qualname__') else str(handler)}")
    
    def unregister_ui(self, handler: EventHandler) -> None:
        """
        Unregister a UI component from receiving events.
        
        Args:
            handler: The handler function to remove
        """
        if handler in self.ui_subscribers:
            self.ui_subscribers.remove(handler)
            logger.debug(f"Unregistered UI event handler: {handler.__qualname__ if hasattr(handler, '__qualname__') else str(handler)}")
    
    async def emit_ui_event(self, event_type: str, data: Dict[str, Any]) -> None:
        logger.debug(f"Core emit_ui_event {event_type} keys={list(data.keys())}")
        """
        Emit an event to all registered UI subscribers.
        
        Args:
            event_type: Type of event (e.g., "stream_chunk", "token_update", etc.)
            data: Event data relevant to the event type
        """
        if event_type not in self.event_types:
            logger.warning(f"Emitting event of unknown type: {event_type}")
            
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

        logger.debug(f"Emitting UI event: {event_type} with data keys: {list(data.keys())}")
        
        for handler in self.ui_subscribers:
            try:
                # CRITICAL FIX: Make event emission fire-and-forget to prevent blocking streaming
                # Check if the handler is a coroutine function and call it appropriately
                if asyncio.iscoroutinefunction(handler):
                    # Don't await - let it run in background to prevent stalling streaming
                    asyncio.create_task(self._handle_ui_event_safe(handler, event_type, data))
                else:
                    # Call synchronous handler directly (these are typically fast)
                    handler(event_type, data)
            except Exception as e:
                logger.error(f"Error in UI event handler during {event_type} event: {e}", exc_info=True)

    async def _handle_ui_event_safe(self, handler: Callable, event_type: str, data: Dict[str, Any]) -> None:
        """
        Safely handle UI events in background without blocking streaming.
        
        This wrapper ensures that slow or failing UI handlers don't stall
        the core streaming process.
        """
        try:
            await handler(event_type, data)
        except Exception as e:
            logger.error(f"Error in background UI event handler during {event_type} event: {e}", exc_info=True)

    # Update stream_chunk to use the event system
    async def _handle_stream_chunk(self, chunk: str, message_type: Optional[str] = None, role: str = "assistant") -> None:
        """
        Central handler for all streaming content chunks from any source.
        Updates internal streaming state and notifies subscribers via events.
        
        Args:
            chunk: The content chunk to add
            message_type: Type of message - "assistant", "reasoning", "tool_output", etc.
            role: The role of the message (default: "assistant")
        """
        # If message_type is not provided, default to "assistant"
        if message_type is None:
            message_type = "assistant"
            
        if not chunk or not chunk.strip():
            # Don't initialize streaming or emit events for empty chunks
            # Only track empty chunks if streaming is already active
            if self._streaming_state["active"]:
                self._streaming_state["empty_response_count"] += 1
                if self._streaming_state["empty_response_count"] > 3:
                    if not self._streaming_state["error"]:
                        self._streaming_state["error"] = "Multiple empty responses received"
                    logger.warning(f"PenguinCore: Multiple empty responses ({self._streaming_state['empty_response_count']}) received during streaming")
            return
        
        # Reset empty counter if we got actual content
        self._streaming_state["empty_response_count"] = 0
        
        # Initialize streaming if this is the first chunk
        now = datetime.now()
        if not self._streaming_state["active"]:
            # --- Begin new streaming message ---
            self._streaming_state["active"] = True
            self._streaming_state["content"] = ""
            self._streaming_state["reasoning_content"] = ""
            self._streaming_state["message_type"] = message_type
            self._streaming_state["role"] = role
            self._streaming_state["started_at"] = now
            self._streaming_state["metadata"] = {"is_streaming": True}
            # Generate a unique stream_id to tag all subsequent chunks.
            self._streaming_state["id"] = uuid.uuid4().hex
        
        # Handle different message types
        if message_type == "reasoning":
            # Track reasoning separately and emit immediately (it's lightweight)
            self._streaming_state["reasoning_content"] += chunk
            self._streaming_state["last_update"] = now
            await self.emit_ui_event("stream_chunk", {
                "stream_id": self._streaming_state.get("id"),
                "chunk": chunk,
                "is_final": False,
                "message_type": message_type,
                "role": role,
                "content_so_far": self._streaming_state["content"],
                "reasoning_so_far": self._streaming_state.get("reasoning_content", ""),
                "metadata": self._streaming_state["metadata"],
                "is_reasoning": True,
            })
            return
        
        # Regular assistant content – append and coalesce tiny bursts to avoid
        # token-by-token UI updates in RunMode.
        self._streaming_state["content"] += chunk
        self._streaming_state["last_update"] = now

        # Coalescing thresholds
        try:
            import time as _time
            ts_now = _time.monotonic()
        except Exception:
            ts_now = 0.0
        buf: str = self._streaming_state.get("emit_buffer", "") + chunk
        last_ts: float = float(self._streaming_state.get("last_emit_ts", 0.0))
        min_interval = 0.04  # ~25 fps
        min_chars = 12       # small bursts

        should_emit = (len(buf) >= min_chars) or (last_ts == 0.0) or ((ts_now - last_ts) >= min_interval)
        if should_emit:
            # Emit buffered chunk
            await self.emit_ui_event("stream_chunk", {
                "stream_id": self._streaming_state.get("id"),
                "chunk": buf,
                "is_final": False,
                "message_type": message_type,
                "role": role,
                "content_so_far": self._streaming_state["content"],
                "reasoning_so_far": self._streaming_state.get("reasoning_content", ""),
                "metadata": self._streaming_state["metadata"],
                "is_reasoning": False,
            })
            self._streaming_state["emit_buffer"] = ""
            self._streaming_state["last_emit_ts"] = ts_now
        else:
            # Keep buffering until threshold; defer UI emission
            self._streaming_state["emit_buffer"] = buf

        if chunk and self._streaming_state["content"].endswith(chunk):
            return          # suppress prefix-repeat

    def finalize_streaming_message(self) -> Optional[Dict[str, Any]]:
        """
        Finalizes the current streaming message, adds it to ConversationManager,
        and resets the streaming state. Emits a final event with is_final=True.
        
        Returns:
            The finalized message dict or None if no streaming was active
        """
        if not self._streaming_state["active"]:
            return None
            
        reasoning_content = self._streaming_state.get("reasoning_content", "")
        
        # --- Build final assistant content ---------------------------------
        # We embed internal reasoning as a <details> block so the UI can render
        # a collapsible section **without** duplicating the content in the
        # visible answer.  This is safe because Markdown renders <details>
        # natively in modern terminals with our Expander / fallback widget.

        assistant_visible = self._streaming_state["content"]

        if reasoning_content:
            details_block = (
                "<details>\n"
                "<summary>🧠  Click to show / hide internal reasoning</summary>\n\n"
                + reasoning_content.strip("\n")
                + "\n\n</details>\n\n"
            )
            merged_content = details_block + assistant_visible
        else:
            merged_content = assistant_visible

        # Construct the assistant message for storage (collapsed reasoning)
        final_message = {
            "role": self._streaming_state["role"],
            "content": merged_content,
            "type": self._streaming_state["message_type"],  # keep original for storage
            "metadata": {
                **self._streaming_state["metadata"],
                "has_reasoning": bool(reasoning_content),
                "reasoning_length": self.api_client.count_tokens(reasoning_content) if reasoning_content and self.api_client else len(reasoning_content) // 4,
            }
        }
        
        # Content to add to the conversation is *only* the assistant visible text.
        # The TUI has already streamed reasoning tokens live; re-injecting would duplicate them.
        content_to_add = merged_content
        if reasoning_content and not self.model_config.reasoning_exclude:
            # Do NOT merge reasoning back into the assistant text; UI already rendered
            # it live during streaming and adding it again leads to duplication.
            pass
        
        if content_to_add.strip():
            # Add to conversation manager
            if self._streaming_state["role"] == "assistant":
                category = MessageCategory.DIALOG
            elif self._streaming_state["role"] == "system":
                category = MessageCategory.SYSTEM
            else:
                category = MessageCategory.DIALOG
                
            # Remove streaming flag from metadata for final version
            final_metadata = final_message["metadata"].copy()
            if "is_streaming" in final_metadata:
                del final_metadata["is_streaming"]
            
            # Add reasoning metadata if present
            if reasoning_content:
                final_metadata["has_reasoning"] = True
                final_metadata["reasoning_length"] = self.api_client.count_tokens(reasoning_content) if self.api_client else len(reasoning_content) // 4
                
            if hasattr(self, "conversation_manager") and self.conversation_manager:
                self.conversation_manager.conversation.add_message(
                    role=final_message["role"],
                    content=content_to_add,
                    category=category,
                    metadata=final_metadata
                )
                
                # Skip emitting a separate 'message' event – the UI has been
                # streaming content live. Emitting again causes a duplicated
                # assistant block.  Conversation persistence is already
                # handled above; UI just needs the final `stream_chunk` with
                # `is_final=True` which we emit later.

        # Flush any residual coalesced buffer before the final event so the UI
        # doesn't miss the tail end of the message.
        try:
            pending = self._streaming_state.get("emit_buffer", "")
            if pending:
                asyncio.create_task(self.emit_ui_event("stream_chunk", {
                    "stream_id": self._streaming_state.get("id"),
                    "chunk": pending,
                    "is_final": False,
                    "message_type": "assistant",
                    "role": self._streaming_state["role"],
                    "content_so_far": self._streaming_state["content"],
                    "reasoning_so_far": reasoning_content,
                    "metadata": final_message["metadata"],
                }))
        except Exception:
            pass

        # Emit final streaming event with is_final=True
        asyncio.create_task(self.emit_ui_event("stream_chunk", {
            "stream_id": self._streaming_state.get("id"),
            "chunk": "",
            "is_final": True,
            "message_type": "assistant",  # mark final chunk as assistant content
            "role": self._streaming_state["role"],
            "content": self._streaming_state["content"],
            "reasoning": reasoning_content,
            "metadata": final_message["metadata"],
        }))
        
        # Reset streaming state
        self._streaming_state = {
            "active": False,
            "content": "",
            "reasoning_content": "",
            "message_type": None,
            "role": None,
            "metadata": {},
            "started_at": None,
            "last_update": None,
            "empty_response_count": 0,
            "error": None,
            "emit_buffer": "",
            "last_emit_ts": 0.0,
        }
        
        return final_message

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
        
        except Exception as e:
            logger.error(f"Error in PenguinCore._handle_run_mode_event: {str(e)}", exc_info=True)

    def _update_config_file_with_model(self, model_id: str, model_specs: Dict[str, Any]) -> None:
        """Update config.yml with new model specifications."""
        from pathlib import Path
        import yaml
        
        config_path = Path(__file__).parent / "config.yml"
        
        try:
            # Load current config
            with open(config_path, 'r') as f:
                config_data = yaml.safe_load(f)
            
            # Update model settings
            config_data['model']['default'] = model_id
            
            # Update max_tokens using the context window when available
            if 'context_length' in model_specs:
                config_data['model']['max_tokens'] = model_specs['context_length']
            elif 'max_output_tokens' in model_specs:
                config_data['model']['max_tokens'] = model_specs['max_output_tokens']
            else:
                logger.error(f"No context_length/max_output_tokens available for model {model_id}")
                return
            
            # Store context window info for reference
            if 'context_length' in model_specs:
                config_data['model']['context_window'] = model_specs['context_length']
            
            # Remove max_output_tokens if it exists (we only need max_tokens)
            if 'max_output_tokens' in config_data['model']:
                del config_data['model']['max_output_tokens']
            
            # Write back to file
            with open(config_path, 'w') as f:
                yaml.safe_dump(config_data, f, default_flow_style=False, sort_keys=False)
                
            logger.info(f"Updated config.yml with model {model_id}, max_tokens (context window) {config_data['model']['max_tokens']}, context_window {model_specs.get('context_length', 'unknown')}")
            
        except Exception as e:
            logger.error(f"Failed to update config.yml: {e}")

    async def _fetch_model_specifications(self, model_id: str) -> Dict[str, Any]:
        """Fetch model specifications from OpenRouter API or use fallback data."""
        import httpx
        
        # Try to fetch from OpenRouter API
        try:
            async with httpx.AsyncClient() as client:
                response = await client.get("https://openrouter.ai/api/v1/models", timeout=5.0)
                response.raise_for_status()
                models = response.json().get("data", [])
                
                for model in models:
                    if model.get("id") == model_id:
                        return {
                            "context_length": model.get("context_length", 200000),
                            "max_output_tokens": model.get("max_output_tokens", model.get("context_length", 200000) // 4),  # Default to 1/4 of context if not specified
                            "name": model.get("name", model_id),
                            "provider": model_id.split('/')[0] if '/' in model_id else "unknown"
                        }
                        
        except Exception as e:
            logger.debug(f"Failed to fetch model specs from API: {e}")
        
        # Fallback specifications for common models
        fallback_specs = {
            "anthropic/claude-4-opus": {"context_length": 200000, "max_output_tokens": 64000, "name": "Claude 4 Opus"},
            "anthropic/claude-4-sonnet": {"context_length": 200000, "max_output_tokens": 64000, "name": "Claude 4 Sonnet"},
            "anthropic/claude-sonnet-4": {"context_length": 200000, "max_output_tokens": 64000, "name": "Claude Sonnet 4"},
            "anthropic/claude-opus-4": {"context_length": 200000, "max_output_tokens": 64000, "name": "Claude Opus 4"},
            "anthropic/claude-3-5-sonnet-20240620": {"context_length": 200000, "max_output_tokens": 64000, "name": "Claude 3.5 Sonnet"},
            "google/gemini-2.5-pro-preview": {"context_length": 1048576, "max_output_tokens": 65536, "name": "Gemini 2.5 Pro"},
            "google/gemini-2-5-pro-preview": {"context_length": 1048576, "max_output_tokens": 65536, "name": "Gemini 2.5 Pro"},
            "openai/o3-mini": {"context_length": 128000, "max_output_tokens": 16384, "name": "O3 Mini"},
            "openai/gpt-4o": {"context_length": 128000, "max_output_tokens": 16384, "name": "GPT-4o"},
            "deepseek/deepseek-chat": {"context_length": 163840, "max_output_tokens": 32768, "name": "DeepSeek V3"},
            "mistral/devstral": {"context_length": 32000, "max_output_tokens": 8192, "name": "Devstral"},
        }
        
        fallback_data = fallback_specs.get(model_id)
        if fallback_data:
            return fallback_data
        else:
            # No fallback available - this should trigger an error in load_model
            logger.warning(f"No specifications available for model {model_id}. Please add model configuration to config.yml manually.")
            return {}

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
