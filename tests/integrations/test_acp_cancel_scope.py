"""Cancelling a turn does not deny approvals after that turn has ended.

Covers SM-89: ``session.cancelled`` was reset only when the next prompt
started, so after a cancelled turn every approval or question for the session
from work that outlived the turn was silently denied, while after a normally
finished turn the same request was shown to the user.
"""

from __future__ import annotations

import asyncio
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from acp.schema import AllowedOutcome, RequestPermissionResponse
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager


@pytest.mark.asyncio
async def test_an_approval_after_a_cancelled_turn_reaches_the_user(tmp_path) -> None:
    manager = get_approval_manager()
    manager.reset()
    core = PersistentCore(tmp_path / "store")
    started = asyncio.Event()

    async def process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        started.set()
        await asyncio.Event().wait()
        return {}

    core.process = process
    core.abort_session = AsyncMock()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        turn = asyncio.create_task(agent.prompt(sid, [text_block("slow")]))
        await asyncio.wait_for(started.wait(), 5)
        await agent.cancel(sid)
        assert (await turn).stop_reason == "cancelled"

        request = manager.create_request(
            "background",
            "filesystem.write",
            str(tmp_path / "f"),
            "test",
            session_id=sid,
        )
        for _ in range(200):
            if manager.get_request(request.id).status.value != "pending":
                break
            await asyncio.sleep(0.005)

        conn.request_permission.assert_called_once()
        assert manager.get_request(request.id).status.value == "approved"
    finally:
        agent.close()
