"""Tests for core startup helper contracts."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core_runtime import startup


class _RuntimeConfig:
    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload
        self.observers: list[Any] = []

    def register_observer(self, observer: Any) -> None:
        self.observers.append(observer)


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
