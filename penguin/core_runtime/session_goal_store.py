"""Durable session-goal persistence with compare-and-set semantics."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from dataclasses import dataclass
from typing import Any

from penguin.core_runtime import session_lookup
from penguin.core_runtime.session_goals import (
    GOAL_METADATA_KEY,
    UNFINISHED_GOAL_STATUSES,
    GoalConflictError,
    GoalNotFoundError,
    GoalPersistenceError,
    GoalValidationError,
    create_goal,
    normalize_goal,
    transition_goal_status,
)

__all__ = [
    "SessionGoalRecord",
    "clear_session_goal",
    "get_session_goal_lock",
    "load_session_goal",
    "load_session_goal_record",
    "save_session_goal",
    "set_session_goal",
]


@dataclass(frozen=True)
class SessionGoalRecord:
    """A validated goal with its persisted session and owning manager."""

    session: Any
    manager: Any
    goal: dict[str, Any] | None


def get_session_goal_lock(core: Any, session_id: str) -> asyncio.Lock:
    """Return the in-process mutation lock for one session goal."""

    locks = getattr(core, "_goal_run_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        core._goal_run_locks = locks
    lock = locks.get(session_id)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        locks[session_id] = lock
    return lock


def _load_without_switching(manager: Any, session_id: str) -> Any | None:
    previous = getattr(manager, "current_session", None)
    try:
        loader = getattr(manager, "load_session", None)
        session = loader(session_id) if callable(loader) else None
        if session is None or str(getattr(session, "id", "")) != session_id:
            return None
        return session
    finally:
        if hasattr(manager, "current_session"):
            manager.current_session = previous


def _session_store(core: Any, session_id: str) -> tuple[Any, Any]:
    session, manager = session_lookup.find_session_store(
        core,
        session_id,
        load_session=_load_without_switching,
    )
    if session is None or manager is None:
        raise GoalNotFoundError(f"Session {session_id} not found")
    return session, manager


def _metadata(session: Any) -> dict[str, Any]:
    metadata = getattr(session, "metadata", None)
    if isinstance(metadata, dict):
        return metadata
    metadata = {}
    session.metadata = metadata
    return metadata


def _goal_from_metadata(
    metadata: dict[str, Any],
    *,
    require_goal: bool,
) -> dict[str, Any] | None:
    if GOAL_METADATA_KEY not in metadata:
        if require_goal:
            raise GoalNotFoundError("Session goal not found")
        return None
    goal = normalize_goal(metadata.get(GOAL_METADATA_KEY))
    if goal is None:
        raise GoalPersistenceError("Stored session goal is corrupt")
    return goal


def load_session_goal(
    core: Any,
    session_id: str,
    *,
    require_goal: bool = False,
) -> dict[str, Any] | None:
    """Load and validate the goal belonging to ``session_id``."""

    session, _manager = _session_store(core, session_id)
    return _goal_from_metadata(_metadata(session), require_goal=require_goal)


def load_session_goal_record(
    core: Any,
    session_id: str,
    *,
    require_goal: bool = False,
    allow_corrupt_goal: bool = False,
) -> SessionGoalRecord:
    """Load a goal together with its owning persisted session and manager."""

    session, manager = _session_store(core, session_id)
    try:
        goal = _goal_from_metadata(_metadata(session), require_goal=require_goal)
    except GoalPersistenceError:
        if not allow_corrupt_goal:
            raise
        goal = None
    return SessionGoalRecord(session=session, manager=manager, goal=goal)


def _persist_metadata_goal(
    session: Any,
    manager: Any,
    goal: dict[str, Any] | None,
) -> None:
    metadata = _metadata(session)
    previous_present = GOAL_METADATA_KEY in metadata
    previous = deepcopy(metadata.get(GOAL_METADATA_KEY))
    if goal is None:
        metadata.pop(GOAL_METADATA_KEY, None)
    else:
        metadata[GOAL_METADATA_KEY] = deepcopy(goal)

    try:
        manager.mark_session_modified(session.id)
        saved = manager.save_session(session)
        if saved is False:
            raise GoalPersistenceError(f"Failed to save session goal for {session.id}")
    except Exception as exc:
        if previous_present:
            metadata[GOAL_METADATA_KEY] = previous
        else:
            metadata.pop(GOAL_METADATA_KEY, None)
        if isinstance(exc, GoalPersistenceError):
            raise
        raise GoalPersistenceError(
            f"Failed to save session goal for {session.id}: {exc}"
        ) from exc


def save_session_goal(
    core: Any,
    session_id: str,
    goal: dict[str, Any],
    *,
    expected_goal_id: str | None = None,
    expected_revision: int | None = None,
    expected_run_id: str | None = None,
) -> bool:
    """Persist ``goal`` when all supplied compare-and-set fields still match."""

    normalized = normalize_goal(goal)
    if normalized is None:
        raise GoalValidationError("goal is invalid")
    session, manager = _session_store(core, session_id)
    current = _goal_from_metadata(_metadata(session), require_goal=True)
    assert current is not None

    if expected_goal_id is not None and current["id"] != expected_goal_id:
        return False
    if expected_revision is not None and current["revision"] != expected_revision:
        return False
    if expected_run_id is not None and current.get("active_run_id") != expected_run_id:
        return False

    _persist_metadata_goal(session, manager, normalized)
    return True


def set_session_goal(
    core: Any,
    session_id: str,
    *,
    objective: str | None = None,
    status: str | None = None,
    replace: bool = False,
    token_budget: int | None = None,
    metadata: dict[str, Any] | None = None,
    persist: bool = True,
) -> dict[str, Any]:
    """Create, replace, pause, or resume a session goal.

    ``persist=False`` stages the validated goal on the session so a caller can
    commit it atomically with other session metadata in one checked save.
    """

    session, manager = _session_store(core, session_id)
    session_metadata = _metadata(session)
    current = _goal_from_metadata(session_metadata, require_goal=False)

    if objective is not None and status is not None:
        raise GoalValidationError("objective and status cannot be updated together")

    if objective is not None:
        if current is not None and current.get("active_run_id"):
            raise GoalConflictError("Goal is currently running")
        if (
            current is not None
            and current["status"] in UNFINISHED_GOAL_STATUSES
            and not replace
        ):
            raise GoalConflictError("unfinished goal requires replace=true")
        next_revision = current["revision"] + 1 if current is not None else 1
        goal = create_goal(
            objective,
            revision=next_revision,
            token_budget=token_budget,
            metadata=metadata,
        )
    elif status is not None:
        if current is None:
            raise GoalNotFoundError("Session goal not found")
        normalized_status = (
            status.strip().lower() if isinstance(status, str) else status
        )
        if current.get("active_run_id") and normalized_status not in {
            current["status"],
            "paused",
        }:
            raise GoalConflictError("Goal is currently running")
        goal = transition_goal_status(current, status, actor="user")
    else:
        raise GoalValidationError("objective or status is required")

    if persist:
        _persist_metadata_goal(session, manager, goal)
    else:
        session_metadata[GOAL_METADATA_KEY] = deepcopy(goal)
    return goal


def clear_session_goal(
    core: Any,
    session_id: str,
    *,
    persist: bool = True,
) -> bool:
    """Remove a non-running goal, including explicitly corrupt stored state."""

    session, manager = _session_store(core, session_id)
    metadata = _metadata(session)
    if GOAL_METADATA_KEY not in metadata:
        raise GoalNotFoundError("Session goal not found")
    current = normalize_goal(metadata.get(GOAL_METADATA_KEY))
    if current is not None and current.get("active_run_id"):
        raise GoalConflictError("Goal is currently running")
    if persist:
        _persist_metadata_goal(session, manager, None)
    else:
        metadata.pop(GOAL_METADATA_KEY, None)
    return True
