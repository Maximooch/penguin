"""A background process that finishes after its session closed is resolved.

Covers SM-88: completion events for a session that was no longer open were
ignored before they were recorded, so the process stayed "unresolved":
``delete_session`` kept refusing, and in isolated mode the root's runtime
stayed allocated until the session was loaded and closed again.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from test_acp_isolation import setup
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent


@pytest.mark.asyncio
async def test_a_process_finishing_after_close_is_resolved(tmp_path) -> None:
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "sessions"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    agent.on_connect(conn)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent._processes.update(
            {"session_id": sid, "process_id": "p", "process_status": "running"},
            completed=False,
        )
        await agent.close_session(sid)
        sent = conn.session_update.call_count

        await agent._processes.update(
            {
                "session_id": sid,
                "process_id": "p",
                "process_status": "exited",
                "returncode": 0,
            },
            completed=True,
        )

        assert agent._processes.states[(sid, "p")]["completed"] is True
        assert conn.session_update.call_count == sent
        await agent.delete_session(sid)
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_an_isolated_runtime_is_released_when_its_last_process_ends(
    tmp_path,
) -> None:
    router, _, _ = await setup(tmp_path)
    router.limit = 1
    running = {"session_id": "", "process_id": "p", "process_status": "running"}
    try:
        sid = (await router.new_session(str(tmp_path))).session_id
        runtime = router.roots[sid]
        with runtime.services.activate():
            await runtime.agent._processes.update(
                {**running, "session_id": sid}, completed=False
            )
        await router.close_session(sid)
        assert router.roots[sid] is runtime  # kept for its running process

        with runtime.services.activate():
            await runtime.agent._processes.update(
                {**running, "session_id": sid, "process_status": "exited"},
                completed=True,
            )
        for _ in range(100):
            if sid not in router.roots:
                break
            await asyncio.sleep(0.01)

        assert sid not in router.roots
        assert runtime.agent._closed
        await router.new_session(str(tmp_path))  # the limit is free again
    finally:
        await router.aclose()
