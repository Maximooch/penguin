"""
Tool Permission Mapping for Penguin Security.

Maps tool names to permission operations and extracts resources from tool inputs.
This module provides the bridge between ToolManager and PermissionEnforcer.
"""

from __future__ import annotations

import logging
import re
import shlex
from fnmatch import fnmatchcase
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

if TYPE_CHECKING:
    from penguin.security.permission_engine import PermissionEnforcer

from penguin.security.permission_engine import Operation, PermissionResult

logger = logging.getLogger(__name__)


# Map tool names to their required operations
# Tools can require multiple operations (e.g., apply_diff needs read + write)
TOOL_OPERATION_MAP: dict[str, list[Operation]] = {
    # File read operations
    "read_file": [Operation.FILESYSTEM_READ],
    "list_files": [Operation.FILESYSTEM_LIST],
    "find_file": [Operation.FILESYSTEM_LIST],
    "get_file_map": [Operation.FILESYSTEM_LIST],
    "read_image": [Operation.FILESYSTEM_READ],
    "enhanced_read": [Operation.FILESYSTEM_READ],
    # File write operations
    "create_folder": [Operation.FILESYSTEM_MKDIR],
    "create_file": [Operation.FILESYSTEM_WRITE],
    "write_file": [Operation.FILESYSTEM_WRITE],
    "write_to_file": [Operation.FILESYSTEM_WRITE],
    "enhanced_write": [Operation.FILESYSTEM_WRITE],
    # File operations that read and write
    "edit_file": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "apply_patch": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "patch_file": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "patch_files": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "apply_diff": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "edit_with_pattern": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "enhanced_diff": [Operation.FILESYSTEM_READ],
    "multiedit": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "multiedit_apply": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    # Code execution
    "code_execution": [Operation.PROCESS_EXECUTE],
    "execute_command": [Operation.PROCESS_EXECUTE],
    "process_start": [Operation.PROCESS_SPAWN],
    "process_poll": [Operation.PROCESS_INSPECT],
    "process_write_stdin": [Operation.PROCESS_EXECUTE],
    "process_stop": [Operation.PROCESS_KILL],
    # Search operations (generally safe)
    "grep_search": [Operation.FILESYSTEM_READ],
    "memory_search": [Operation.MEMORY_READ],
    "perplexity_search": [Operation.NETWORK_FETCH],
    "analyze_codebase": [Operation.FILESYSTEM_READ],
    "analyze_project": [Operation.FILESYSTEM_READ],
    # Memory operations
    "add_declarative_note": [Operation.MEMORY_WRITE],
    "add_summary_note": [Operation.MEMORY_WRITE],
    # Browser operations
    "browser_navigate": [Operation.NETWORK_FETCH],
    "browser_interact": [Operation.NETWORK_FETCH],
    "browser_screenshot": [Operation.FILESYSTEM_WRITE],  # Saves screenshot
    "pydoll_browser_navigate": [Operation.NETWORK_FETCH],
    "pydoll_browser_interact": [Operation.NETWORK_FETCH],
    "pydoll_browser_screenshot": [Operation.FILESYSTEM_WRITE],
    "browser_status": [Operation.NETWORK_FETCH],
    "browser_cleanup": [Operation.NETWORK_POST],
    "browser_open_tab": [Operation.NETWORK_FETCH],
    "browser_page_info": [Operation.NETWORK_FETCH],
    "browser_harness_screenshot": [Operation.FILESYSTEM_WRITE],
    "browser_click": [Operation.NETWORK_POST],
    "browser_type": [Operation.NETWORK_POST],
    "browser_key": [Operation.NETWORK_POST],
    "browser_fill": [Operation.NETWORK_POST],
    "browser_wait": [Operation.NETWORK_FETCH],
    "browser_js": [Operation.NETWORK_POST],
    "browser_list_tabs": [Operation.NETWORK_FETCH],
    "browser_switch_tab": [Operation.NETWORK_POST],
    # Git operations
    "git_status": [Operation.GIT_READ],
    "git_diff": [Operation.GIT_READ],
    "git_log": [Operation.GIT_READ],
    "git_commit": [Operation.GIT_WRITE],
    "git_push": [Operation.GIT_PUSH],
    # Indexing (requires filesystem access)
    "reindex_workspace": [Operation.FILESYSTEM_READ],
    # Image encoding
    "encode_image_to_base64": [Operation.FILESYSTEM_READ],
    # Linting
    "lint_python": [Operation.FILESYSTEM_READ, Operation.PROCESS_EXECUTE],
}


def get_tool_operations(tool_name: str) -> list[Operation]:
    """Get the operations required by a tool.

    Args:
        tool_name: Name of the tool

    Returns:
        List of Operation enums required by the tool.
        Returns empty list if tool is unknown (allows by default).
    """
    if str(tool_name or "").startswith("mcp__"):
        return [Operation.NETWORK_POST]

    return TOOL_OPERATION_MAP.get(tool_name, [])


def _find_git_push_args(command: str) -> list[str] | None:
    """Return the arguments following a direct ``git push`` invocation.

    This deliberately recognizes direct Git CLI invocations rather than trying
    to interpret arbitrary shell programs. It closes the policy bypass where a
    caller uses ``execute_command`` instead of Penguin's dedicated Git tool.
    """
    try:
        tokens = shlex.split(str(command or ""), posix=True)
    except ValueError:
        return None

    separators = {"&&", "||", ";", "|"}
    global_options_with_value = {
        "-C",
        "-c",
        "--config-env",
        "--git-dir",
        "--namespace",
        "--work-tree",
    }
    for index, token in enumerate(tokens):
        if Path(token).name != "git":
            continue

        cursor = index + 1
        while cursor < len(tokens):
            token = tokens[cursor]
            if token in global_options_with_value:
                cursor += 2
                continue
            if token == "--":
                cursor += 1
                break
            if token.startswith("-"):
                cursor += 1
                continue
            break

        if cursor < len(tokens) and tokens[cursor] == "push":
            end = cursor + 1
            while end < len(tokens) and tokens[end] not in separators:
                end += 1
            return tokens[cursor + 1 : end]

    for token in tokens:
        if (
            token != command
            and "git" in token
            and any(char.isspace() for char in token)
        ):
            nested_args = _find_git_push_args(token)
            if nested_args is not None:
                return nested_args
    return None


def _get_tool_operations_for_input(
    tool_name: str,
    tool_input: dict[str, Any],
) -> list[Operation]:
    """Classify operations using both the tool identity and its payload."""
    operations = list(get_tool_operations(tool_name))
    if tool_name not in {
        "execute_command",
        "code_execution",
        "process_start",
        "process_write_stdin",
    }:
        return operations

    command = (
        tool_input.get("command") or tool_input.get("code") or tool_input.get("text")
    )
    push_args = _find_git_push_args(str(command or ""))
    if push_args is None:
        return operations

    if Operation.GIT_PUSH not in operations:
        operations.append(Operation.GIT_PUSH)
    if any(
        argument == "-f"
        or argument == "--force"
        or argument.startswith("--force=")
        or argument == "--force-with-lease"
        or argument.startswith("--force-with-lease=")
        or argument.startswith("+")
        for argument in push_args
    ):
        operations.append(Operation.GIT_FORCE)
    return operations


def extract_resource_from_input(
    tool_name: str, tool_input: dict[str, Any]
) -> str | None:
    """Extract the primary resource (usually file path) from tool input.

    Args:
        tool_name: Name of the tool
        tool_input: Tool input dictionary

    Returns:
        Resource string (usually a path) or None if not applicable
    """
    if tool_name in ("execute_command", "code_execution", "process_start"):
        # For commands, the resource is the command itself
        return tool_input.get("command") or tool_input.get("code")

    # File path extraction for common patterns
    path_keys = ["path", "file_path", "filepath", "file", "target", "directory", "dir"]

    for key in path_keys:
        if key in tool_input:
            return str(tool_input[key])

    # Special cases

    if tool_name in ("browser_navigate", "pydoll_browser_navigate", "browser_open_tab"):
        return tool_input.get("url")

    if tool_name in ("browser_fill",):
        return tool_input.get("selector")

    if tool_name in ("browser_js",):
        return tool_input.get("expression")

    if tool_name in ("browser_switch_tab",):
        return tool_input.get("target_id")

    if tool_name in ("grep_search",):
        return tool_input.get("pattern")

    if tool_name in ("memory_search", "perplexity_search"):
        return tool_input.get("query")

    if tool_name in ("process_write_stdin", "process_stop"):
        return tool_input.get("process_id")

    if tool_name == "git_push":
        return (
            tool_input.get("remote")
            or tool_input.get("remote_name")
            or tool_input.get("remote_url")
            or tool_input.get("url")
        )

    # For operations without a clear resource, return None
    return None


def _resolve_resource_path(resource: str, context: dict[str, Any] | None) -> str:
    """Resolve relative resource paths against request-scoped directory hints."""
    text = str(resource or "").strip()
    if not text:
        return text

    candidate = Path(text).expanduser()
    if candidate.is_absolute():
        return str(candidate)

    ctx = context or {}
    for key in ("directory", "project_root", "workspace_root"):
        base = ctx.get(key)
        if isinstance(base, str) and base.strip():
            try:
                return str((Path(base).expanduser().resolve() / candidate).resolve())
            except Exception:
                continue
    return text


def _extract_patch_files_content_paths(content: str) -> list[str]:
    """Extract candidate file paths from legacy patch_files content payloads."""
    text = str(content or "")
    if not text.strip():
        return []

    paths: list[str] = []

    for match in re.finditer(r"^\+\+\+\s+(?:b/)?(.+)$", text, re.MULTILINE):
        value = match.group(1).strip()
        if value and value != "/dev/null":
            paths.append(value)

    if paths:
        return paths

    sections = re.split(r"(?:^|\n)(?![+\-@ ])([a-zA-Z0-9_./-]+):\n", text)
    for index in range(1, len(sections), 2):
        value = sections[index].strip()
        if value:
            paths.append(value)
    return paths


def _extract_apply_patch_paths(content: str) -> list[str]:
    """Extract file paths from Codex-style apply_patch headers."""
    paths: list[str] = []
    for line in content.splitlines():
        match = re.match(
            r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+?)\s*$",
            line,
        )
        if match:
            paths.append(match.group(1).strip())
            continue
        move_match = re.match(r"^\*\*\* Move to:\s+(.+?)\s*$", line)
        if move_match:
            paths.append(move_match.group(1).strip())
    return paths


def extract_resources_from_input(
    tool_name: str,
    tool_input: dict[str, Any],
    context: dict[str, Any] | None = None,
) -> list[str]:
    """Extract primary tool resources normalized for permission checks."""
    resources: list[str] = []

    if tool_name == "patch_files":
        operations = tool_input.get("operations")
        if isinstance(operations, list):
            for item in operations:
                if not isinstance(item, dict):
                    continue
                path_value = item.get("path") or item.get("file_path")
                if isinstance(path_value, str) and path_value.strip():
                    resources.append(_resolve_resource_path(path_value, context))

        content = tool_input.get("content")
        if isinstance(content, str) and content.strip():
            resources.extend(
                _resolve_resource_path(path_value, context)
                for path_value in _extract_patch_files_content_paths(content)
            )
    elif tool_name == "apply_patch":
        patch = tool_input.get("patch")
        if isinstance(patch, str) and patch.strip():
            resources.extend(
                _resolve_resource_path(path_value, context)
                for path_value in _extract_apply_patch_paths(patch)
            )

    single = extract_resource_from_input(tool_name, tool_input)
    if single:
        operations = get_tool_operations(tool_name)
        is_path_resource = any(
            operation.value.startswith("filesystem.") for operation in operations
        )
        resources.append(
            _resolve_resource_path(single, context) if is_path_resource else single
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for resource in resources:
        text = str(resource or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def is_safe_tool(tool_name: str) -> bool:
    """Check if a tool is considered safe (read-only or low-risk).

    Safe tools don't modify files, execute commands, or access network
    in dangerous ways.

    Args:
        tool_name: Name of the tool

    Returns:
        True if tool is safe, False otherwise
    """
    operations = get_tool_operations(tool_name)

    if not operations:
        # Unknown tools are not considered safe by default
        return False

    return all(Operation.is_read_only(op) for op in operations)


def get_highest_risk_operation(tool_name: str) -> Operation | None:
    """Get the highest-risk operation for a tool.

    Useful for permission checking when multiple operations are involved.

    Args:
        tool_name: Name of the tool

    Returns:
        The highest-risk Operation or None if no operations
    """
    operations = get_tool_operations(tool_name)

    if not operations:
        return None

    # Risk hierarchy (highest to lowest)
    risk_order = [
        Operation.GIT_FORCE,
        Operation.GIT_PUSH,
        Operation.FILESYSTEM_DELETE,
        Operation.PROCESS_SPAWN,
        Operation.PROCESS_EXECUTE,
        Operation.NETWORK_POST,
        Operation.NETWORK_LISTEN,
        Operation.FILESYSTEM_WRITE,
        Operation.GIT_WRITE,
        Operation.MEMORY_WRITE,
        Operation.FILESYSTEM_MKDIR,
        Operation.NETWORK_FETCH,
        Operation.PROCESS_INSPECT,
        Operation.FILESYSTEM_READ,
        Operation.FILESYSTEM_LIST,
        Operation.GIT_READ,
        Operation.MEMORY_READ,
    ]

    for risky_op in risk_order:
        if risky_op in operations:
            return risky_op

    # Default to first operation
    return operations[0]


def check_tool_permission(
    tool_name: str,
    tool_input: dict[str, Any],
    enforcer: PermissionEnforcer,
    context: dict[str, Any] | None = None,
) -> tuple[PermissionResult, str]:
    """Check if a tool execution is allowed.

    This is the main entry point for ToolManager integration.
    Checks both global policies and agent-specific policies if an agent_id
    is provided in context.

    Args:
        tool_name: Name of the tool to check
        tool_input: Input parameters for the tool
        enforcer: PermissionEnforcer instance
        context: Additional context (agent_id, etc.)

    Returns:
        Tuple of (PermissionResult, reason_string)
    """
    operations = _get_tool_operations_for_input(tool_name, tool_input)

    if not operations:
        permission_mode = (context or {}).get("permission_mode")
        if permission_mode == "read_only":
            return PermissionResult.DENY, "Unknown tools are denied in read-only mode"
        if isinstance((context or {}).get("approval_policy"), dict):
            return PermissionResult.DENY, "Unknown tools are denied by request policy"
        # Legacy callers without a request policy retain the existing behavior.
        logger.debug(f"Tool '{tool_name}' not in permission map, allowing by default")
        return PermissionResult.ALLOW, "Unknown tool - allowed by default"

    resources = extract_resources_from_input(tool_name, tool_input, context)
    resource = resources[0] if resources else None
    ctx = dict(context or {})
    ctx["tool_name"] = tool_name

    request_policy_allows = False
    request_result = _check_request_approval_policy(
        operations,
        resources,
        ctx,
        tool_input,
    )
    if request_result is not None:
        result, reason = request_result
        if result != PermissionResult.ALLOW:
            return result, reason
        request_policy_allows = True

    # Check agent-specific policy first (if agent_id in context)
    agent_id = ctx.get("agent_id")
    if agent_id:
        agent_result, agent_reason = _check_agent_permission(
            agent_id, operations, resource or tool_name, ctx
        )
        if agent_result == PermissionResult.DENY:
            return agent_result, agent_reason
        if agent_result == PermissionResult.ASK:
            # Agent policy requires approval - don't short-circuit,
            # but remember to return ASK if global also allows
            ctx["_agent_ask"] = agent_reason

    # Check each required operation against global policy
    results = []
    target_resources = resources or [tool_name]
    for resource_candidate in target_resources:
        for operation in operations:
            result = enforcer.check(operation, resource_candidate, ctx)
            results.append((result, operation, resource_candidate))

            # Short-circuit on DENY
            if result == PermissionResult.DENY:
                return (
                    result,
                    f"Operation '{operation.value}' denied for '{resource_candidate}'",
                )

    # If any ASK, return ASK
    for result, operation, resource_candidate in results:
        if result == PermissionResult.ASK and not request_policy_allows:
            message = (
                f"Operation '{operation.value}' requires approval for "
                f"'{resource_candidate}'"
            )
            return (
                result,
                message,
            )

    # Check if agent policy said ASK
    if "_agent_ask" in ctx and not request_policy_allows:
        return PermissionResult.ASK, ctx["_agent_ask"]

    return PermissionResult.ALLOW, "All operations allowed"


_READ_OPERATIONS = {
    Operation.FILESYSTEM_READ,
    Operation.FILESYSTEM_LIST,
    Operation.GIT_READ,
    Operation.MEMORY_READ,
    Operation.PROCESS_INSPECT,
}

_ACTION_FOR_OPERATION = {
    Operation.FILESYSTEM_WRITE: "fileWrite",
    Operation.FILESYSTEM_MKDIR: "fileWrite",
    Operation.FILESYSTEM_DELETE: "fileDelete",
    Operation.PROCESS_EXECUTE: "shell",
    Operation.PROCESS_SPAWN: "shell",
    Operation.PROCESS_KILL: "shell",
    Operation.NETWORK_FETCH: "network",
    Operation.NETWORK_POST: "network",
    Operation.NETWORK_LISTEN: "network",
    Operation.GIT_WRITE: "shell",
    Operation.GIT_PUSH: "gitPush",
    Operation.GIT_FORCE: "gitPush",
    Operation.MEMORY_WRITE: "fileWrite",
    Operation.MEMORY_DELETE: "fileDelete",
}

_ALLOW_LIST_FOR_ACTION = {
    "shell": "shellCommands",
    "fileWrite": "writablePaths",
    "fileDelete": "writablePaths",
    "gitPush": "gitRemotes",
    "network": "networkHosts",
    "secrets": "secretNames",
}


def _check_request_approval_policy(
    operations: list[Operation],
    resources: list[str],
    context: dict[str, Any],
    tool_input: dict[str, Any],
) -> tuple[PermissionResult, str] | None:
    """Apply Link's immutable per-turn policy before Penguin's local policy."""
    policy = context.get("approval_policy")
    if not isinstance(policy, dict):
        return None

    allow_lists = policy.get("allowLists")
    if not isinstance(allow_lists, dict):
        allow_lists = {}
    permission_mode = str(policy.get("permissionMode") or "")
    decisions: list[tuple[PermissionResult, str]] = []

    for operation in operations:
        if operation in _READ_OPERATIONS:
            continue
        action = _ACTION_FOR_OPERATION.get(operation)
        if action is None:
            decisions.append(
                (
                    PermissionResult.DENY,
                    f"Unclassified operation '{operation.value}' is denied",
                )
            )
            continue

        decision = policy.get(action, "ask")
        if decision == "deny":
            decisions.append((PermissionResult.DENY, f"Policy denies '{action}'"))
            continue

        allowed_values = allow_lists.get(_ALLOW_LIST_FOR_ACTION[action], [])
        if not isinstance(allowed_values, list):
            allowed_values = []
        targets = _targets_for_action(
            action,
            str(context.get("tool_name") or "unknown"),
            tool_input,
            resources,
        )
        allow_list_matches = (
            bool(allowed_values)
            and bool(targets)
            and all(
                _target_matches_allow_list(action, target, allowed_values, context)
                for target in targets
            )
        )

        if allow_list_matches and (
            decision == "allow" or permission_mode in {"approve_safe_actions", "custom"}
        ):
            decisions.append((PermissionResult.ALLOW, f"Policy allows '{action}'"))
            continue

        if decision == "allow" and not allowed_values:
            decisions.append((PermissionResult.ALLOW, f"Policy allows '{action}'"))
            continue

        if allowed_values:
            decisions.append(
                (
                    PermissionResult.ASK,
                    f"'{action}' target is not allow-listed",
                )
            )
            continue

        decisions.append(
            (
                PermissionResult.ASK,
                f"Policy requires approval for '{action}'",
            )
        )

    for result, reason in decisions:
        if result == PermissionResult.DENY:
            return result, reason
    for result, reason in decisions:
        if result == PermissionResult.ASK:
            return result, reason

    return PermissionResult.ALLOW, "Request policy allows all operations"


def _targets_for_action(
    action: str,
    tool_name: str,
    tool_input: dict[str, Any],
    resources: list[str],
) -> list[str]:
    """Extract the resource representation expected by one policy action."""
    if action == "shell" and tool_name in {
        "execute_command",
        "code_execution",
        "process_start",
        "process_write_stdin",
    }:
        command = (
            tool_input.get("command")
            or tool_input.get("code")
            or tool_input.get("text")
        )
        return [str(command)] if command else resources

    if action == "gitPush":
        if tool_name == "git_push":
            remote = (
                tool_input.get("remote")
                or tool_input.get("remote_name")
                or tool_input.get("remote_url")
                or tool_input.get("url")
            )
            return [str(remote)] if remote else []

        command = (
            tool_input.get("command")
            or tool_input.get("code")
            or tool_input.get("text")
        )
        push_args = _find_git_push_args(str(command or ""))
        if push_args is None:
            return []
        remote = _extract_git_push_remote(push_args)
        return [remote] if remote else []

    return resources


def _extract_git_push_remote(arguments: list[str]) -> str | None:
    """Extract an explicit remote identity from Git push arguments."""
    options_with_values = {
        "--exec",
        "--receive-pack",
        "--repo",
        "-o",
        "--push-option",
    }
    index = 0
    while index < len(arguments):
        argument = arguments[index]
        if argument.startswith("--repo="):
            return argument.split("=", 1)[1]
        if argument in options_with_values:
            if argument == "--repo" and index + 1 < len(arguments):
                return arguments[index + 1]
            index += 2
            continue
        if argument.startswith("-"):
            index += 1
            continue
        return argument
    return None


def _target_matches_allow_list(
    action: str,
    target: str,
    allowed_values: list[Any],
    context: dict[str, Any],
) -> bool:
    """Match a target using the resource semantics for its policy action."""
    entries = [str(value).strip() for value in allowed_values if str(value).strip()]
    if not entries:
        return False

    if action == "shell":
        command = str(target).strip()
        return any(_shell_pattern_matches(pattern, command) for pattern in entries)

    if action in {"fileWrite", "fileDelete"}:
        target_path = Path(_resolve_resource_path(target, context)).resolve()
        for entry in entries:
            allowed_path = Path(_resolve_resource_path(entry, context)).resolve()
            if target_path == allowed_path or allowed_path in target_path.parents:
                return True
        return False

    if action == "network":
        hostname = _normalize_network_host(target)
        if not hostname:
            return False
        return any(
            fnmatchcase(hostname, pattern.lower().rstrip(".")) for pattern in entries
        )

    if action == "gitPush":
        remote = _normalize_git_remote(target)
        return any(remote == _normalize_git_remote(entry) for entry in entries)

    return str(target).strip() in entries


def _shell_pattern_matches(pattern: str, command: str) -> bool:
    """Match shell patterns token-by-token without spanning control operators."""
    try:
        pattern_tokens = _tokenize_shell_pattern(pattern)
        command_tokens = _tokenize_shell_pattern(command)
    except ValueError:
        return False

    control_tokens = {"&&", "||", ";", "|", "&", ">", ">>", "<", "<<"}
    if any(token in control_tokens for token in command_tokens):
        return pattern_tokens == command_tokens
    if len(pattern_tokens) != len(command_tokens):
        return False
    return all(
        fnmatchcase(command_token, pattern_token)
        for pattern_token, command_token in zip(pattern_tokens, command_tokens)
    )


def _tokenize_shell_pattern(value: str) -> list[str]:
    """Tokenize a command while preserving shell control operators."""
    lexer = shlex.shlex(value, posix=True, punctuation_chars=";&|<>")
    lexer.whitespace_split = True
    lexer.commenters = ""
    return list(lexer)


def _normalize_network_host(value: str) -> str | None:
    """Return a lowercase hostname from a URL or host-like value."""
    text = str(value or "").strip()
    if not text:
        return None
    parsed = urlsplit(text if "://" in text else f"//{text}")
    return parsed.hostname.lower().rstrip(".") if parsed.hostname else None


def _normalize_git_remote(value: str) -> str:
    """Normalize a Git remote name or URL for identity comparison."""
    text = str(value or "").strip()
    scp_match = (
        re.fullmatch(r"(?:[^@\s]+@)?([^:\s]+):(.+)", text)
        if "://" not in text
        else None
    )
    if scp_match:
        hostname, path = scp_match.groups()
        path = path.rstrip("/")
        if path.endswith(".git"):
            path = path[:-4]
        return f"{hostname.lower()}/{path.lstrip('/')}"
    if "://" not in text:
        return text
    parsed = urlsplit(text)
    hostname = parsed.hostname.lower() if parsed.hostname else ""
    path = parsed.path.rstrip("/")
    if path.endswith(".git"):
        path = path[:-4]
    return f"{hostname}{path}"


def _check_agent_permission(
    agent_id: str,
    operations: list[Operation],
    resource: str,
    context: dict[str, Any],
) -> tuple[PermissionResult, str]:
    """Check agent-specific permission policy.

    Args:
        agent_id: Agent ID to check
        operations: Operations to check
        resource: Resource being accessed
        context: Additional context

    Returns:
        Tuple of (PermissionResult, reason)
    """
    try:
        from penguin.security.agent_permissions import get_agent_policy

        policy = get_agent_policy(agent_id)
        if policy is None:
            # No agent-specific policy, defer to global
            return PermissionResult.ALLOW, "No agent-specific policy"

        # Check all operations first, accumulate results
        # DENY takes precedence over ASK, ASK takes precedence over ALLOW
        results = []
        for operation in operations:
            result, reason = policy.check_operation(operation, resource, context)
            results.append((result, reason, operation))

            # Short-circuit on DENY (safe - nothing can override a denial)
            if result == PermissionResult.DENY:
                return result, reason

        # Check for any ASK results (only after confirming no DENY)
        for result, reason, operation in results:
            if result == PermissionResult.ASK:
                return result, reason

        return PermissionResult.ALLOW, f"Agent '{agent_id}' allowed"

    except ImportError:
        # Agent permissions module not available
        return PermissionResult.ALLOW, "Agent permissions module not available"
    except Exception as e:
        logger.warning(f"Error checking agent permission: {e}")
        return PermissionResult.ALLOW, f"Agent permission check failed: {e}"
