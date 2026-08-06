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


def _policy(
    decision: str,
    *,
    permission_mode: str = "workspace",
    allow_lists: dict[str, list[str]] | None = None,
) -> dict:
    return {
        "permissionMode": permission_mode,
        "shell": decision,
        "fileWrite": decision,
        "fileDelete": decision,
        "gitPush": decision,
        "network": decision,
        "secrets": decision,
        "allowLists": allow_lists or {},
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


def test_link_shell_deny_covers_persistent_process_tools(tmp_path: Path) -> None:
    context = {
        "permission_mode": "workspace",
        "approval_policy": _policy("deny"),
        "directory": str(tmp_path),
    }

    for tool_name, tool_input in (
        ("process_start", {"command": "pnpm dev"}),
        ("process_write_stdin", {"process_id": "proc-1", "text": "yes\n"}),
        ("process_stop", {"process_id": "proc-1"}),
    ):
        result, _reason = check_tool_permission(
            tool_name,
            tool_input,
            _enforcer(tmp_path),
            context,
        )

        assert result == PermissionResult.DENY


def test_link_process_poll_remains_read_only_when_shell_is_denied(
    tmp_path: Path,
) -> None:
    result, _reason = check_tool_permission(
        "process_poll",
        {"process_id": "proc-1"},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": _policy("deny"),
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.ALLOW


def test_link_approve_safe_actions_allows_matching_shell_pattern(
    tmp_path: Path,
) -> None:
    policy = _policy(
        "ask",
        permission_mode="approve_safe_actions",
        allow_lists={"shellCommands": ["pnpm test --filter *"]},
    )
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    allowed, _reason = check_tool_permission(
        "execute_command",
        {"command": "pnpm test --filter unit"},
        _enforcer(tmp_path),
        context,
    )
    unmatched, _reason = check_tool_permission(
        "execute_command",
        {"command": "pnpm build"},
        _enforcer(tmp_path),
        context,
    )

    assert allowed == PermissionResult.ALLOW
    assert unmatched == PermissionResult.ASK


def test_link_shell_patterns_do_not_span_shell_control_operators(
    tmp_path: Path,
) -> None:
    policy = _policy(
        "ask",
        permission_mode="approve_safe_actions",
        allow_lists={"shellCommands": ["pnpm test *"]},
    )

    result, _reason = check_tool_permission(
        "execute_command",
        {"command": "pnpm test unit && rm -rf build"},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": policy,
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.ASK


def test_link_custom_policy_matches_relative_writable_paths(tmp_path: Path) -> None:
    policy = _policy(
        "ask",
        permission_mode="custom",
        allow_lists={"writablePaths": ["src"]},
    )
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    allowed, _reason = check_tool_permission(
        "write_file",
        {"path": str(tmp_path / "src" / "app.py")},
        _enforcer(tmp_path),
        context,
    )
    unmatched, _reason = check_tool_permission(
        "write_file",
        {"path": str(tmp_path / "secrets.txt")},
        _enforcer(tmp_path),
        context,
    )

    assert allowed == PermissionResult.ALLOW
    assert unmatched == PermissionResult.ASK


def test_link_custom_policy_matches_network_hosts_not_full_urls(
    tmp_path: Path,
) -> None:
    policy = _policy(
        "ask",
        permission_mode="custom",
        allow_lists={"networkHosts": ["api.github.com", "*.example.com"]},
    )
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    exact, _reason = check_tool_permission(
        "browser_navigate",
        {"url": "https://api.github.com/repos/Maximooch/penguin"},
        _enforcer(tmp_path),
        context,
    )
    wildcard, _reason = check_tool_permission(
        "browser_navigate",
        {"url": "https://docs.example.com/guide"},
        _enforcer(tmp_path),
        context,
    )
    unmatched, _reason = check_tool_permission(
        "browser_navigate",
        {"url": "https://example.net"},
        _enforcer(tmp_path),
        context,
    )

    assert exact == PermissionResult.ALLOW
    assert wildcard == PermissionResult.ALLOW
    assert unmatched == PermissionResult.ASK


def test_link_git_push_deny_cannot_be_bypassed_through_shell(
    tmp_path: Path,
) -> None:
    policy = _policy("allow")
    policy["gitPush"] = "deny"

    result, _reason = check_tool_permission(
        "execute_command",
        {"command": "git push origin main"},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": policy,
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.DENY


def test_link_git_push_deny_dominates_shell_approval(
    tmp_path: Path,
) -> None:
    policy = _policy("ask")
    policy["gitPush"] = "deny"

    result, _reason = check_tool_permission(
        "execute_command",
        {"command": "git push origin main"},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": policy,
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.DENY


def test_link_git_push_deny_covers_nested_and_persistent_shells(
    tmp_path: Path,
) -> None:
    policy = _policy("allow")
    policy["gitPush"] = "deny"
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    for tool_name, tool_input in (
        ("execute_command", {"command": "bash -c 'git push origin main'"}),
        ("process_start", {"command": "git push origin main"}),
        ("process_write_stdin", {"process_id": "proc-1", "text": "git push\n"}),
    ):
        result, _reason = check_tool_permission(
            tool_name,
            tool_input,
            _enforcer(tmp_path),
            context,
        )

        assert result == PermissionResult.DENY


def test_link_force_push_is_classified_as_git_push(tmp_path: Path) -> None:
    policy = _policy("allow")
    policy["gitPush"] = "deny"

    for command in (
        "git push --force origin main",
        "git push origin +main",
    ):
        result, _reason = check_tool_permission(
            "execute_command",
            {"command": command},
            _enforcer(tmp_path),
            {
                "permission_mode": "workspace",
                "approval_policy": policy,
                "directory": str(tmp_path),
            },
        )

        assert result == PermissionResult.DENY


def test_link_custom_policy_matches_git_remote_identity(tmp_path: Path) -> None:
    policy = _policy(
        "allow",
        permission_mode="custom",
        allow_lists={"gitRemotes": ["origin"]},
    )
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    allowed, _reason = check_tool_permission(
        "execute_command",
        {"command": "git push origin main"},
        _enforcer(tmp_path),
        context,
    )
    unmatched, _reason = check_tool_permission(
        "execute_command",
        {"command": "git push upstream main"},
        _enforcer(tmp_path),
        context,
    )

    assert allowed == PermissionResult.ALLOW
    assert unmatched == PermissionResult.ASK


def test_link_custom_policy_normalizes_git_remote_urls(tmp_path: Path) -> None:
    policy = _policy(
        "ask",
        permission_mode="custom",
        allow_lists={
            "gitRemotes": ["https://github.com/Maximooch/penguin.git"],
            "shellCommands": ["git push --repo=git@github.com:Maximooch/penguin main"],
        },
    )
    context = {
        "permission_mode": "workspace",
        "approval_policy": policy,
        "directory": str(tmp_path),
    }

    shell_result, _reason = check_tool_permission(
        "execute_command",
        {"command": "git push --repo=git@github.com:Maximooch/penguin main"},
        _enforcer(tmp_path),
        context,
    )
    dedicated_result, _reason = check_tool_permission(
        "git_push",
        {"remote_url": "ssh://git@github.com/Maximooch/penguin"},
        _enforcer(tmp_path),
        context,
    )

    assert shell_result == PermissionResult.ALLOW
    assert dedicated_result == PermissionResult.ALLOW


def test_link_unknown_tool_fails_closed_when_request_policy_is_present(
    tmp_path: Path,
) -> None:
    result, _reason = check_tool_permission(
        "unclassified_mutating_tool",
        {},
        _enforcer(tmp_path),
        {
            "permission_mode": "workspace",
            "approval_policy": _policy("allow"),
            "directory": str(tmp_path),
        },
    )

    assert result == PermissionResult.DENY
