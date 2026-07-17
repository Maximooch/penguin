"""Tests for prompt and output-style core runtime helpers."""

from __future__ import annotations

import logging
from importlib import import_module
from types import SimpleNamespace

from penguin.core import PenguinCore
from penguin.core_runtime import prompt_settings


class _ConversationManager:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def set_system_prompt(self, prompt: str) -> None:
        self.prompts.append(prompt)


def _prompt(mode: str, **_kwargs: object) -> str:
    return f"prompt:{mode}"


def test_set_prompt_mode_normalizes_and_updates_owner_and_conversation() -> None:
    api_prompts: list[str] = []
    owner = SimpleNamespace(
        api_client=SimpleNamespace(set_system_prompt=api_prompts.append),
        conversation_manager=_ConversationManager(),
    )

    result = prompt_settings.set_prompt_mode(
        owner,
        " Review ",
        get_system_prompt=_prompt,
        logger=logging.getLogger(__name__),
    )

    assert result == "Prompt mode set to 'review'."
    assert owner.prompt_mode == "review"
    assert owner.system_prompt == "prompt:review"
    assert api_prompts == ["prompt:review"]
    assert owner.conversation_manager.prompts == ["prompt:review"]


def test_set_prompt_mode_returns_error_message_when_prompt_builder_fails() -> None:
    def failing_prompt(_mode: str, **_kwargs: object) -> str:
        raise RuntimeError("bad mode")

    result = prompt_settings.set_prompt_mode(
        SimpleNamespace(conversation_manager=_ConversationManager()),
        "bad",
        get_system_prompt=failing_prompt,
        logger=logging.getLogger(__name__),
    )

    assert result == "Failed to set prompt mode 'bad': bad mode"


def test_set_prompt_mode_can_canonicalize_an_alias() -> None:
    owner = SimpleNamespace(conversation_manager=_ConversationManager())

    result = prompt_settings.set_prompt_mode(
        owner,
        "Ponytail",
        get_system_prompt=_prompt,
        normalize_prompt_mode=lambda _mode: "complexity_review",
        logger=logging.getLogger(__name__),
    )

    assert result == "Prompt mode set to 'complexity_review'."
    assert owner.prompt_mode == "complexity_review"
    assert owner.system_prompt == "prompt:complexity_review"


def test_set_prompt_mode_preserves_the_owners_output_style() -> None:
    render_calls: list[tuple[str, str | None, bool]] = []

    def render(
        mode: str,
        *,
        output_style: str | None = None,
        git_attribution_prompt: bool = True,
    ) -> str:
        render_calls.append((mode, output_style, git_attribution_prompt))
        return f"prompt:{mode}:{output_style}"

    owner = SimpleNamespace(
        output_style="plain",
        conversation_manager=_ConversationManager(),
    )

    prompt_settings.set_prompt_mode(
        owner,
        "review",
        get_system_prompt=render,
        logger=logging.getLogger(__name__),
    )

    assert render_calls == [("review", "plain", True)]
    assert owner.system_prompt == "prompt:review:plain"


def test_prompt_rebuilds_preserve_disabled_git_attribution() -> None:
    render_calls: list[tuple[str, str | None, bool]] = []

    def render(
        mode: str,
        *,
        output_style: str | None = None,
        git_attribution_prompt: bool = True,
    ) -> str:
        render_calls.append((mode, output_style, git_attribution_prompt))
        return f"prompt:{mode}:{output_style}:{git_attribution_prompt}"

    owner = SimpleNamespace(
        prompt_mode="direct",
        output_style="plain",
        git_attribution_prompt=False,
        conversation_manager=_ConversationManager(),
    )

    prompt_settings.set_prompt_mode(
        owner,
        "review",
        get_system_prompt=render,
        logger=logging.getLogger(__name__),
    )
    prompt_settings.set_output_style(
        owner,
        "json_guided",
        get_system_prompt=render,
        set_output_formatting=lambda _style: None,
        logger=logging.getLogger(__name__),
    )

    assert render_calls == [
        ("review", "plain", False),
        ("review", "json_guided", False),
    ]


def test_prompt_and_output_style_getters_default_when_missing() -> None:
    owner = SimpleNamespace()

    assert prompt_settings.get_prompt_mode(owner) == "direct"
    assert prompt_settings.get_output_style(owner) == "steps_final"
    assert prompt_settings.get_work_mode(owner) == "build"


def test_set_work_mode_preserves_configured_prompt_layers() -> None:
    calls: list[dict[str, object]] = []
    owner = SimpleNamespace(
        output_style="plain",
        personality_profile="minimal",
        personality_overlay="Prefer concrete examples.",
        quality_overlays=("rigorous",),
        conversation_manager=_ConversationManager(),
    )

    def render(**kwargs: object) -> str:
        calls.append(kwargs)
        return "composed"

    result = prompt_settings.set_work_mode(
        owner,
        " Review ",
        get_system_prompt=render,
        normalize_work_mode=lambda mode: mode.strip().lower(),
        logger=logging.getLogger(__name__),
    )

    assert result == "Work mode set to 'review'."
    assert owner.work_mode == "review"
    assert owner.prompt_mode == "review"
    assert calls == [
        {
            "work_mode": "review",
            "output_style": "plain",
            "git_attribution_prompt": True,
            "personality_profile": "minimal",
            "personality_overlay": "Prefer concrete examples.",
            "quality_overlays": ("rigorous",),
        }
    ]


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
    prompt_builder = import_module("penguin.prompt.builder")
    monkeypatch.setattr(prompt_builder, "set_output_formatting", formats.append)

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
    assert formats == ["prompt:test", "manual", "json_guided", "prompt:test"]
