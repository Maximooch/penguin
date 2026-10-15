"""Exercise the existing ACP adapter over real stdio, without a model provider."""

import asyncio
import os
import sys

import pytest

acp = pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import ImageContentBlock


# A subprocess, not an in-process mock connection: assertions cover framing,
# stdout cleanliness and the SDK's actual request/notification dispatcher.
_FAKE_AGENT = """
import asyncio
import os
from pathlib import Path
from acp import run_agent
from penguin.integrations.acp.server import PenguinACPAgent

class Core:
    def __init__(self):
        self.number = 0
    def create_conversation(self):
        self.number += 1
        return f'session-{self.number}'
    async def process(self, text, **kwargs):
        await kwargs['stream_callback'](f'{text}: ', 'assistant')
        await kwargs['stream_callback']('done', 'assistant')
        return {'assistant_response': f'{text}: done'}
    async def abort_session(self, session_id):
        return True

async def main():
    agent = PenguinACPAgent(Core(), allowed_roots=(Path(os.environ['ACP_TEST_ROOT']),))
    try:
        await run_agent(agent)
    finally:
        agent.close()

asyncio.run(main())
"""


class RecordingClient:
    def __init__(self):
        self.updates = []

    async def session_update(self, session_id, update, **kwargs):
        self.updates.append((session_id, update))


@pytest.mark.asyncio
async def test_acp_stdio_initialize_sessions_and_two_turns(tmp_path):
    client = RecordingClient()
    env = {**os.environ, "ACP_TEST_ROOT": str(tmp_path)}
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _FAKE_AGENT, env=env
    ) as (conn, process):
        response = await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 10)
        assert response.protocol_version == acp.PROTOCOL_VERSION
        assert response.agent_capabilities.load_session is False
        first = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        second = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        assert first != second
        for sid, text in ((first, "one"), (second, "other"), (first, "two")):
            result = await asyncio.wait_for(conn.prompt(sid, [text_block(text)]), 10)
            assert result.stop_reason == "end_turn"
            chunks = [update.content.text for session, update in client.updates
                      if session == sid and update.content.text.startswith(text)]
            assert chunks[-1] == f"{text}: "
        assert [update.content.text for sid, update in client.updates if sid == first] == [
            "one: ", "done", "two: ", "done"
        ]
        assert [update.content.text for sid, update in client.updates if sid == second] == [
            "other: ", "done"
        ]
        assert process.returncode is None


@pytest.mark.asyncio
async def test_acp_stdio_rejects_unsupported_requests_without_killing_connection(tmp_path):
    client = RecordingClient()
    env = {**os.environ, "ACP_TEST_ROOT": str(tmp_path)}
    async with acp.spawn_agent_process(
        client, sys.executable, "-c", _FAKE_AGENT, env=env
    ) as (conn, process):
        with pytest.raises(RequestError):
            await asyncio.wait_for(conn.initialize(0), 10)
        await asyncio.wait_for(conn.initialize(acp.PROTOCOL_VERSION), 10)
        with pytest.raises(RequestError):
            await asyncio.wait_for(conn.new_session(str(tmp_path.parent)), 10)
        sid = (await asyncio.wait_for(conn.new_session(str(tmp_path)), 10)).session_id
        with pytest.raises(RequestError):
            await asyncio.wait_for(conn.prompt(sid, [
                ImageContentBlock(type="image", data="aGVsbG8=", mime_type="image/png")
            ]), 10)
        assert (await asyncio.wait_for(conn.prompt(sid, [text_block("okay")]), 10)).stop_reason == "end_turn"
        assert process.returncode is None
