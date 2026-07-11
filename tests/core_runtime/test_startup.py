"""Tests for core startup helper contracts."""

from __future__ import annotations

import logging
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import startup


class _RuntimeConfig:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.observers: list[Any] = []

    def register_observer(self, observer: Any) -> None:
        self.observers.append(observer)


class _FakeProgressBar:
    def __init__(self) -> None:
        self.descriptions: list[str] = []
        self.updates: list[int] = []
        self.closed = False

    def set_description(self, label: str) -> None:
        self.descriptions.append(label)

    def update(self, value: int) -> None:
        self.updates.append(value)

    def close(self) -> None:
        self.closed = True


class _FakeLogger:
    def __init__(self) -> None:
        self.debug_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.info_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.warning_calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.error_calls: list[tuple[str, tuple[Any, ...]]] = []

    def debug(self, message: str, *args: Any) -> None:
        self.debug_calls.append((message, args))

    def info(self, message: str, *args: Any) -> None:
        self.info_calls.append((message, args))

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.warning_calls.append((message, args, kwargs))

    def error(self, message: str, *args: Any) -> None:
        self.error_calls.append((message, args))


class _SequenceClock:
    def __init__(self, values: list[float]) -> None:
        self.values = values
        self.index = 0

    def __call__(self) -> float:
        value = self.values[self.index]
        self.index += 1
        return value


class _ProfilePhase:
    def __init__(self, labels: list[str], label: str) -> None:
        self.labels = labels
        self.label = label

    def __enter__(self) -> None:
        self.labels.append(self.label)

    def __exit__(self, *_args: Any) -> bool:
        return False


def _profile_factory(labels: list[str]):
    return lambda label: _ProfilePhase(labels, label)


def test_startup_progress_uses_tqdm_without_external_callback() -> None:
    pbar = _FakeProgressBar()
    factory_calls: list[dict[str, Any]] = []

    def _tqdm_factory(steps: list[str], **kwargs: Any) -> _FakeProgressBar:
        factory_calls.append({"steps": steps, **kwargs})
        return pbar

    progress = startup.StartupProgress.create(
        enable_cli=True,
        show_progress=True,
        progress_callback=None,
        tqdm_factory=_tqdm_factory,
    )

    progress.start_step("Loading environment")
    progress.complete_step()
    progress.finish()

    assert progress.total_steps == 8
    assert factory_calls == [
        {
            "steps": [
                "Loading environment",
                "Setting up logging",
                "Loading configuration",
                "Creating model config",
                "Initializing API client",
                "Creating tool manager",
                "Creating core instance",
                "Initializing CLI",
            ],
            "desc": "Initializing Penguin",
            "unit": "step",
        }
    ]
    assert pbar.descriptions == ["Loading environment"]
    assert pbar.updates == [1]
    assert pbar.closed is True


def test_startup_progress_callback_gets_step_counts_and_finish_guard() -> None:
    calls: list[tuple[int, int, str]] = []

    progress = startup.StartupProgress.create(
        enable_cli=False,
        show_progress=True,
        progress_callback=lambda current, total, label: calls.append(
            (current, total, label)
        ),
        tqdm_factory=lambda *_args, **_kwargs: _FakeProgressBar(),
    )

    progress.start_step("Loading environment")
    progress.start_step("Setting up logging")
    progress.finish()

    assert progress.pbar is None
    assert calls == [
        (1, 7, "Loading environment"),
        (2, 7, "Setting up logging"),
        (7, 7, "Initialization complete"),
    ]


def test_startup_timing_records_steps_and_summary_with_deterministic_clock() -> None:
    clock = _SequenceClock([100.0, 101.5, 102.0, 104.0])
    logger = _FakeLogger()
    timing = startup.StartupTiming(clock=clock)

    elapsed = timing.record_step("Load configuration", logger=logger)
    mark = timing.mark()

    assert elapsed == 1.5
    assert mark == 102.0
    assert timing.timings == {"Load configuration": 1.5}
    assert logger.info_calls == [
        ("PROFILING: %s took %.4f seconds", ("Load configuration", 1.5))
    ]

    startup.log_startup_summary(
        timing,
        fast_startup=True,
        tool_manager=SimpleNamespace(get_startup_stats=lambda: {"tools": 3}),
        logger=logger,
    )

    assert logger.info_calls[-5:] == [
        (
            "STARTUP COMPLETE: Total initialization time: %.4f seconds",
            (4.0,),
        ),
        ("STARTUP TIMING SUMMARY:", ()),
        ("  - %s: %.4fs (%.1f%%)", ("Load configuration", 1.5, 37.5)),
        ("FAST STARTUP enabled - memory indexing deferred to first use", ()),
        ("ToolManager startup stats: %s", ({"tools": 3},)),
    ]


def test_startup_failure_logging_returns_public_error_message() -> None:
    clock = _SequenceClock([10.0, 12.25])
    logger = _FakeLogger()
    timing = startup.StartupTiming(clock=clock)
    error = RuntimeError("boom")

    message = startup.log_startup_failure(
        timing,
        error,
        logger=logger,
    )

    assert message == "Failed to initialize PenguinCore: boom"
    assert logger.error_calls == [
        ("STARTUP FAILED after %.4fs: %s", (2.25, error)),
        ("Failed to initialize PenguinCore: boom", ()),
    ]


def test_ensure_tokenizers_parallelism_sets_default_without_overwriting() -> None:
    env: dict[str, str] = {}

    startup.ensure_tokenizers_parallelism(env)
    startup.ensure_tokenizers_parallelism(env)

    assert env == {"TOKENIZERS_PARALLELISM": "false"}

    env["TOKENIZERS_PARALLELISM"] = "true"
    startup.ensure_tokenizers_parallelism(env)

    assert env["TOKENIZERS_PARALLELISM"] == "true"


def test_configure_startup_logging_sets_expected_logger_levels() -> None:
    basic_calls: list[dict[str, Any]] = []
    levels: dict[str, Any] = {}

    class _Logger:
        def __init__(self, name: str) -> None:
            self.name = name

        def setLevel(self, level: Any) -> None:
            levels[self.name] = level

    startup.configure_startup_logging(
        basic_config=lambda **kwargs: basic_calls.append(kwargs),
        get_logger=lambda name: _Logger(name),
    )

    assert basic_calls == [{"level": logging.WARNING}]
    assert levels == {
        "httpx": logging.WARNING,
        "sentence_transformers": logging.WARNING,
        "LiteLLM": logging.WARNING,
        "tools": logging.WARNING,
        "llm": logging.WARNING,
        "chat": logging.DEBUG,
    }


@pytest.mark.asyncio
async def test_create_core_instance_builds_core_with_startup_dependencies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "configure_startup_logging", lambda: None)
    logger = _FakeLogger()
    profile_labels: list[str] = []
    progress_calls: list[tuple[int, int, str]] = []
    env_calls: list[str] = []
    log_error = object()
    config = SimpleNamespace(
        model_config=SimpleNamespace(
            model="configured-model",
            provider="configured-provider",
            client_preference="openai",
        ),
        api=SimpleNamespace(base_url="https://api.example.test/v1"),
        fast_startup=True,
        to_dict=lambda: {"config": True},
    )
    created: dict[str, Any] = {}

    class _ModelConfig:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs
            self.model = kwargs["model"]
            self.provider = kwargs["provider"]
            self.client_preference = kwargs["client_preference"]

    class _ApiClient:
        def __init__(self, *, model_config: Any) -> None:
            self.model_config = model_config
            self.system_prompt = ""

        def set_system_prompt(self, prompt: str) -> None:
            self.system_prompt = prompt

    class _ToolManager:
        def __init__(
            self,
            payload: dict[str, Any],
            error_logger: Any,
            *,
            fast_startup: bool,
        ) -> None:
            self.payload = payload
            self.error_logger = error_logger
            self.fast_startup = fast_startup
            self.tools = {"read": object()}

        def get_startup_stats(self) -> dict[str, int]:
            return {"tools": len(self.tools)}

    class _Core:
        def __init__(self, **kwargs: Any) -> None:
            created.update(kwargs)
            self.kwargs = kwargs

    result = await startup.create_core_instance(
        _Core,
        config=config,
        model="override-model",
        provider="override-provider",
        workspace_path=None,
        enable_cli=False,
        show_progress=True,
        progress_callback=lambda current, total, label: progress_calls.append(
            (current, total, label)
        ),
        fast_startup=True,
        default_model="default-model",
        default_provider="default-provider",
        system_prompt="system prompt",
        config_loader=lambda: SimpleNamespace(name="unused"),
        model_config_factory=_ModelConfig,
        api_client_factory=_ApiClient,
        tool_manager_factory=_ToolManager,
        ensure_env_loaded=lambda: env_calls.append("loaded"),
        log_error=log_error,
        tqdm_factory=lambda *_args, **_kwargs: _FakeProgressBar(),
        profile_phase=_profile_factory(profile_labels),
        logger=logger,
    )

    assert isinstance(result, _Core)
    assert created["config"] is config
    assert created["model_config"].model == "override-model"
    assert created["model_config"].provider == "override-provider"
    assert created["api_client"].system_prompt == "system prompt"
    assert created["tool_manager"].payload == {"config": True}
    assert created["tool_manager"].error_logger is log_error
    assert created["tool_manager"].fast_startup is True
    assert env_calls == ["loaded"]
    assert progress_calls == [
        (1, 7, "Loading environment"),
        (2, 7, "Setting up logging"),
        (3, 7, "Loading configuration"),
        (4, 7, "Creating model config"),
        (5, 7, "Initializing API client"),
        (6, 7, "Creating tool manager"),
        (7, 7, "Creating core instance"),
    ]
    assert profile_labels == [
        "PenguinCore.create_total",
        "Load environment",
        "Setup logging",
        "Load configuration",
        "Create model config",
        "Initialize API client",
        "Create tool manager",
        "Create core instance",
    ]


@pytest.mark.asyncio
async def test_create_core_instance_returns_cli_tuple_when_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "configure_startup_logging", lambda: None)
    config = SimpleNamespace(
        model_config=SimpleNamespace(model="gpt-5", provider="openai"),
        to_dict=lambda: {},
    )

    class _ModelConfig:
        model = "gpt-5"
        provider = "openai"
        client_preference = "openai"

        def __init__(self, **_kwargs: Any) -> None:
            return None

    class _ApiClient:
        def __init__(self, *, model_config: Any) -> None:
            self.model_config = model_config

        def set_system_prompt(self, _prompt: str) -> None:
            return None

    class _ToolManager:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            self.tools: dict[str, Any] = {}

        def get_startup_stats(self) -> dict[str, int]:
            return {}

    class _Core:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    class _Cli:
        def __init__(self, core: Any) -> None:
            self.core = core

    core, cli = await startup.create_core_instance(
        _Core,
        config=config,
        model=None,
        provider=None,
        workspace_path=None,
        enable_cli=True,
        show_progress=False,
        progress_callback=None,
        fast_startup=True,
        default_model="default-model",
        default_provider="default-provider",
        system_prompt="system prompt",
        config_loader=lambda: config,
        model_config_factory=_ModelConfig,
        api_client_factory=_ApiClient,
        tool_manager_factory=_ToolManager,
        ensure_env_loaded=lambda: None,
        log_error=lambda *_args, **_kwargs: None,
        tqdm_factory=lambda *_args, **_kwargs: _FakeProgressBar(),
        profile_phase=_profile_factory([]),
        logger=_FakeLogger(),
        cli_factory_loader=lambda: _Cli,
    )

    assert isinstance(core, _Core)
    assert isinstance(cli, _Cli)
    assert cli.core is core


@pytest.mark.asyncio
async def test_create_core_instance_closes_progress_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(startup, "configure_startup_logging", lambda: None)
    pbar = _FakeProgressBar()

    def _raise_config() -> None:
        raise RuntimeError("config failed")

    with pytest.raises(RuntimeError, match="Failed to initialize PenguinCore"):
        await startup.create_core_instance(
            lambda **_kwargs: SimpleNamespace(),
            config=None,
            model=None,
            provider=None,
            workspace_path=None,
            enable_cli=False,
            show_progress=True,
            progress_callback=None,
            fast_startup=True,
            default_model="default-model",
            default_provider="default-provider",
            system_prompt="system prompt",
            config_loader=_raise_config,
            model_config_factory=lambda **kwargs: kwargs,
            api_client_factory=lambda **_kwargs: SimpleNamespace(),
            tool_manager_factory=lambda *_args, **_kwargs: SimpleNamespace(),
            ensure_env_loaded=lambda: None,
            log_error=lambda *_args, **_kwargs: None,
            tqdm_factory=lambda *_args, **_kwargs: pbar,
            profile_phase=_profile_factory([]),
            logger=_FakeLogger(),
        )

    assert pbar.closed is True


def test_load_startup_config_temporarily_sets_workspace_env_and_restores(
    tmp_path,
) -> None:
    env = {"PENGUIN_WORKSPACE": "/previous/workspace"}
    seen_env: list[str | None] = []

    def _load() -> SimpleNamespace:
        seen_env.append(env.get("PENGUIN_WORKSPACE"))
        return SimpleNamespace()

    config = startup.load_startup_config(
        None,
        workspace_path=str(tmp_path),
        config_loader=_load,
        environ=env,
    )

    assert seen_env == [str(tmp_path.resolve())]
    assert env == {"PENGUIN_WORKSPACE": "/previous/workspace"}
    assert config.workspace_path == tmp_path.resolve()


def test_load_startup_config_uses_supplied_config_and_clears_new_workspace_env(
    tmp_path,
) -> None:
    env: dict[str, str] = {}
    supplied = SimpleNamespace(workspace_path=None)

    config = startup.load_startup_config(
        supplied,
        workspace_path=str(tmp_path),
        config_loader=lambda: SimpleNamespace(loaded=True),
        environ=env,
    )

    assert config is supplied
    assert supplied.workspace_path == tmp_path.resolve()
    assert env == {}


def test_resolve_fast_startup_preserves_current_config_override_behavior() -> None:
    assert startup.resolve_fast_startup(SimpleNamespace(fast_startup=True), False)
    assert not startup.resolve_fast_startup(SimpleNamespace(fast_startup=False), False)
    assert startup.resolve_fast_startup(SimpleNamespace(fast_startup=False), True)
    assert not startup.resolve_fast_startup(SimpleNamespace(), False)


def test_build_api_client_loads_env_then_sets_system_prompt() -> None:
    calls: list[tuple[str, Any]] = []
    model_config = SimpleNamespace(model="gpt-5")

    class _Client:
        def __init__(self, *, model_config: Any) -> None:
            calls.append(("create", model_config))
            self.system_prompt = ""

        def set_system_prompt(self, prompt: str) -> None:
            calls.append(("prompt", prompt))
            self.system_prompt = prompt

    client = startup.build_api_client(
        model_config,
        system_prompt="system prompt",
        api_client_factory=_Client,
        ensure_env_loaded=lambda: calls.append(("env", None)),
    )

    assert isinstance(client, _Client)
    assert client.system_prompt == "system prompt"
    assert calls == [
        ("env", None),
        ("create", model_config),
        ("prompt", "system prompt"),
    ]


def test_build_initial_model_config_uses_live_config_and_api_base_fallback() -> None:
    captured: dict[str, Any] = {}
    config = SimpleNamespace(
        model_config=SimpleNamespace(
            model="gpt-5",
            provider="openai",
            api_base=None,
            use_assistants_api=True,
            client_preference="openai",
            streaming_enabled=False,
            max_output_tokens=4096,
            max_context_window_tokens=128000,
            service_tier="flex",
        ),
        api=SimpleNamespace(base_url="https://api.example.test/v1"),
    )

    def _factory(**kwargs: Any) -> dict[str, Any]:
        captured.update(kwargs)
        return kwargs

    model_config = startup.build_initial_model_config(
        config,
        model=None,
        provider=None,
        default_model="default-model",
        default_provider="default-provider",
        model_config_factory=_factory,
    )

    assert model_config == captured
    assert model_config == {
        "model": "gpt-5",
        "provider": "openai",
        "api_base": "https://api.example.test/v1",
        "use_assistants_api": True,
        "client_preference": "openai",
        "streaming_enabled": False,
        "max_output_tokens": 4096,
        "max_context_window_tokens": 128000,
        "service_tier": "flex",
    }


def test_build_initial_model_config_prefers_explicit_overrides_and_old_token_name() -> (
    None
):
    config = SimpleNamespace(
        model_config=SimpleNamespace(
            model="configured-model",
            provider="configured-provider",
            api_base="https://model.example.test/v1",
            max_output_tokens=None,
            max_tokens=2048,
        ),
    )

    model_config = startup.build_initial_model_config(
        config,
        model="override-model",
        provider="override-provider",
        default_model="default-model",
        default_provider="default-provider",
        model_config_factory=lambda **kwargs: kwargs,
    )

    assert model_config["model"] == "override-model"
    assert model_config["provider"] == "override-provider"
    assert model_config["api_base"] == "https://model.example.test/v1"
    assert model_config["client_preference"] == "openrouter"
    assert model_config["streaming_enabled"] is True
    assert model_config["max_output_tokens"] == 2048


def test_initialize_core_base_state_attaches_constructor_inputs() -> None:
    owner = SimpleNamespace()
    config = SimpleNamespace(name="config")
    api_client = SimpleNamespace(name="api")
    tool_manager = SimpleNamespace(name="tools")
    model_config = SimpleNamespace(name="model")

    startup.initialize_core_base_state(
        owner,
        config=config,
        api_client=api_client,
        tool_manager=tool_manager,
        model_config=model_config,
        config_factory=lambda: SimpleNamespace(name="loaded"),
    )

    assert owner.config is config
    assert owner.api_client is api_client
    assert owner.tool_manager is tool_manager
    assert owner.model_config is model_config
    assert owner._interrupted is False
    assert owner.progress_callbacks == []
    assert owner.token_callbacks == []
    assert owner._active_contexts == set()


def test_initialize_core_base_state_loads_config_when_missing() -> None:
    loaded = SimpleNamespace(name="loaded")
    owner = SimpleNamespace()

    startup.initialize_core_base_state(
        owner,
        config=None,
        api_client=None,
        tool_manager=None,
        model_config=None,
        config_factory=lambda: loaded,
    )

    assert owner.config is loaded


def test_initialize_core_instance_state_orchestrates_constructor_dependencies(
    tmp_path,
) -> None:
    calls: list[str] = []

    class _EventType:
        def __init__(self, value: str) -> None:
            self.value = value

    class _ConversationManager:
        def __init__(self, **kwargs: Any) -> None:
            calls.append("conversation")
            self.kwargs = kwargs

    class _Engine:
        def __init__(self, *_args: Any, **_kwargs: Any) -> None:
            calls.append("engine")
            self.message_bus_callbacks: list[Any] = []

        def setup_message_bus(self, *, ui_event_callback: Any) -> None:
            self.message_bus_callbacks.append(ui_event_callback)

    def _action_executor_factory(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        calls.append("action")
        return SimpleNamespace(name="action")

    def _project_manager_factory(*, workspace_path: Any) -> SimpleNamespace:
        calls.append("project")
        return SimpleNamespace(workspace_path=workspace_path)

    def _adapter_factory(*_args: Any, **_kwargs: Any) -> SimpleNamespace:
        calls.append("adapter")
        return SimpleNamespace(name="adapter")

    def _emit_ui_event(*_args: Any, **_kwargs: Any) -> None:
        return None

    validate_calls: list[Any] = []
    owner = SimpleNamespace(
        _persist_opencode_event=lambda *_args, **_kwargs: None,
        _subscribe_to_stream_events=lambda: calls.append("subscribe"),
        emit_ui_event=_emit_ui_event,
        get_coordinator=lambda: SimpleNamespace(name="coordinator"),
        validate_path=lambda path: validate_calls.append(path),
    )
    config = SimpleNamespace(
        workspace_path=tmp_path,
        diagnostics=SimpleNamespace(enabled=True),
        output=None,
        to_dict=lambda: {"skills": {"enabled": True}},
    )
    tool_manager = SimpleNamespace(
        project_root=tmp_path / "repo",
        set_core=lambda core: calls.append(f"set_core:{core is owner}"),
    )

    startup.initialize_core_instance_state(
        owner,
        config=config,
        api_client=SimpleNamespace(name="api"),
        tool_manager=tool_manager,
        model_config=SimpleNamespace(streaming_enabled=True),
        runtime_config=None,
        config_factory=lambda: SimpleNamespace(name="loaded"),
        runtime_config_factory=_RuntimeConfig,
        event_bus_factory=lambda: SimpleNamespace(name="bus"),
        event_type_enum=[_EventType("message"), _EventType("token_update")],
        stream_lock_factory=lambda: SimpleNamespace(name="lock"),
        stream_manager_factory=lambda: SimpleNamespace(name="stream"),
        part_event_adapter_factory=_adapter_factory,
        telemetry_ensurer=lambda _owner: calls.append("telemetry"),
        raw_config={"prompt": {"mode": "direct"}},
        get_system_prompt=lambda mode: f"prompt:{mode}",
        fallback_system_prompt="fallback",
        default_workspace_path="/unused",
        project_manager_factory=_project_manager_factory,
        diagnostics_disabler=lambda: calls.append("disable_diagnostics"),
        checkpoint_config_factory=lambda **kwargs: kwargs,
        conversation_manager_factory=_ConversationManager,
        action_executor_factory=_action_executor_factory,
        default_max_messages_per_session=42,
        engine_factory=_Engine,
        engine_settings_factory=lambda **kwargs: kwargs,
        logger=_FakeLogger(),
    )

    assert owner.config is config
    assert owner.event_types == {"message", "token_update"}
    assert owner.system_prompt == "prompt:direct"
    assert owner.project_manager.workspace_path == tmp_path
    assert owner.conversation_manager.core is owner
    assert owner.conversation_manager.kwargs["project_root"] == tmp_path / "repo"
    assert owner.action_executor.name == "action"
    assert isinstance(owner.engine, _Engine)
    assert owner.initialized is True
    assert owner._litellm_configured is False
    assert validate_calls == [tmp_path]
    assert calls == [
        "adapter",
        "subscribe",
        "telemetry",
        "project",
        "conversation",
        "set_core:True",
        "action",
        "engine",
    ]


def test_initialize_runtime_config_builds_config_and_registers_tool_observer() -> None:
    owner = SimpleNamespace()
    tool_manager = SimpleNamespace(on_runtime_config_change=lambda _payload: None)
    config = SimpleNamespace(to_dict=lambda: {"model": {"default": "gpt-5"}})

    startup.initialize_runtime_config(
        owner,
        config=config,
        runtime_config=None,
        tool_manager=tool_manager,
        runtime_config_factory=_RuntimeConfig,
    )

    assert owner.runtime_config.payload == {"model": {"default": "gpt-5"}}
    assert owner.runtime_config.observers == [tool_manager.on_runtime_config_change]


def test_build_tool_manager_passes_deterministic_config_payload() -> None:
    calls: list[tuple[dict[str, Any], Any, bool]] = []

    def _log_error(*_args: Any, **_kwargs: Any) -> None:
        return None

    def _factory(
        payload: dict[str, Any],
        log_error: Any,
        *,
        fast_startup: bool,
    ) -> dict[str, Any]:
        calls.append((payload, log_error, fast_startup))
        return {"tools": payload}

    result = startup.build_tool_manager(
        SimpleNamespace(to_dict=lambda: {"tools": {"enabled": True}}),
        log_error=_log_error,
        fast_startup=True,
        tool_manager_factory=_factory,
    )

    assert result == {"tools": {"tools": {"enabled": True}}}
    assert calls == [({"tools": {"enabled": True}}, _log_error, True)]


def test_build_tool_manager_uses_empty_payload_when_config_dict_fails() -> None:
    class _BrokenConfig:
        def to_dict(self) -> dict[str, Any]:
            raise RuntimeError("config unavailable")

    captured: list[dict[str, Any]] = []

    startup.build_tool_manager(
        _BrokenConfig(),
        log_error=lambda *_args, **_kwargs: None,
        fast_startup=False,
        tool_manager_factory=lambda payload, _log, *, fast_startup: (
            captured.append({"payload": payload, "fast_startup": fast_startup}) or {}
        ),
    )

    assert captured == [{"payload": {}, "fast_startup": False}]


def test_initialize_project_diagnostics_state_builds_manager_and_disables(
    tmp_path,
) -> None:
    owner = SimpleNamespace(
        config=SimpleNamespace(
            workspace_path=tmp_path,
            diagnostics=SimpleNamespace(enabled=False),
        )
    )
    disabled: list[bool] = []
    project_payloads: list[dict[str, Any]] = []

    def _project_manager_factory(*, workspace_path: Any) -> SimpleNamespace:
        project_payloads.append({"workspace_path": workspace_path})
        return SimpleNamespace(workspace_path=workspace_path)

    workspace_path = startup.initialize_project_diagnostics_state(
        owner,
        default_workspace_path="/default/workspace",
        project_manager_factory=_project_manager_factory,
        diagnostics_disabler=lambda: disabled.append(True),
    )

    assert workspace_path == tmp_path
    assert owner.project_manager.workspace_path == tmp_path
    assert project_payloads == [{"workspace_path": tmp_path}]
    assert disabled == [True]


def test_initialize_project_diagnostics_state_uses_default_workspace() -> None:
    owner = SimpleNamespace(config=SimpleNamespace(diagnostics=None))
    disabled: list[bool] = []

    workspace_path = startup.initialize_project_diagnostics_state(
        owner,
        default_workspace_path="/default/workspace",
        project_manager_factory=lambda *, workspace_path: SimpleNamespace(
            workspace_path=workspace_path
        ),
        diagnostics_disabler=lambda: disabled.append(True),
    )

    assert workspace_path == Path("/default/workspace")
    assert owner.project_manager.workspace_path == Path("/default/workspace")
    assert disabled == []


def test_initialize_runtime_config_uses_supplied_runtime_config() -> None:
    owner = SimpleNamespace()
    runtime_config = _RuntimeConfig({"existing": True})

    startup.initialize_runtime_config(
        owner,
        config=SimpleNamespace(to_dict=lambda: {"ignored": True}),
        runtime_config=runtime_config,
        tool_manager=None,
        runtime_config_factory=_RuntimeConfig,
    )

    assert owner.runtime_config is runtime_config
    assert runtime_config.observers == []


def test_initialize_tui_bridge_state_wires_event_stream_and_opencode_state() -> None:
    class _EventType:
        def __init__(self, value: str) -> None:
            self.value = value

    bus = SimpleNamespace(name="bus")
    lock = object()
    stream_manager = SimpleNamespace(name="stream")
    adapter_calls: list[dict[str, Any]] = []

    def _adapter_factory(
        event_bus: Any,
        *,
        persist_callback: Any,
        emit_session_status_events: bool,
    ) -> SimpleNamespace:
        adapter_calls.append(
            {
                "event_bus": event_bus,
                "persist_callback": persist_callback,
                "emit_session_status_events": emit_session_status_events,
            }
        )
        return SimpleNamespace(name="adapter")

    def _persist(event_type: str, payload: dict[str, Any]) -> None:
        del event_type, payload

    subscribe_calls: list[str] = []
    owner = SimpleNamespace(
        _persist_opencode_event=_persist,
        _subscribe_to_stream_events=lambda: subscribe_calls.append("subscribed"),
    )

    startup.initialize_tui_bridge_state(
        owner,
        event_bus_factory=lambda: bus,
        event_type_enum=[_EventType("status"), _EventType("stream_chunk")],
        stream_lock_factory=lambda: lock,
        stream_manager_factory=lambda: stream_manager,
        part_event_adapter_factory=_adapter_factory,
    )

    assert owner.event_bus is bus
    assert owner.event_types == {"status", "stream_chunk"}
    assert owner.current_stream is None
    assert owner.stream_lock is lock
    assert owner._stream_manager is stream_manager
    assert owner._tui_adapter.name == "adapter"
    assert owner._tui_adapters == {}
    assert owner._opencode_abort_sessions == set()
    assert owner._opencode_active_requests == {}
    assert owner._opencode_process_tasks == {}
    assert owner._runmode_stream_callback is None
    assert owner._runmode_active is False
    assert owner.run_mode is None
    assert subscribe_calls == ["subscribed"]
    assert adapter_calls == [
        {
            "event_bus": bus,
            "persist_callback": _persist,
            "emit_session_status_events": False,
        }
    ]


def test_build_default_checkpoint_config_uses_core_checkpoint_defaults() -> None:
    checkpoint_config = startup.build_default_checkpoint_config(
        checkpoint_config_factory=lambda **kwargs: kwargs,
    )

    assert checkpoint_config == {
        "enabled": True,
        "frequency": 1,
        "planes": {"conversation": True, "tasks": False, "code": False},
        "retention": {
            "keep_all_hours": 24,
            "keep_every_nth": 10,
            "max_age_days": 30,
        },
        "max_auto_checkpoints": 1000,
    }


def test_initialize_conversation_action_state_wires_managers_and_backrefs(
    tmp_path,
) -> None:
    checkpoint_payloads: list[dict[str, Any]] = []
    conversation_payloads: list[dict[str, Any]] = []
    action_payloads: list[dict[str, Any]] = []
    set_core_calls: list[Any] = []

    def _checkpoint_factory(**kwargs: Any) -> SimpleNamespace:
        checkpoint_payloads.append(kwargs)
        return SimpleNamespace(name="checkpoint", payload=kwargs)

    class _ConversationManager:
        def __init__(self, **kwargs: Any) -> None:
            conversation_payloads.append(kwargs)
            self.kwargs = kwargs

    def _action_executor_factory(
        tool_manager: Any,
        project_manager: Any,
        conversation_manager: Any,
        *,
        ui_event_callback: Any,
    ) -> SimpleNamespace:
        action_payloads.append(
            {
                "tool_manager": tool_manager,
                "project_manager": project_manager,
                "conversation_manager": conversation_manager,
                "ui_event_callback": ui_event_callback,
            }
        )
        return SimpleNamespace(name="executor")

    def _emit_ui_event(event_type: str, payload: dict[str, Any]) -> None:
        del event_type, payload

    tool_manager = SimpleNamespace(
        project_root=tmp_path / "repo",
        set_core=lambda owner: set_core_calls.append(owner),
    )
    owner = SimpleNamespace(
        config=SimpleNamespace(to_dict=lambda: {"skills": {"enabled": True}}),
        model_config=SimpleNamespace(name="model"),
        api_client=SimpleNamespace(name="api"),
        system_prompt="system prompt",
        tool_manager=tool_manager,
        project_manager=SimpleNamespace(name="project"),
        emit_ui_event=_emit_ui_event,
    )

    startup.initialize_conversation_action_state(
        owner,
        workspace_path=tmp_path,
        checkpoint_config_factory=_checkpoint_factory,
        conversation_manager_factory=_ConversationManager,
        action_executor_factory=_action_executor_factory,
        default_max_messages_per_session=42,
    )

    assert checkpoint_payloads == [
        {
            "enabled": True,
            "frequency": 1,
            "planes": {"conversation": True, "tasks": False, "code": False},
            "retention": {
                "keep_all_hours": 24,
                "keep_every_nth": 10,
                "max_age_days": 30,
            },
            "max_auto_checkpoints": 1000,
        }
    ]
    assert conversation_payloads == [
        {
            "model_config": owner.model_config,
            "api_client": owner.api_client,
            "workspace_path": tmp_path,
            "system_prompt": "system prompt",
            "max_messages_per_session": 42,
            "max_sessions_in_memory": 20,
            "auto_save_interval": 60,
            "checkpoint_config": owner.conversation_manager.kwargs["checkpoint_config"],
            "skills_config": {"skills": {"enabled": True}},
            "project_root": tmp_path / "repo",
        }
    ]
    assert owner.conversation_manager.core is owner
    assert set_core_calls == [owner]
    assert owner.action_executor.name == "executor"
    assert action_payloads == [
        {
            "tool_manager": tool_manager,
            "project_manager": owner.project_manager,
            "conversation_manager": owner.conversation_manager,
            "ui_event_callback": _emit_ui_event,
        }
    ]
    assert owner.current_runmode_status_summary == "RunMode idle."


def test_initialize_conversation_action_state_uses_empty_skills_without_config_dict(
    tmp_path,
) -> None:
    conversation_payloads: list[dict[str, Any]] = []

    class _BrokenConfig:
        def to_dict(self) -> dict[str, Any]:
            raise RuntimeError("config unavailable")

    startup.initialize_conversation_action_state(
        SimpleNamespace(
            config=_BrokenConfig(),
            model_config=None,
            api_client=None,
            system_prompt="prompt",
            tool_manager=None,
            project_manager=SimpleNamespace(name="project"),
            emit_ui_event=lambda *_args, **_kwargs: None,
        ),
        workspace_path=tmp_path,
        checkpoint_config_factory=lambda **kwargs: kwargs,
        conversation_manager_factory=lambda **kwargs: (
            conversation_payloads.append(kwargs) or SimpleNamespace()
        ),
        action_executor_factory=lambda *_args, **_kwargs: SimpleNamespace(),
        default_max_messages_per_session=7,
    )

    assert conversation_payloads[0]["skills_config"] == {}
    assert conversation_payloads[0]["project_root"] is None


def test_initialize_engine_state_wires_engine_without_implicit_token_stop() -> None:
    logger = _FakeLogger()

    class _EngineSettings:
        def __init__(self, *, streaming_default: bool) -> None:
            self.streaming_default = streaming_default

    class _Engine:
        def __init__(
            self,
            settings: Any,
            conversation_manager: Any,
            api_client: Any,
            tool_manager: Any,
            action_executor: Any,
            *,
            stop_conditions: list[Any],
        ) -> None:
            self.settings = settings
            self.conversation_manager = conversation_manager
            self.api_client = api_client
            self.tool_manager = tool_manager
            self.action_executor = action_executor
            self.stop_conditions = stop_conditions
            self.message_bus_callbacks: list[Any] = []

        def setup_message_bus(self, *, ui_event_callback: Any) -> None:
            self.message_bus_callbacks.append(ui_event_callback)

    def _emit_ui_event(event_type: str, payload: dict[str, Any]) -> None:
        del event_type, payload

    owner = SimpleNamespace(
        model_config=SimpleNamespace(streaming_enabled=False),
        conversation_manager=SimpleNamespace(name="conversation"),
        api_client=SimpleNamespace(name="api"),
        tool_manager=SimpleNamespace(name="tools"),
        action_executor=SimpleNamespace(name="actions"),
        telemetry=SimpleNamespace(name="telemetry"),
        emit_ui_event=_emit_ui_event,
        get_coordinator=lambda: SimpleNamespace(name="coordinator"),
    )

    startup.initialize_engine_state(
        owner,
        engine_factory=_Engine,
        engine_settings_factory=_EngineSettings,
        logger=logger,
    )

    assert owner.engine.settings.streaming_default is False
    assert owner.engine.conversation_manager is owner.conversation_manager
    assert owner.engine.api_client is owner.api_client
    assert owner.engine.tool_manager is owner.tool_manager
    assert owner.engine.action_executor is owner.action_executor
    assert owner.engine.stop_conditions == []
    assert owner.engine.model_config is owner.model_config
    assert owner.engine.coordinator.name == "coordinator"
    assert owner.engine.telemetry is owner.telemetry
    assert owner.engine.message_bus_callbacks == [_emit_ui_event]
    assert logger.debug_calls == []
    assert logger.warning_calls == []


def test_initialize_engine_state_defaults_streaming_when_model_config_unavailable() -> (
    None
):
    class _BrokenModelConfig:
        @property
        def streaming_enabled(self) -> bool:
            raise RuntimeError("missing")

    engine_settings: list[Any] = []

    class _Engine:
        def __init__(self, settings: Any, *_args: Any, **_kwargs: Any) -> None:
            engine_settings.append(settings)

        def setup_message_bus(self, *, ui_event_callback: Any) -> None:
            del ui_event_callback

    startup.initialize_engine_state(
        SimpleNamespace(
            model_config=_BrokenModelConfig(),
            conversation_manager=None,
            api_client=None,
            tool_manager=None,
            action_executor=None,
            emit_ui_event=lambda *_args, **_kwargs: None,
            get_coordinator=lambda: None,
        ),
        engine_factory=_Engine,
        engine_settings_factory=lambda **kwargs: kwargs,
        logger=_FakeLogger(),
    )

    assert engine_settings == [{"streaming_default": True}]


def test_initialize_engine_state_keeps_engine_when_coordination_setup_fails() -> None:
    logger = _FakeLogger()

    class _Engine:
        def setup_message_bus(self, *, ui_event_callback: Any) -> None:
            del ui_event_callback

    def _get_coordinator() -> None:
        raise RuntimeError("coordinator unavailable")

    owner = SimpleNamespace(
        model_config=SimpleNamespace(streaming_enabled=True),
        conversation_manager=None,
        api_client=None,
        tool_manager=None,
        action_executor=None,
        emit_ui_event=lambda *_args, **_kwargs: None,
        get_coordinator=_get_coordinator,
    )

    startup.initialize_engine_state(
        owner,
        engine_factory=lambda *_args, **_kwargs: _Engine(),
        engine_settings_factory=lambda **kwargs: kwargs,
        logger=logger,
    )

    assert isinstance(owner.engine, _Engine)
    assert logger.debug_calls[0][0] == "Coordinator unavailable during engine init: %s"
    assert isinstance(logger.debug_calls[0][1][0], RuntimeError)
    assert str(logger.debug_calls[0][1][0]) == "coordinator unavailable"
    assert logger.warning_calls == []


def test_initialize_engine_state_sets_none_when_engine_construction_fails() -> None:
    logger = _FakeLogger()

    def _engine_factory(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("engine unavailable")

    owner = SimpleNamespace(
        model_config=SimpleNamespace(streaming_enabled=True),
        conversation_manager=None,
        api_client=None,
        tool_manager=None,
        action_executor=None,
    )

    startup.initialize_engine_state(
        owner,
        engine_factory=_engine_factory,
        engine_settings_factory=lambda **kwargs: kwargs,
        logger=logger,
    )

    assert owner.engine is None
    assert logger.warning_calls[0][0] == (
        "Failed to initialize Engine layer (fallback to legacy core processing): %s"
    )
    assert isinstance(logger.warning_calls[0][1][0], RuntimeError)
    assert str(logger.warning_calls[0][1][0]) == "engine unavailable"
    assert logger.warning_calls[0][2] == {"exc_info": True}


def test_finalize_core_startup_state_sets_flags_and_validates_workspace(
    tmp_path,
) -> None:
    logger = _FakeLogger()
    validate_calls: list[Any] = []
    owner = SimpleNamespace(validate_path=lambda path: validate_calls.append(path))

    startup.finalize_core_startup_state(
        owner,
        workspace_path=tmp_path,
        logger=logger,
    )

    assert owner.initialized is True
    assert owner.accumulated_tokens == {"prompt": 0, "completion": 0, "total": 0}
    assert owner._litellm_configured is False
    assert owner._last_model_load_error is None
    assert validate_calls == [tmp_path]
    assert logger.info_calls[-1] == ("PenguinCore initialized successfully", ())


def test_initialize_prompt_and_output_state_prefers_typed_output_config() -> None:
    formatted: list[str] = []
    owner = SimpleNamespace(
        config=SimpleNamespace(
            output=SimpleNamespace(
                show_tool_results=False,
                prompt_style="json_guided",
            )
        )
    )

    startup.initialize_prompt_and_output_state(
        owner,
        {"prompt": {"mode": "TEST"}, "output": {"prompt_style": "plain"}},
        get_system_prompt=lambda mode: f"prompt:{mode}",
        fallback_system_prompt="fallback",
        set_output_formatting=formatted.append,
    )

    assert owner.show_tool_results is False
    assert owner.prompt_mode == "test"
    assert owner.output_style == "json_guided"
    assert owner.system_prompt == "prompt:test"
    assert formatted == ["json_guided"]


def test_initialize_prompt_and_output_state_uses_raw_output_fallbacks() -> None:
    formatted: list[str] = []
    owner = SimpleNamespace(config=SimpleNamespace(output=None))

    startup.initialize_prompt_and_output_state(
        owner,
        {
            "prompt": {"mode": "review"},
            "output": {"show_tool_results": "no", "prompt_style": "plain"},
        },
        get_system_prompt=lambda mode: f"prompt:{mode}",
        fallback_system_prompt="fallback",
        set_output_formatting=formatted.append,
    )

    assert owner.show_tool_results is False
    assert owner.prompt_mode == "review"
    assert owner.output_style == "plain"
    assert owner.system_prompt == "prompt:review"
    assert formatted == ["plain"]


def test_initialize_prompt_and_output_state_falls_back_on_prompt_failures() -> None:
    owner = SimpleNamespace(config=SimpleNamespace(output=None))

    def _raise_prompt(_mode: str) -> str:
        raise RuntimeError("prompt unavailable")

    def _raise_format(_style: str) -> None:
        raise RuntimeError("formatter unavailable")

    startup.initialize_prompt_and_output_state(
        owner,
        {"prompt": {"mode": ""}, "output": {"prompt_style": "json_guided"}},
        get_system_prompt=_raise_prompt,
        fallback_system_prompt="fallback",
        set_output_formatting=_raise_format,
    )

    assert owner.show_tool_results is True
    assert owner.prompt_mode == "direct"
    assert owner.output_style == "steps_final"
    assert owner.system_prompt == "fallback"
