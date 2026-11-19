"""An ACP load either completes or leaves no trace.

Covers SM-100: building the replay wrote "never completed" failures for open
tool calls into the journal before the load was validated, so a load that
was then refused (for example for active children) still changed history.
Covers SM-101: a replay failure after the session was installed left it open
with a live MCP provider, restored grants and half-sent history.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.schema import ToolCallStart
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.children import Child
from penguin.integrations.acp.server import PenguinACPAgent


async def _agent(tmp_path) -> PenguinACPAgent:
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    agent.on_connect(AsyncMock())
    await agent.initialize(1)
    return agent


def _journal(agent: PenguinACPAgent, sid: str) -> int:
    return len(agent._registry._records(agent._registry.get(sid)))


@pytest.mark.asyncio
async def test_a_refused_load_does_not_change_history(tmp_path) -> None:
    agent = await _agent(tmp_path)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        agent._registry.record(
            sid,
            ToolCallStart(
                session_update="tool_call",
                tool_call_id="call-1",
                title="Read",
                status="in_progress",
            ),
        )
        agent._registry.checkpoint(sid)
        await agent.close_session(sid)
        agent._children.children["child-1"] = Child(
            parent=sid, root=sid, agent="worker", cwd=tmp_path, active=True
        )
        before = _journal(agent, sid)

        with pytest.raises(RequestError):
            await agent.load_session(str(tmp_path), sid)

        assert _journal(agent, sid) == before
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_a_failed_replay_leaves_the_session_closed(tmp_path) -> None:
    agent = await _agent(tmp_path)
    closed: list[bool] = []
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        agent._registry.append(
            sid,
            {
                "acp_target": "nobody",
                "update": {"sessionUpdate": "agent_message_chunk", "content": {}},
            },
        )
        agent._registry.checkpoint(sid)
        await agent.close_session(sid)

        async def provider(*_args: object) -> SimpleNamespace:
            return SimpleNamespace(close=lambda: closed.append(True))

        agent._new_mcp_provider = provider

        with pytest.raises((RequestError, ValueError)):
            await agent.load_session(str(tmp_path), sid)

        assert sid not in agent.sessions
        assert closed == [True]
        assert sid not in agent._children.replay_known
    finally:
        agent.close()
