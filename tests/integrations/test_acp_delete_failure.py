"""A failed delete leaves the session open, as the error tells the client.

Covers SM-104: ``delete_session`` closed the session before the delete that
could fail, so on failure the client got an error and kept using a session
that had already been detached ("invalid sessionId" on the next prompt).
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent


@pytest.mark.asyncio
async def test_a_failed_delete_keeps_the_session_open(tmp_path) -> None:
    core = PersistentCore(tmp_path / "store")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    await agent.initialize(1)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id

        def refuse(_session_id: str) -> bool:
            return False

        core.conversation_manager.delete_conversation = refuse

        with pytest.raises(RequestError):
            await agent.delete_session(sid)

        assert sid in agent.sessions
        response: Any = await agent.prompt(sid, [text_block("still here")])
        assert response.stop_reason
    finally:
        agent.close()
