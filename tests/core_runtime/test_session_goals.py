"""Tests for the persisted session-goal state machine."""

from __future__ import annotations

import pytest

from penguin.core_runtime.session_goals import (
    MAX_GOAL_METADATA_BYTES,
    MAX_GOAL_OBJECTIVE_CHARS,
    GoalConflictError,
    GoalValidationError,
    create_goal,
    goal_status_from_run_result,
    normalize_goal,
    transition_goal_status,
)


def test_normalize_goal_fails_closed_for_corrupt_numeric_fields() -> None:
    goal = create_goal("Ship it")

    for field, value in (
        ("revision", "not-a-number"),
        ("revision", True),
        ("tokens_used", -1),
        ("tokens_used", False),
        ("time_used_seconds", float("nan")),
    ):
        corrupt = dict(goal)
        corrupt[field] = value
        assert normalize_goal(corrupt) is None


def test_create_goal_rejects_boolean_and_blank_values() -> None:
    with pytest.raises(GoalValidationError, match="objective"):
        create_goal("   ")
    with pytest.raises(GoalValidationError, match="objective"):
        create_goal("x" * (MAX_GOAL_OBJECTIVE_CHARS + 1))
    with pytest.raises(GoalValidationError, match="token_budget"):
        create_goal("Ship it", token_budget=True)
    with pytest.raises(GoalValidationError, match="metadata"):
        create_goal("Ship it", metadata={"payload": "x" * MAX_GOAL_METADATA_BYTES})


def test_create_goal_accepts_any_positive_user_token_budget() -> None:
    goal = create_goal("Run until complete", token_budget=100_000_000)

    assert goal["token_budget"] == 100_000_000


def test_normalize_goal_fails_closed_for_invalid_metadata() -> None:
    goal = create_goal("Ship it")
    goal["metadata"] = {"value": float("nan")}

    assert normalize_goal(goal) is None


def test_user_transition_policy_is_narrow_and_complete_is_terminal() -> None:
    active = create_goal("Ship it")
    paused = transition_goal_status(active, "paused", actor="user")
    assert paused["status"] == "paused"
    assert paused["revision"] == active["revision"] + 1

    resumed = transition_goal_status(paused, "active", actor="user")
    assert resumed["status"] == "active"

    complete = transition_goal_status(active, "complete", actor="runtime")
    with pytest.raises(GoalConflictError, match="terminal"):
        transition_goal_status(complete, "active", actor="user")
    with pytest.raises(GoalConflictError, match="cannot transition"):
        transition_goal_status(active, "blocked", actor="user")


@pytest.mark.parametrize(
    ("result", "expected"),
    [
        ({"status": "pending_review", "finish_status": "done"}, "complete"),
        ({"status": "pending_review", "finish_status": "partial"}, "active"),
        ({"status": "pending_review", "finish_status": "blocked"}, "blocked"),
        ({"status": "waiting_input"}, "blocked"),
        ({"completion_type": "clarification_needed"}, "blocked"),
        ({"status": "budget_limited"}, "budget_limited"),
        ({"status": "usage_limited"}, "usage_limited"),
        ({"status": "rate_limited"}, "usage_limited"),
        ({"status": "provider_recoverable_error"}, "usage_limited"),
        ({"status": "cancelled"}, "paused"),
        ({"status": "interrupted"}, "paused"),
        ({"status": "provider_error"}, "blocked"),
        ({"status": "llm_empty_response_error"}, "blocked"),
        ({"status": "error"}, "blocked"),
        ({"status": "iterations_exceeded"}, "active"),
    ],
)
def test_result_mapping_is_exhaustive(result: dict[str, str], expected: str) -> None:
    assert goal_status_from_run_result(result) == expected


def test_unknown_runtime_failure_fails_closed() -> None:
    assert goal_status_from_run_result({"status": "mystery_failure"}) == "blocked"
