"""No permission dialog is shown for a request that is no longer pending.

Covers SM-98: the dialog task was scheduled from the approval listener and
only checked that the request still existed, so a request denied in between
(by a cancel, or by expiry) was still shown for up to 300 s and the user's
answer was ignored.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager


@pytest.mark.asyncio
async def test_a_request_denied_before_its_dialog_is_not_shown(tmp_path) -> None:
    manager = get_approval_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    agent.on_connect(conn)
    await agent.initialize(1)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        request = manager.create_request(
            "tool", "filesystem.write", str(tmp_path / "f"), "test", session_id=sid
        )
        manager.deny(request.id)  # e.g. a cancel handled before the dialog ran

        await asyncio.sleep(0.05)

        conn.request_permission.assert_not_called()
    finally:
        agent.close()
