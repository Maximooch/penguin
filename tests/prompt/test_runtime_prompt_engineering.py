from __future__ import annotations

import json

from penguin.system_prompt import (
    build_active_turn_envelope,
    get_system_prompt,
    prompt_metrics,
)


def test_prompt_modes_are_materially_distinct_and_remove_tool_quotas() -> None:
    prompts = {
        mode: get_system_prompt(mode)
        for mode in ("direct", "implement", "review", "explain", "compatibility")
    }

    assert len({prompt for prompt in prompts.values()}) == len(prompts)
    assert "Implement mode" in prompts["implement"]
    assert "Review mode" in prompts["review"]
    assert "Explain mode" in prompts["explain"]
    assert "Minimum 5-12 tool calls" not in prompts["direct"]
    assert "One action per response" not in prompts["implement"]
    assert len(prompts["implement"]) < len(prompts["compatibility"])


def test_prompt_metrics_fingerprint_each_section() -> None:
    metrics = prompt_metrics("implement")

    assert metrics["mode"] == "implement"
    assert metrics["total_chars"] > 0
    assert len(metrics["fingerprint"]) == 64
    assert set(metrics["sections"]) >= {
        "base",
        "mode",
        "safety",
        "tools",
        "workflow",
    }
    assert metrics["sections"]["tools"]["chars"] < 20_000


def test_active_turn_envelope_is_compact_structured_and_bounded() -> None:
    envelope = build_active_turn_envelope(
        mode="build",
        active_task="x" * 5_000,
        continuation="resume",
        terminal_reason="max_iterations",
        tool_state="pending_tool_call",
    )

    assert envelope.startswith("[PENGUIN_ACTIVE_TURN]")
    payload = envelope.removeprefix("[PENGUIN_ACTIVE_TURN]").removesuffix(
        "[/PENGUIN_ACTIVE_TURN]"
    )
    parsed = json.loads(payload)
    assert parsed["mode"] == "implement"
    assert parsed["continuation"] == "resume"
    assert len(parsed["active_task"]) == 1_000
