"""Runtime-to-ACP event contracts, including cancelled and crossed sessions."""

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from test_acp_server import FakeCore

from penguin.cli.events import EventBus
from penguin.integrations.acp.server import PenguinACPAgent


@pytest.mark.asyncio
async def test_runtime_tools_and_plan_are_scoped_and_ordered(tmp_path):
    core = FakeCore()
    core.event_bus = EventBus()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    sid = (await agent.new_session(str(tmp_path))).session_id

    async def process(*args, **kwargs):
        await core.event_bus.emit(
            "action", {"session_id": "other", "id": "foreign", "type": "read_file"}
        )
        await core.event_bus.emit(
            "action",
            {
                "session_id": sid,
                "id": "read",
                "type": "read_file",
                "params": {"path": "test.txt"},
            },
        )
        await core.event_bus.emit(
            "action_result",
            {
                "session_id": sid,
                "id": "read",
                "status": "completed",
                "result": "contents",
            },
        )
        await core.event_bus.emit(
            "action_result",
            {
                "session_id": sid,
                "id": "read",
                "status": "completed",
                "result": "duplicate",
            },
        )
        await core.event_bus.emit(
            "todo.updated",
            {
                "session_id": sid,
                "todos": [
                    {"content": "Verify", "status": "in_progress", "priority": "high"}
                ],
            },
        )
        return {"assistant_response": "done"}

    core.process.side_effect = process
    try:
        await agent.prompt(sid, [text_block("go")])
        updates = [c.kwargs["update"] for c in conn.session_update.call_args_list]
        assert [u.session_update for u in updates] == [
            "tool_call",
            "tool_call_update",
            "plan",
            "agent_message_chunk",
        ]
        assert updates[0].tool_call_id == updates[1].tool_call_id == "read"
        assert updates[0].locations[0].path == str(tmp_path / "test.txt")
        assert updates[1].status == "completed"
        assert updates[1].content[0].content.text == "contents"
        assert updates[2].entries[0].status == "in_progress"
        assert all(
            c.kwargs["session_id"] == sid for c in conn.session_update.call_args_list
        )
    finally:
        agent.close()
    assert not core.event_bus.subscribers["action"]


@pytest.mark.asyncio
async def test_cancel_finalizes_pending_tool_and_ignores_late_event(tmp_path):
    core = FakeCore()
    core.event_bus = EventBus()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    sid = (await agent.new_session(str(tmp_path))).session_id
    started = asyncio.Event()

    async def process(*args, **kwargs):
        await core.event_bus.emit(
            "action", {"session_id": sid, "id": "shell", "type": "execute_command"}
        )
        started.set()
        await asyncio.Event().wait()

    core.process.side_effect = process
    try:
        task = asyncio.create_task(agent.prompt(sid, [text_block("go")]))
        await started.wait()
        await agent.cancel(sid)
        assert (await task).stop_reason == "cancelled"
        updates = [c.kwargs["update"] for c in conn.session_update.call_args_list]
        assert [u.status for u in updates] == ["pending", "failed"]
        await core.event_bus.emit(
            "action_result",
            {"session_id": sid, "id": "shell", "status": "completed", "result": "late"},
        )
        assert conn.session_update.await_count == 2
    finally:
        agent.close()
