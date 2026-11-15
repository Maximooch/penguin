"""Every pending ``vcs.branch.updated`` emit is kept until it finishes.

Covers SM-75 (VCS watcher slot): each emit task was stored in one module slot,
so a second scope's emit dropped the only strong reference to the first one.
asyncio holds tasks weakly, so the garbage collector could destroy a pending
emit and the client never saw that branch change.
"""

from __future__ import annotations

import asyncio
import gc
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.web.services import system_status


@pytest.mark.asyncio
async def test_pending_branch_emits_survive_garbage_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(system_status, "_LAST_BRANCH_KEYS", {})
    destroyed: list[str] = []

    async def emit(_event: str, payload: dict[str, Any]) -> None:
        # Nothing else holds this future, so only the task slot keeps it alive.
        try:
            await asyncio.get_running_loop().create_future()
        except GeneratorExit:
            destroyed.append(payload["properties"]["sessionID"])
            raise

    core = SimpleNamespace(event_bus=SimpleNamespace(emit=emit))
    snapshot = {
        "vcs": "git",
        "worktree": "/repo",
        "branch": "main",
        "head": "abc",
        "detached": False,
    }
    before = asyncio.all_tasks()
    system_status._emit_vcs_update(core, snapshot, "/repo", "session-a")
    system_status._emit_vcs_update(core, snapshot, "/repo", "session-b")
    await asyncio.sleep(0)

    gc.collect()

    try:
        assert destroyed == []
    finally:
        for task in asyncio.all_tasks() - before:
            task.cancel()
        await asyncio.sleep(0)
