"""Startup helpers used by :mod:`penguin.core` construction."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, MutableMapping

from penguin.core_runtime.model_runtime import provider_credential_available

ActionExecutorFactory = Callable[..., Any]
ApiClientFactory = Callable[..., Any]
CheckpointConfigFactory = Callable[..., Any]
ConfigLoader = Callable[[], Any]
ConversationManagerFactory = Callable[..., Any]
EngineFactory = Callable[..., Any]
EngineSettingsFactory = Callable[..., Any]
RuntimeConfigFactory = Callable[[dict[str, Any]], Any]
ModelConfigFactory = Callable[..., Any]
ToolManagerFactory = Callable[..., Any]
SystemPromptBuilder = Callable[[str], str]
OutputFormatter = Callable[[str], Any]
EnvLoader = Callable[[], Any]
ProgressCallback = Callable[[int, int, str], Any]
TqdmFactory = Callable[..., Any]
Clock = Callable[[], float]

__all__ = [
    "ActionExecutorFactory",
    "ApiClientFactory",
    "CheckpointConfigFactory",
    "Clock",
    "ConfigLoader",
    "ConversationManagerFactory",
    "EngineFactory",
    "EngineSettingsFactory",
    "EnvLoader",
    "ModelConfigFactory",
    "OutputFormatter",
    "ProgressCallback",
    "RuntimeConfigFactory",
    "StartupProgress",
    "StartupTiming",
    "SystemPromptBuilder",
    "ToolManagerFactory",
    "TqdmFactory",
    "build_api_client",
    "build_default_checkpoint_config",
    "build_initial_model_config",
    "build_tool_manager",
    "configure_startup_logging",
    "create_core_instance",
    "ensure_tokenizers_parallelism",
    "finalize_core_startup_state",
    "initialize_conversation_action_state",
    "initialize_core_base_state",
    "initialize_core_instance_state",
    "initialize_engine_state",
    "initialize_project_diagnostics_state",
    "initialize_prompt_and_output_state",
    "initialize_runtime_config",
    "initialize_tui_bridge_state",
    "load_penguin_cli",
    "load_startup_config",
    "log_startup_failure",
    "log_startup_summary",
    "resolve_fast_startup",
]

_BASE_STARTUP_STEPS = [
    "Loading environment",
    "Setting up logging",
    "Loading configuration",
    "Creating model config",
    "Initializing API client",
    "Creating tool manager",
    "Creating core instance",
]

_CONVERSATION_MAX_SESSIONS_IN_MEMORY = 20
_CONVERSATION_AUTO_SAVE_INTERVAL_SECONDS = 60
_CHECKPOINT_FREQUENCY_MESSAGES = 1
_CHECKPOINT_MAX_AUTO_CHECKPOINTS = 1000


@dataclass
class StartupProgress:
    """Track startup progress callbacks and optional console progress bar."""

    steps: list[str]
    progress_callback: ProgressCallback | None = None
    pbar: Any = None
    current_step_index: int = 0

    @classmethod
    def create(
        cls,
        *,
        enable_cli: bool,
        show_progress: bool,
        progress_callback: ProgressCallback | None,
        tqdm_factory: TqdmFactory,
    ) -> StartupProgress:
        """Build startup progress state for PenguinCore.create."""

        steps = list(_BASE_STARTUP_STEPS)
        if enable_cli:
            steps.append("Initializing CLI")

        pbar = None
        if show_progress and progress_callback is None:
            pbar = tqdm_factory(steps, desc="Initializing Penguin", unit="step")
        return cls(
            steps=steps,
            progress_callback=progress_callback,
            pbar=pbar,
        )

    @property
    def total_steps(self) -> int:
        return len(self.steps)

    def start_step(self, label: str) -> None:
        """Mark a step as active for both tqdm and callback consumers."""

        if self.pbar:
            self.pbar.set_description(label)
        if self.progress_callback:
            self.current_step_index += 1
            self.progress_callback(
                self.current_step_index,
                self.total_steps,
                label,
            )

    def complete_step(self) -> None:
        """Advance the visual progress bar when present."""

        if self.pbar:
            self.pbar.update(1)

    def finish(self) -> None:
        """Close progress and send a final callback if not every step emitted."""

        self.close()
        if self.progress_callback and self.current_step_index < self.total_steps:
            self.progress_callback(
                self.total_steps,
                self.total_steps,
                "Initialization complete",
            )

    def close(self) -> None:
        """Close the visual progress bar if one was created."""

        if self.pbar:
            self.pbar.close()


@dataclass
class StartupTiming:
    """Track PenguinCore.create timing with an injectable clock."""

    clock: Clock = time.time
    timings: dict[str, float] = field(default_factory=dict)
    step_started_at: float = field(init=False)
    overall_started_at: float = field(init=False)

    def __post_init__(self) -> None:
        started_at = self.clock()
        self.step_started_at = started_at
        self.overall_started_at = started_at

    def mark(self) -> float:
        """Return the current clock value for ad hoc duration logging."""

        return self.clock()

    def elapsed_since(self, started_at: float) -> float:
        """Return elapsed seconds since a previous mark."""

        return self.clock() - started_at

    def elapsed_total(self) -> float:
        """Return elapsed seconds since startup timing began."""

        return self.clock() - self.overall_started_at

    def record_step(self, step_name: str, *, logger: Any) -> float:
        """Record and log elapsed time for one startup phase."""

        step_ended_at = self.clock()
        elapsed = step_ended_at - self.step_started_at
        self.timings[step_name] = elapsed
        logger.info("PROFILING: %s took %.4f seconds", step_name, elapsed)
        self.step_started_at = step_ended_at
        return elapsed


def log_startup_summary(
    timing: StartupTiming,
    *,
    fast_startup: bool,
    tool_manager: Any,
    logger: Any,
) -> float:
    """Log the final startup timing summary and return total elapsed seconds."""

    total_time = timing.elapsed_total()
    logger.info(
        "STARTUP COMPLETE: Total initialization time: %.4f seconds",
        total_time,
    )
    logger.info("STARTUP TIMING SUMMARY:")
    for step, duration in timing.timings.items():
        percentage = (duration / total_time) * 100 if total_time > 0 else 0.0
        logger.info("  - %s: %.4fs (%.1f%%)", step, duration, percentage)

    if fast_startup:
        logger.info("FAST STARTUP enabled - memory indexing deferred to first use")

    tool_stats = tool_manager.get_startup_stats()
    logger.info("ToolManager startup stats: %s", tool_stats)
    return total_time


def log_startup_failure(
    timing: StartupTiming,
    error: BaseException,
    *,
    logger: Any,
) -> str:
    """Log startup failure timing and return the public RuntimeError message."""

    error_time = timing.elapsed_total()
    logger.error("STARTUP FAILED after %.4fs: %s", error_time, error)
    error_msg = f"Failed to initialize PenguinCore: {error!s}"
    logger.error(error_msg)
    return error_msg


def ensure_tokenizers_parallelism(
    environ: MutableMapping[str, str] | None = None,
) -> None:
    """Set the tokenizer parallelism default before model libraries initialize."""

    env = environ if environ is not None else os.environ
    env.setdefault("TOKENIZERS_PARALLELISM", "false")


def configure_startup_logging(
    *,
    basic_config: Callable[..., Any] = logging.basicConfig,
    get_logger: Callable[[str], Any] = logging.getLogger,
) -> None:
    """Apply Penguin's quiet startup logging defaults."""

    basic_config(level=logging.WARNING)
    for logger_name in ("httpx", "sentence_transformers", "LiteLLM", "tools", "llm"):
        get_logger(logger_name).setLevel(logging.WARNING)
    get_logger("chat").setLevel(logging.DEBUG)


def load_penguin_cli() -> Any:
    """Load the CLI class lazily so headless startup avoids chat imports."""

    from penguin.chat.cli import PenguinCLI

    return PenguinCLI


async def create_core_instance(
    core_factory: Callable[..., Any],
    *,
    config: Any | None,
    model: str | None,
    provider: str | None,
    workspace_path: str | None,
    enable_cli: bool,
    show_progress: bool,
    progress_callback: ProgressCallback | None,
    fast_startup: bool,
    default_model: str,
    default_provider: str,
    system_prompt: str,
    config_loader: ConfigLoader,
    model_config_factory: ModelConfigFactory,
    api_client_factory: ApiClientFactory,
    tool_manager_factory: ToolManagerFactory,
    ensure_env_loaded: EnvLoader,
    log_error: Callable[..., Any],
    tqdm_factory: TqdmFactory,
    profile_phase: Callable[[str], Any],
    logger: Any,
    cli_factory_loader: Callable[[], Any] | None = None,
) -> Any:
    """Create a PenguinCore instance and optional CLI with startup telemetry."""

    ensure_tokenizers_parallelism()
    startup_timing = StartupTiming()
    progress = None

    try:
        with profile_phase("PenguinCore.create_total"):
            progress = StartupProgress.create(
                enable_cli=enable_cli,
                show_progress=show_progress,
                progress_callback=progress_callback,
                tqdm_factory=tqdm_factory,
            )

            with profile_phase("Load environment"):
                logger.info("STARTUP: Loading environment variables")
                progress.start_step("Loading environment")
                progress.complete_step()
                startup_timing.record_step("Load environment", logger=logger)

            with profile_phase("Setup logging"):
                logger.info("STARTUP: Setting up logging configuration")
                progress.start_step("Setting up logging")
                configure_startup_logging()
                progress.complete_step()
                startup_timing.record_step("Setup logging", logger=logger)

            with profile_phase("Load configuration"):
                logger.info("STARTUP: Loading and parsing configuration")
                progress.start_step("Loading configuration")
                start_config_time = startup_timing.mark()
                config = load_startup_config(
                    config,
                    workspace_path=workspace_path,
                    config_loader=config_loader,
                )
                fast_startup = resolve_fast_startup(config, fast_startup)
                logger.info(
                    "STARTUP: Config loaded in %.4fs",
                    startup_timing.elapsed_since(start_config_time),
                )
                progress.complete_step()
                startup_timing.record_step("Load configuration", logger=logger)

            with profile_phase("Create model config"):
                logger.info("STARTUP: Creating model configuration")
                progress.start_step("Creating model config")
                model_config = build_initial_model_config(
                    config,
                    model=model,
                    provider=provider,
                    default_model=default_model,
                    default_provider=default_provider,
                    model_config_factory=model_config_factory,
                )
                logger.info(
                    "STARTUP: Using model=%s, provider=%s, client=%s",
                    model_config.model,
                    model_config.provider,
                    model_config.client_preference,
                )
                progress.complete_step()
                startup_timing.record_step("Create model config", logger=logger)

            with profile_phase("Initialize API client"):
                logger.info("STARTUP: Initializing API client")
                progress.start_step("Initializing API client")
                api_client_start = startup_timing.mark()
                api_client = build_api_client(
                    model_config,
                    system_prompt=system_prompt,
                    api_client_factory=api_client_factory,
                    ensure_env_loaded=ensure_env_loaded,
                )
                logger.info(
                    "STARTUP: API client initialized in %.4fs",
                    startup_timing.elapsed_since(api_client_start),
                )
                progress.complete_step()
                startup_timing.record_step("Initialize API client", logger=logger)

            with profile_phase("Create tool manager"):
                logger.info(
                    "STARTUP: Creating tool manager (fast_startup=%s)",
                    fast_startup,
                )
                progress.start_step("Creating tool manager")
                tool_manager_start = startup_timing.mark()
                print("DEBUG: Creating ToolManager in PenguinCore...")
                print(f"DEBUG: Passing config of type {type(config)} to ToolManager.")
                print(
                    f"DEBUG: Passing log_error of type {type(log_error)} to "
                    "ToolManager."
                )
                print(f"DEBUG: Fast startup mode: {fast_startup}")
                tool_manager = build_tool_manager(
                    config,
                    log_error=log_error,
                    fast_startup=fast_startup,
                    tool_manager_factory=tool_manager_factory,
                )
                logger.info(
                    "STARTUP: Tool manager created in %.4fs with %s tools",
                    startup_timing.elapsed_since(tool_manager_start),
                    (
                        len(tool_manager.tools)
                        if hasattr(tool_manager, "tools")
                        else "unknown"
                    ),
                )
                progress.complete_step()
                startup_timing.record_step("Create tool manager", logger=logger)

            with profile_phase("Create core instance"):
                logger.info("STARTUP: Creating core instance")
                progress.start_step("Creating core instance")
                core_start = startup_timing.mark()
                instance = core_factory(
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

            cli = None
            if enable_cli:
                with profile_phase("Initialize CLI"):
                    logger.info("STARTUP: Initializing CLI")
                    progress.start_step("Initializing CLI")
                    cli_start = startup_timing.mark()
                    cli_factory = (cli_factory_loader or load_penguin_cli)()
                    cli = cli_factory(instance)
                    logger.info(
                        "STARTUP: CLI initialized in %.4fs",
                        startup_timing.elapsed_since(cli_start),
                    )
                    progress.complete_step()
                    startup_timing.record_step("Initialize CLI", logger=logger)

            progress.finish()
            log_startup_summary(
                startup_timing,
                fast_startup=fast_startup,
                tool_manager=tool_manager,
                logger=logger,
            )

            return instance if not enable_cli else (instance, cli)

    except Exception as error:
        if progress is not None:
            progress.close()
        error_msg = log_startup_failure(startup_timing, error, logger=logger)
        raise RuntimeError(error_msg) from error


def load_startup_config(
    config: Any,
    *,
    workspace_path: str | None,
    config_loader: ConfigLoader,
    environ: MutableMapping[str, str] | None = None,
) -> Any:
    """Load Config with temporary workspace env override and restore env state."""

    env = environ if environ is not None else os.environ
    previous_workspace = env.get("PENGUIN_WORKSPACE")
    resolved_workspace = (
        str(Path(workspace_path).expanduser().resolve()) if workspace_path else None
    )

    if resolved_workspace:
        env["PENGUIN_WORKSPACE"] = resolved_workspace
    try:
        loaded_config = config or config_loader()
    finally:
        if resolved_workspace:
            if previous_workspace is None:
                env.pop("PENGUIN_WORKSPACE", None)
            else:
                env["PENGUIN_WORKSPACE"] = previous_workspace

    if resolved_workspace:
        loaded_config.workspace_path = Path(resolved_workspace)
    return loaded_config


def resolve_fast_startup(config: Any, requested_fast_startup: bool) -> bool:
    """Preserve current startup override behavior for Config.fast_startup."""

    if requested_fast_startup is False and hasattr(config, "fast_startup"):
        return bool(config.fast_startup)
    return requested_fast_startup


def build_api_client(
    model_config: Any,
    *,
    system_prompt: str,
    api_client_factory: ApiClientFactory,
    ensure_env_loaded: EnvLoader,
) -> Any:
    """Build the startup API client after env files are available."""

    ensure_env_loaded()
    provider = str(getattr(model_config, "provider", "") or "").strip().lower()
    model = str(getattr(model_config, "model", "") or "").strip()
    if not provider or not model:
        return None

    if not provider_credential_available(model_config):
        return None

    api_client = api_client_factory(model_config=model_config)
    api_client.set_system_prompt(system_prompt)
    return api_client


def build_initial_model_config(
    config: Any,
    *,
    model: str | None,
    provider: str | None,
    default_model: str,
    default_provider: str,
    model_config_factory: ModelConfigFactory,
) -> Any:
    """Build the startup model config from live config plus explicit overrides."""

    source_model_config = getattr(config, "model_config", None)
    return model_config_factory(
        model=model or getattr(source_model_config, "model", default_model),
        provider=provider or getattr(source_model_config, "provider", default_provider),
        api_base=_initial_api_base(config, source_model_config),
        use_assistants_api=bool(
            getattr(source_model_config, "use_assistants_api", False)
        ),
        client_preference=getattr(
            source_model_config,
            "client_preference",
            "openrouter",
        ),
        streaming_enabled=bool(getattr(source_model_config, "streaming_enabled", True)),
        max_output_tokens=_initial_max_output_tokens(source_model_config),
        max_context_window_tokens=getattr(
            source_model_config,
            "max_context_window_tokens",
            None,
        ),
        service_tier=getattr(source_model_config, "service_tier", None),
    )


def initialize_core_base_state(
    owner: Any,
    *,
    config: Any | None,
    api_client: Any | None,
    tool_manager: Any | None,
    model_config: Any | None,
    config_factory: ConfigLoader,
) -> None:
    """Attach constructor inputs and initialize primitive runtime state."""

    owner.config = config or config_factory()
    owner.api_client = api_client
    owner.tool_manager = tool_manager
    owner.model_config = model_config
    owner._interrupted = False
    owner.progress_callbacks = []
    owner.token_callbacks = []
    owner._active_contexts = set()


def initialize_core_instance_state(
    owner: Any,
    *,
    config: Any | None,
    api_client: Any | None,
    tool_manager: Any | None,
    model_config: Any | None,
    runtime_config: Any | None,
    config_factory: ConfigLoader,
    runtime_config_factory: RuntimeConfigFactory,
    event_bus_factory: Callable[[], Any],
    event_type_enum: Any,
    stream_lock_factory: Callable[[], Any],
    stream_manager_factory: Callable[[], Any],
    part_event_adapter_factory: Callable[..., Any],
    telemetry_ensurer: Callable[[Any], Any],
    raw_config: Any,
    get_system_prompt: SystemPromptBuilder,
    fallback_system_prompt: str,
    default_workspace_path: Any,
    project_manager_factory: Callable[..., Any],
    diagnostics_disabler: Callable[[], Any],
    checkpoint_config_factory: CheckpointConfigFactory,
    conversation_manager_factory: ConversationManagerFactory,
    action_executor_factory: ActionExecutorFactory,
    default_max_messages_per_session: int,
    engine_factory: EngineFactory,
    engine_settings_factory: EngineSettingsFactory,
    logger: Any,
) -> None:
    """Initialize all constructor-owned runtime state for ``PenguinCore``."""

    initialize_core_base_state(
        owner,
        config=config,
        api_client=api_client,
        tool_manager=tool_manager,
        model_config=model_config,
        config_factory=config_factory,
    )
    initialize_runtime_config(
        owner,
        config=config,
        runtime_config=runtime_config,
        tool_manager=tool_manager,
        runtime_config_factory=runtime_config_factory,
    )
    initialize_tui_bridge_state(
        owner,
        event_bus_factory=event_bus_factory,
        event_type_enum=event_type_enum,
        stream_lock_factory=stream_lock_factory,
        stream_manager_factory=stream_manager_factory,
        part_event_adapter_factory=part_event_adapter_factory,
    )
    telemetry_ensurer(owner)
    initialize_prompt_and_output_state(
        owner,
        raw_config,
        get_system_prompt=get_system_prompt,
        fallback_system_prompt=fallback_system_prompt,
    )
    workspace_path = initialize_project_diagnostics_state(
        owner,
        default_workspace_path=default_workspace_path,
        project_manager_factory=project_manager_factory,
        diagnostics_disabler=diagnostics_disabler,
    )
    initialize_conversation_action_state(
        owner,
        workspace_path=workspace_path,
        checkpoint_config_factory=checkpoint_config_factory,
        conversation_manager_factory=conversation_manager_factory,
        action_executor_factory=action_executor_factory,
        default_max_messages_per_session=default_max_messages_per_session,
    )
    initialize_engine_state(
        owner,
        engine_factory=engine_factory,
        engine_settings_factory=engine_settings_factory,
        logger=logger,
    )
    finalize_core_startup_state(
        owner,
        workspace_path=workspace_path,
        logger=logger,
    )


def initialize_runtime_config(
    owner: Any,
    *,
    config: Any,
    runtime_config: Any | None,
    tool_manager: Any | None,
    runtime_config_factory: RuntimeConfigFactory,
) -> None:
    """Attach runtime config and register the tool manager as an observer."""

    if runtime_config is None:
        config_dict = config.to_dict() if hasattr(config, "to_dict") else {}
        owner.runtime_config = runtime_config_factory(config_dict)
    else:
        owner.runtime_config = runtime_config

    observer = getattr(tool_manager, "on_runtime_config_change", None)
    if tool_manager is not None and callable(observer):
        owner.runtime_config.register_observer(observer)


def initialize_tui_bridge_state(
    owner: Any,
    *,
    event_bus_factory: Callable[[], Any],
    event_type_enum: Any,
    stream_lock_factory: Callable[[], Any],
    stream_manager_factory: Callable[[], Any],
    part_event_adapter_factory: Callable[..., Any],
) -> None:
    """Initialize event, streaming, OpenCode adapter, and run-mode bridge state."""

    owner.event_bus = event_bus_factory()
    owner.event_types = {event_type.value for event_type in event_type_enum}

    owner.current_stream = None
    owner.stream_lock = stream_lock_factory()
    owner._stream_manager = stream_manager_factory()

    owner._tui_adapter = part_event_adapter_factory(
        owner.event_bus,
        persist_callback=owner._persist_opencode_event,
        emit_session_status_events=False,
    )
    owner._tui_adapters = {}
    owner._opencode_abort_sessions = set()
    owner._opencode_active_requests = {}
    owner._opencode_process_tasks = {}

    owner._subscribe_to_stream_events()

    owner._runmode_stream_callback = None
    owner._runmode_active = False
    owner.run_mode = None


def build_default_checkpoint_config(
    *,
    checkpoint_config_factory: CheckpointConfigFactory,
) -> Any:
    """Build the default checkpoint config used by PenguinCore construction."""

    return checkpoint_config_factory(
        enabled=True,
        frequency=_CHECKPOINT_FREQUENCY_MESSAGES,
        planes={"conversation": True, "tasks": False, "code": False},
        retention={"keep_all_hours": 24, "keep_every_nth": 10, "max_age_days": 30},
        max_auto_checkpoints=_CHECKPOINT_MAX_AUTO_CHECKPOINTS,
    )


def initialize_project_diagnostics_state(
    owner: Any,
    *,
    default_workspace_path: Any,
    project_manager_factory: Callable[..., Any],
    diagnostics_disabler: Callable[[], Any],
) -> Path:
    """Initialize project manager and diagnostics from loaded core config."""

    workspace_path = Path(
        getattr(owner.config, "workspace_path", default_workspace_path)
    )
    owner.project_manager = project_manager_factory(workspace_path=workspace_path)

    diagnostics_config = getattr(owner.config, "diagnostics", None)
    if not getattr(diagnostics_config, "enabled", True):
        diagnostics_disabler()

    return workspace_path


def initialize_conversation_action_state(
    owner: Any,
    *,
    workspace_path: Path,
    checkpoint_config_factory: CheckpointConfigFactory,
    conversation_manager_factory: ConversationManagerFactory,
    action_executor_factory: ActionExecutorFactory,
    default_max_messages_per_session: int,
) -> None:
    """Initialize conversation manager, tool back-reference, and action executor."""

    tool_manager = getattr(owner, "tool_manager", None)
    checkpoint_config = build_default_checkpoint_config(
        checkpoint_config_factory=checkpoint_config_factory,
    )
    owner.conversation_manager = conversation_manager_factory(
        model_config=owner.model_config,
        api_client=owner.api_client,
        workspace_path=workspace_path,
        system_prompt=owner.system_prompt,
        max_messages_per_session=default_max_messages_per_session,
        max_sessions_in_memory=_CONVERSATION_MAX_SESSIONS_IN_MEMORY,
        auto_save_interval=_CONVERSATION_AUTO_SAVE_INTERVAL_SECONDS,
        checkpoint_config=checkpoint_config,
        skills_config=_safe_config_dict(owner.config),
        project_root=getattr(tool_manager, "project_root", None),
    )
    owner.conversation_manager.core = owner

    set_core = getattr(tool_manager, "set_core", None)
    if tool_manager is not None and callable(set_core):
        set_core(owner)

    owner.action_executor = action_executor_factory(
        tool_manager,
        owner.project_manager,
        owner.conversation_manager,
        ui_event_callback=owner.emit_ui_event,
    )
    owner.current_runmode_status_summary = "RunMode idle."


def initialize_engine_state(
    owner: Any,
    *,
    engine_factory: EngineFactory,
    engine_settings_factory: EngineSettingsFactory,
    logger: Any,
) -> None:
    """Initialize Engine wiring without injecting a hidden stop condition."""

    try:
        streaming_pref = _resolve_engine_streaming_default(owner.model_config)
        engine_settings = engine_settings_factory(streaming_default=streaming_pref)
        owner.engine = engine_factory(
            engine_settings,
            owner.conversation_manager,
            owner.api_client,
            owner.tool_manager,
            owner.action_executor,
            stop_conditions=[],
        )
        try:
            owner.engine.model_config = owner.model_config
            owner.engine.coordinator = owner.get_coordinator()
            owner.engine.telemetry = getattr(owner, "telemetry", None)
            owner.engine.setup_message_bus(ui_event_callback=owner.emit_ui_event)
        except Exception as coord_err:  # pragma: no cover
            logger.debug("Coordinator unavailable during engine init: %s", coord_err)
    except Exception as error:
        logger.warning(
            "Failed to initialize Engine layer "
            "(fallback to legacy core processing): %s",
            error,
            exc_info=True,
        )
        owner.engine = None


def finalize_core_startup_state(
    owner: Any,
    *,
    workspace_path: Path,
    logger: Any,
) -> None:
    """Set final construction flags and validate the active workspace."""

    owner.initialized = True
    logger.info("PenguinCore initialized successfully")
    owner.validate_path(workspace_path)
    owner.accumulated_tokens = {"prompt": 0, "completion": 0, "total": 0}
    owner._litellm_configured = False
    owner._last_model_load_error = None


def build_tool_manager(
    config: Any,
    *,
    log_error: Callable[..., Any],
    fast_startup: bool,
    tool_manager_factory: ToolManagerFactory,
) -> Any:
    """Build ToolManager with a deterministic dict payload from live Config."""

    return tool_manager_factory(
        _safe_config_dict(config),
        log_error,
        fast_startup=fast_startup,
    )


def initialize_prompt_and_output_state(
    owner: Any,
    raw_config: Any,
    *,
    get_system_prompt: SystemPromptBuilder,
    fallback_system_prompt: str,
    set_output_formatting: OutputFormatter | None = None,
) -> None:
    """Initialize output display flags, prompt mode, style, and prompt text."""

    output_config = getattr(owner.config, "output", None)
    owner.show_tool_results = _resolve_show_tool_results(output_config, raw_config)
    owner.prompt_mode = _resolve_prompt_mode(raw_config)
    owner.output_style = _apply_output_style(
        output_config,
        raw_config,
        set_output_formatting=set_output_formatting,
    )
    try:
        owner.system_prompt = get_system_prompt(owner.prompt_mode)
    except Exception:
        owner.system_prompt = fallback_system_prompt


def _resolve_show_tool_results(output_config: Any, raw_config: Any) -> bool:
    if output_config and hasattr(output_config, "show_tool_results"):
        return bool(output_config.show_tool_results)

    try:
        raw_output_config = (
            raw_config.get("output", {}) if isinstance(raw_config, dict) else {}
        )
        show_tool_value = raw_output_config.get("show_tool_results", True)
        if isinstance(show_tool_value, str):
            return show_tool_value.strip().lower() in {"1", "true", "yes", "on"}
        return bool(show_tool_value)
    except Exception:
        return True


def _safe_config_dict(config: Any) -> dict[str, Any]:
    try:
        return config.to_dict() if hasattr(config, "to_dict") else {}
    except Exception:
        return {}


def _resolve_prompt_mode(raw_config: Any) -> str:
    try:
        mode = str(raw_config.get("prompt", {}).get("mode", "direct")).strip().lower()
    except Exception:
        mode = "direct"
    return mode or "direct"


def _apply_output_style(
    output_config: Any,
    raw_config: Any,
    *,
    set_output_formatting: OutputFormatter | None,
) -> str:
    try:
        formatter = set_output_formatting or _load_output_formatter()
        if output_config and getattr(output_config, "prompt_style", None):
            prompt_style = str(output_config.prompt_style).strip().lower()
        else:
            prompt_style = (
                str(raw_config.get("output", {}).get("prompt_style", "steps_final"))
                .strip()
                .lower()
            )
        output_style = prompt_style or "steps_final"
        formatter(output_style)
        return output_style
    except Exception:
        return "steps_final"


def _resolve_engine_streaming_default(model_config: Any) -> bool:
    try:
        return bool(model_config.streaming_enabled)
    except Exception:
        return True


def _load_output_formatter() -> OutputFormatter:
    from penguin.prompt.builder import set_output_formatting

    return set_output_formatting


def _initial_api_base(config: Any, source_model_config: Any) -> str | None:
    api_base = getattr(source_model_config, "api_base", None)
    if api_base:
        return api_base

    api_config = getattr(config, "api", None)
    return getattr(api_config, "base_url", None)


def _initial_max_output_tokens(source_model_config: Any) -> Any:
    try:
        raw_values = vars(source_model_config)
    except TypeError:
        raw_values = {}

    if isinstance(raw_values, dict):
        max_output_tokens = raw_values.get("max_output_tokens")
        if max_output_tokens is not None:
            return max_output_tokens
        if "max_tokens" in raw_values:
            return raw_values.get("max_tokens")

    max_output_tokens = getattr(source_model_config, "max_output_tokens", None)
    if max_output_tokens is not None:
        return max_output_tokens
    return None
