"""Additional roots propagate through real file tools and session recovery."""

import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.schema import ResourceContentBlock
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.core_runtime import agent_lifecycle
from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.scoped_paths import enforce_execution_path
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    get_current_execution_context,
)
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
@pytest.mark.parametrize("permissions", [True, False])
async def test_additional_root_write_escape_and_resume(tmp_path, permissions):
    primary, extra, foreign = (
        tmp_path / name for name in ("primary", "extra", "extra-sibling")
    )
    for directory in (primary, extra, foreign):
        directory.mkdir()
    core = PersistentCore(tmp_path / "store")
    core.tool_manager = ToolManager(
        {"workspace_path": str(primary)}, lambda *_: None, fast_startup=True
    )
    core.tool_manager._permission_enabled = permissions
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    results = []

    async def process(*args, **kwargs):
        context = get_current_execution_context()
        assert context.allowed_roots[:2] == (str(primary), str(extra))
        assert context.allowed_roots[2] == str(
            core.store.base_path / "acp-assets" / kwargs["conversation_id"]
        )
        for path in (extra / "okay.txt", foreign / "denied.txt"):
            results.append(
                await core.tool_manager.execute_tool_async(
                    "write_to_file",
                    {"path": str(path), "content": "test"},
                    context={"allowed_roots": (str(foreign),)},
                )
            )
        attachment = await core.tool_manager.execute_tool_async(
            "read_file", {"path": str(Path(context.allowed_roots[2]) / "copy.txt")}
        )
        assert "attachment fixture" in str(attachment)
        return {"assistant_response": "done"}

    core.process = process
    try:
        initialized = await agent.initialize(1)
        assert (
            initialized.agent_capabilities.session_capabilities.additional_directories
            is not None
        )
        sid = (
            await agent.new_session(str(primary), additional_directories=[str(extra)])
        ).session_id
        (core.store.base_path / "acp-assets" / sid / "copy.txt").write_text(
            "attachment fixture"
        )
        await agent.prompt(
            sid,
            [
                ResourceContentBlock(
                    type="resource_link", name="file", uri=(extra / "okay.txt").as_uri()
                )
            ],
        )
        assert (extra / "okay.txt").read_text() == "test"
        assert not (foreign / "denied.txt").exists()
        assert "denied" in str(results[1]).lower()
        await agent.close_session(sid)
        await agent.load_session(str(primary), sid)
        assert agent.sessions[sid].roots == (primary,)
        with pytest.raises(RequestError):
            await agent.prompt(
                sid,
                [
                    ResourceContentBlock(
                        type="resource_link",
                        name="extra",
                        uri=(extra / "okay.txt").as_uri(),
                    )
                ],
            )
        await agent.load_session(str(primary), sid, additional_directories=[str(extra)])
        assert agent.sessions[sid].roots == (primary, extra)
        with pytest.raises(RequestError):
            await agent.new_session(str(primary), additional_directories=["relative"])
        with pytest.raises(RequestError):
            await agent.new_session(
                str(primary), additional_directories=[str(tmp_path.parent)]
            )
        with pytest.raises(RequestError):
            await agent.prompt(
                sid,
                [
                    ResourceContentBlock(
                        type="resource_link",
                        name="outside",
                        uri=(foreign / "x").as_uri(),
                    )
                ],
            )
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_child_retains_roots_and_cannot_switch_outside(tmp_path, monkeypatch):
    primary, extra = tmp_path / "primary", tmp_path / "extra"
    primary.mkdir()
    extra.mkdir()
    roots = (str(primary), str(extra))
    directory = str(extra)

    def resolve(*args, **kwargs):
        return {
            "session_id": "child",
            "conversation_id": "child",
            "directory": directory,
            "project_root": directory,
            "workspace_root": directory,
            "agent_mode": "build",
        }

    monkeypatch.setattr(agent_lifecycle, "resolve_agent_execution_scope", resolve)
    seen = []

    async def process(**kwargs):
        seen.append(get_current_execution_context().allowed_roots)
        enforce_execution_path(extra / "file")
        return {"assistant_response": "child"}

    core = SimpleNamespace(process=process)
    with execution_context_scope(
        ExecutionContext(session_id="root", allowed_roots=roots)
    ):
        await agent_lifecycle.run_agent_prompt_in_session(core, "worker", "work")
        directory = str(tmp_path)
        with pytest.raises(ValueError):
            await agent_lifecycle.run_agent_prompt_in_session(core, "worker", "escape")
    assert seen == [roots]
    assert get_current_execution_context() is None


@pytest.mark.asyncio
async def test_roots_roundtrip_over_cli_stdio(tmp_path):
    primary, extra = tmp_path / "primary", tmp_path / "extra"
    primary.mkdir()
    extra.mkdir()

    async def handler(*args):
        return None

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "store"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", _CLI_AGENT, env=env
    ) as (conn, _):
        init = await asyncio.wait_for(
            conn.send_request("initialize", {"protocolVersion": 1}), 15
        )
        assert (
            init["agentCapabilities"]["sessionCapabilities"]["additionalDirectories"]
            == {}
        )
        created = await conn.send_request(
            "session/new",
            {
                "cwd": str(primary),
                "mcpServers": [],
                "additionalDirectories": [str(extra)],
            },
        )
        listed = await conn.send_request("session/list", {})
        assert listed["sessions"][0]["additionalDirectories"] == [str(extra)]
        await conn.send_request("session/close", {"sessionId": created["sessionId"]})
        resumed = await conn.send_request(
            "session/resume",
            {
                "sessionId": created["sessionId"],
                "cwd": str(primary),
                "mcpServers": [],
                "additionalDirectories": [str(extra)],
            },
        )
        assert "error" not in resumed
        listed = await conn.send_request("session/list", {})
        assert listed["sessions"][0]["additionalDirectories"] == [str(extra)]
