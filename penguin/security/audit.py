"""
Permission Audit Logging for Penguin Security.

Provides structured logging of permission checks with:
- Per-category verbosity control
- File-based persistence
- In-memory buffer for API queries
- JSON structured format for machine parsing
"""

from __future__ import annotations

import json
import logging
import os
import threading
from collections import deque
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Deque, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


@dataclass
class AuditEntry:
    """A single permission audit log entry.
    
    Attributes:
        timestamp: ISO format timestamp (UTC)
        operation: Operation string (e.g., "filesystem.write")
        resource: Resource being accessed (e.g., file path, URL)
        result: Permission result ("allow", "ask", "deny")
        reason: Human-readable reason for the decision
        policy: Policy that made the decision
        agent_id: Agent ID if agent-scoped
        tool_name: Tool that triggered the check
        session_id: Session ID if available
        context: Additional context (if include_context enabled)
    """
    timestamp: str
    operation: str
    resource: str
    result: str
    reason: str
    policy: str = ""
    agent_id: Optional[str] = None
    tool_name: Optional[str] = None
    session_id: Optional[str] = None
    context: Optional[Dict[str, Any]] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary, excluding None values."""
        d = asdict(self)
        return {k: v for k, v in d.items() if v is not None}
    
    def to_json(self) -> str:
        """Convert to JSON string."""
        return json.dumps(self.to_dict())
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AuditEntry":
        """Create from dictionary."""
        return cls(
            timestamp=data.get("timestamp", ""),
            operation=data.get("operation", ""),
            resource=data.get("resource", ""),
            result=data.get("result", ""),
            reason=data.get("reason", ""),
            policy=data.get("policy", ""),
            agent_id=data.get("agent_id"),
            tool_name=data.get("tool_name"),
            session_id=data.get("session_id"),
            context=data.get("context"),
        )


class PermissionAuditLogger:
    """Handles permission audit logging with file persistence and memory buffer.
    
    Features:
    - Per-category verbosity filtering
    - Rotating file output with JSON lines format
    - In-memory circular buffer for recent entries
    - Thread-safe operations
    
    Example:
        audit_logger = PermissionAuditLogger(
            log_file=".penguin/permission_audit.log",
            categories={"filesystem": "all", "process": "deny_only"},
            max_memory_entries=1000,
        )
        
        audit_logger.log(
            operation="filesystem.write",
            resource="/path/to/file.py",
            result="deny",
            reason="Path outside workspace",
            policy="workspace_boundary",
        )
    """
    
    def __init__(
        self,
        log_file: Optional[str] = None,
        categories: Optional[Dict[str, str]] = None,
        max_memory_entries: int = 1000,
        include_context: bool = False,
        workspace_root: Optional[str] = None,
        enabled: bool = True,
    ):
        """Initialize the audit logger.
        
        Args:
            log_file: Path to audit log file (relative to workspace or absolute)
            categories: Per-category verbosity settings
            max_memory_entries: Maximum entries to keep in memory
            include_context: Whether to include full context in logs
            workspace_root: Workspace root for relative paths
            enabled: Whether audit logging is enabled
        """
        self._enabled = enabled
        self._log_file = log_file or ".penguin/permission_audit.log"
        self._categories = categories or {
            "filesystem": "all",
            "process": "ask_and_deny",
            "network": "deny_only",
            "git": "ask_and_deny",
            "memory": "off",
        }
        self._max_memory_entries = max_memory_entries
        self._include_context = include_context
        self._workspace_root = workspace_root or os.getcwd()
        
        # In-memory circular buffer for recent entries
        self._memory_buffer: Deque[AuditEntry] = deque(maxlen=max_memory_entries)
        self._lock = threading.Lock()
        
        # Statistics
        self._stats = {
            "total": 0,
            "allow": 0,
            "ask": 0,
            "deny": 0,
            "by_category": {},
        }
        
        # Ensure log directory exists
        if self._enabled and self._log_file:
            self._ensure_log_directory()
    
    def _ensure_log_directory(self) -> None:
        """Create log directory if it doesn't exist."""
        try:
            log_path = self._get_absolute_log_path()
            log_dir = os.path.dirname(log_path)
            if log_dir:
                os.makedirs(log_dir, exist_ok=True)
        except Exception as e:
            logger.warning(f"Failed to create audit log directory: {e}")
    
    def _get_absolute_log_path(self) -> str:
        """Get absolute path to log file."""
        if os.path.isabs(self._log_file):
            return self._log_file
        return os.path.join(self._workspace_root, self._log_file)
    
    def _get_category(self, operation: str) -> str:
        """Extract category from operation string."""
        if "." in operation:
            return operation.split(".")[0]
        return operation
    
    def should_log(self, operation: str, result: str) -> bool:
        """Check if this permission check should be logged.
        
        Args:
            operation: Operation string (e.g., "filesystem.write")
            result: Permission result ("allow", "ask", "deny")
            
        Returns:
            True if this check should be logged
        """
        if not self._enabled:
            return False
        
        category = self._get_category(operation)
        verbosity = self._categories.get(category, "deny_only")
        
        if verbosity == "off":
            return False
        elif verbosity == "deny_only":
            return result.lower() == "deny"
        elif verbosity == "ask_and_deny":
            return result.lower() in ("ask", "deny")
        elif verbosity == "all":
            return True
        else:
            return result.lower() == "deny"
    
    def log(
        self,
        operation: str,
        resource: str,
        result: str,
        reason: str,
        policy: str = "",
        agent_id: Optional[str] = None,
        tool_name: Optional[str] = None,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Optional[AuditEntry]:
        """Log a permission check.
        
        Args:
            operation: Operation string (e.g., "filesystem.write")
            resource: Resource being accessed
            result: Permission result ("allow", "ask", "deny")
            reason: Human-readable reason
            policy: Policy that made the decision
            agent_id: Agent ID if agent-scoped
            tool_name: Tool that triggered the check
            session_id: Session ID if available
            context: Additional context
            
        Returns:
            AuditEntry if logged, None if filtered out
        """
        # Update statistics regardless of filtering
        self._update_stats(operation, result)
        
        # Check if we should log this entry
        if not self.should_log(operation, result):
            return None
        
        # Create entry
        entry = AuditEntry(
            timestamp=datetime.now(timezone.utc).isoformat(),
            operation=operation,
            resource=resource,
            result=result.lower(),
            reason=reason,
            policy=policy,
            agent_id=agent_id,
            tool_name=tool_name,
            session_id=session_id,
            context=context if self._include_context else None,
        )
        
        # Add to memory buffer and write to file
        with self._lock:
            self._memory_buffer.append(entry)
            self._write_to_file(entry)
        
        # Log to standard logger as well
        log_level = logging.WARNING if result.lower() == "deny" else logging.DEBUG
        logger.log(
            log_level,
            f"Permission {result.upper()}: {operation} on '{resource}' - {reason}"
        )
        
        return entry
    
    def _update_stats(self, operation: str, result: str) -> None:
        """Update statistics counters."""
        result_lower = result.lower()
        category = self._get_category(operation)
        
        with self._lock:
            self._stats["total"] += 1
            if result_lower in self._stats:
                self._stats[result_lower] += 1
            
            if category not in self._stats["by_category"]:
                self._stats["by_category"][category] = {"total": 0, "allow": 0, "ask": 0, "deny": 0}
            self._stats["by_category"][category]["total"] += 1
            if result_lower in self._stats["by_category"][category]:
                self._stats["by_category"][category][result_lower] += 1
    
    def _write_to_file(self, entry: AuditEntry) -> None:
        """Write entry to audit log file."""
        if not self._log_file:
            return
        
        try:
            log_path = self._get_absolute_log_path()
            with open(log_path, "a", encoding="utf-8") as f:
                f.write(entry.to_json() + "\n")
        except Exception as e:
            logger.warning(f"Failed to write audit log: {e}")
    
    def get_recent_entries(
        self,
        limit: int = 100,
        result_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        agent_filter: Optional[str] = None,
    ) -> List[AuditEntry]:
        """Get recent audit entries from memory buffer.
        
        Args:
            limit: Maximum number of entries to return
            result_filter: Filter by result ("allow", "ask", "deny")
            category_filter: Filter by category ("filesystem", "process", etc.)
            agent_filter: Filter by agent ID
            
        Returns:
            List of matching AuditEntry objects (newest first)
        """
        with self._lock:
            entries = list(self._memory_buffer)
        
        # Apply filters
        if result_filter:
            entries = [e for e in entries if e.result == result_filter.lower()]
        
        if category_filter:
            entries = [e for e in entries if self._get_category(e.operation) == category_filter]
        
        if agent_filter:
            entries = [e for e in entries if e.agent_id == agent_filter]
        
        # Return newest first, limited
        return list(reversed(entries))[:limit]
    
    def get_stats(self) -> Dict[str, Any]:
        """Get audit statistics.
        
        Returns:
            Dictionary with statistics about permission checks
        """
        with self._lock:
            return dict(self._stats)
    
    def get_summary(self) -> str:
        """Get a human-readable summary of recent activity.
        
        Returns:
            Formatted string with audit summary
        """
        stats = self.get_stats()
        recent = self.get_recent_entries(limit=10, result_filter="deny")
        
        lines = [
            "=== Permission Audit Summary ===",
            f"Total checks: {stats['total']}",
            f"  Allowed: {stats['allow']}",
            f"  Asked: {stats['ask']}",
            f"  Denied: {stats['deny']}",
            "",
            "By category:",
        ]
        
        for category, cat_stats in stats.get("by_category", {}).items():
            lines.append(
                f"  {category}: {cat_stats['total']} total, "
                f"{cat_stats['deny']} denied"
            )
        
        if recent:
            lines.extend(["", "Recent denials:"])
            for entry in recent[:5]:
                lines.append(f"  - {entry.operation} on '{entry.resource}': {entry.reason}")
        
        return "\n".join(lines)
    
    def clear(self) -> None:
        """Clear the in-memory buffer and reset statistics."""
        with self._lock:
            self._memory_buffer.clear()
            self._stats = {
                "total": 0,
                "allow": 0,
                "ask": 0,
                "deny": 0,
                "by_category": {},
            }
    
    def set_enabled(self, enabled: bool) -> None:
        """Enable or disable audit logging."""
        self._enabled = enabled
        logger.info(f"Permission audit logging {'enabled' if enabled else 'disabled'}")
    
    def update_categories(self, categories: Dict[str, str]) -> None:
        """Update category verbosity settings."""
        self._categories.update(categories)
        logger.debug(f"Updated audit categories: {categories}")


# Global audit logger instance (singleton)
_audit_logger: Optional[PermissionAuditLogger] = None
_audit_logger_lock = threading.Lock()


def get_audit_logger() -> PermissionAuditLogger:
    """Get or create the global audit logger instance.
    
    Lazily initializes with default settings. Call configure_audit_logger()
    to customize settings before first use.
    """
    global _audit_logger
    
    if _audit_logger is None:
        with _audit_logger_lock:
            if _audit_logger is None:
                _audit_logger = PermissionAuditLogger()
    
    return _audit_logger


def configure_audit_logger(
    log_file: Optional[str] = None,
    categories: Optional[Dict[str, str]] = None,
    max_memory_entries: int = 1000,
    include_context: bool = False,
    workspace_root: Optional[str] = None,
    enabled: bool = True,
) -> PermissionAuditLogger:
    """Configure the global audit logger.
    
    Should be called early in application startup before permission checks begin.
    """
    global _audit_logger
    
    with _audit_logger_lock:
        _audit_logger = PermissionAuditLogger(
            log_file=log_file,
            categories=categories,
            max_memory_entries=max_memory_entries,
            include_context=include_context,
            workspace_root=workspace_root,
            enabled=enabled,
        )
        logger.info(f"Permission audit logger configured: enabled={enabled}, log_file={log_file}")
    
    return _audit_logger


def configure_from_config(audit_config: "AuditConfig", workspace_root: Optional[str] = None) -> PermissionAuditLogger:
    """Configure audit logger from AuditConfig dataclass.
    
    Args:
        audit_config: AuditConfig instance from SecurityConfig
        workspace_root: Workspace root for relative paths
    """
    return configure_audit_logger(
        log_file=audit_config.log_file,
        categories=audit_config.categories,
        max_memory_entries=audit_config.max_memory_entries,
        include_context=audit_config.include_context,
        workspace_root=workspace_root,
        enabled=audit_config.enabled,
    )

