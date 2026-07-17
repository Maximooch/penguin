"""Contract tests for Penguin's canonical, mode-aware system prompt."""

from __future__ import annotations

import pytest

from penguin.prompt.builder import PromptBuilder
from penguin.prompt.profiles import (
    PromptMode,
    get_work_mode_profile,
    list_available_work_modes,
    list_quality_overlays,
)
from penguin.prompt.soul import list_personality_profiles
from penguin.system_prompt import SYSTEM_PROMPT, get_system_prompt, list_output_styles


def test_default_system_prompt_contains_the_core_engineering_contract() -> None:
    assert isinstance(SYSTEM_PROMPT, str)

    prompt = get_system_prompt("direct")
    for needle in (
        "## Engineering discipline",
        "smallest excellent change",
        "Use this decision ladder:",
        "## Character and counsel",
        "humorous or lightly sarcastic",
        "Do not accept an excuse where an honest",
        "## Operating contract",
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


def test_each_work_mode_renders_a_distinct_intent_profile() -> None:
    prompts = {
        mode: get_system_prompt(work_mode=mode)
        for mode in list_available_work_modes(include_internal=True)
    }

    assert len(set(prompts.values())) == len(prompts)
    assert "## Build mode" in prompts["build"]
    assert "## Review mode" in prompts["review"]
    assert "## Research mode" in prompts["research"]


def test_quality_presets_compose_without_inventing_new_work_modes() -> None:
    product = get_system_prompt("product")
    rigorous = get_system_prompt("rigorous")
    complexity = get_system_prompt("complexity_review")

    assert "## Build mode" in product
    assert "## Product quality overlay" in product
    assert "## Build mode" in rigorous
    assert "## Rigorous systems overlay" in rigorous
    assert "## Review mode" in complexity
    assert "## Complexity review overlay" in complexity


def test_mode_aliases_resolve_to_their_canonical_profiles() -> None:
    assert get_system_prompt("lean") == get_system_prompt("direct")
    assert get_system_prompt("ponytail") == get_system_prompt("complexity_review")
    assert get_system_prompt("complexity-review") == get_system_prompt(
        "complexity_review"
    )


def test_unknown_mode_is_an_explicit_configuration_error() -> None:
    with pytest.raises(ValueError, match="Unknown prompt preset"):
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


def test_personality_profile_does_not_change_work_mode_or_capability() -> None:
    default = get_system_prompt(work_mode="review")
    minimal = get_system_prompt(work_mode="review", personality_profile="minimal")

    assert "## Review mode" in default
    assert "## Review mode" in minimal
    assert "## Character and counsel" in default
    assert "## Character and counsel" not in minimal
    assert get_work_mode_profile("review").capability_profile == "read_only"


def test_user_personality_overlay_is_local_to_the_soul_layer() -> None:
    prompt = get_system_prompt(
        work_mode="plan",
        personality_overlay="Prefer nautical metaphors when they clarify a tradeoff.",
    )

    assert "## User personality preferences" in prompt
    assert "Prefer nautical metaphors" in prompt
    assert "## Plan mode" in prompt


def test_explicit_work_mode_does_not_inherit_a_legacy_preset_bundle() -> None:
    prompt = get_system_prompt("terse", work_mode="review")

    assert "## Review mode" in prompt
    assert "## Character and counsel" in prompt
    assert "Use concise prose." not in prompt


def test_legacy_prompt_enum_retains_old_members() -> None:
    assert get_system_prompt(PromptMode.PRODUCT.value) == get_system_prompt("product")


def test_prompt_dimensions_are_discoverable_for_future_clients() -> None:
    assert list_available_work_modes() == [
        "build",
        "plan",
        "review",
        "research",
        "chat",
    ]
    assert list_personality_profiles() == ["penguin", "minimal"]
    assert list_quality_overlays() == ["product", "rigorous", "complexity_review"]
    assert list_output_styles() == [
        "steps_final",
        "plain",
        "json_guided",
        "explanatory",
    ]
