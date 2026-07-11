"""Tests for durable session-goal persistence and compare-and-set behavior."""

from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from penguin.core_runtime.session_goal_store import (
    clear_session_goal,
    load_session_goal,
    save_session_goal,
    set_session_goal,
)
from penguin.core_runtime.session_goals import (
    GoalConflictError,
    GoalNotFoundError,
    GoalPersistenceError,
)
from penguin.system.state import Session

if TYPE_CHECKING:
    from pathlib import Path


class _Manager:
    def __init__(self, session: Session) -> None:
        self.sessions = {session.id: (session, False)}
        self.session_index = {session.id: {}}
        self.current_session = session
        self.save_result = True
        self.saved: list[str] = []
        self.marked: list[str] = []

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        return item[0] if item else None

    def mark_session_modified(self, session_id: str) -> None:
        self.marked.append(session_id)

    def save_session(self, session: Session) -> bool:
        self.saved.append(session.id)
        if self.save_result:
            self.sessions[session.id] = (session, False)
        return self.save_result


def _core(tmp_path: Path) -> tuple[Any, Session, _Manager]:
    session = Session(id="session_goal_store")
    session.metadata.update({"directory": str(tmp_path), "unrelated": {"keep": True}})
    manager = _Manager(session)
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
        )
    )
    return core, session, manager


def test_set_goal_preserves_unrelated_metadata_and_checks_save(tmp_path: Path) -> None:
    core, session, manager = _core(tmp_path)

    goal = set_session_goal(core, session.id, objective="Ship it")

    assert goal["objective"] == "Ship it"
    assert session.metadata["unrelated"] == {"keep": True}
    assert manager.marked == [session.id]
    assert manager.saved == [session.id]


def test_failed_save_restores_previous_in_memory_goal(tmp_path: Path) -> None:
    core, session, manager = _core(tmp_path)
    original = set_session_goal(core, session.id, objective="Original")
    before = deepcopy(session.metadata)
    manager.save_result = False

    with pytest.raises(GoalPersistenceError, match="save"):
        set_session_goal(
            core,
            session.id,
            objective="Replacement",
            replace=True,
        )

    assert session.metadata == before
    assert load_session_goal(core, session.id, require_goal=True) == original


def test_missing_goal_controls_are_not_treated_as_invalid_create(
    tmp_path: Path,
) -> None:
    core, session, _manager = _core(tmp_path)

    with pytest.raises(GoalNotFoundError, match="goal"):
        set_session_goal(core, session.id, status="paused")
    with pytest.raises(GoalNotFoundError, match="goal"):
        clear_session_goal(core, session.id)


def test_pause_is_allowed_during_run_and_preserves_run_fence(tmp_path: Path) -> None:
    core, session, _manager = _core(tmp_path)
    goal = set_session_goal(core, session.id, objective="Ship it")
    claimed = dict(goal)
    claimed.update(
        {
            "active_run_id": "run_1",
            "active_run_owner": "process_1",
            "active_run_started_at": "2026-07-09T00:00:00+00:00",
            "revision": goal["revision"] + 1,
        }
    )
    assert save_session_goal(
        core,
        session.id,
        claimed,
        expected_goal_id=goal["id"],
        expected_revision=goal["revision"],
    )

    paused = set_session_goal(core, session.id, status="paused")

    assert paused["status"] == "paused"
    assert paused["active_run_id"] == "run_1"
    with pytest.raises(GoalConflictError, match="running"):
        clear_session_goal(core, session.id)


def test_compare_and_set_rejects_stale_revision_without_saving(tmp_path: Path) -> None:
    core, session, manager = _core(tmp_path)
    goal = set_session_goal(core, session.id, objective="Ship it")
    saves_before = len(manager.saved)
    stale = dict(goal)
    stale["status"] = "paused"
    stale["revision"] += 1

    changed = save_session_goal(
        core,
        session.id,
        stale,
        expected_goal_id=goal["id"],
        expected_revision=goal["revision"] + 99,
    )

    assert changed is False
    assert len(manager.saved) == saves_before
    assert load_session_goal(core, session.id, require_goal=True)["status"] == "active"
