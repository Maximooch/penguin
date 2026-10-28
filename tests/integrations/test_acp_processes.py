"""A real background process must update ACP without consuming its output."""

import asyncio
import shlex
import subprocess
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.core_runtime.process_notifications import prepare_process_step
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.system.execution_context import get_current_execution_context
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
async def test_process_streams_after_parent_turn_and_keeps_model_cursor(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = ToolManager(
        {"workspace_path": str(tmp_path)}, lambda *_args: None, fast_startup=True
    )
    core.emit_ui_event = core.event_bus.emit
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    connection = AsyncMock()
    agent.on_connect(connection)
    finished = asyncio.Event()

    async def update(**kwargs):
        event = kwargs["update"]
        if (
            getattr(event, "tool_call_id", "").startswith("process:")
            and getattr(event, "status", "") == "completed"
        ):
            finished.set()

    connection.session_update.side_effect = update
    process_id = None

    async def process(*args, **kwargs):
        nonlocal process_id
        context = get_current_execution_context()
        prepare_process_step(core.tool_manager, SimpleNamespace(core=core), context)
        argv = [
            sys.executable,
            "-c",
            "import time; print('first', flush=True); "
            "time.sleep(.2); print('last', flush=True)",
        ]
        command = (
            subprocess.list2cmdline(argv)
            if sys.platform == "win32"
            else shlex.join(argv)
        )
        result = await asyncio.to_thread(
            core.tool_manager.process_tools.execute,
            "process_start",
            {"command": command},
            context.as_dict(),
        )
        process_id = result["process_id"]
        await core.emit_ui_event(
            "action_result", {"session_id": context.session_id, "result": result}
        )
        return {"assistant_response": "running"}

    core.process = process
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.prompt(sid, [text_block("start")])
        assert agent.sessions[sid].task is None
        await asyncio.wait_for(finished.wait(), 10)
        runtime = core.tool_manager.process_runtime
        assert runtime._processes[process_id].cursors == {}
        updates = [
            call.kwargs["update"]
            for call in connection.session_update.call_args_list
            if getattr(call.kwargs["update"], "tool_call_id", "")
            == "process:" + process_id
        ]
        assert updates[0].status == "in_progress"
        assert updates[-1].status == "completed"
        assert "last" in updates[-1].content[0].content.text
        retained = runtime.poll(process_id, since_sequence=0, wait_ms=0)
        assert "first" in retained["output"] and "last" in retained["output"]
    finally:
        core.tool_manager.process_tools.cleanup()
        agent.close()


@pytest.mark.asyncio
async def test_scoped_process_events_work_after_parent_turn(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent._processes.update(
            {
                "session_id": sid,
                "process_id": "p",
                "process_status": "running",
                "output_tail": "first",
            },
            completed=False,
        )
        await agent._processes.update(
            {
                "session_id": sid,
                "process_id": "p",
                "process_status": "exited",
                "output_tail": "first\nlast",
                "returncode": 0,
            },
            completed=True,
        )
        await agent._processes.update(
            {
                "session_id": "other",
                "process_id": "foreign",
                "process_status": "running",
            },
            completed=False,
        )
        updates = [c.kwargs["update"] for c in conn.session_update.call_args_list]
        assert [u.status for u in updates] == [
            "in_progress",
            "in_progress",
            "completed",
        ]
        assert "last" in updates[-1].content[0].content.text
        history = agent._registry.history(agent._registry.get(sid))
        assert not any(getattr(u, "status", None) == "failed" for u in history)
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_reconnect_does_not_claim_unknown_process_completed(tmp_path):
    storage = tmp_path / "sessions"
    first = PenguinACPAgent(PersistentCore(storage), allowed_roots=(tmp_path,))
    first.on_connect(AsyncMock())
    sid = (await first.new_session(str(tmp_path))).session_id
    await first._processes.update(
        {"session_id": sid, "process_id": "gone", "process_status": "running"},
        completed=False,
    )
    first.close()
    second = PenguinACPAgent(PersistentCore(storage), allowed_roots=(tmp_path,))
    conn = AsyncMock()
    second.on_connect(conn)
    try:
        await second.load_session(str(tmp_path), sid)
        updates = [c.kwargs["update"] for c in conn.session_update.call_args_list]
        final = [
            u for u in updates if getattr(u, "tool_call_id", "") == "process:gone"
        ][-1]
        assert final.status == "failed"
        assert "outcome unknown" in final.content[0].content.text
        assert not any(getattr(u, "status", None) == "completed" for u in updates)
        count = len(updates)
        second.close()
        await second._processes.on_event(
            "opencode_event",
            {
                "type": "tool.process.output",
                "properties": {
                    "session_id": sid,
                    "process_id": "late",
                    "process_status": "running",
                },
            },
        )
        assert conn.session_update.call_count == count
    finally:
        second.close()
