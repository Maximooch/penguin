"""
Prompt Integration for Penguin Security.

Provides functions to generate permission context for system prompts,
ensuring the agent understands what operations are allowed/denied.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def get_permission_section(
    mode: str = "workspace",
    enabled: bool = True,
    allowed_paths: Optional[List[str]] = None,
    denied_paths: Optional[List[str]] = None,
    require_approval: Optional[List[str]] = None,
    workspace_root: Optional[str] = None,
    project_root: Optional[str] = None,
) -> str:
    """Generate a permission context section for the system prompt.
    
    This creates a clear, concise summary of what the agent can and cannot do,
    formatted for inclusion in the system prompt.
    
    Args:
        mode: Permission mode ('read_only', 'workspace', 'full')
        enabled: Whether permission checks are active
        allowed_paths: Additional allowed path patterns
        denied_paths: Denied path patterns
        require_approval: Operations requiring user approval
        workspace_root: Current workspace directory
        project_root: Current project directory
    
    Returns:
        Formatted permission section string for system prompt
    """
    if not enabled:
        return """## Permission Model
**Mode: YOLO (All Checks Disabled)**
You have unrestricted access to all operations. Use caution.
"""
    
    # Build capability lists based on mode
    can_do: List[str] = []
    cannot_do: List[str] = []
    needs_approval: List[str] = []
    
    if mode == "read_only":
        can_do = [
            "Read files anywhere",
            "Search and analyze code",
            "Query memory and notes",
            "View git status and history",
        ]
        cannot_do = [
            "Write or modify files",
            "Delete files",
            "Execute commands",
            "Push to git remotes",
        ]
    elif mode == "workspace":
        can_do = [
            f"Read/write files in workspace ({_truncate_path(workspace_root)})" if workspace_root else "Read/write files in workspace",
            f"Read/write files in project ({_truncate_path(project_root)})" if project_root else "Read/write files in project",
            "Execute safe commands within boundaries",
            "Search and analyze code",
            "Manage memory and notes",
        ]
        cannot_do = [
            "Write files outside workspace/project boundaries",
            "Access system paths (/etc, /bin, etc.)",
            "Modify sensitive files (.env, *.key, etc.)",
        ]
        needs_approval = [
            "Delete files",
            "Push to git remotes",
            "Force operations (git force push, etc.)",
        ]
    else:  # full
        can_do = [
            "Read/write files anywhere",
            "Execute any commands",
            "Full git operations",
        ]
        cannot_do = []
        needs_approval = [
            "Destructive operations (delete, force)",
        ]
    
    # Add custom require_approval items
    if require_approval:
        for op in require_approval:
            op_name = _format_operation_name(op)
            if op_name not in needs_approval:
                needs_approval.append(op_name)
    
    # Build the section
    lines = [
        "## Permission Model",
        f"**Mode: {mode.upper()}**",
        "",
    ]
    
    if can_do:
        lines.append("**You can:**")
        for item in can_do:
            lines.append(f"- {item}")
        lines.append("")
    
    if cannot_do:
        lines.append("**You cannot:**")
        for item in cannot_do:
            lines.append(f"- {item}")
        lines.append("")
    
    if needs_approval:
        lines.append("**Requires approval:**")
        for item in needs_approval:
            lines.append(f"- {item}")
        lines.append("")
    
    # Add note about denied paths if any sensitive patterns
    if denied_paths:
        sensitive_examples = [p for p in denied_paths[:3] if not p.startswith("**")]
        if sensitive_examples:
            lines.append(f"*Sensitive files blocked: {', '.join(sensitive_examples)}*")
    
    return "\n".join(lines)


def get_permission_summary(
    mode: str = "workspace",
    enabled: bool = True,
) -> str:
    """Get a one-line permission summary for status displays.
    
    Args:
        mode: Permission mode
        enabled: Whether checks are enabled
    
    Returns:
        Short summary string
    """
    if not enabled:
        return "🔓 YOLO mode (no restrictions)"
    
    mode_icons = {
        "read_only": "🔒",
        "workspace": "📁",
        "full": "⚠️",
    }
    icon = mode_icons.get(mode, "📁")
    
    mode_descriptions = {
        "read_only": "Read-only access",
        "workspace": "Workspace boundaries enforced",
        "full": "Full access (use caution)",
    }
    desc = mode_descriptions.get(mode, mode)
    
    return f"{icon} {desc}"


def get_capabilities_for_prompt(enforcer: "PermissionEnforcer") -> Dict[str, Any]:
    """Get capabilities from a PermissionEnforcer for prompt generation.
    
    Args:
        enforcer: The active PermissionEnforcer instance
    
    Returns:
        Dictionary with 'mode', 'can', 'cannot', 'requires_approval'
    """
    if enforcer is None:
        return {
            "mode": "unknown",
            "can": ["Unable to determine capabilities"],
            "cannot": [],
            "requires_approval": [],
        }
    
    return enforcer.get_capabilities_summary()


def _truncate_path(path: Optional[str], max_len: int = 30) -> str:
    """Truncate a path for display, keeping the end."""
    if not path:
        return ""
    if len(path) <= max_len:
        return path
    return "..." + path[-(max_len - 3):]


def _format_operation_name(op: str) -> str:
    """Format an operation string for display.
    
    Converts 'filesystem.delete' to 'File deletion', etc.
    """
    op_names = {
        "filesystem.delete": "Delete files",
        "filesystem.write": "Write files",
        "filesystem.read": "Read files",
        "process.execute": "Execute commands",
        "process.spawn": "Spawn processes",
        "git.push": "Push to git remotes",
        "git.force": "Force git operations",
        "git.write": "Git commits",
        "network.post": "Network POST requests",
    }
    return op_names.get(op, op.replace(".", " ").title())

