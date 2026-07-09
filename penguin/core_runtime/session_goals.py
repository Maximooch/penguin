"""Session-scoped goal model and transition policy."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4

GOAL_STATUSES = {
    "active",
    "paused",
    "blocked",
    "usage_limited",
    "budget_limited",
    "complete",
}
UNFINISHED_GOAL_STATUSES = GOAL_STATUSES - {"complete"}


class GoalError(ValueError):
    """Base exception for invalid goal operations."""


class GoalValidationError(GoalError):
    """Raised when a goal payload is invalid."""


class GoalConflictError(GoalError):
    """Raised when an unfinished goal would be replaced implicitly."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _objective(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoalValidationError("objective must be a non-empty string")
    return value.strip()


def _status(value: Any) -> str:
    if not isinstance(value, str):
        raise GoalValidationError("status must be a string")
    normalized = value.strip().lower()
    if normalized not in GOAL_STATUSES:
        allowed = ", ".join(sorted(GOAL_STATUSES))
        raise GoalValidationError(f"status must be one of: {allowed}")
    return normalized


def normalize_goal(value: Any) -> dict[str, Any] | None:
    """Return a validated copy of persisted goal state."""
    if not isinstance(value, dict):
        return None

    goal = deepcopy(value)
    try:
        goal["objective"] = _objective(goal.get("objective"))
        goal["status"] = _status(goal.get("status"))
    except GoalValidationError:
        return None

    goal_id = goal.get("id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        return None
    goal["id"] = goal_id.strip()
    goal["revision"] = max(1, int(goal.get("revision", 1)))
    goal["tokens_used"] = max(0, int(goal.get("tokens_used", 0)))
    goal["time_used_seconds"] = max(0.0, float(goal.get("time_used_seconds", 0)))
    goal["active_run_id"] = goal.get("active_run_id") or None
    goal["last_run_id"] = goal.get("last_run_id") or None
    goal["last_result"] = goal.get("last_result") or None
    goal["metadata"] = (
        deepcopy(goal["metadata"]) if isinstance(goal.get("metadata"), dict) else {}
    )
    return goal


def create_goal(
    objective: Any,
    *,
    revision: int = 1,
    status: Any = "active",
    token_budget: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create normalized goal state."""
    if token_budget is not None and (
        not isinstance(token_budget, int) or token_budget <= 0
    ):
        raise GoalValidationError("token_budget must be a positive integer or null")

    now = _timestamp()
    return {
        "id": f"goal_{uuid4().hex}",
        "objective": _objective(objective),
        "status": _status(status),
        "revision": max(1, int(revision)),
        "token_budget": token_budget,
        "tokens_used": 0,
        "time_used_seconds": 0.0,
        "created_at": now,
        "updated_at": now,
        "active_run_id": None,
        "last_run_id": None,
        "last_result": None,
        "metadata": deepcopy(metadata) if isinstance(metadata, dict) else {},
    }


def update_goal_status(goal: dict[str, Any], status: Any) -> dict[str, Any]:
    """Return goal state with a validated lifecycle status."""
    normalized = normalize_goal(goal)
    if normalized is None:
        raise GoalValidationError("stored goal is invalid")
    normalized["status"] = _status(status)
    normalized["revision"] += 1
    normalized["updated_at"] = _timestamp()
    return normalized
