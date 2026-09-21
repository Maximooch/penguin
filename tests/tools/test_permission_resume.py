"""Permission boundaries and the TUI reply-to-tool execution contract."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from penguin.security.approval import ApprovalScope, get_approval_manager
from penguin.security.permission_engine import PermissionEnforcer, PermissionResult
from penguin.security.policies.workspace import WorkspaceBoundaryPolicy
from penguin.security.tool_permissions import check_tool_permission
from penguin.tools.tool_manager import ToolManager


@pytest.fixture
def permissions(tmp_path: Path):
    approvals = get_approval_manager()
    approvals.reset()
    root = tmp_path / "link"
    root.mkdir()
    sibling = tmp_path / "link-memory"
    sibling.mkdir()
    manager = ToolManager({"diagnostics": {"enabled": False}}, lambda *_: None)
    manager._permission_enabled = True
    enforcer = PermissionEnforcer()
    enforcer.add_policy(WorkspaceBoundaryPolicy(str(root), str(root)))
    manager._permission_enforcer = enforcer
    context = {
        "directory": str(root),
        "project_root": str(root),
        "workspace_root": str(root),
        "session_id": "session-a",
    }
    yield manager, approvals, context, sibling
    approvals.reset()


def test_sibling_worktree_requires_approval(permissions):
    manager, _, context, sibling = permissions
    result, _ = manager.check_tool_permission(
        "edit_file", {"path": str(sibling / "app.ts")}, context
    )
    assert result == PermissionResult.ASK


@pytest.mark.asyncio
@pytest.mark.parametrize("reply", ["once", "always", "reject"])
async def test_tui_reply_resumes_original_file_call(permissions, reply):
    manager, approvals, context, sibling = permissions
    created = asyncio.Queue()
    loop = asyncio.get_running_loop()

    def capture(request):
        assert asyncio.get_running_loop() is loop
        loop.call_soon_threadsafe(created.put_nowait, request)

    approvals.on_request_created(capture)
    target = sibling / "app.ts"
    task = asyncio.create_task(
        manager.execute_tool_async(
            "write_file", {"path": str(target), "content": "hello"}, context
        )
    )
    try:
        request = await asyncio.wait_for(created.get(), 2)
        assert not task.done(), "Tool must wait for the TUI reply"
        assert not target.exists()
        assert request.operation == "filesystem.write"
        assert request.resource == str(target.resolve())
        if reply == "reject":
            approvals.deny(request.id)
        else:
            approvals.approve(
                request.id,
                scope=(
                    ApprovalScope.ONCE if reply == "once" else ApprovalScope.PATTERN
                ),
                pattern=request.resource,
            )
        result = await asyncio.wait_for(task, 2)
        if reply == "reject":
            assert json.loads(result)["error"] == "permission_denied"
            assert not target.exists()
        else:
            assert target.exists(), result
            assert target.read_text() == "hello"
        assert not approvals.get_pending()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(capture)


def test_request_ask_cannot_mask_hard_denial(permissions):
    manager, _, context, sibling = permissions
    result, _ = check_tool_permission(
        "write_file",
        {"path": str(sibling / "app.ts")},
        manager.permission_enforcer,
        {
            **context,
            "permission_mode": "read_only",
            "approval_policy": {"fileWrite": "ask"},
        },
    )
    assert result == PermissionResult.DENY


@pytest.mark.asyncio
async def test_once_does_not_authorize_next_call_or_other_session(permissions):
    manager, approvals, context, sibling = permissions
    from penguin.web.routes import PermissionReplyAction, reply_permission_request

    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    try:
        for session in ["session-a", "session-a", "session-b"]:
            task = asyncio.create_task(
                manager.execute_tool_async(
                    "write_file",
                    {"path": str(sibling / "app.ts"), "content": session},
                    {**context, "session_id": session},
                )
            )
            request = await asyncio.wait_for(queue.get(), 2)
            assert not task.done()
            await reply_permission_request(
                request.id, PermissionReplyAction(reply="once")
            )
            await asyncio.wait_for(task, 2)
        assert (sibling / "app.ts").read_text() == "session-b"
    finally:
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
async def test_always_is_literal_target_and_session_scoped(permissions):
    manager, approvals, context, sibling = permissions
    from penguin.web.routes import PermissionReplyAction, reply_permission_request

    target = sibling / "file[1].ts"
    request = approvals.create_request(
        "write_file", "filesystem.write", str(target), "outside", "session-a"
    )
    await reply_permission_request(request.id, PermissionReplyAction(reply="always"))
    assert approvals.check_pre_approved("filesystem.write", str(target), "session-a")
    assert not approvals.check_pre_approved(
        "filesystem.write", str(sibling / "file1.ts"), "session-a"
    )
    assert not approvals.check_pre_approved(
        "filesystem.write", str(target), "session-b"
    )
    await asyncio.wait_for(
        manager.execute_tool_async(
            "write_file",
            {"path": str(target), "content": "approved"},
            context,
        ),
        2,
    )
    assert target.read_text() == "approved"
    assert not approvals.get_pending()


@pytest.mark.asyncio
@pytest.mark.parametrize("termination", ["cancel", "expire"])
async def test_unanswered_requests_do_not_write_or_remain_pending(
    permissions, termination
):
    manager, approvals, context, sibling = permissions
    from datetime import datetime, timedelta

    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    target = sibling / "app.ts"
    task = asyncio.create_task(
        manager.execute_tool_async(
            "write_file",
            {"path": str(target), "content": "no"},
            context,
        )
    )
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        if termination == "cancel":
            task.cancel()
            with pytest.raises(asyncio.CancelledError):
                await task
        else:
            request.expires_at = datetime.utcnow() - timedelta(seconds=1)
            result = await asyncio.wait_for(task, 2)
            assert json.loads(result)["error"] == "permission_denied"
        assert not target.exists()
        assert not approvals.get_pending()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "tool,args,expected",
    [
        (
            "edit_file",
            {"path": "../link-memory/app.ts", "old_string": "old", "new_string": "new"},
            "new",
        ),
        (
            "apply_patch",
            {
                "patch": (
                    "*** Begin Patch\n*** Update File: ../link-memory/app.ts\n"
                    "@@\n-old\n+new\n*** End Patch"
                )
            },
            "new\n",
        ),
        (
            "create_file",
            {"path": "../link-memory/created.ts", "content": "new"},
            "old\n",
        ),
    ],
)
async def test_sibling_edit_tools_share_approval_boundary(
    permissions, tool, args, expected
):
    manager, approvals, context, sibling = permissions
    (sibling / "app.ts").write_text("old\n" if tool != "edit_file" else "old")
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(manager.execute_tool_async(tool, args, context))
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        approvals.approve(request.id)
        result = await asyncio.wait_for(task, 2)
        assert (sibling / "app.ts").read_text() == expected, result
        if tool == "create_file":
            assert (sibling / "created.ts").read_text() == "new", result
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


def test_multi_file_and_command_approval_identity(permissions):
    from penguin.security.tool_approval import approval_identity

    _, _, context, sibling = permissions
    operation, resource, resources = approval_identity(
        "apply_patch",
        {
            "patch": (
                "*** Begin Patch\n*** Add File: ../link-memory/a.ts\n+a\n"
                "*** Add File: ../link-memory/b.ts\n+b\n*** End Patch"
            )
        },
        context,
    )
    assert operation == "filesystem.write"
    assert resources == [str(sibling / "a.ts"), str(sibling / "b.ts")]
    assert json.loads(resource) == resources
    operation, resource, _ = approval_identity(
        "execute_command",
        {"command": "python -c 'print(1)'", "directory": context["directory"]},
        context,
    )
    assert operation == "process.execute"
    assert resource == "python -c 'print(1)'"


@pytest.mark.asyncio
async def test_approval_does_not_leak_to_concurrent_session(permissions):
    manager, approvals, context, sibling = permissions
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    tasks = []
    try:
        for session in ["session-a", "session-b"]:
            tasks.append(
                asyncio.create_task(
                    manager.execute_tool_async(
                        "write_file",
                        {"path": str(sibling / f"{session}.ts"), "content": session},
                        {**context, "session_id": session},
                    )
                )
            )
        first = await asyncio.wait_for(queue.get(), 2)
        second = await asyncio.wait_for(queue.get(), 2)
        approvals.approve(first.id)
        index = 0 if first.session_id == "session-a" else 1
        await asyncio.wait_for(tasks[index], 2)
        assert not tasks[1 - index].done()
        assert not (sibling / f"{second.session_id}.ts").exists()
        approvals.deny(second.id)
        await asyncio.wait_for(tasks[1 - index], 2)
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
async def test_changed_symlink_cannot_expand_approved_targets(permissions):
    manager, approvals, context, sibling = permissions
    original = sibling / "original.ts"
    original.write_text("original")
    alternate = sibling / "alternate.ts"
    alternate.write_text("alternate")
    link = sibling / "link.ts"
    link.symlink_to(original)
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(
        manager.execute_tool_async(
            "write_file",
            {"path": str(link), "content": "changed"},
            context,
        )
    )
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        assert request.resource == str(original)
        link.unlink()
        link.symlink_to(alternate)
        approvals.approve(request.id)
        await asyncio.wait_for(task, 2)
        assert alternate.read_text() == "alternate"
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
async def test_approved_command_keeps_grant_through_cancellation_context(permissions):
    """Process cancellation metadata must not invalidate a one-call approval."""
    manager, approvals, context, _ = permissions
    context = {**context, "approval_policy": {"shell": "ask"}}
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(
        manager.execute_tool_async(
            "execute_command",
            {"command": "printf approved"},
            context,
        )
    )
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        approvals.approve(request.id)
        result = await asyncio.wait_for(task, 2)
        assert isinstance(result, dict), result
        assert result["output"].strip() == "[stdout] approved"
        assert result["returncode"] == 0
        assert not approvals.get_pending()
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)
        manager.process_tools.cleanup()
