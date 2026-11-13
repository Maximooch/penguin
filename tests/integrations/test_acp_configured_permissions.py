"""Configured approval rules must reach real tool dispatch."""

import asyncio
from unittest.mock import AsyncMock

import pytest

pytest.importorskip("acp")
from acp.helpers import text_block
from acp.schema import AllowedOutcome, RequestPermissionResponse
from test_acp_sessions import PersistentCore

from penguin.integrations.acp.server import PenguinACPAgent
from penguin.tools.tool_manager import ToolManager


@pytest.mark.asyncio
@pytest.mark.parametrize("choice", ["allow_once", "reject_once"])
async def test_configured_write_approval_roundtrip(tmp_path, choice):
    core = PersistentCore(tmp_path / "sessions")
    core.tool_manager = ToolManager(
        {
            "workspace_path": str(tmp_path),
            "security": {"require_approval": ["filesystem.write"]},
        },
        lambda *_: None,
        fast_startup=True,
    )
    core.tool_manager._core = core
    agent = PenguinACPAgent(core, allowed_roots=(tmp_path,))
    conn = AsyncMock()
    conn.request_permission.return_value = RequestPermissionResponse(
        outcome=AllowedOutcome(outcome="selected", option_id=choice)
    )
    agent.on_connect(conn)
    await agent.initialize(1)

    async def process(*args, **kwargs):
        result = await core.tool_manager.execute_tool_async(
            "write_file",
            {"path": str(tmp_path / "approved.txt"), "content": "approved"},
        )
        return {"assistant_response": str(result)}

    core.process = process
    try:
        sid = (await agent.new_session(str(tmp_path))).session_id
        await asyncio.wait_for(agent.prompt(sid, [text_block("write")]), 10)
        assert conn.request_permission.call_count == 1
        assert (tmp_path / "approved.txt").exists() == (choice == "allow_once")
    finally:
        agent.close()


def test_configured_process_approval_rule_is_enforced(tmp_path):
    from penguin.security.permission_engine import (
        Operation,
        PermissionResult,
    )
    from penguin.security.policies.workspace import WorkspaceBoundaryPolicy

    policy = WorkspaceBoundaryPolicy(
        workspace_root=str(tmp_path), require_approval=["process.execute"]
    )
    assert (
        policy.check_operation(Operation.PROCESS_EXECUTE, "echo hello")[0]
        is PermissionResult.ASK
    )


def test_rules_loaded_from_explicit_config_path(tmp_path, monkeypatch):
    from penguin.config import Config
    from penguin.security.permission_engine import PermissionResult

    config_file = tmp_path / "config.yml"
    config_file.write_text(
        "security:\n  require_approval: [filesystem.write]\n"
        "  denied_paths: [blocked.txt]\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_file))
    monkeypatch.setenv("PENGUIN_YOLO", "0")
    config = Config.load_config()
    manager = ToolManager(config, lambda *_: None, fast_startup=True)
    result, _ = manager.check_tool_permission(
        "write_file",
        {"path": str(tmp_path / "allowed.txt"), "content": "test"},
        {"directory": str(tmp_path)},
    )
    assert result is PermissionResult.ASK
    result, _ = manager.check_tool_permission(
        "write_file",
        {"path": str(tmp_path / "blocked.txt"), "content": "test"},
        {"directory": str(tmp_path)},
    )
    assert result is PermissionResult.DENY


def test_configured_read_only_mode_rejects_write(tmp_path):
    from penguin.security.permission_engine import PermissionResult

    manager = ToolManager(
        {"workspace_path": str(tmp_path), "security": {"mode": "read_only"}},
        lambda *_: None,
        fast_startup=True,
    )
    result, _ = manager.check_tool_permission(
        "write_file", {"path": str(tmp_path / "read-only.txt"), "content": "forbidden"}
    )
    assert result is PermissionResult.DENY


def test_invalid_policy_cannot_leave_permissive_enforcer(tmp_path):
    manager = ToolManager(
        {"workspace_path": str(tmp_path), "security": {"mode": "invalid"}},
        lambda *_: None,
        fast_startup=True,
    )
    for _ in range(2):
        with pytest.raises(ValueError):
            manager.check_tool_permission(
                "write_file",
                {"path": str(tmp_path / "invalid.txt"), "content": "forbidden"},
            )
        assert manager._permission_enforcer is None
