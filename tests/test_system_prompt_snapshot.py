"""Contract tests for Penguin's canonical, mode-aware system prompt."""

from __future__ import annotations

import pytest

from penguin.prompt.builder import PromptBuilder
from penguin.prompt.profiles import list_available_modes
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt


def test_default_system_prompt_contains_the_core_engineering_contract() -> None:
    assert isinstance(SYSTEM_PROMPT, str)

    prompt = get_system_prompt("direct")
    for needle in (
        "## Engineering discipline",
        "smallest excellent change",
        "Use this decision ladder:",
        "## Voice and counsel",
        "humorous or lightly sarcastic",
        "Do not accept excuses in place of an honest constraint,",
        "## Runtime and completion",
        "Do not invent a deadline, token budget, iteration cap, or wall-clock stop.",
        "## Tool Invocation Protocol",
        "### finish_task",
    ):
        assert needle in prompt


def test_default_system_prompt_omits_legacy_ceremony_and_tool_encyclopedia() -> None:
    prompt = get_system_prompt("direct")

    for forbidden in (
        "Minimum 5-12 tool calls",
        "One action per response",
        "Commit frequently (IN A SEPARATE BRANCH)",
        "simulated internal dialog",
        "### pydoll_browser_navigate",
        "### spawn_sub_agent",
    ):
        assert forbidden not in prompt


def test_each_declared_mode_renders_a_distinct_profile() -> None:
    prompts = {mode: get_system_prompt(mode) for mode in list_available_modes()}

    assert len(set(prompts.values())) == len(prompts)
    assert "## Product quality mode" in prompts["product"]
    assert "## Rigorous systems mode" in prompts["rigorous"]
    assert "## Complexity review mode" in prompts["complexity_review"]
    assert "## Complexity review mode" not in prompts["direct"]


def test_mode_aliases_resolve_to_their_canonical_profiles() -> None:
    assert get_system_prompt("lean") == get_system_prompt("direct")
    assert get_system_prompt("ponytail") == get_system_prompt("complexity_review")
    assert get_system_prompt("complexity-review") == get_system_prompt(
        "complexity_review"
    )


def test_unknown_mode_is_an_explicit_configuration_error() -> None:
    with pytest.raises(ValueError, match="Unknown prompt mode"):
        get_system_prompt("invent_a_mode")


def test_output_style_is_a_real_renderer_overlay() -> None:
    builder = PromptBuilder()
    builder.set_output_style("plain")

    prompt = builder.build("direct")

    assert "Use concise prose." in prompt
    assert "Keep progress updates concrete and brief." not in prompt


def test_explicit_output_style_does_not_mutate_builder_state() -> None:
    builder = PromptBuilder()
    builder.set_output_style("plain")

    json_prompt = builder.build("direct", output_style="json_guided")
    plain_prompt = builder.build("direct")

    assert "Use clear, structured output" in json_prompt
    assert "Use concise prose." in plain_prompt
