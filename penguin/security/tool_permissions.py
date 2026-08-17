"""
Tool Permission Mapping for Penguin Security.

Maps tool names to permission operations and extracts resources from tool inputs.
This module provides the bridge between ToolManager and PermissionEnforcer.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from penguin.security.permission_engine import PermissionEnforcer

from penguin.security.permission_engine import Operation, PermissionResult

logger = logging.getLogger(__name__)

_SECRET_PATH_PATTERN = re.compile(
    r"(?:^|[/\\\s'\"`])(?:"
    r"\.env(?:\.[A-Za-z0-9_-]+)?|"
    r"\.netrc|\.npmrc|\.pypirc|"
    r"credentials(?:\.[A-Za-z0-9_-]+)?|"
    r"id_(?:rsa|dsa|ecdsa|ed25519)|"
    r"[^/\\\s'\"`]+\.(?:pem|key|p12|pfx)"
    r")(?:$|[/\\\s'\"`;])|"
    r"(?:^|[/\\])(?:secrets?|\.ssh)(?:[/\\]|$)",
    re.IGNORECASE,
)
_SECRET_ENV_PATTERN = re.compile(
    r"\$(?:\{)?[A-Z0-9_]*(?:TOKEN|SECRET|PASSWORD|API_KEY|PRIVATE_KEY)"
    r"[A-Z0-9_]*(?:\})?|"
    r"\b(?:os\.environ|os\.getenv|process\.env|printenv)\b|"
    r"(?:^|[;&|]\s*)env(?:\s|$)",
    re.IGNORECASE,
)
_SECRET_ENV_NAME_PATTERN = re.compile(
    r"(?:TOKEN|SECRET|PASSWORD|PASSWD|API_KEY|PRIVATE_KEY|ACCESS_KEY|CREDENTIAL)",
    re.IGNORECASE,
)


# Map tool names to their required operations
# Tools can require multiple operations (e.g., apply_diff needs read + write)
TOOL_OPERATION_MAP: dict[str, list[Operation]] = {
    # File read operations
    "read_file": [Operation.FILESYSTEM_READ],
    "list_files": [Operation.FILESYSTEM_LIST],
    "find_file": [Operation.FILESYSTEM_LIST],
    "get_file_map": [Operation.FILESYSTEM_LIST],
    "read_image": [Operation.FILESYSTEM_READ],
    "publish_artifact": [Operation.FILESYSTEM_READ, Operation.NETWORK_POST],
    "enhanced_read": [Operation.FILESYSTEM_READ],
    # Skill discovery and activation only read local instruction files. Activating a
    # skill changes model context, but it does not mutate the host or external state.
    "list_skills": [Operation.FILESYSTEM_LIST],
    "activate_skill": [Operation.FILESYSTEM_READ],
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
    # Polling reads Penguin's bounded process buffer without changing the process.
    "process_poll": [Operation.MEMORY_READ],
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
    "browser_interact": [Operation.NETWORK_POST],
    "browser_screenshot": [Operation.FILESYSTEM_WRITE],  # Saves screenshot
    "pydoll_browser_navigate": [Operation.NETWORK_FETCH],
    "pydoll_browser_interact": [Operation.NETWORK_POST],
    "pydoll_browser_screenshot": [Operation.FILESYSTEM_WRITE],
    "pydoll_browser_scroll": [Operation.NETWORK_POST],
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
    "get_repository_status": [Operation.GIT_READ],
    "create_and_switch_branch": [Operation.GIT_WRITE],
    "commit_and_push_changes": [Operation.GIT_WRITE, Operation.GIT_PUSH],
    "create_improvement_pr": [
        Operation.GIT_WRITE,
        Operation.GIT_PUSH,
        Operation.NETWORK_POST,
    ],
    "create_feature_pr": [
        Operation.GIT_WRITE,
        Operation.GIT_PUSH,
        Operation.NETWORK_POST,
    ],
    "create_bugfix_pr": [
        Operation.GIT_WRITE,
        Operation.GIT_PUSH,
        Operation.NETWORK_POST,
    ],
    # Indexing reads files and persists their contents in Penguin memory.
    "reindex_workspace": [Operation.FILESYSTEM_READ, Operation.MEMORY_WRITE],
    # Image encoding
    "encode_image_to_base64": [Operation.FILESYSTEM_READ],
    # Linting
    "lint_python": [Operation.FILESYSTEM_READ, Operation.PROCESS_EXECUTE],
    # Agent orchestration. Starting or resuming autonomous work is deliberately
    # treated like process spawning; approving it does not approve the child's
    # later tools, which remain subject to their own permission checks.
    "spawn_sub_agent": [Operation.PROCESS_SPAWN],
    "resume_sub_agent": [Operation.PROCESS_SPAWN],
    "stop_sub_agent": [Operation.PROCESS_KILL],
    "delegate": [Operation.PROCESS_SPAWN, Operation.NETWORK_POST],
    "delegate_explore_task": [
        Operation.PROCESS_SPAWN,
        Operation.FILESYSTEM_READ,
        Operation.NETWORK_POST,
    ],
    "send_message": [Operation.NETWORK_POST],
    "sync_context": [Operation.MEMORY_WRITE],
    # Inspection and lifecycle controls have no host side effect. MEMORY_READ is
    # the existing read-only operation closest to Penguin runtime-state reads.
    "get_agent_status": [Operation.MEMORY_READ],
    "get_context_info": [Operation.MEMORY_READ],
    "wait_for_agents": [Operation.MEMORY_READ],
    "finish_response": [Operation.MEMORY_READ],
    # The batch wrapper is inert; every child is authorized independently.
    "ordered_tool_batch": [Operation.MEMORY_READ],
    "finish_task": [Operation.MEMORY_WRITE],
    "task_completed": [Operation.MEMORY_WRITE],
}


_OPERATION_POLICY_KEYS: dict[Operation, str] = {
    Operation.PROCESS_EXECUTE: "shell",
    Operation.PROCESS_SPAWN: "shell",
    Operation.PROCESS_KILL: "shell",
    Operation.FILESYSTEM_DELETE: "fileDelete",
    Operation.FILESYSTEM_WRITE: "fileWrite",
    Operation.FILESYSTEM_MKDIR: "fileWrite",
    Operation.GIT_WRITE: "fileWrite",
    Operation.MEMORY_WRITE: "fileWrite",
    Operation.GIT_PUSH: "gitPush",
    Operation.GIT_FORCE: "gitPush",
    Operation.NETWORK_FETCH: "network",
    Operation.NETWORK_POST: "network",
    Operation.NETWORK_LISTEN: "network",
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


def get_tool_policy_keys(
    tool_name: str,
    tool_input: dict[str, Any] | None = None,
    context: dict[str, Any] | None = None,
) -> set[str]:
    """Return request-policy categories required by a tool.

    Unknown or non-read-only operations fail closed through the ``default``
    category. Pure read operations need no remote approval category because the
    instance permission engine and request mode still enforce their boundaries.
    """

    operations = get_tool_operations(tool_name)
    keys = {
        policy_key
        for operation in operations
        if (policy_key := _OPERATION_POLICY_KEYS.get(operation)) is not None
    }
    if not operations or (
        not keys
        and not all(Operation.is_read_only(operation) for operation in operations)
    ):
        keys.add("default")
    if tool_input is not None and _tool_accesses_secrets(
        tool_name,
        tool_input,
        context,
    ):
        keys.add("secrets")
    return keys


def is_sensitive_resource(resource: str) -> bool:
    """Return whether text references common credential paths or environment data."""

    value = str(resource or "")
    return bool(_SECRET_PATH_PATTERN.search(value) or _SECRET_ENV_PATTERN.search(value))


def extract_resource_from_input(
    tool_name: str, tool_input: dict[str, Any]
) -> Optional[str]:
    """Extract the primary resource (usually file path) from tool input.

    Args:
        tool_name: Name of the tool
        tool_input: Tool input dictionary

    Returns:
        Resource string (usually a path) or None if not applicable
    """
    # File path extraction for common patterns
    path_keys = ["path", "file_path", "filepath", "file", "target", "directory", "dir"]

    for key in path_keys:
        if key in tool_input:
            return str(tool_input[key])

    # Special cases
    if tool_name in ("execute_command", "code_execution", "process_start"):
        # For commands, the resource is the command itself
        return tool_input.get("command") or tool_input.get("code")

    if tool_name == "process_write_stdin":
        return (
            tool_input.get("text") or tool_input.get("data") or tool_input.get("input")
        )

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

    # For operations without a clear resource, return None
    return None


def _resolve_resource_path(resource: str, context: Optional[dict[str, Any]]) -> str:
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
    context: Optional[dict[str, Any]] = None,
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
        resources.append(_resolve_resource_path(single, context))

    deduped: list[str] = []
    seen: set[str] = set()
    for resource in resources:
        text = str(resource or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        deduped.append(text)
    return deduped


def _tool_accesses_secrets(
    tool_name: str,
    tool_input: dict[str, Any],
    context: dict[str, Any] | None,
) -> bool:
    """Return whether a tool targets common credential paths or environment data."""

    if tool_name == "process_start":
        environment = tool_input.get("env")
        if isinstance(environment, dict):
            for name, value in environment.items():
                if _SECRET_ENV_NAME_PATTERN.search(str(name)):
                    return True
                value_text = str(value or "")
                if _SECRET_ENV_NAME_PATTERN.search(value_text) or is_sensitive_resource(
                    value_text
                ):
                    return True

    resources = extract_resources_from_input(tool_name, tool_input, context)
    return any(is_sensitive_resource(resource) for resource in resources)


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


def get_highest_risk_operation(tool_name: str) -> Optional[Operation]:
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
    enforcer: "PermissionEnforcer",
    context: Optional[dict[str, Any]] = None,
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
    operations = get_tool_operations(tool_name)

    if not operations:
        # Unknown tools - allow but log
        logger.debug(f"Tool '{tool_name}' not in permission map, allowing by default")
        return PermissionResult.ALLOW, "Unknown tool - allowed by default"

    resources = extract_resources_from_input(tool_name, tool_input, context)
    resource = resources[0] if resources else None
    ctx = dict(context or {})
    ctx["tool_name"] = tool_name

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
        if result == PermissionResult.ASK:
            message = (
                f"Operation '{operation.value}' requires approval for "
                f"'{resource_candidate}'"
            )
            return (
                result,
                message,
            )

    # Check if agent policy said ASK
    if "_agent_ask" in ctx:
        return PermissionResult.ASK, ctx["_agent_ask"]

    return PermissionResult.ALLOW, "All operations allowed"


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
