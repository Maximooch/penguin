"""Real SDK permission requests must reach the client before file dispatch."""

import asyncio
import os
import sys

import pytest

pytest.importorskip("acp")
from acp.stdio import spawn_stdio_connection
from test_acp_wire import _CLI_AGENT


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["allow_once", "reject_once"])
async def test_real_cli_permission_roundtrip(tmp_path, choice):
    script = _CLI_AGENT.replace(
        "        self.model_config = types.SimpleNamespace(vision_enabled=True)",
        """        self.model_config = types.SimpleNamespace(vision_enabled=True)
        from penguin.tools.tool_manager import ToolManager
        from penguin.security.permission_engine import PermissionResult
        self.tool_manager = ToolManager(
            {'workspace_path': os.environ['PENGUIN_WORKSPACE']},
            lambda *_: None, fast_startup=True)
        self.tool_manager._permission_enabled = True
        self.tool_manager.check_tool_permission = lambda *_: (
            PermissionResult.ASK, 'confirm')
""",
    ).replace(
        "        print('provider diagnostic')",
        """
        print('provider diagnostic')
        if text == 'write':
            result = await self.tool_manager.execute_tool_async('write_file', {
                'path': str(Path(os.environ['PENGUIN_WORKSPACE']) / 'permission.txt'),
                'content': 'allowed'})
            return {'assistant_response': str(result)}
""",
    )
    requests = []

    async def handler(method, params, notification):
        if method == "session/request_permission":
            requests.append(params)
            return {"outcome": {"outcome": "selected", "optionId": choice}}

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "store"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", script, env=env
    ) as (conn, _):
        await asyncio.wait_for(
            conn.send_request("initialize", {"protocolVersion": 1}), 15
        )
        sid = (
            await conn.send_request(
                "session/new", {"cwd": str(tmp_path), "mcpServers": []}
            )
        )["sessionId"]
        await conn.send_request(
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "write"}]},
        )
    assert len(requests) == 1
    assert requests[0]["sessionId"] == sid
    assert "sessionUpdate" not in requests[0]["toolCall"]
    assert (tmp_path / "permission.txt").exists() == (choice == "allow_once")
