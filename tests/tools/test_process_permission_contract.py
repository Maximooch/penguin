"""Offline process permission contracts; no shell commands are launched."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.security.approval import ApprovalScope, get_approval_manager
from penguin.security.permission_engine import PermissionEnforcer
from penguin.security.tool_approval import authorized_call, is_call_authorized
from penguin.security.tool_permissions import extract_resources_from_input
from penguin.tools.process_tools import ProcessTools
from penguin.tools.tool_manager import ToolManager


@pytest.fixture
def contract(tmp_path, monkeypatch):
    monkeypatch.delenv("PENGUIN_YOLO", raising=False)
    approvals = get_approval_manager()
    approvals.reset()
    manager = ToolManager({}, lambda *_: None, fast_startup=True)
    manager._permission_enabled = True
    manager._permission_enforcer = PermissionEnforcer()
    service = Mock()
    service.execute.return_value = {"status": "completed"}
    manager._process_tools = service
    context = {
        "session_id": "one",
        "agent_id": "agent",
        "directory": str(tmp_path),
        "approval_policy": {"shell": "ask"},
    }
    yield manager, approvals, context, service
    approvals.reset()


@pytest.mark.parametrize(
    "name,args",
    [
        ("execute_command", {"command": "test"}),
        ("process_start", {"command": "test"}),
        ("process_write_stdin", {"process_id": "p", "text": "yes"}),
        ("process_stop", {"process_id": "p"}),
    ],
)
def test_process_asks_are_not_reusable_session_grants(contract, name, args):
    manager, approvals, ctx, service = contract
    first = json.loads(manager.execute_tool(name, args, ctx))
    approvals.approve(first["approval_id"], scope=ApprovalScope.SESSION)
    second = json.loads(manager.execute_tool(name, args, ctx))
    assert second["status"] == "pending_approval"
    assert second["approval_id"] != first["approval_id"]
    service.execute.assert_not_called()


@pytest.mark.parametrize(
    "name,args",
    [
        ("process_start", {"command": "test"}),
        ("process_write_stdin", {"process_id": "p", "text": "yes"}),
        ("process_stop", {"process_id": "p"}),
    ],
)
def test_new_policy_applies_to_each_operation(contract, name, args):
    manager, _, ctx, service = contract
    assert (
        manager.execute_tool(
            name, args, {**ctx, "approval_policy": {"shell": "allow"}}
        )["status"]
        == "completed"
    )
    service.reset_mock()
    result = manager.execute_tool(name, args, {**ctx, "permission_mode": "read_only"})
    assert json.loads(result)["error"] == "permission_denied"
    service.execute.assert_not_called()


@pytest.mark.asyncio
@pytest.mark.parametrize("name", ["execute_command", "process_start"])
@pytest.mark.parametrize("cwd", [None, "child"])
async def test_approval_and_launch_share_resolved_cwd(contract, name, cwd):
    manager, approvals, ctx, service = contract
    args = {"command": "test", "cwd": cwd}
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(manager.execute_tool_async(name, args, ctx))
    try:
        request = await asyncio.wait_for(queue.get(), 3)
        expected = str((Path(ctx["directory"]) / (cwd or "")).resolve())
        assert request.context["tool_input"]["cwd"] == expected
        approvals.approve(request.id)
        await asyncio.wait_for(task, 3)
        assert service.execute.call_args.args[1]["cwd"] == expected
        assert not approvals.get_pending()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.parametrize(
    "changed",
    [{"agent_id": "child"}, {"session_id": "two"}, {"permission_mode": "read_only"}],
)
def test_dispatch_grant_cannot_transfer(changed):
    ctx = {"agent_id": "agent", "session_id": "one"}
    args = {"process_id": "p", "text": "yes"}
    with authorized_call("process_write_stdin", args, ctx, ["p"]):
        assert is_call_authorized("process_write_stdin", args, ctx)
        assert not is_call_authorized("process_write_stdin", args, {**ctx, **changed})
        assert not is_call_authorized(
            "process_write_stdin", {**args, "text": "no"}, ctx
        )
    assert not is_call_authorized("process_write_stdin", args, ctx)


@pytest.mark.parametrize(
    "name", ["process_poll", "process_write_stdin", "process_stop"]
)
@pytest.mark.parametrize("owner", [("two", "agent"), ("one", "child")])
def test_service_ownership_blocks_other_sessions_and_agents(name, owner):
    runtime = Mock()
    runtime._processes = {"p": SimpleNamespace(owner=("one", "agent"))}
    runtime._error.return_value = {"error": "unknown_process_id"}
    service = ProcessTools(runtime)
    try:
        result = service.execute(
            name,
            {"process_id": "p", "text": "yes"},
            {"session_id": owner[0], "agent_id": owner[1]},
        )
        assert result["error"] == "unknown_process_id"
        runtime.poll.assert_not_called()
        runtime.write_stdin.assert_not_called()
        runtime.stop.assert_not_called()
    finally:
        service.cleanup()


def test_poll_policy_targets_handle_not_generic_tool():
    assert extract_resources_from_input("process_poll", {"process_id": "p"}) == ["p"]


@pytest.mark.asyncio
@pytest.mark.parametrize("resolution", ["deny", "expire", "mode_change"])
async def test_unusable_approval_never_dispatches(contract, resolution):
    from datetime import datetime, timedelta

    manager, approvals, ctx, service = contract
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(
        manager.execute_tool_async("process_stop", {"process_id": "p"}, ctx)
    )
    try:
        request = await asyncio.wait_for(queue.get(), 3)
        if resolution == "deny":
            approvals.deny(request.id)
        elif resolution == "expire":
            request.expires_at = datetime.utcnow() - timedelta(seconds=1)
        else:
            # A newly installed hard-deny policy must beat the outstanding grant.
            from penguin.security.permission_engine import (
                PermissionResult,
                PolicyEngine,
            )

            class Deny(PolicyEngine):
                def check_operation(self, operation, resource, context=None):
                    return PermissionResult.DENY, "mode changed"

            manager.permission_enforcer.add_policy(Deny())
            approvals.approve(request.id)
        result = await asyncio.wait_for(task, 3)
        assert json.loads(result)["error"] == "permission_denied"
        service.execute.assert_not_called()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


def test_poll_remains_available_in_read_only_mode(contract):
    manager, _, ctx, service = contract
    result = manager.execute_tool(
        "process_poll", {"process_id": "p"}, {**ctx, "permission_mode": "read_only"}
    )
    assert result["status"] == "completed"
    service.execute.assert_called_once()
