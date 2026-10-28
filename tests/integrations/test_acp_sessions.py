"""Exercise ACP restart/replay against the actual Penguin session store."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import AgentMessageChunk

from penguin.cli.events import EventBus
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory


class PersistentCore:
    def __init__(self, root):
        self.store = SessionManager(str(root), auto_save_interval=0)
        self.conversation_manager = SimpleNamespace(session_manager=self.store)
        self.event_bus = EventBus()

    def create_conversation(self):
        return self.store.create_session().id

    async def process(self, text, *, conversation_id, stream_callback, **kwargs):
        session = self.store.load_session(conversation_id)
        previous = len(session.messages)
        session.add_message(
            Message(role="user", content=text, category=MessageCategory.DIALOG)
        )
        await self.event_bus.emit(
            "action",
            {
                "session_id": conversation_id,
                "id": f"call-{previous}",
                "type": "read_file",
            },
        )
        await self.event_bus.emit(
            "action_result",
            {
                "session_id": conversation_id,
                "id": f"call-{previous}",
                "status": "completed",
                "result": "read",
            },
        )
        answer = f"previous={previous}"
        session.add_message(
            Message(role="assistant", content=answer, category=MessageCategory.DIALOG)
        )
        await stream_callback(answer)
        return {"assistant_response": answer}


@pytest.mark.asyncio
async def test_restart_replays_all_visible_updates_and_continues_core(tmp_path):
    workspace = tmp_path / "project"
    workspace.mkdir()
    storage = tmp_path / "sessions"
    first = PenguinACPAgent(PersistentCore(storage), allowed_roots=(workspace,))
    first_conn = AsyncMock()
    first.on_connect(first_conn)
    sid = (await first.new_session(str(workspace))).session_id
    await first.prompt(sid, [text_block("first")])
    first.close()

    second = PenguinACPAgent(PersistentCore(storage), allowed_roots=(workspace,))
    second_conn = AsyncMock()
    second.on_connect(second_conn)
    try:
        response = await second.initialize(1)
        assert response.agent_capabilities.load_session
        assert [s.session_id for s in (await second.list_sessions()).sessions] == [sid]
        await second.load_session(str(workspace), sid)
        replay = [c.kwargs["update"] for c in second_conn.session_update.call_args_list]
        assert [u.session_update for u in replay] == [
            "user_message_chunk",
            "tool_call",
            "tool_call_update",
            "agent_message_chunk",
        ]
        assert replay[0].content.text == "first"
        assert replay[-1].content.text == "previous=0"
        await second.prompt(sid, [text_block("next")])
        assert (
            second_conn.session_update.call_args.kwargs["update"].content.text
            == "previous=2"
        )
        assert len(second._registry.history(second._registry.get(sid))) == 8
    finally:
        second.close()


@pytest.mark.asyncio
async def test_cannot_load_or_list_another_workspace_or_plain_session(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    core = PersistentCore(tmp_path / "sessions")
    first = PenguinACPAgent(core, allowed_roots=(a,))
    first.on_connect(AsyncMock())
    sid = (await first.new_session(str(a))).session_id
    plain = core.create_conversation()
    core.store.save_session()
    second = PenguinACPAgent(core, allowed_roots=(b,))
    second.on_connect(AsyncMock())
    try:
        assert not (await second.list_sessions()).sessions
        for target in (sid, plain, "../session_index"):
            with pytest.raises(RequestError):
                await second.load_session(str(b), target)
        with pytest.raises(RequestError):
            await first.load_session(str(b), sid)
    finally:
        first.close()
        second.close()


@pytest.mark.asyncio
async def test_replay_recovers_unfinished_tool_without_reexecuting(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    sid = (await agent.new_session(str(tmp_path))).session_id
    saved = agent._registry.get(sid)
    saved.metadata["acp_history"] = [
        {
            "sessionUpdate": "tool_call",
            "toolCallId": "unfinished",
            "title": "write",
            "status": "pending",
        }
    ]
    agent._registry.save(saved)
    try:
        await agent.load_session(str(tmp_path), sid)
        updates = [c.kwargs["update"] for c in conn.session_update.call_args_list]
        assert [u.status for u in updates] == ["pending", "failed"]
        assert not core.store.load_session(sid).messages
        assert len(agent._registry.history(saved)) == 2
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_session_list_pagination(tmp_path):
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "sessions"), allowed_roots=(tmp_path,)
    )
    try:
        ids = {(await agent.new_session(str(tmp_path))).session_id for _ in range(51)}
        page = await agent.list_sessions()
        assert len(page.sessions) == 50
        assert page.next_cursor
        tail = await agent.list_sessions(cursor=page.next_cursor)
        assert len(tail.sessions) == 1
        assert tail.next_cursor is None
        assert {s.session_id for s in page.sessions + tail.sessions} == ids
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_long_stream_appends_linear_bytes_without_session_rewrites(
    tmp_path, monkeypatch
):
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    sid = (await agent.new_session(str(tmp_path))).session_id
    original_save = core.store.save_session
    saves = []
    monkeypatch.setattr(
        core.store,
        "save_session",
        lambda session: saves.append(session.id) or original_save(session),
    )
    try:
        for _ in range(2000):
            agent._registry.record(
                sid,
                AgentMessageChunk(
                    session_update="agent_message_chunk", content=text_block("x")
                ),
            )
        path = core.store.base_path / "acp-history" / (sid + ".jsonl")
        assert path.stat().st_size < 2000 * 150
        assert saves == []  # No quadratic full-session writes for streamed text.
        agent._registry.checkpoint(sid)
        assert saves == [sid]
        assert len(agent._registry.history(agent._registry.get(sid))) == 2000
        with path.open("ab") as file:
            file.write(b'{"sessionUpdate":')  # Simulate interrupted final append.
        assert len(agent._registry.history(agent._registry.get(sid))) == 2000
        agent._registry.record(
            sid,
            AgentMessageChunk(
                session_update="agent_message_chunk", content=text_block("end")
            ),
        )
        assert len(agent._registry.history(agent._registry.get(sid))) == 2001
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_new_session_waits_for_active_turn_checkpoint(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    sid = (await agent.new_session(str(tmp_path))).session_id
    original_process = core.process
    started, release = asyncio.Event(), asyncio.Event()

    async def process(*args, **kwargs):
        started.set()
        await release.wait()
        return await original_process(*args, **kwargs)

    core.process = process
    try:
        first = asyncio.create_task(agent.prompt(sid, [text_block("first")]))
        await started.wait()
        other = asyncio.create_task(agent.new_session(str(tmp_path)))
        await asyncio.sleep(0)
        assert not other.done()
        release.set()
        await first
        new_id = (await other).session_id
        assert len(core.store.load_session(sid).messages) == 2
        assert len(core.store.load_session(new_id).messages) == 0
    finally:
        agent.close()
