"""Bounded execution bridge for persisted session goals."""

from __future__ import annotations

import asyncio
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable
from uuid import uuid4

from penguin.core_runtime import process_lifecycle
from penguin.core_runtime.session_goals import normalize_goal
from penguin.run_mode import RunMode
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.web.services.session_events import emit_session_goal_event
from penguin.web.services.session_view import GOAL_KEY, get_session_goal, get_session_info
from penguin.core_runtime import session_lookup


class GoalRunError(RuntimeError):
    """Base exception for goal execution failures."""


class GoalRunNotFoundError(GoalRunError):
    """Raised when the target session or goal does not exist."""


class GoalRunStateError(GoalRunError):
    """Raised when a goal is not runnable in its current state."""


class GoalRunConflictError(GoalRunError):
    """Raised when the session already has active work."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _persist_goal(core: Any, session_id: str, goal: dict[str, Any]) -> None:
    session, manager = session_lookup.find_session_store(core, session_id)
    if session is None or manager is None:
        raise GoalRunNotFoundError(f"Session {session_id} not found")
    metadata = getattr(session, "metadata", None)
    if not isinstance(metadata, dict):
        metadata = {}
        session.metadata = metadata
    metadata[GOAL_KEY] = deepcopy(goal)
    manager.mark_session_modified(session.id)
    manager.save_session(session)


def _result_status(result: dict[str, Any]) -> str:
    if result.get("completion_type") == "clarification_needed":
        return "blocked"
    if result.get("status") == "waiting_input":
        return "blocked"
    if result.get("status") in {"usage_limited", "rate_limited"}:
        return "usage_limited"
    if result.get("status") == "budget_limited":
        return "budget_limited"
    if result.get("status") in {"aborted", "cancelled"}:
        return "paused"
    finish_status = result.get("finish_status")
    if finish_status == "done":
        return "complete"
    if finish_status == "blocked":
        return "blocked"
    if result.get("status") == "error":
        return "blocked"
    return "active"


def _goal_prompt(goal: dict[str, Any]) -> str:
    return (
        "You are executing the active session goal.\n\n"
        f"Goal: {goal['objective']}\n"
        f"Status: {goal['status']}\n\n"
        "Work toward this goal using the available tools. Make concrete progress.\n"
        "When fully satisfied, call finish_task with status done.\n"
        "If blocked, call finish_task with status blocked or use the existing "
        "clarification flow.\n"
        "Do not loop indefinitely. Stop after meaningful bounded progress."
    )


async def run_session_goal(
    core: Any,
    session_id: str,
    *,
    max_iterations: int | None = None,
    run_mode_factory: Callable[..., Any] = RunMode,
) -> dict[str, Any]:
    """Run one bounded autonomous step for a persisted active goal."""
    goal = get_session_goal(core, session_id)
    if goal is None:
        if get_session_info(core, session_id) is None:
            raise GoalRunNotFoundError(f"Session {session_id} not found")
        raise GoalRunNotFoundError("Session goal not found")
    if goal["status"] != "active":
        raise GoalRunStateError(f"Goal status {goal['status']} is not runnable")

    locks = getattr(core, "_goal_run_locks", None)
    if not isinstance(locks, dict):
        locks = {}
        core._goal_run_locks = locks
    lock = locks.setdefault(session_id, asyncio.Lock())

    async with lock:
        active_requests = getattr(core, "_opencode_active_requests", {})
        if isinstance(active_requests, dict) and active_requests.get(session_id, 0) > 0:
            raise GoalRunConflictError("Session already has active work")

        current = get_session_goal(core, session_id)
        if current is None or current["id"] != goal["id"]:
            raise GoalRunConflictError("Goal changed before execution started")
        if current["status"] != "active" or current.get("active_run_id"):
            raise GoalRunConflictError("Goal is already running or no longer active")

        run_id = f"goalrun_{uuid4().hex}"
        claimed_revision = current["revision"] + 1
        current["revision"] = claimed_revision
        current["active_run_id"] = run_id
        current["last_run_id"] = run_id
        current["updated_at"] = _timestamp()
        _persist_goal(core, session_id, current)
        await emit_session_goal_event(core, session_id, current)

        tracked = await process_lifecycle.register_opencode_process_request(
            core, session_id, asyncio.current_task()
        )
        info = get_session_info(core, session_id) or {}
        directory = info.get("directory")
        if not isinstance(directory, str) or not Path(directory).is_dir():
            directory = None
        context = {
            "run_kind": "session_goal",
            "session_id": session_id,
            "conversation_id": session_id,
            "goal_id": current["id"],
            "goal_revision": claimed_revision,
            "goal_objective": current["objective"],
            "max_iterations": max_iterations,
            "metadata": {"goal_id": current["id"], "run_id": run_id},
        }
        execution_context = ExecutionContext(
            session_id=session_id,
            conversation_id=session_id,
            directory=directory,
            project_root=directory,
            workspace_root=directory,
            request_id=run_id,
        )

        result: dict[str, Any]
        try:
            run_mode = run_mode_factory(core)
            with execution_context_scope(execution_context):
                result = await run_mode.start(
                    name=f"Session goal: {current['objective']}",
                    description=_goal_prompt(current),
                    context=context,
                )
        except asyncio.CancelledError:
            result = {"status": "aborted", "message": "Goal run aborted"}
        except Exception as exc:
            result = {"status": "error", "message": str(exc)}
        finally:
            await process_lifecycle.finalize_opencode_process_request(
                core,
                session_id,
                asyncio.current_task(),
                request_tracked=tracked,
            )

        latest = get_session_goal(core, session_id)
        if latest is None:
            return {"goal": None, "status": "cleared", "result": result}
        if latest["id"] != current["id"] or latest.get("active_run_id") != run_id:
            return {"goal": latest, "status": latest["status"], "result": result}

        latest["status"] = _result_status(result)
        latest["active_run_id"] = None
        latest["last_result"] = deepcopy(result)
        latest["time_used_seconds"] += max(
            0.0, float(result.get("execution_time", 0) or 0)
        )
        latest["revision"] += 1
        latest["updated_at"] = _timestamp()
        _persist_goal(core, session_id, latest)
        await emit_session_goal_event(core, session_id, latest)
        return {"goal": latest, "status": latest["status"], "result": result}
