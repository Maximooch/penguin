"""Tests for core startup helper contracts."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

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
        self.info_calls: list[tuple[str, tuple[Any, ...]]] = []
        self.error_calls: list[tuple[str, tuple[Any, ...]]] = []

    def info(self, message: str, *args: Any) -> None:
        self.info_calls.append((message, args))

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
