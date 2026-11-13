"""Negotiated, opt-in editor text buffers through actual tool dispatch."""

import asyncio
import json
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import ClientCapabilities, FileSystemCapabilities
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction


@pytest.mark.asyncio
async def test_client_buffers_are_opt_in_and_never_fall_back_to_local(tmp_path):
    file = tmp_path / "file.txt"
    file.write_text("local")
    core = PersistentCore(tmp_path / "store")
    core.tool_manager = ToolManager(
        {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
    )
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.read_text_file.return_value = SimpleNamespace(content="unsaved client buffer")
    agent.on_connect(conn)
    await agent.initialize(
        1,
        client_capabilities=ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=True, write_text_file=True)
        ),
    )
    sid = (await agent.new_session(str(tmp_path))).session_id
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async("read_file", {"path": str(file)})
        )
        if agent.sessions[kwargs["conversation_id"]].filesystem == "client":
            tools = {t["name"] for t in core.tool_manager.get_tools()}
            assert "patch_file" not in tools
            assert "execute_command" not in tools
            results.append(
                await core.tool_manager.execute_tool_async(
                    "write_to_file", {"path": str(file), "content": "new client"}
                )
            )
            executor = ActionExecutor(
                tool_manager=core.tool_manager, task_manager=SimpleNamespace()
            )
            legacy = await executor.execute_action(
                CodeActAction(ActionType.READ_FILE, str(file))
            )
            assert "unsaved client buffer" in str(legacy)
            await executor.execute_action(
                CodeActAction(
                    ActionType.WRITE_FILE,
                    json.dumps({"path": str(file), "content": "legacy client"}),
                )
            )
            results.append(
                await core.tool_manager.execute_tool_async(
                    "patch_file",
                    {
                        "path": str(file),
                        "operation": {
                            "type": "exact_replace",
                            "old": "local",
                            "new": "oops",
                        },
                    },
                )
            )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.prompt(sid, [text_block("read")])
        conn.read_text_file.assert_not_called()
        assert "local" in str(results[-1])
        await agent.set_config_option(sid, "file_access", "client")
        await agent.prompt(sid, [text_block("edit")])
        assert "unsaved client buffer" in str(results[-3])
        assert json.loads(results[-1])["error"] == "unsupported_client_file_operation"
        assert file.read_text() == "local"
        assert conn.read_text_file.call_args.kwargs["line"] == 1
        assert conn.write_text_file.called, results
        assert conn.write_text_file.call_args.kwargs["content"] == "legacy client"
        await agent.set_session_mode(sid, "plan")
        await agent.prompt(sid, [text_block("read-only")])
        assert conn.write_text_file.call_count == 2
        assert "permission_denied" in str(results[-2])
        await agent.set_session_mode(sid, "build")
        calls = conn.read_text_file.call_count
        other = (await agent.new_session(str(tmp_path))).session_id
        await agent.prompt(other, [text_block("local again")])
        assert conn.read_text_file.call_count == calls
        assert "local" in str(results[-1])
        agent.sessions[sid].task = object()
        with pytest.raises(RequestError):
            await agent.set_config_option(sid, "file_access", "local")
        agent.sessions[sid].task = None
        await agent.close_session(sid)
        await agent.initialize(1)
        with pytest.raises(RequestError):
            await agent.load_session(str(tmp_path), sid)
        await agent.initialize(
            1,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapabilities(read_text_file=True, write_text_file=True)
            ),
        )
        await agent.load_session(str(tmp_path), sid)
        assert agent.sessions[sid].filesystem == "client"
    finally:
        if sid in agent.sessions:
            agent.sessions[sid].task = None
        agent.close()


@pytest.mark.asyncio
async def test_unadvertised_client_files_cannot_be_selected(tmp_path):
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    agent.on_connect(AsyncMock())
    try:
        await agent.initialize(1)
        sid = (await agent.new_session(str(tmp_path))).session_id
        with pytest.raises(RequestError):
            await agent.set_config_option(sid, "file_access", "client")
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_cancelled_client_write_is_never_acknowledged(tmp_path):
    core = PersistentCore(tmp_path / "store")
    core.tool_manager = ToolManager(
        {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
    )
    core.abort_session = AsyncMock()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    started, finished = asyncio.Event(), asyncio.Event()

    async def writing(**kwargs):
        started.set()
        await asyncio.Event().wait()
        finished.set()

    conn.write_text_file.side_effect = writing
    agent.on_connect(conn)
    await agent.initialize(
        1,
        client_capabilities=ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=True, write_text_file=True)
        ),
    )
    sid = (await agent.new_session(str(tmp_path))).session_id
    await agent.set_config_option(sid, "file_access", "client")
    acknowledged = []

    async def process(*args, **kwargs):
        result = await core.tool_manager.execute_tool_async(
            "write_file", {"path": str(tmp_path / "client.txt"), "content": "value"}
        )
        acknowledged.append(result)
        return {"assistant_response": "written"}

    core.process = process
    prompt = asyncio.create_task(agent.prompt(sid, [text_block("write")]))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await agent.cancel(sid)
        assert (await prompt).stop_reason == "cancelled"
        assert not acknowledged and not finished.is_set()
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_client_file_rpc_roundtrip_from_real_cli(tmp_path):
    script = _CLI_AGENT.replace(
        "        self.model_config = types.SimpleNamespace(vision_enabled=True)",
        """        self.model_config = types.SimpleNamespace(vision_enabled=True)
        from penguin.tools.tool_manager import ToolManager
        self.tool_manager = ToolManager(
            {'workspace_path': os.environ['PENGUIN_WORKSPACE']},
            lambda *_: None, fast_startup=True)
""",
    ).replace(
        "        print('provider diagnostic')",
        """
        print('provider diagnostic')
        if text == 'client-files':
            path = str(Path(os.environ['PENGUIN_WORKSPACE']) / 'buffer.txt')
            read = await self.tool_manager.execute_tool_async(
                'read_file', {'path': path})
            write = await self.tool_manager.execute_tool_async(
                'write_file', {'path': path, 'content': 'new buffer'})
            return {'assistant_response': str([read, write])}
""",
    )
    calls = []

    async def handler(method, params, notification):
        if method.startswith("fs/"):
            calls.append((method, params))
            return (
                {"content": "unsaved buffer"} if method == "fs/read_text_file" else {}
            )

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "store"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", script, env=env
    ) as (conn, _):
        await asyncio.wait_for(
            conn.send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {
                        "fs": {"readTextFile": True, "writeTextFile": True}
                    },
                },
            ),
            15,
        )
        sid = (
            await conn.send_request(
                "session/new", {"cwd": str(tmp_path), "mcpServers": []}
            )
        )["sessionId"]
        await conn.send_request(
            "session/set_config_option",
            {"sessionId": sid, "configId": "file_access", "value": "client"},
        )
        await conn.send_request(
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "client-files"}]},
        )
    assert [method for method, _ in calls] == [
        "fs/read_text_file",
        "fs/write_text_file",
    ]
    assert all(params["sessionId"] == sid for _, params in calls)
    assert calls[0][1]["line"] == 1
    assert calls[1][1]["content"] == "new buffer"
    assert not (tmp_path / "buffer.txt").exists()
