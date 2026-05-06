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


# Map tool names to their required operations
# Tools can require multiple operations (e.g., apply_diff needs read + write)
TOOL_OPERATION_MAP: dict[str, list[Operation]] = {
    # File read operations
    "read_file": [Operation.FILESYSTEM_READ],
    "list_files": [Operation.FILESYSTEM_LIST],
    "find_file": [Operation.FILESYSTEM_LIST],
    "get_file_map": [Operation.FILESYSTEM_LIST],
    "enhanced_read": [Operation.FILESYSTEM_READ],
    # File write operations
    "create_folder": [Operation.FILESYSTEM_MKDIR],
    "create_file": [Operation.FILESYSTEM_WRITE],
    "write_file": [Operation.FILESYSTEM_WRITE],
    "write_to_file": [Operation.FILESYSTEM_WRITE],
    "enhanced_write": [Operation.FILESYSTEM_WRITE],
    # File operations that read and write
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
    if tool_name in ("execute_command", "code_execution"):
        # For commands, the resource is the command itself
        return tool_input.get("command") or tool_input.get("code")

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


def extract_resources_from_input(
    tool_name: str,
    tool_input: dict[str, Any],
    context: Optional[dict[str, Any]] = None,
) -> list[str]:
    """Extract all primary resources from tool input, normalized for permission checks."""
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
            return (
                result,
                f"Operation '{operation.value}' requires approval for '{resource_candidate}'",
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
