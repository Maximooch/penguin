from pathlib import Path

from penguin.security.permission_engine import (
    PermissionEnforcer,
    PermissionMode,
    PermissionResult,
)
from penguin.security.policies.workspace import WorkspaceBoundaryPolicy
from penguin.security.tool_permissions import check_tool_permission


def _enforcer(root: Path) -> PermissionEnforcer:
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
    enforcer.add_policy(
        WorkspaceBoundaryPolicy(
            workspace_root=root,
            project_root=root,
            mode=PermissionMode.WORKSPACE,
        )
    )
    return enforcer


def _policy(decision: str) -> dict:
    return {
        "shell": decision,
        "fileWrite": decision,
        "fileDelete": decision,
        "gitPush": decision,
        "network": decision,
        "secrets": decision,
        "allowLists": {},
    }


def test_link_read_only_turn_denies_file_writes(tmp_path: Path) -> None:
    result, _reason = check_tool_permission(
        "write_file",
        {"path": str(tmp_path / "blocked.txt")},
        _enforcer(tmp_path),
        {
            "permission_mode": "read_only",
            "approval_policy": _policy("deny"),
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.DENY


def test_link_workspace_turn_preserves_ask_decisions(tmp_path: Path) -> None:
    result, _reason = check_tool_permission(
        "execute_command",
        {"command": "pnpm test"},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": _policy("ask"),
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.ASK


def test_link_full_access_turn_can_relax_workspace_runtime_mode(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-link-policy.txt"
    result, _reason = check_tool_permission(
        "write_file",
        {"path": str(outside)},
        _enforcer(tmp_path),
        {
            "permission_mode": "full_access",
            "approval_policy": _policy("allow"),
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.ALLOW
