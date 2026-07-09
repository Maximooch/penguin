from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime.session_goal_runtime import (
    GoalRunConflictError,
    GoalRunStateError,
    run_session_goal,
)
from penguin.system.state import Session
from penguin.web.services.session_view import get_session_goal, set_session_goal


class _Manager:
    def __init__(self, session: Session) -> None:
        self.sessions = {session.id: (session, False)}
        self.session_index = {session.id: {}}
        self.current_session = session

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        return item[0] if item else None

    def mark_session_modified(self, session_id: str) -> None:
        return None

    def save_session(self, session: Session) -> bool:
        self.sessions[session.id] = (session, False)
        return True


class _Core:
    def __init__(self, session: Session, result: dict[str, Any]) -> None:
        manager = _Manager(session)
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
        self._opencode_active_requests: dict[str, int] = {}
        self._goal_run_locks: dict[str, Any] = {}
        self._emit_opencode_session_status = AsyncMock()
        self._ensure_opencode_session_status_heartbeat = lambda session_id: None
        self._cancel_opencode_session_status_heartbeat = lambda session_id: None
        self.event_bus = SimpleNamespace(emit=AsyncMock())
        self.run_mode_result = result
        self.run_mode = None


class _RunMode:
    def __init__(self, core: _Core) -> None:
        self.core = core
        core.run_mode = self
        self.start = AsyncMock(return_value=core.run_mode_result)


def _session(tmp_path: Path, status: str = "active") -> tuple[Session, _Core]:
    session = Session(id="session_goal")
    session.metadata["directory"] = str(tmp_path)
    core = _Core(
        session,
        {
            "status": "pending_review",
            "finish_status": "done",
            "message": "done",
            "iterations": 2,
            "execution_time": 1.25,
        },
    )
    set_session_goal(core, session.id, objective="Ship /goal", status=status)
    return session, core


@pytest.mark.asyncio
async def test_run_session_goal_runs_once_and_marks_complete(tmp_path: Path) -> None:
    session, core = _session(tmp_path)

    result = await run_session_goal(
        core,
        session.id,
        run_mode_factory=_RunMode,
        max_iterations=3,
    )

    assert result["status"] == "complete"
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "complete"
    assert goal["active_run_id"] is None
    assert goal["last_run_id"]
    assert core.run_mode is not None
    call = core.run_mode.start.await_args
    assert call.kwargs["context"]["run_kind"] == "session_goal"
    assert call.kwargs["context"]["max_iterations"] == 3
    core._emit_opencode_session_status.assert_any_await(session.id, "busy")
    core._emit_opencode_session_status.assert_any_await(session.id, "idle")


@pytest.mark.asyncio
async def test_run_session_goal_maps_partial_and_blocked(tmp_path: Path) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result["finish_status"] = "partial"

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)
    assert result["status"] == "active"

    set_session_goal(core, session.id, status="active")
    core.run_mode_result = {
        "status": "waiting_input",
        "completion_type": "clarification_needed",
        "message": "Need input",
    }
    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_run_session_goal_rejects_invalid_or_busy_state(tmp_path: Path) -> None:
    session, core = _session(tmp_path, status="paused")
    with pytest.raises(GoalRunStateError):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    current = get_session_goal(core, session.id)
    assert current is not None
    current["status"] = "active"
    current["revision"] += 1
    core.conversation_manager.session_manager.current_session.metadata[
        "_penguin_goal_v1"
    ] = current
    core._opencode_active_requests[session.id] = 1
    with pytest.raises(GoalRunConflictError):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)
