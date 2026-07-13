"""Session-scoped goal model, validation, and transition policy."""

from __future__ import annotations

import json
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from typing import Any, Literal
from uuid import uuid4

GoalActor = Literal["user", "runtime"]

GOAL_STATUSES = frozenset(
    {
        "active",
        "paused",
        "blocked",
        "usage_limited",
        "budget_limited",
        "complete",
    }
)
GOAL_METADATA_KEY = "_penguin_goal_v1"
UNFINISHED_GOAL_STATUSES = GOAL_STATUSES - {"complete"}
MAX_GOAL_OBJECTIVE_CHARS = 8_000
MAX_GOAL_METADATA_BYTES = 32_768

_USER_TRANSITIONS = {
    "active": frozenset({"paused"}),
    "paused": frozenset({"active"}),
    "blocked": frozenset({"active"}),
    "usage_limited": frozenset({"active"}),
    "budget_limited": frozenset({"active"}),
    "complete": frozenset(),
}
_RUNTIME_TRANSITIONS = {
    "active": GOAL_STATUSES,
    "paused": frozenset({"paused"}),
    "blocked": frozenset({"blocked"}),
    "usage_limited": frozenset({"usage_limited"}),
    "budget_limited": frozenset({"budget_limited"}),
    "complete": frozenset({"complete"}),
}

__all__ = [
    "GOAL_METADATA_KEY",
    "GOAL_STATUSES",
    "MAX_GOAL_METADATA_BYTES",
    "MAX_GOAL_OBJECTIVE_CHARS",
    "UNFINISHED_GOAL_STATUSES",
    "GoalActor",
    "GoalConflictError",
    "GoalError",
    "GoalNotFoundError",
    "GoalPersistenceError",
    "GoalValidationError",
    "create_goal",
    "goal_status_from_run_result",
    "normalize_goal",
    "transition_goal_status",
    "update_goal_status",
]


class GoalError(ValueError):
    """Base exception for invalid goal operations."""


class GoalValidationError(GoalError):
    """Raised when a goal payload or persisted value is invalid."""


class GoalConflictError(GoalError):
    """Raised when a goal mutation conflicts with its lifecycle state."""


class GoalNotFoundError(GoalError):
    """Raised when a control operation targets a missing session goal."""


class GoalPersistenceError(GoalError):
    """Raised when durable goal state cannot be saved."""


def _timestamp() -> str:
    """Return a UTC ISO-8601 timestamp."""

    return datetime.now(timezone.utc).isoformat()


def _objective(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise GoalValidationError("objective must be a non-empty string")
    normalized = value.strip()
    if len(normalized) > MAX_GOAL_OBJECTIVE_CHARS:
        raise GoalValidationError(
            f"objective must be at most {MAX_GOAL_OBJECTIVE_CHARS} characters"
        )
    return normalized


def _status(value: Any) -> str:
    if not isinstance(value, str):
        raise GoalValidationError("status must be a string")
    normalized = value.strip().lower()
    if normalized not in GOAL_STATUSES:
        allowed = ", ".join(sorted(GOAL_STATUSES))
        raise GoalValidationError(f"status must be one of: {allowed}")
    return normalized


def _strict_int(value: Any, *, field: str, minimum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < minimum:
        raise GoalValidationError(f"{field} must be an integer >= {minimum}")
    return value


def _non_negative_float(value: Any, *, field: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise GoalValidationError(f"{field} must be a non-negative number")
    normalized = float(value)
    if not isfinite(normalized) or normalized < 0:
        raise GoalValidationError(f"{field} must be a finite non-negative number")
    return normalized


def _optional_non_empty_string(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GoalValidationError(f"{field} must be a non-empty string or null")
    return value.strip()


def _token_budget(value: Any) -> int | None:
    if value is None:
        return None
    return _strict_int(value, field="token_budget", minimum=1)


def _goal_metadata(value: Any) -> dict[str, Any]:
    if value is None:
        return {}
    if not isinstance(value, dict):
        raise GoalValidationError("metadata must be an object")
    try:
        encoded = json.dumps(
            value,
            allow_nan=False,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    except (TypeError, ValueError, RecursionError) as exc:
        raise GoalValidationError("metadata must be JSON-serializable") from exc
    if len(encoded) > MAX_GOAL_METADATA_BYTES:
        raise GoalValidationError(
            f"metadata must be at most {MAX_GOAL_METADATA_BYTES} bytes"
        )
    return deepcopy(value)


def normalize_goal(value: Any) -> dict[str, Any] | None:
    """Return a validated copy of persisted goal state.

    Corrupt persisted state fails closed and returns ``None``. Callers that need
    to distinguish corruption from absence should inspect the raw metadata key.
    """

    if not isinstance(value, dict):
        return None

    goal = deepcopy(value)
    try:
        goal["objective"] = _objective(goal.get("objective"))
        goal["status"] = _status(goal.get("status"))
        goal["revision"] = _strict_int(
            goal.get("revision", 1), field="revision", minimum=1
        )
        goal["token_budget"] = _token_budget(goal.get("token_budget"))
        goal["tokens_used"] = _strict_int(
            goal.get("tokens_used", 0), field="tokens_used", minimum=0
        )
        goal["time_used_seconds"] = _non_negative_float(
            goal.get("time_used_seconds", 0), field="time_used_seconds"
        )
        goal["active_run_id"] = _optional_non_empty_string(
            goal.get("active_run_id"), field="active_run_id"
        )
        goal["active_run_owner"] = _optional_non_empty_string(
            goal.get("active_run_owner"), field="active_run_owner"
        )
        goal["active_run_started_at"] = _optional_non_empty_string(
            goal.get("active_run_started_at"), field="active_run_started_at"
        )
        goal["last_run_id"] = _optional_non_empty_string(
            goal.get("last_run_id"), field="last_run_id"
        )
    except GoalValidationError:
        return None

    goal_id = goal.get("id")
    if not isinstance(goal_id, str) or not goal_id.strip():
        return None
    goal["id"] = goal_id.strip()

    for field in ("created_at", "updated_at"):
        timestamp = goal.get(field)
        if not isinstance(timestamp, str) or not timestamp.strip():
            return None
        goal[field] = timestamp.strip()

    goal["last_result"] = deepcopy(goal.get("last_result"))
    try:
        goal["metadata"] = _goal_metadata(goal.get("metadata"))
    except GoalValidationError:
        return None
    return goal


def create_goal(
    objective: Any,
    *,
    revision: int = 1,
    status: Any = "active",
    token_budget: int | None = None,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Create a validated, JSON-serializable session goal."""

    normalized_status = _status(status)
    if normalized_status != "active":
        raise GoalValidationError("new goals must start with status active")
    normalized_revision = _strict_int(revision, field="revision", minimum=1)
    normalized_budget = _token_budget(token_budget)
    now = _timestamp()
    return {
        "id": f"goal_{uuid4().hex}",
        "objective": _objective(objective),
        "status": normalized_status,
        "revision": normalized_revision,
        "token_budget": normalized_budget,
        "tokens_used": 0,
        "time_used_seconds": 0.0,
        "created_at": now,
        "updated_at": now,
        "active_run_id": None,
        "active_run_owner": None,
        "active_run_started_at": None,
        "last_run_id": None,
        "last_result": None,
        "metadata": _goal_metadata(metadata),
    }


def transition_goal_status(
    goal: dict[str, Any],
    status: Any,
    *,
    actor: GoalActor,
) -> dict[str, Any]:
    """Return goal state after an allowed user or runtime transition."""

    normalized = normalize_goal(goal)
    if normalized is None:
        raise GoalValidationError("stored goal is invalid")
    next_status = _status(status)
    current_status = normalized["status"]
    if next_status == current_status:
        return normalized
    if current_status == "complete":
        raise GoalConflictError("complete is a terminal goal status")

    transitions = _USER_TRANSITIONS if actor == "user" else _RUNTIME_TRANSITIONS
    if next_status not in transitions[current_status]:
        raise GoalConflictError(
            f"{actor} cannot transition goal from {current_status} to {next_status}"
        )

    normalized["status"] = next_status
    normalized["revision"] += 1
    normalized["updated_at"] = _timestamp()
    return normalized


def update_goal_status(goal: dict[str, Any], status: Any) -> dict[str, Any]:
    """Compatibility wrapper for a user-controlled status transition."""

    return transition_goal_status(goal, status, actor="user")


def goal_status_from_run_result(result: dict[str, Any]) -> str:
    """Map one typed RunMode result to a durable goal status.

    Unknown non-empty statuses fail closed to ``blocked``. Only explicitly
    recognized partial-progress outcomes remain active.
    """

    finish_status = result.get("finish_status")
    if finish_status == "done":
        return "complete"
    if finish_status == "blocked":
        return "blocked"
    if finish_status == "partial":
        return "active"

    completion_type = result.get("completion_type")
    status = result.get("status")
    if completion_type == "clarification_needed" or status == "waiting_input":
        return "blocked"
    if status == "budget_limited":
        return "budget_limited"
    if status in {
        "usage_limited",
        "rate_limited",
        "provider_recoverable_error",
    }:
        return "usage_limited"
    if status in {"aborted", "cancelled", "interrupted", "stopped", "timeout"}:
        return "paused"
    if status in {
        "error",
        "provider_error",
        "llm_empty_response_error",
        "llm_empty",
    }:
        return "blocked"
    if status in {
        None,
        "",
        "active",
        "pending",
        "pending_review",
        "partial",
        "iterations_exceeded",
        "max_iterations",
        "implicit_completion",
    }:
        return "active"
    return "blocked"
