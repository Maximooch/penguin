"""
Core Permission Engine for Penguin.

This module provides the foundational permission checking infrastructure:
- PermissionMode: Operating modes that define default behaviors
- PermissionResult: Outcomes of permission checks
- Operation: Standardized operation taxonomy
- PolicyEngine: Base class for implementing permission policies
- PermissionEnforcer: Wrapper that enforces policies on tool execution
"""

from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Set, Union

logger = logging.getLogger(__name__)


class PermissionMode(Enum):
    """Operating modes for permission enforcement.
    
    READ_ONLY: Only read operations allowed. No writes, deletes, or execution.
    WORKSPACE: Full permissions within workspace boundaries, deny outside.
    FULL: All operations allowed (use with caution, or with --yolo flag).
    """
    READ_ONLY = "read_only"
    WORKSPACE = "workspace"
    FULL = "full"


class PermissionResult(Enum):
    """Result of a permission check.
    
    ALLOW: Operation is permitted, proceed immediately.
    ASK: Operation requires user approval before proceeding.
    DENY: Operation is forbidden, do not proceed.
    """
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class Operation(Enum):
    """Standardized operation taxonomy for permission checks.
    
    Operations are namespaced by category:
    - filesystem.*: File and directory operations
    - process.*: Command and process execution
    - network.*: Network access
    - git.*: Version control operations
    - memory.*: Memory/note storage operations
    """
    # Filesystem operations
    FILESYSTEM_READ = "filesystem.read"
    FILESYSTEM_WRITE = "filesystem.write"
    FILESYSTEM_DELETE = "filesystem.delete"
    FILESYSTEM_MKDIR = "filesystem.mkdir"
    FILESYSTEM_LIST = "filesystem.list"
    
    # Process operations
    PROCESS_EXECUTE = "process.execute"
    PROCESS_SPAWN = "process.spawn"
    PROCESS_KILL = "process.kill"
    # TODO: Process enter
    
    # Network operations
    NETWORK_FETCH = "network.fetch"
    NETWORK_POST = "network.post"
    NETWORK_LISTEN = "network.listen"
    
    # Git operations
    GIT_READ = "git.read"
    GIT_WRITE = "git.write"
    GIT_PUSH = "git.push"
    GIT_FORCE = "git.force"
    
    # Memory operations
    MEMORY_READ = "memory.read"
    MEMORY_WRITE = "memory.write"
    MEMORY_DELETE = "memory.delete"
    
    @classmethod
    def from_string(cls, op_str: str) -> "Operation":
        """Convert string to Operation enum."""
        for op in cls:
            if op.value == op_str:
                return op
        raise ValueError(f"Unknown operation: {op_str}")
    
    @property
    def category(self) -> str:
        """Get the category prefix (e.g., 'filesystem' from 'filesystem.read')."""
        return self.value.split(".")[0]
    
    @property
    def action(self) -> str:
        """Get the action suffix (e.g., 'read' from 'filesystem.read')."""
        return self.value.split(".")[1]
    
    @classmethod
    def is_read_only(cls, op: "Operation") -> bool:
        """Check if operation is read-only (safe)."""
        return op in {
            cls.FILESYSTEM_READ,
            cls.FILESYSTEM_LIST,
            cls.GIT_READ,
            cls.MEMORY_READ,
            cls.NETWORK_FETCH,
        }


class PermissionDeniedError(Exception):
    """Raised when an operation is denied by the permission engine."""
    
    def __init__(
        self,
        operation: Operation,
        resource: str,
        reason: str,
        mode: Optional[PermissionMode] = None,
        suggestion: Optional[str] = None,
    ):
        self.operation = operation
        self.resource = resource
        self.reason = reason
        self.mode = mode
        self.suggestion = suggestion
        
        message = f"Permission denied: {reason}"
        if suggestion:
            message += f" {suggestion}"
        super().__init__(message)
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize for API responses."""
        return {
            "error": "permission_denied",
            "operation": self.operation.value,
            "resource": self.resource,
            "reason": self.reason,
            "mode": self.mode.value if self.mode else None,
            "suggestion": self.suggestion,
        }


@dataclass
class PermissionCheck:
    """Record of a permission check for audit logging."""
    operation: Operation
    resource: str
    result: PermissionResult
    reason: str
    policy: str
    timestamp: str = field(default_factory=lambda: __import__("datetime").datetime.utcnow().isoformat())
    agent_id: Optional[str] = None
    tool_name: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "operation": self.operation.value,
            "resource": self.resource,
            "result": self.result.value,
            "reason": self.reason,
            "policy": self.policy,
            "timestamp": self.timestamp,
            "agent_id": self.agent_id,
            "tool_name": self.tool_name,
        }


class PolicyEngine:
    """Base class for permission policies.
    
    Subclasses implement specific policy logic by overriding check_operation().
    Multiple policies can be composed via PermissionEnforcer.
    
    Example:
        class MyPolicy(PolicyEngine):
            def check_operation(self, op, resource, context):
                if op == Operation.FILESYSTEM_DELETE:
                    return PermissionResult.DENY, "Deletion not allowed"
                return PermissionResult.ALLOW, "Permitted by default"
    """
    
    name: str = "base"
    priority: int = 0  # Higher priority policies are checked first
    
    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize policy with optional configuration."""
        self.config = config or {}
        self._enabled = True
    
    @property
    def enabled(self) -> bool:
        return self._enabled
    
    def enable(self) -> None:
        self._enabled = True
        logger.info(f"Policy '{self.name}' enabled")
    
    def disable(self) -> None:
        self._enabled = False
        logger.info(f"Policy '{self.name}' disabled")
    
    def check_operation(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> tuple[PermissionResult, str]:
        """Check if an operation on a resource is allowed.
        
        Args:
            operation: The operation being attempted
            resource: The resource being accessed (e.g., file path, URL)
            context: Additional context (agent_id, tool_name, etc.)
        
        Returns:
            Tuple of (PermissionResult, reason_string)
        """
        raise NotImplementedError("Subclasses must implement check_operation()")
    
    def get_capabilities_summary(self) -> Dict[str, List[str]]:
        """Return a summary of what this policy allows/denies.
        
        Returns:
            Dict with keys: 'can', 'cannot', 'requires_approval'
        """
        return {
            "can": [],
            "cannot": [],
            "requires_approval": [],
        }


class PermissionEnforcer:
    """Enforces permission policies on tool execution.
    
    Composes multiple PolicyEngine instances and provides:
    - Policy chain evaluation (first DENY wins, then first ASK, else ALLOW)
    - Audit logging of all permission checks
    - YOLO mode to bypass all checks
    - Integration with RuntimeConfig for dynamic policy updates
    
    Example:
        enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
        enforcer.add_policy(WorkspaceBoundaryPolicy(workspace_root="/path/to/ws"))
        
        result = enforcer.check(Operation.FILESYSTEM_WRITE, "/path/to/file.py")
        if result == PermissionResult.DENY:
            raise PermissionDeniedError(...)
    """
    
    def __init__(
        self,
        mode: PermissionMode = PermissionMode.WORKSPACE,
        yolo: bool = False,
        audit_all: bool = True,
    ):
        """Initialize the permission enforcer.
        
        Args:
            mode: Default permission mode
            yolo: If True, bypass all permission checks (--yolo flag)
            audit_all: If True, log all checks; if False, only log denials
        """
        self._mode = mode
        self._yolo = yolo
        self._audit_all = audit_all
        self._policies: List[PolicyEngine] = []
        self._audit_log: List[PermissionCheck] = []
        self._session_allowlist: Set[str] = set()  # "operation:resource" patterns allowed for session
        
        # Check for YOLO mode via environment
        if os.environ.get("PENGUIN_YOLO", "").lower() in ("1", "true", "yes"):
            self._yolo = True
            logger.warning("YOLO mode enabled via environment variable - all permission checks bypassed!")
    
    @property
    def mode(self) -> PermissionMode:
        return self._mode
    
    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        logger.info(f"Permission mode changed from {self._mode.value} to {value.value}")
        self._mode = value
    
    @property
    def yolo(self) -> bool:
        return self._yolo
    
    def set_yolo(self, enabled: bool) -> None:
        """Enable or disable YOLO mode."""
        self._yolo = enabled
        if enabled:
            logger.warning("YOLO mode enabled - all permission checks bypassed!")
        else:
            logger.info("YOLO mode disabled - permission checks active")
    
    def add_policy(self, policy: PolicyEngine) -> None:
        """Add a policy to the enforcement chain."""
        self._policies.append(policy)
        # Sort by priority (highest first)
        self._policies.sort(key=lambda p: p.priority, reverse=True)
        logger.debug(f"Added policy '{policy.name}' with priority {policy.priority}")
    
    def remove_policy(self, policy_name: str) -> bool:
        """Remove a policy by name."""
        for i, p in enumerate(self._policies):
            if p.name == policy_name:
                self._policies.pop(i)
                logger.debug(f"Removed policy '{policy_name}'")
                return True
        return False
    
    def add_session_allowlist(self, pattern: str) -> None:
        """Add a pattern to the session allowlist.
        
        Pattern format: "operation:resource_pattern"
        Example: "filesystem.write:*.py" allows writing to Python files
        """
        self._session_allowlist.add(pattern)
        logger.info(f"Added session allowlist pattern: {pattern}")
    
    def clear_session_allowlist(self) -> None:
        """Clear all session allowlist patterns."""
        self._session_allowlist.clear()
        logger.info("Cleared session allowlist")
    
    def _check_session_allowlist(self, operation: Operation, resource: str) -> bool:
        """Check if operation+resource matches session allowlist."""
        import fnmatch
        
        for pattern in self._session_allowlist:
            if ":" in pattern:
                op_pattern, res_pattern = pattern.split(":", 1)
                if fnmatch.fnmatch(operation.value, op_pattern) and fnmatch.fnmatch(resource, res_pattern):
                    return True
            elif fnmatch.fnmatch(operation.value, pattern):
                return True
        return False
    
    def check(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> PermissionResult:
        """Check if an operation is allowed.
        
        Policy evaluation order:
        1. YOLO mode bypasses everything
        2. Session allowlist checked
        3. Policies evaluated in priority order
        4. First DENY wins
        5. If any ASK, return ASK
        6. Otherwise ALLOW
        
        Args:
            operation: The operation to check
            resource: The resource being accessed
            context: Additional context (agent_id, tool_name, etc.)
        
        Returns:
            PermissionResult indicating whether to allow, ask, or deny
        """
        context = context or {}
        
        # YOLO mode bypasses everything
        if self._yolo:
            self._log_check(operation, resource, PermissionResult.ALLOW, "YOLO mode", "yolo", context)
            return PermissionResult.ALLOW
        
        # Check session allowlist
        if self._check_session_allowlist(operation, resource):
            self._log_check(operation, resource, PermissionResult.ALLOW, "Session allowlist", "session", context)
            return PermissionResult.ALLOW
        
        # Evaluate policies
        ask_reasons: List[str] = []
        
        for policy in self._policies:
            if not policy.enabled:
                continue
            
            try:
                result, reason = policy.check_operation(operation, resource, context)
            except Exception as e:
                logger.error(f"Policy '{policy.name}' raised exception: {e}", exc_info=True)
                continue
            
            if result == PermissionResult.DENY:
                self._log_check(operation, resource, result, reason, policy.name, context)
                return PermissionResult.DENY
            
            if result == PermissionResult.ASK:
                ask_reasons.append(f"{policy.name}: {reason}")
        
        # If any policy said ASK, return ASK
        if ask_reasons:
            combined_reason = "; ".join(ask_reasons)
            self._log_check(operation, resource, PermissionResult.ASK, combined_reason, "combined", context)
            return PermissionResult.ASK
        
        # Default: ALLOW
        self._log_check(operation, resource, PermissionResult.ALLOW, "No policy denied", "default", context)
        return PermissionResult.ALLOW
    
    def check_and_raise(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Check permission and raise PermissionDeniedError if denied.
        
        Does NOT raise for ASK - caller must handle approval flow separately.
        """
        result = self.check(operation, resource, context)
        if result == PermissionResult.DENY:
            raise PermissionDeniedError(
                operation=operation,
                resource=resource,
                reason=self._get_last_denial_reason(),
                mode=self._mode,
                suggestion=self._get_suggestion(operation, resource),
            )
    
    def _log_check(
        self,
        operation: Operation,
        resource: str,
        result: PermissionResult,
        reason: str,
        policy: str,
        context: Dict[str, Any],
    ) -> None:
        """Log a permission check to the audit log and audit logger."""
        if not self._audit_all and result == PermissionResult.ALLOW:
            return
        
        check = PermissionCheck(
            operation=operation,
            resource=resource,
            result=result,
            reason=reason,
            policy=policy,
            agent_id=context.get("agent_id"),
            tool_name=context.get("tool_name"),
        )
        self._audit_log.append(check)
        
        # Send to audit logger (handles its own filtering)
        try:
            from penguin.security.audit import get_audit_logger
            audit_logger = get_audit_logger()
            audit_logger.log(
                operation=operation.value,
                resource=resource,
                result=result.value,
                reason=reason,
                policy=policy,
                agent_id=context.get("agent_id"),
                tool_name=context.get("tool_name"),
                session_id=context.get("session_id"),
                context=context if audit_logger._include_context else None,
            )
        except ImportError:
            pass  # Audit module not available
        except Exception as e:
            logger.debug(f"Failed to log to audit logger: {e}")
        
        # Also log to standard logger
        level = logging.DEBUG if result == PermissionResult.ALLOW else logging.INFO
        logger.log(level, f"Permission check: {operation.value} on {resource} -> {result.value} ({reason})")
    
    def _get_last_denial_reason(self) -> str:
        """Get the reason from the last DENY result."""
        for check in reversed(self._audit_log):
            if check.result == PermissionResult.DENY:
                return check.reason
        return "Permission denied"
    
    def _get_suggestion(self, operation: Operation, resource: str) -> Optional[str]:
        """Generate a helpful suggestion for denied operations."""
        suggestions = {
            Operation.FILESYSTEM_WRITE: f"Run with --yolo flag or add '{resource}' to allowed_paths in config.",
            Operation.FILESYSTEM_DELETE: "File deletion requires explicit approval. Use --allow-delete flag.",
            Operation.PROCESS_EXECUTE: "Command execution can be enabled with --allow-exec flag.",
            Operation.GIT_PUSH: "Git push requires explicit approval. Use --allow-push flag.",
        }
        return suggestions.get(operation)
    
    def get_audit_log(self, limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Get the audit log as a list of dictionaries."""
        log = self._audit_log[-limit:] if limit else self._audit_log
        return [check.to_dict() for check in log]
    
    def clear_audit_log(self) -> None:
        """Clear the audit log."""
        self._audit_log.clear()
    
    def get_capabilities_summary(self) -> Dict[str, Any]:
        """Get a summary of current capabilities based on mode and policies."""
        if self._yolo:
            return {
                "mode": "yolo",
                "can": ["Everything (YOLO mode enabled)"],
                "cannot": [],
                "requires_approval": [],
            }
        
        summary = {
            "mode": self._mode.value,
            "can": [],
            "cannot": [],
            "requires_approval": [],
        }
        
        # Mode-based defaults
        if self._mode == PermissionMode.READ_ONLY:
            summary["can"].extend(["Read files", "Search", "List directories", "Git status/log"])
            summary["cannot"].extend(["Write files", "Delete files", "Execute commands", "Git push"])
        elif self._mode == PermissionMode.WORKSPACE:
            summary["can"].extend(["Read/write within workspace", "Execute safe commands"])
            summary["cannot"].extend(["Modify files outside workspace", "System-level operations"])
            summary["requires_approval"].extend(["File deletion", "Git push"])
        else:  # FULL
            summary["can"].extend(["All operations"])
            summary["requires_approval"].extend(["Destructive operations"])
        
        # Add policy-specific capabilities
        for policy in self._policies:
            if policy.enabled:
                policy_caps = policy.get_capabilities_summary()
                for key in ("can", "cannot", "requires_approval"):
                    summary[key].extend(policy_caps.get(key, []))
        
        # Deduplicate
        for key in ("can", "cannot", "requires_approval"):
            summary[key] = list(dict.fromkeys(summary[key]))
        
        return summary

