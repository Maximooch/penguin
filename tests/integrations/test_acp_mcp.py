"""Client-supplied MCP configuration and actual local stdio isolation."""

import asyncio
import sys
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
pytest.importorskip("mcp.server.fastmcp")
from acp import RequestError
from acp.helpers import text_block
from acp.schema import (
    AllowedOutcome,
    EnvVariable,
    McpServerStdio,
    RequestPermissionResponse,
)
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.mcp import session_provider
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.tools.providers.mcp import active_mcp_provider, mcp_provider_scope
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
async def test_two_sessions_use_distinct_real_mcp_servers(tmp_path):
    script = tmp_path / "echo.py"
    script.write_text(
        """import os
from mcp.server.fastmcp import FastMCP
server = FastMCP('echo')
@server.tool()
def echo(value: str) -> str:
    return os.environ['VALUE'] + ':' + value
server.run(transport='stdio')
""",
        encoding="utf-8",
    )
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = ToolManager(
        {}, lambda *_args, **_kwargs: None, fast_startup=True
    )
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_once")
    )
    agent.on_connect(conn)
    await agent.initialize(1)

    async def process(text, **kwargs):
        schemas = core.tool_manager.get_responses_tools()
        assert "mcp__echo__echo" in {
            schema.get("name") or schema.get("function", {}).get("name")
            for schema in schemas
        }
        restricted = core.tool_manager.get_responses_tools(allowed_names=["read_file"])
        assert "mcp__echo__echo" not in {
            schema.get("name") or schema.get("function", {}).get("name")
            for schema in restricted
        }
        result = await core.tool_manager.execute_tool_async(
            "mcp__echo__echo", {"value": text}
        )
        return {"assistant_response": result}

    core.process = process
    try:
        ids = []
        for value in ("$LITERAL", "second"):
            server = McpServerStdio(
                type="stdio",
                name="echo",
                command=sys.executable,
                args=[str(script)],
                env=[EnvVariable(name="VALUE", value=value)],
            )
            ids.append(
                (
                    await agent.new_session(str(tmp_path), mcp_servers=[server])
                ).session_id
            )
        providers = [agent.sessions[sid].mcp_provider for sid in ids]
        assert providers[0] is not providers[1]
        for sid, prefix in zip(ids, ("$LITERAL", "second")):
            await asyncio.wait_for(agent.prompt(sid, [text_block("hello")]), 15)
            output = conn.session_update.call_args.kwargs["update"].content.text
            assert prefix + ":hello" in output
        assert active_mcp_provider(core.tool_manager, None) is None
        assert not [
            t
            for t in core.tool_manager.get_tools()
            if t["name"].startswith("mcp__echo")
        ]
    finally:
        agent.close()


def test_invalid_mcp_config_rejected_without_expanding_environment(tmp_path):
    server = McpServerStdio(
        type="stdio", name="echo", command=sys.executable, args=[], env=[]
    )
    with pytest.raises(RequestError):
        session_provider([server, server], tmp_path, {})


@pytest.mark.asyncio
async def test_request_provider_isolation_and_permission_gate(monkeypatch):
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    first, second = object(), object()

    async def read_scope(provider):
        with mcp_provider_scope(manager, provider):
            await asyncio.sleep(0)
            assert manager._get_mcp_provider() is provider

    await asyncio.gather(read_scope(first), read_scope(second))
    assert manager._get_mcp_provider() is manager._mcp_provider
    provider = AsyncMock()
    provider.is_mcp_tool = lambda _: True
    monkeypatch.setattr(
        manager, "_permission_response", lambda *_args: '{"error":"permission_denied"}'
    )
    with mcp_provider_scope(manager, provider):
        result = await manager.execute_tool_async("mcp__echo__echo", {"value": "test"})
    assert "permission_denied" in result
    provider.execute_tool.assert_not_called()
