"""Agent mode policy for plan/build behavior gating.

This policy enforces OpenCode-style plan mode constraints at the permission
layer. In ``plan`` mode, only read-only operations are allowed.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Tuple

from penguin.security.permission_engine import (
    Operation,
    PermissionResult,
    PolicyEngine,
)


class AgentModePolicy(PolicyEngine):
    """Enforce mode-aware operation permissions.

    The policy reads ``agent_mode`` from the permission context. When set to
    ``plan``, non-read operations are denied.
    """

    name = "agent_mode"
    priority = 200

    def check_operation(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[PermissionResult, str]:
        del resource

        ctx = context or {}
        raw_mode = ctx.get("agent_mode")
        if not isinstance(raw_mode, str):
            return PermissionResult.ALLOW, "No agent mode override"

        mode = raw_mode.strip().lower()
        if mode != "plan":
            return (
                PermissionResult.ALLOW,
                f"Agent mode '{mode or 'build'}' allows operation",
            )

        if Operation.is_read_only(operation):
            return PermissionResult.ALLOW, "Plan mode allows read-only operations"

        return (
            PermissionResult.DENY,
            f"Agent mode 'plan' blocks non-read operation '{operation.value}'",
        )

    def get_capabilities_summary(self) -> Dict[str, list[str]]:
        return {
            "can": ["Read-only operations in plan mode"],
            "cannot": ["Non-read operations in plan mode"],
            "requires_approval": [],
        }
