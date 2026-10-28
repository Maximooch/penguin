"""Exact-resource permission retention without policy or agent bypass."""

import asyncio
import os
import sys
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from acp.schema import AllowedOutcome, RequestPermissionResponse
from acp.stdio import spawn_stdio_connection
from test_acp_sessions import PersistentCore
from test_acp_wire import _CLI_AGENT

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.security.approval import get_approval_manager
from penguin.security.permission_engine import PermissionResult
from penguin.tools.tool_manager import ToolManager


def core_for(path, workspace):
    core = PersistentCore(path)
    core.tool_manager = ToolManager(
        {"workspace_path": str(workspace)}, lambda *_: None, fast_startup=True
    )
    core.tool_manager.check_tool_permission = lambda *_: (
        PermissionResult.ASK,
        "confirm",
    )
    core.tool_manager._permission_enabled = True
    return core


@pytest.mark.asyncio
async def test_saved_exact_grant_survives_reload_but_not_policy_deny(tmp_path):
    approvals = get_approval_manager()
    approvals.reset()
    core = core_for(tmp_path / "store", tmp_path)
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_saved")
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    sid = (await agent.new_session(str(tmp_path))).session_id
    file = tmp_path / "literal[1].txt"
    value = "one"
    results = []

    async def process(*args, **kwargs):
        results.append(
            await core.tool_manager.execute_tool_async(
                "write_file", {"path": str(file), "content": value}
            )
        )
        return {"assistant_response": "done"}

    core.process = process
    try:
        await agent.prompt(sid, [text_block("write")])
        assert file.read_text() == "one"
        value = "two"
        await agent.prompt(sid, [text_block("write again")])
        assert file.read_text() == "two"
        assert conn.request_permission.call_count == 1
        core.tool_manager.check_tool_permission = lambda *_: (
            PermissionResult.DENY,
            "new policy",
        )
        value = "denied"
        await agent.prompt(sid, [text_block("policy")])
        assert file.read_text() == "two"
        assert "permission_denied" in str(results[-1])
        assert conn.request_permission.call_count == 1
        await agent.close_session(sid)
    finally:
        agent.close()

    core = core_for(tmp_path / "store", tmp_path)
    second = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn2 = AsyncMock()
    conn2.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="reject_once")
    )
    second.on_connect(conn2)
    await second.initialize(1)
    core.process = process
    try:
        await second.load_session(str(tmp_path), sid)
        value = "after reload"
        await second.prompt(sid, [text_block("write")])
        assert file.read_text() == value
        conn2.request_permission.assert_not_called()
        await second.prompt(sid, [text_block("/permissions reset")])
        value = "rejected"
        await second.prompt(sid, [text_block("write")])
        assert conn2.request_permission.call_count == 1
        assert file.read_text() == "after reload"
    finally:
        second.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("operation", ["process.execute", "filesystem.delete"])
async def test_unsafe_operations_cannot_forge_remembered_approval(tmp_path, operation):
    manager = get_approval_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_saved")
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    sid = (await agent.new_session(str(tmp_path))).session_id
    request = manager.create_request(
        "danger", operation, str(tmp_path / "file"), "test", session_id=sid
    )
    try:
        for _ in range(100):
            if manager.get_request(request.id).status.value != "pending":
                break
            await asyncio.sleep(0.005)
        assert manager.get_request(request.id).status.value == "denied"
        assert not agent._grants.saved
        assert {
            o.option_id for o in conn.request_permission.call_args.kwargs["options"]
        } == {"allow_once", "reject_once"}
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_real_cli_permission_remember_choice_is_scoped(tmp_path):
    script = _CLI_AGENT.replace(
        "        self.model_config = types.SimpleNamespace(vision_enabled=True)",
        """
        self.model_config = types.SimpleNamespace(vision_enabled=True)
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
        if text.startswith('save'):
            result = await self.tool_manager.execute_tool_async('write_file', {
                'path': str(Path(os.environ['PENGUIN_WORKSPACE']) / 'shared.txt'),
                'content': text})
            return {'assistant_response': str(result)}
""",
    )
    requests = []
    updates = []

    async def handler(method, params, notification):
        if method == "session/update":
            updates.append(params)
        if method == "session/request_permission":
            requests.append(params)
            return {"outcome": {"outcome": "selected", "optionId": "allow_saved"}}

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
        for text in ("save one", "save two"):
            await conn.send_request(
                "session/prompt",
                {"sessionId": sid, "prompt": [{"type": "text", "text": text}]},
            )
    assert len(requests) == 1, updates
    assert "allow_saved" in {o["optionId"] for o in requests[0]["options"]}
    assert (tmp_path / "shared.txt").read_text() == "save two"


@pytest.mark.asyncio
async def test_ephemeral_grant_is_exact_and_closes_with_session(tmp_path):
    manager = get_approval_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id="allow_session")
    )
    agent.on_connect(conn)
    await agent.initialize(1)
    sid = (await agent.new_session(str(tmp_path))).session_id

    def request(path, agent_id="one"):
        return manager.create_request(
            "write_file",
            "filesystem.write",
            str(path),
            "test",
            session_id=sid,
            context={"agent_id": agent_id},
        )

    async def resolved(req):
        for _ in range(100):
            if manager.get_request(req.id).status.value != "pending":
                return
            await asyncio.sleep(0.005)
        raise AssertionError("not resolved")

    try:
        one = request(tmp_path / "literal[1].txt")
        await resolved(one)
        await resolved(request(tmp_path / "literal[1].txt"))
        assert conn.request_permission.call_count == 1
        await resolved(request(tmp_path / "literal1.txt"))
        await resolved(request(tmp_path / "literal[1].txt", "two"))
        assert conn.request_permission.call_count == 3
        await agent.close_session(sid)
        await agent.load_session(str(tmp_path), sid)
        await resolved(request(tmp_path / "literal[1].txt"))
        assert conn.request_permission.call_count == 4
    finally:
        agent.close()


@pytest.mark.asyncio
async def test_cancelled_permission_cannot_create_a_saved_grant(tmp_path):
    manager = get_approval_manager()
    manager.reset()
    agent = PenguinACPAgent(
        PersistentCore(tmp_path / "store"), allowed_roots=(tmp_path,)
    )
    conn = AsyncMock()
    started = asyncio.Event()

    async def permission(**kwargs):
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            return RequestPermissionResponse(
                outcome=AllowedOutcome(outcome="selected", option_id="allow_saved")
            )

    conn.request_permission.side_effect = permission
    agent.on_connect(conn)
    await agent.initialize(1)
    sid = (await agent.new_session(str(tmp_path))).session_id
    request = manager.create_request(
        "write_file", "filesystem.write", str(tmp_path / "file"), "test", session_id=sid
    )
    try:
        await asyncio.wait_for(started.wait(), 2)
        await agent.cancel(sid)
        await asyncio.gather(*agent._approval_tasks, return_exceptions=True)
        assert manager.get_request(request.id).status.value == "denied"
        assert not agent._grants.saved
        assert "acp_exact_grants_v1" not in agent._registry.get(sid).metadata
    finally:
        agent.close()
