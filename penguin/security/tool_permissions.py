"""
Tool Permission Mapping for Penguin Security.

Maps tool names to permission operations and extracts resources from tool inputs.
This module provides the bridge between ToolManager and PermissionEnforcer.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from penguin.security.permission_engine import Operation, PermissionResult

logger = logging.getLogger(__name__)


# Map tool names to their required operations
# Tools can require multiple operations (e.g., apply_diff needs read + write)
TOOL_OPERATION_MAP: Dict[str, List[Operation]] = {
    # File read operations
    "read_file": [Operation.FILESYSTEM_READ],
    "list_files": [Operation.FILESYSTEM_LIST],
    "find_file": [Operation.FILESYSTEM_LIST],
    "get_file_map": [Operation.FILESYSTEM_LIST],
    "enhanced_read": [Operation.FILESYSTEM_READ],
    
    # File write operations
    "create_folder": [Operation.FILESYSTEM_MKDIR],
    "create_file": [Operation.FILESYSTEM_WRITE],
    "write_to_file": [Operation.FILESYSTEM_WRITE],
    "enhanced_write": [Operation.FILESYSTEM_WRITE],
    
    # File operations that read and write
    "apply_diff": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "edit_with_pattern": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    "enhanced_diff": [Operation.FILESYSTEM_READ],
    "multiedit": [Operation.FILESYSTEM_READ, Operation.FILESYSTEM_WRITE],
    
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


def get_tool_operations(tool_name: str) -> List[Operation]:
    """Get the operations required by a tool.
    
    Args:
        tool_name: Name of the tool
    
    Returns:
        List of Operation enums required by the tool.
        Returns empty list if tool is unknown (allows by default).
    """
    return TOOL_OPERATION_MAP.get(tool_name, [])


def extract_resource_from_input(tool_name: str, tool_input: Dict[str, Any]) -> Optional[str]:
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
    
    if tool_name in ("browser_navigate", "pydoll_browser_navigate"):
        return tool_input.get("url")
    
    if tool_name in ("grep_search",):
        return tool_input.get("pattern")
    
    if tool_name in ("memory_search", "perplexity_search"):
        return tool_input.get("query")
    
    # For operations without a clear resource, return None
    return None


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
    tool_input: Dict[str, Any],
    enforcer: "PermissionEnforcer",
    context: Optional[Dict[str, Any]] = None,
) -> Tuple[PermissionResult, str]:
    """Check if a tool execution is allowed.
    
    This is the main entry point for ToolManager integration.
    
    Args:
        tool_name: Name of the tool to check
        tool_input: Input parameters for the tool
        enforcer: PermissionEnforcer instance
        context: Additional context (agent_id, etc.)
    
    Returns:
        Tuple of (PermissionResult, reason_string)
    """
    from penguin.security.permission_engine import PermissionEnforcer
    
    operations = get_tool_operations(tool_name)
    
    if not operations:
        # Unknown tools - allow but log
        logger.debug(f"Tool '{tool_name}' not in permission map, allowing by default")
        return PermissionResult.ALLOW, "Unknown tool - allowed by default"
    
    resource = extract_resource_from_input(tool_name, tool_input)
    ctx = dict(context or {})
    ctx["tool_name"] = tool_name
    
    # Check each required operation
    results = []
    for operation in operations:
        result = enforcer.check(operation, resource or tool_name, ctx)
        results.append((result, operation))
        
        # Short-circuit on DENY
        if result == PermissionResult.DENY:
            return result, f"Operation '{operation.value}' denied for '{resource or tool_name}'"
    
    # If any ASK, return ASK
    for result, operation in results:
        if result == PermissionResult.ASK:
            return result, f"Operation '{operation.value}' requires approval for '{resource or tool_name}'"
    
    return PermissionResult.ALLOW, "All operations allowed"

