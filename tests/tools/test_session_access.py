"""Local full-access settings, isolation, and in-flight approval transitions."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from penguin.security.approval import get_approval_manager
from penguin.security.permission_engine import PermissionEnforcer
from penguin.security.policies.agent_mode import AgentModePolicy
from penguin.security.policies.workspace import WorkspaceBoundaryPolicy
from penguin.security.session_access import (
    apply_session_access,
    get_session_access,
    set_session_access,
)
from penguin.system.session_manager import SessionManager
from penguin.tools.tool_manager import ToolManager
from penguin.web.routes import (
    SessionAccessRequest,
    get_session_access_settings,
    update_session_access_settings,
)


@pytest.fixture
def runtime(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    outside = tmp_path / "worktree"
    outside.mkdir()
    sessions = SessionManager(base_path=str(tmp_path / "sessions"))
    first = sessions.create_session()
    second = sessions.create_session()
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(session_manager=sessions)
    )
    tools = ToolManager({"diagnostics": {"enabled": False}}, lambda *_: None)
    tools._permission_enabled = True
    tools._permission_enforcer = PermissionEnforcer()
    tools._permission_enforcer.add_policy(WorkspaceBoundaryPolicy(str(root), str(root)))
    tools._permission_enforcer.add_policy(AgentModePolicy())
    context = {
        "directory": str(root),
        "project_root": str(root),
        "workspace_root": str(root),
        "session_id": first.id,
    }
    approvals = get_approval_manager()
    approvals.reset()
    yield core, tools, context, second.id, outside
    set_session_access(first.id, "workspace")
    set_session_access(second.id, "workspace")
    approvals.reset()


@pytest.mark.asyncio
async def test_full_access_writes_multiple_external_files_without_prompts(runtime):
    core, tools, ctx, other, outside = runtime
    assert (await get_session_access_settings(ctx["session_id"], core))[
        "mode"
    ] == "workspace"
    response = await update_session_access_settings(
        ctx["session_id"], SessionAccessRequest(mode="full_access"), core
    )
    assert response["mode"] == "full_access"
    for name in ["first.ts", "second.ts", ".env"]:
        result = await asyncio.wait_for(
            tools.execute_tool_async(
                "write_file",
                {"path": str(outside / name), "content": name},
                ctx,
            ),
            2,
        )
        assert (outside / name).read_text() == name, result
    assert not get_approval_manager().get_pending()
    assert get_session_access(other) == "workspace"
    assert get_session_access("new-session") == "workspace"


@pytest.mark.asyncio
async def test_enable_full_access_resumes_pending_call_and_revoke_restores_prompt(
    runtime,
):
    core, tools, ctx, _, outside = runtime
    approvals = get_approval_manager()
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(
        tools.execute_tool_async(
            "write_file",
            {"path": str(outside / "first.ts"), "content": "first"},
            ctx,
        )
    )
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        assert request.context["can_enable_full_access"] is True
        await update_session_access_settings(
            ctx["session_id"], SessionAccessRequest(mode="full_access"), core
        )
        await asyncio.wait_for(task, 2)
        assert (outside / "first.ts").read_text() == "first"
        await update_session_access_settings(
            ctx["session_id"], SessionAccessRequest(mode="workspace"), core
        )
        task = asyncio.create_task(
            tools.execute_tool_async(
                "write_file",
                {"path": str(outside / "second.ts"), "content": "second"},
                ctx,
            )
        )
        request = await asyncio.wait_for(queue.get(), 2)
        assert not (outside / "second.ts").exists()
        approvals.deny(request.id)
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "restriction",
    [
        {"agent_mode": "plan"},
        {"permission_mode": "read_only"},
        {"approval_policy": {"fileWrite": "deny"}},
    ],
)
async def test_full_access_preserves_explicit_execution_restrictions(
    runtime, restriction
):
    core, tools, ctx, _, outside = runtime
    await update_session_access_settings(
        ctx["session_id"], SessionAccessRequest(mode="full_access"), core
    )
    result = await tools.execute_tool_async(
        "write_file",
        {"path": str(outside / "blocked.ts"), "content": "no"},
        {**ctx, **restriction},
    )
    assert json.loads(result)["error"] == "permission_denied"
    assert not (outside / "blocked.ts").exists()


@pytest.mark.asyncio
async def test_local_full_access_cannot_approve_external_policy_request(runtime):
    core, tools, ctx, _, outside = runtime
    approvals = get_approval_manager()
    queue = asyncio.Queue()
    approvals.on_request_created(queue.put_nowait)
    task = asyncio.create_task(
        tools.execute_tool_async(
            "write_file",
            {"path": str(outside / "external.ts"), "content": "no"},
            {**ctx, "approval_policy": {"fileWrite": "ask"}},
        )
    )
    try:
        request = await asyncio.wait_for(queue.get(), 2)
        assert request.context["can_enable_full_access"] is False
        await update_session_access_settings(
            ctx["session_id"], SessionAccessRequest(mode="full_access"), core
        )
        assert approvals.get_request(request.id).status.value == "pending"
        assert not (outside / "external.ts").exists()
        approvals.deny(request.id)
        await asyncio.wait_for(task, 2)
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)
        approvals.remove_callback(queue.put_nowait)


@pytest.mark.asyncio
async def test_missing_session_and_invalid_mode_are_rejected(runtime):
    core, _, _, _, _ = runtime
    with pytest.raises(HTTPException) as error:
        await update_session_access_settings(
            "missing", SessionAccessRequest(mode="full_access"), core
        )
    assert error.value.status_code == 404
    assert get_session_access("missing") == "workspace"
    with pytest.raises(ValidationError):
        SessionAccessRequest(mode="arbitrary")


def test_reusing_context_after_revocation_drops_full_access(runtime):
    _, _, ctx, _, _ = runtime
    set_session_access(ctx["session_id"], "full_access")
    overlaid = apply_session_access(ctx)
    assert overlaid["permission_mode"] == "full_access"
    restricted = apply_session_access({**overlaid, "permission_mode": "read_only"})
    assert restricted["permission_mode"] == "read_only"
    set_session_access(ctx["session_id"], "workspace")
    assert apply_session_access(overlaid).get("permission_mode") is None


@pytest.mark.asyncio
async def test_full_access_command_and_session_specific_approval_reset(runtime):
    core, tools, ctx, other, _ = runtime
    approvals = get_approval_manager()
    approvals.pre_approve("filesystem.write", session_id=ctx["session_id"])
    approvals.pre_approve("filesystem.write", session_id=other)
    await update_session_access_settings(
        ctx["session_id"], SessionAccessRequest(mode="full_access"), core
    )
    try:
        result = await asyncio.wait_for(
            tools.execute_tool_async(
                "execute_command",
                {"command": "printf full-access"},
                ctx,
            ),
            2,
        )
        assert result["returncode"] == 0
        assert "full-access" in result["output"]
        assert not approvals.get_pending()
    finally:
        tools.process_tools.cleanup()
    await update_session_access_settings(
        ctx["session_id"], SessionAccessRequest(mode="workspace"), core
    )
    assert not approvals.check_pre_approved(
        "filesystem.write", "file", ctx["session_id"]
    )
    assert approvals.check_pre_approved("filesystem.write", "file", other)
