"""Per-session and per-child ACP bookkeeping is dropped when it is no longer used.

Covers SM-103: child records, replay parents, approval locks and task sets,
question task sets and process states were added per session or child and
never removed, so a long editor connection grew without bound and stale
child ids kept being routed as children.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.schema import AllowedOutcome, RequestPermissionResponse
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.children import Child
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager


async def _agent(tmp_path) -> tuple[PenguinACPAgent, AsyncMock]:
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    return agent, conn


@pytest.mark.asyncio
async def test_a_finished_dialog_leaves_no_task_set(tmp_path) -> None:
    manager = get_approval_manager()
    manager.reset()
    agent, _conn = await _agent(tmp_path)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        request = manager.create_request(
            "tool", "filesystem.write", str(tmp_path / "f"), "t", session_id=sid
        )
        for _ in range(200):
            if manager.get_request(request.id).status.value != "pending":
                break
            await asyncio.sleep(0.005)
        await asyncio.sleep(0.01)

        assert sid not in agent._approval_tasks_by_session
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_closing_and_deleting_a_session_forget_its_bookkeeping(tmp_path) -> None:
    agent, _conn = await _agent(tmp_path)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        child_id = "child-1"
        agent._children.children[child_id] = Child(
            parent=sid, root=sid, agent="worker", cwd=tmp_path, active=False
        )
        agent._children.replay_parents[child_id] = sid
        agent._approval_state_locks[child_id] = asyncio.Lock()
        agent._questions.tasks[sid] = set()
        await agent._processes.update(
            {"session_id": sid, "process_id": "p", "process_status": "exited"},
            completed=True,
        )

        await agent.close_session(sid)

        assert child_id not in agent._children.children
        assert child_id not in agent._children.replay_parents
        assert child_id not in agent._approval_state_locks
        assert sid not in agent._questions.tasks

        await agent.delete_session(sid)

        assert not [key for key in agent._processes.states if key[0] == sid]
    finally:
        agent.close()
