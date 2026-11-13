"""Native diff events must describe committed bytes, not attempted patches."""

from dataclasses import replace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.system.execution_context import (
    execution_context_scope,
    get_current_execution_context,
)
from penguin.tools.editing.observation import capture_edits
from penguin.tools.editing.service import EditService
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
@pytest.mark.parametrize("matches", [True, False])
async def test_committed_native_diff_through_real_tool_dispatch(tmp_path, matches):
    target = tmp_path / "file.txt"
    target.write_text("before\n", encoding="utf-8")
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = ToolManager(
        {"workspace_path": str(tmp_path)}, lambda *_args: None, fast_startup=True
    )
    core.tool_manager._core = core
    core.emit_ui_event = core.event_bus.emit
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    connection = AsyncMock()
    agent.on_connect(connection)

    async def process(*args, **kwargs):
        context = replace(get_current_execution_context(), tool_call_id="edit-1")
        with execution_context_scope(context):
            await core.emit_ui_event(
                "action",
                {"session_id": context.session_id, "id": "edit-1", "type": "edit_file"},
            )
            result = await core.tool_manager.execute_tool_async(
                "edit_file",
                {
                    "path": str(target),
                    "old_string": "before" if matches else "missing",
                    "new_string": "after",
                },
            )
            await core.emit_ui_event(
                "action_result",
                {
                    "session_id": context.session_id,
                    "id": "edit-1",
                    "status": "completed" if matches else "error",
                    "result": result,
                },
            )
        return {"assistant_response": "done"}

    core.process = process
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.prompt(sid, [text_block("edit")])
        diffs = [
            content
            for call in connection.session_update.call_args_list
            for content in (getattr(call.kwargs["update"], "content", None) or [])
            if getattr(content, "type", None) == "diff"
        ]
        if matches:
            assert diffs
            assert diffs[-1].old_text == "before\n"
            assert diffs[-1].new_text == "after\n"
            assert diffs[-1].path == str(target)
            assert target.read_text() == "after\n"
        else:
            assert not diffs
            assert target.read_text() == "before\n"
    finally:
        agent.close()


def test_diff_snapshots_are_complete_or_explicitly_omitted(tmp_path):
    service = EditService(str(tmp_path))
    with capture_edits() as edits:
        assert service.write_file("new.txt", "created", backup=False).ok
    assert edits == [
        {"path": str(tmp_path / "new.txt"), "old_text": None, "new_text": "created"}
    ]
    with capture_edits() as edits:
        assert service.write_file("new.txt", "x" * 140_000, backup=False).ok
    assert edits == [{"path": str(tmp_path / "new.txt"), "omitted": True}]
