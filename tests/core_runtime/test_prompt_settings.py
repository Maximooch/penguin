"""Tests for prompt and output-style core runtime helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace

from penguin.core import PenguinCore
from penguin.core_runtime import prompt_settings


class _ConversationManager:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def set_system_prompt(self, prompt: str) -> None:
        self.prompts.append(prompt)


def _prompt(mode: str) -> str:
    return f"prompt:{mode}"


def test_set_prompt_mode_normalizes_and_updates_owner_and_conversation() -> None:
    owner = SimpleNamespace(conversation_manager=_ConversationManager())

    result = prompt_settings.set_prompt_mode(
        owner,
        " Review ",
        get_system_prompt=_prompt,
        logger=logging.getLogger(__name__),
    )

    assert result == "Prompt mode set to 'review'."
    assert owner.prompt_mode == "review"
    assert owner.system_prompt == "prompt:review"
    assert owner.conversation_manager.prompts == ["prompt:review"]


def test_set_prompt_mode_returns_error_message_when_prompt_builder_fails() -> None:
    def failing_prompt(_mode: str) -> str:
        raise RuntimeError("bad mode")

    result = prompt_settings.set_prompt_mode(
        SimpleNamespace(conversation_manager=_ConversationManager()),
        "bad",
        get_system_prompt=failing_prompt,
        logger=logging.getLogger(__name__),
    )

    assert result == "Failed to set prompt mode 'bad': bad mode"


def test_prompt_and_output_style_getters_default_when_missing() -> None:
    owner = SimpleNamespace()

    assert prompt_settings.get_prompt_mode(owner) == "direct"
    assert prompt_settings.get_output_style(owner) == "steps_final"


def test_set_core_system_prompt_updates_api_client_and_conversation() -> None:
    api_prompts: list[str] = []
    owner = SimpleNamespace(
        api_client=SimpleNamespace(set_system_prompt=api_prompts.append),
        conversation_manager=_ConversationManager(),
    )

    prompt_settings.set_core_system_prompt(owner, "system")

    assert owner.system_prompt == "system"
    assert api_prompts == ["system"]
    assert owner.conversation_manager.prompts == ["system"]


def test_set_output_style_updates_formatting_and_rebuilds_prompt() -> None:
    formats: list[str] = []
    owner = SimpleNamespace(
        prompt_mode="terse",
        conversation_manager=_ConversationManager(),
    )

    result = prompt_settings.set_output_style(
        owner,
        " Plain ",
        get_system_prompt=_prompt,
        set_output_formatting=formats.append,
        logger=logging.getLogger(__name__),
    )

    assert result == "Output style set to 'plain'."
    assert owner.output_style == "plain"
    assert formats == ["plain"]
    assert owner.system_prompt == "prompt:terse"
    assert owner.conversation_manager.prompts == ["prompt:terse"]


def test_set_output_style_returns_error_message_when_formatter_fails() -> None:
    def failing_formatter(_style: str) -> None:
        raise RuntimeError("bad style")

    result = prompt_settings.set_output_style(
        SimpleNamespace(prompt_mode="direct"),
        "bad",
        get_system_prompt=_prompt,
        set_output_formatting=failing_formatter,
        logger=logging.getLogger(__name__),
    )

    assert result == "Failed to set output style 'bad': bad style"


def test_core_prompt_setting_shims_delegate_to_runtime(monkeypatch) -> None:
    formats: list[str] = []
    core = PenguinCore.__new__(PenguinCore)
    core.conversation_manager = _ConversationManager()
    facade_globals = PenguinCore.set_prompt_mode.__globals__

    monkeypatch.setitem(facade_globals, "get_system_prompt", _prompt)
    monkeypatch.setattr("penguin.prompt.builder.set_output_formatting", formats.append)

    core.api_client = SimpleNamespace(set_system_prompt=formats.append)
    assert core.set_prompt_mode("TEST") == "Prompt mode set to 'test'."
    assert core.get_prompt_mode() == "test"
    core.set_system_prompt("manual")
    assert core.set_output_style("JSON_GUIDED") == (
        "Output style set to 'json_guided'."
    )
    assert core.get_output_style() == "json_guided"
    assert core.system_prompt == "prompt:test"
    assert core.conversation_manager.prompts == [
        "prompt:test",
        "manual",
        "prompt:test",
    ]
    assert formats == ["manual", "json_guided"]
