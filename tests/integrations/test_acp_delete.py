"""Workspace-owned deletion and the real CLI's missing-SDK-route shim."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.integrations.acp.server import PenguinACPAgent


@pytest.mark.asyncio
async def test_delete_checks_ownership_busy_and_cleans_attachments(tmp_path):
    root = tmp_path / "workspace"
    root.mkdir()
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(root,))
    agent.on_connect(AsyncMock())
    try:
        sid = (await agent.new_session(str(root))).session_id
        asset = core.store.base_path / "acp-assets" / sid / "image.png"
        asset.parent.mkdir(parents=True, exist_ok=True)
        asset.write_bytes(b"fixture")
        plain = core.create_conversation()
        for invalid in (plain, "../escape"):
            with pytest.raises(RequestError):
                await agent.delete_session(invalid)
        agent.sessions[sid].task = asyncio.current_task()
        with pytest.raises(RequestError):
            await agent.delete_session(sid)
        agent.sessions[sid].task = None
        agent._processes.states[(sid, "active")] = {}
        with pytest.raises(RequestError):
            await agent.delete_session(sid)
        agent._processes.states.clear()
        await agent.delete_session(sid)
        assert sid not in core.store.session_index
        assert plain in core.store.session_index
        assert not asset.exists()
        assert sid not in agent.sessions
        with pytest.raises(RequestError):
            await agent.load_session(str(root), sid)
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_real_cli_delete_route_is_advertised_and_validated(tmp_path):
    async def handler(*args):
        return None

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "sessions"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", _CLI_AGENT, env=env
    ) as (conn, _):
        init = await asyncio.wait_for(
            conn.send_request("initialize", {"protocolVersion": 1}), 15
        )
        assert init["agentCapabilities"]["sessionCapabilities"]["delete"] == {}
        sid = (
            await conn.send_request(
                "session/new", {"cwd": str(tmp_path), "mcpServers": []}
            )
        )["sessionId"]
        with pytest.raises(RequestError):
            await conn.send_request("session/delete", {"sessionId": 123})
        # A notification must not perform this request-only mutation.
        await conn.send_notification("session/delete", {"sessionId": sid})
        listed = await conn.send_request("session/list", {})
        assert [s["sessionId"] for s in listed["sessions"]] == [sid]
        assert await conn.send_request("session/delete", {"sessionId": sid}) == {}
        assert (await conn.send_request("session/list", {}))["sessions"] == []
