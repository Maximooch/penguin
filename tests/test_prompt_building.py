"""Focused rendering checks for every public Penguin prompt mode."""

from __future__ import annotations

import pytest

from penguin.prompt.profiles import list_available_modes
from penguin.system_prompt import get_system_prompt


@pytest.mark.parametrize("mode", list_available_modes())
def test_prompt_mode_builds_with_compact_runtime_contract(mode: str) -> None:
    prompt = get_system_prompt(mode)

    assert "You are Penguin" in prompt
    assert "## Operating contract" in prompt
    assert "## Tool Invocation Protocol" in prompt
    assert "### finish_task" in prompt


def test_product_mode_requires_complete_user_facing_states() -> None:
    prompt = get_system_prompt("product")

    assert "## Product quality overlay" in prompt
    assert "loading, empty, error, success, keyboard, accessibility, and" in prompt
    assert "reuse the existing design system" in prompt


def test_rigorous_mode_prohibits_hidden_goal_stops() -> None:
    prompt = get_system_prompt("rigorous")

    assert "## Rigorous systems overlay" in prompt
    assert "Do not invent a deadline, token budget, iteration cap" in prompt


def test_git_attribution_prompt_is_enabled_by_default() -> None:
    prompt = get_system_prompt("direct")

    assert "## Git attribution" in prompt
    assert (
        "Co-authored-by: penguin-agent[bot] "
        "<penguin-agent[bot]@users.noreply.github.com>" in prompt
    )


def test_git_attribution_prompt_can_be_disabled() -> None:
    prompt = get_system_prompt("direct", git_attribution_prompt=False)

    assert "## Git attribution" not in prompt
    assert (
        "Co-authored-by: penguin-agent[bot] "
        "<penguin-agent[bot]@users.noreply.github.com>" not in prompt
    )
