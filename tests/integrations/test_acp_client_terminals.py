"""Client terminal command ownership, cleanup and cancellation contracts."""

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


async def setup(tmp_path):
    core = PersistentCore(tmp_path / "store")
    core.tool_manager = ToolManager(
        {"workspace_path": str(tmp_path)}, lambda *_: None, fast_startup=True
    )
    core.abort_session = AsyncMock()
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.create_terminal.return_value = SimpleNamespace(terminal_id="terminal-1")
    conn.wait_for_terminal_exit.return_value = SimpleNamespace(exit_code=0, signal=None)
    conn.terminal_output.return_value = SimpleNamespace(
        output="from client", truncated=False
    )
    agent.on_connect(conn)
    await agent.initialize(
        1,
        client_capabilities=ClientCapabilities(
            fs=FileSystemCapabilities(read_text_file=True, write_text_file=True),
            terminal=True,
        ),
    )
    sid = (await agent.new_session(str(tmp_path))).session_id
    await agent.set_config_option(sid, "file_access", "client")
    await agent.set_config_option(sid, "client_terminal", "client")
    await agent.set_config_option(sid, "client_shell", "sh")
    return core, agent, conn, sid


@pytest.mark.asyncio
async def test_client_terminal_runs_native_and_legacy_without_local_shell(tmp_path):
    core, agent, conn, sid = await setup(tmp_path)
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async(
                "execute_command", {"command": "printf hello"}
            )
        )
        executor = ActionExecutor(
            tool_manager=core.tool_manager, task_manager=SimpleNamespace()
        )
        results.append(
            await executor.execute_action(
                CodeActAction(ActionType.EXECUTE_COMMAND, "printf legacy")
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.prompt(sid, [text_block("run")])
        assert all("from client" in result for result in results)
        assert conn.create_terminal.call_count == 2
        assert conn.create_terminal.call_args.kwargs["command"] == "sh"
        assert conn.create_terminal.call_args.kwargs["args"] == ["-c", "printf legacy"]
        assert conn.release_terminal.call_count == 2
        conn.kill_terminal.assert_not_called()
        assert core.tool_manager._process_runtime is None
    finally:
        agent.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["create", "wait"])
async def test_cancel_kills_and_releases_even_after_late_create(tmp_path, phase):
    core, agent, conn, sid = await setup(tmp_path)
    started, release = asyncio.Event(), asyncio.Event()

    async def creating(**kwargs):
        started.set()
        await release.wait()
        return SimpleNamespace(terminal_id="terminal-1")

    async def waiting(**kwargs):
        started.set()
        await asyncio.Event().wait()

    if phase == "create":
        conn.create_terminal.side_effect = creating
    else:
        conn.wait_for_terminal_exit.side_effect = waiting
    acknowledged = []

    async def process(*args, **kwargs):
        acknowledged.append(
            await core.tool_manager.execute_tool_async(
                "execute_command", {"command": "long"}
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    prompt = asyncio.create_task(agent.prompt(sid, [text_block("run")]))
    try:
        await asyncio.wait_for(started.wait(), 2)
        await agent.cancel(sid)
        release.set()
        assert (await asyncio.wait_for(prompt, 2)).stop_reason == "cancelled"
        conn.kill_terminal.assert_awaited_once()
        conn.release_terminal.assert_awaited_once()
        assert not acknowledged
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_client_terminal_timeout_has_no_false_success(tmp_path):
    core, agent, conn, sid = await setup(tmp_path)

    async def waiting(**kwargs):
        await asyncio.Event().wait()

    conn.wait_for_terminal_exit.side_effect = waiting
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async(
                "execute_command", {"command": "long", "timeout_seconds": 0.01}
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.prompt(sid, [text_block("run")])
        assert json.loads(results[0])["error"] == "client_terminal_timeout"
        conn.kill_terminal.assert_awaited_once()
        conn.release_terminal.assert_awaited_once()
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_cleanup_failure_is_reported(tmp_path):
    core, agent, conn, sid = await setup(tmp_path)
    conn.release_terminal.side_effect = RuntimeError("unavailable")
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async(
                "execute_command", {"command": "echo test"}
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.prompt(sid, [text_block("run")])
        assert json.loads(results[0])["cleanup_errors"] == ["release_failed"]
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_client_terminal_requires_capability_and_obeys_plan_mode(tmp_path):
    core, agent, conn, sid = await setup(tmp_path)
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async(
                "execute_command", {"command": "rm file"}
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.set_session_mode(sid, "plan")
        await agent.prompt(sid, [text_block("run")])
        assert "permission_denied" in results[0]
        conn.create_terminal.assert_not_called()
        await agent.initialize(
            1,
            client_capabilities=ClientCapabilities(
                fs=FileSystemCapabilities(read_text_file=True, write_text_file=True),
                terminal=False,
            ),
        )
        with pytest.raises(RequestError):
            await agent.prompt(sid, [text_block("run")])
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_real_cli_client_terminal_lifecycle(tmp_path):
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
        if text == 'terminal':
            result = await self.tool_manager.execute_tool_async(
                'execute_command', {'command': 'echo test > must-not-exist.txt',
                                    'env': {'BUILD_LABEL': 'client'}})
            return {'assistant_response': str(result)}
""",
    )
    calls = []

    async def handler(method, params, notification):
        if method.startswith("terminal/"):
            calls.append((method, params))
            return {
                "terminal/create": {"terminalId": "client-terminal"},
                "terminal/wait_for_exit": {"exitCode": 0},
                "terminal/output": {"output": "client output", "truncated": False},
                "terminal/release": {},
            }[method]

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
                        "terminal": True,
                        "fs": {"readTextFile": True, "writeTextFile": True},
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
        for key, value in (
            ("file_access", "client"),
            ("client_terminal", "client"),
            ("client_shell", "sh"),
        ):
            await conn.send_request(
                "session/set_config_option",
                {"sessionId": sid, "configId": key, "value": value},
            )
        await conn.send_request(
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "terminal"}]},
        )
    assert [method for method, _ in calls] == [
        "terminal/create",
        "terminal/wait_for_exit",
        "terminal/output",
        "terminal/release",
    ]
    assert calls[0][1]["env"] == [{"name": "BUILD_LABEL", "value": "client"}]
    assert calls[0][1]["command"] == "sh"
    assert not (tmp_path / "must-not-exist.txt").exists()
