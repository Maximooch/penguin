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
