"""Configuration must stay local to each ACP session and enforce its mode."""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp import RequestError
from acp.helpers import text_block
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.system.execution_context import get_current_execution_context
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
async def test_model_selection_is_request_scoped_and_persisted(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    core.model_config = SimpleNamespace(model="original", vision_enabled=False)
    core.list_available_models = lambda: [{"id": "other", "name": "Other"}]
    selected = SimpleNamespace(model="other", vision_enabled=False)
    client = object()
    core.resolve_request_runtime = AsyncMock(return_value=(selected, client))
    core.process = AsyncMock(return_value={"assistant_response": "ok"})
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    try:
        first = (await agent.new_session(str(tmp_path))).session_id
        second = (await agent.new_session(str(tmp_path))).session_id
        await agent.set_config_option(first, "model", "other")
        await agent.prompt(first, [text_block("go")])
        assert core.process.call_args.kwargs["model_config_override"] is selected
        assert core.process.call_args.kwargs["api_client_override"] is client
        await agent.prompt(second, [text_block("go")])
        assert "model_config_override" not in core.process.call_args.kwargs
        assert core.model_config.model == "original"
        await agent.close_session(first)
        await agent.resume_session(str(tmp_path), first)
        assert agent.sessions[first].model_id == "other"
        with pytest.raises(RequestError):
            await agent.set_config_option(first, "model", "invented")
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_plan_mode_blocks_real_tool_mutation(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = ToolManager(
        {}, lambda *_args, **_kwargs: None, fast_startup=True
    )
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    agent.on_connect(conn)

    async def process(*args, **kwargs):
        assert get_current_execution_context().agent_mode == "plan"
        result = await core.tool_manager.execute_tool_async(
            "write_file", {"path": "blocked.txt", "content": "no"}
        )
        return {"assistant_response": result}

    core.process = process
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.set_session_mode(sid, "plan")
        await agent.prompt(sid, [text_block("write")])
        assert (
            "permission_denied"
            in conn.session_update.call_args.kwargs["update"].content.text
        )
        assert not (tmp_path / "blocked.txt").exists()
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_stored_plan_fails_closed_when_enforcement_is_disabled(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = SimpleNamespace(_permission_enabled=True)
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.set_session_mode(sid, "plan")
        await agent.close_session(sid)
        core.tool_manager._permission_enabled = False
        with pytest.raises(RequestError):
            await agent.load_session(str(tmp_path), sid)
        assert sid not in agent.sessions
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_controls_reject_active_prompt(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    started, release = asyncio.Event(), asyncio.Event()

    async def process(*args, **kwargs):
        started.set()
        await release.wait()
        return {"assistant_response": "done"}

    core.process = process
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        task = asyncio.create_task(agent.prompt(sid, [text_block("go")]))
        await started.wait()
        with pytest.raises(RequestError):
            await agent.set_session_mode(sid, "build")
        with pytest.raises(RequestError):
            await agent.set_config_option(sid, "model", "default")
        release.set()
        await task
    finally:
        release.set()
        agent.close()
