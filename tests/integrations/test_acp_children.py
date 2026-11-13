"""Draft child-session negotiation over raw ACP stdio with runtime producers."""

# ruff: noqa: E402 -- optional dependency gate.
import asyncio
import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

acp = pytest.importorskip("acp")
from acp.helpers import text_block
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore

from penguin.core_runtime import agent_lifecycle
from penguin.integrations.acp.server import PenguinACPAgent

_AGENT = """
import os, sys, types
from pathlib import Path
sys.path.insert(0, str(Path.cwd() / 'tests' / 'integrations'))
from test_acp_sessions import PersistentCore
from penguin.core_runtime import agent_lifecycle
module = types.ModuleType('penguin.core')
class Core(PersistentCore):
    @classmethod
    async def create(cls, **kwargs):
        return cls(Path(os.environ['ACP_TEST_STORE']))
    async def emit_ui_event(self, kind, data):
        await self.event_bus.emit(kind, data)
    async def process(self, *args, agent_id=None, **kwargs):
        if agent_id:
            await self.event_bus.emit('action', {
                'session_id': 'child-session', 'id': 'child-tool',
                'type': 'read_file'})
            await self.event_bus.emit('action_result', {
                'session_id': 'child-session', 'id': 'child-tool',
                'status': 'completed', 'result': 'child file'})
            return {'assistant_response': 'child answer'}
        await agent_lifecycle.run_agent_prompt_in_session(
            self, 'worker', 'investigate', session_id='child-session',
            directory=os.environ['PENGUIN_WORKSPACE'])
        return {'assistant_response': 'parent answer'}
agent_lifecycle.resolve_agent_execution_scope = lambda core, agent, **kw: {
    'session_id': kw['session_id'], 'conversation_id': kw['session_id'],
    'directory': kw['directory'], 'project_root': kw['directory'],
    'workspace_root': kw['directory'], 'agent_mode': 'build'}
module.PenguinCore = Core
sys.modules['penguin.core'] = module
from penguin.cli.entrypoint import main
raise SystemExit(main(['acp']))
"""


@pytest.mark.asyncio
@pytest.mark.parametrize("native", [False, True])
async def test_runtime_child_events_negotiate_and_replay(tmp_path, native):
    updates = []

    async def handler(method, params, is_notification):
        if method == "session/update":
            updates.append(params)
        return None

    env = {
        **os.environ,
        "PENGUIN_WORKSPACE": str(tmp_path),
        "ACP_TEST_STORE": str(tmp_path / "sessions"),
    }
    async with spawn_stdio_connection(
        handler, sys.executable, "-c", _AGENT, env=env
    ) as (conn, _):
        await asyncio.wait_for(
            conn.send_request(
                "initialize",
                {
                    "protocolVersion": 1,
                    "clientCapabilities": {"subagents": {}} if native else {},
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
            "session/prompt",
            {"sessionId": sid, "prompt": [{"type": "text", "text": "spawn"}]},
        )
        if native:
            association = next(
                i
                for i, item in enumerate(updates)
                if item["update"]["sessionUpdate"] == "subagent_update"
            )
            child_updates = [
                i
                for i, item in enumerate(updates)
                if item["sessionId"] == "child-session"
            ]
            assert child_updates and association < min(child_updates)
            assert any(
                item["update"].get("state")
                == {"state": "idle", "stopReason": "end_turn"}
                for item in updates
            )
            assert any(
                item["update"]["sessionUpdate"] == "tool_call_update"
                and item["sessionId"] == "child-session"
                for item in updates
            )
            before = len(updates)
            await conn.send_request(
                "session/load",
                {"sessionId": sid, "cwd": str(tmp_path), "mcpServers": []},
            )
            replay = updates[before:]
            assert any(
                item["update"]["sessionUpdate"] == "session_message" for item in replay
            )
            assert all(
                not item["update"].get("capabilities")
                for item in replay
                if item["update"]["sessionUpdate"] == "subagent_update"
            )
        else:
            assert not any(
                item["update"]["sessionUpdate"] == "subagent_update" for item in updates
            )
            assert all(item["sessionId"] == sid for item in updates)
            assert any(
                item["update"].get("toolCallId") == "child:child-session"
                for item in updates
            )


@pytest.mark.asyncio
async def test_background_child_can_be_cancelled_without_stopping_parent(
    tmp_path, monkeypatch
):
    core = PersistentCore(tmp_path / "sessions")
    core.emit_ui_event = core.event_bus.emit
    monkeypatch.setattr(
        agent_lifecycle,
        "resolve_agent_execution_scope",
        lambda *_args, **_kwargs: {
            "session_id": "child",
            "conversation_id": "child",
            "directory": str(tmp_path),
            "project_root": str(tmp_path),
            "workspace_root": str(tmp_path),
            "agent_mode": "build",
        },
    )
    started = asyncio.Event()

    async def process(*args, **kwargs):
        if kwargs.get("agent_id"):
            started.set()
            await asyncio.Event().wait()
        child_task = asyncio.create_task(
            agent_lifecycle.run_agent_prompt_in_session(core, "worker", "work")
        )
        assert child_task is not None
        await started.wait()
        return {"assistant_response": "delegated"}

    core.process = process
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    agent._transport = SimpleNamespace(subagents=True, send=AsyncMock())
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await agent.prompt(sid, [text_block("spawn")])
        assert agent._children.children["child"].cancellable
        await agent.cancel("child")
        assert not agent._children.children["child"].active
        states = [
            c.args[0]["params"]["update"].get("state")
            for c in agent._transport.send.call_args_list
        ]
        assert {"state": "idle", "stopReason": "cancelled"} in states
        core.process = AsyncMock(return_value={"assistant_response": "still usable"})
        assert (
            await agent.prompt(sid, [text_block("again")])
        ).stop_reason == "end_turn"
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_nested_replay_preserves_parentage_and_current_store(tmp_path):
    core = PersistentCore(tmp_path / "sessions")
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    agent.on_connect(AsyncMock())
    transport = SimpleNamespace(subagents=True, send=AsyncMock())
    agent._transport = transport
    try:
        root = (await agent.new_session(str(tmp_path))).session_id
        other = (await agent.new_session(str(tmp_path))).session_id
        for parent, child in ((root, "child"), ("child", "grandchild")):
            await core.event_bus.emit(
                "agent.lifecycle",
                {
                    "parent_session_id": parent,
                    "session_id": child,
                    "agent_id": child,
                    "state": "running",
                    "directory": str(tmp_path),
                },
            )
        assert core.store.current_session.id == other
        history = agent._registry.history(agent._registry.get(root))
        transport.send.reset_mock()
        for update in history:
            if isinstance(update, dict):
                await agent._children.replay(root, update)
        await agent._children.finish_replay(root)
        grandchild_updates = [
            call.args[0]["params"]
            for call in transport.send.call_args_list
            if call.args[0]["params"]["update"].get("sessionId") == "grandchild"
        ]
        assert grandchild_updates
        assert all(item["sessionId"] == "child" for item in grandchild_updates)
    finally:
        agent.close()
