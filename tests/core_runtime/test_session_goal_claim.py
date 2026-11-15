"""A goal claim means the run holds the session, and is not taken from a live owner.

Covers SM-40: the session gate was checked, the claim recorded, and only then
the gate acquired in a separate task, so another request could reserve the
session while the goal record said the goal was running; and any claim made
by a different owner counted as orphaned, even one held by another live
Penguin process sharing the workspace.
"""

from __future__ import annotations

import asyncio
import os
from typing import TYPE_CHECKING, Any

import pytest

from penguin.core_runtime import process_lifecycle, session_goal_runtime
from penguin.core_runtime.session_goal_runtime import (
    GoalRunConflictError,
    goal_run_owner_id,
    run_session_goal,
)
from penguin.core_runtime.session_goal_store import save_session_goal
from penguin.web.services.session_view import get_session_goal
from tests.core_runtime.test_session_goal_runtime import _RunMode, _session

if TYPE_CHECKING:
    from pathlib import Path


@pytest.mark.asyncio
async def test_no_request_holds_the_session_while_the_goal_is_claimed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    session, core = _session(tmp_path)
    gate = process_lifecycle.get_session_request_gate(core, session.id)
    seen_by_competitor: list[Any] = []
    competitors: list[asyncio.Task] = []
    original_save = session_goal_runtime.save_session_goal

    async def competing_request() -> None:
        async with gate:
            goal = get_session_goal(core, session.id)
            seen_by_competitor.append(goal["active_run_id"] if goal else None)

    def save_and_compete(*args: Any, **kwargs: Any) -> bool:
        saved = original_save(*args, **kwargs)
        goal = args[2]
        if saved and goal.get("active_run_id") and not competitors:
            # A request arrives just as the claim is written.
            competitors.append(
                asyncio.get_running_loop().create_task(competing_request())
            )
        return saved

    monkeypatch.setattr(session_goal_runtime, "save_session_goal", save_and_compete)

    await run_session_goal(
        core, session.id, timeout_seconds=5, run_mode_factory=_RunMode
    )
    await asyncio.wait_for(competitors[0], 2)

    assert seen_by_competitor == [None]


@pytest.mark.asyncio
async def test_a_claim_held_by_a_live_process_is_not_recovered(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    goal = get_session_goal(core, session.id)
    assert goal is not None
    claimed = dict(goal)
    claimed.update(
        {
            "active_run_id": "run_in_other_process",
            "active_run_owner": goal_run_owner_id(os.getppid()),
            "active_run_started_at": "2026-11-15T00:00:00+00:00",
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

    with pytest.raises(GoalRunConflictError, match="another Penguin process"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    still = get_session_goal(core, session.id)
    assert still is not None
    assert still["status"] == "active"
    assert still["active_run_id"] == "run_in_other_process"
