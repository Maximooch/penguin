"""ACP close and load cannot interleave with another request on the session.

Covers SM-86: ``close_session`` awaited several steps before removing the
session and nothing marked it as closing, so a load or prompt arriving in
between ran on a session the close then removed or shut down.
Covers SM-87: ``session/load`` checked "busy" before waiting for the process
gate and replaced the ``Session`` object after it, so a prompt queued in
between ran on the replaced object, where cancel and events no longer worked.
"""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent


async def _agent(tmp_path) -> PenguinACPAgent:
    core = PersistentCore(tmp_path / "store")

    async def process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"assistant_response": "done"}

    core.process = process
    core.abort_session = AsyncMock()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    await agent.initialize(1)
    return agent


@pytest.mark.asyncio
async def test_a_load_during_close_is_refused(tmp_path) -> None:
    agent = await _agent(tmp_path)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        closing = threading.Event()
        release = threading.Event()

        def slow_close() -> None:
            closing.set()
            release.wait(5)

        agent.sessions[sid].mcp_provider = SimpleNamespace(close=slow_close)
        close = asyncio.create_task(agent.close_session(sid))
        await asyncio.to_thread(closing.wait, 5)

        with pytest.raises(RequestError):
            await agent.load_session(str(tmp_path), sid)
        with pytest.raises(RequestError):
            await agent.prompt(sid, [text_block("hi")])
        release.set()
        await close

        assert sid not in agent.sessions
        await agent.load_session(str(tmp_path), sid)
        assert (await agent.prompt(sid, [text_block("hi")])).stop_reason
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_a_load_queued_behind_a_prompt_does_not_replace_its_session(
    tmp_path,
) -> None:
    agent = await _agent(tmp_path)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        original = agent.sessions[sid]
        await agent._process_gate.acquire()  # another session's long turn
        load = asyncio.create_task(agent.load_session(str(tmp_path), sid))
        await asyncio.sleep(0.05)
        turn = asyncio.create_task(agent.prompt(sid, [text_block("hi")]))
        await asyncio.sleep(0.05)
        agent._process_gate.release()

        with pytest.raises(RequestError):
            await load
        await turn

        assert agent.sessions[sid] is original
    finally:
        agent.close()
