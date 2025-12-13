"""
Workspace Boundary Policy for Penguin Security.

Enforces that file operations stay within allowed boundaries:
- Workspace root (Penguin's data directory)
- Project root (current working project)
- Explicitly allowed paths

Provides protection against:
- Path traversal attacks (../)
- Symlink escapes
- Access to system paths
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

from penguin.security.command_filter import is_command_safe, CommandFilterResult
from penguin.security.permission_engine import (
    Operation,
    PermissionMode,
    PermissionResult,
    PolicyEngine,
)

logger = logging.getLogger(__name__)


# System paths that should never be written to
SYSTEM_DENY_PATHS: Set[str] = {
    "/etc",
    "/bin",
    "/sbin",
    "/usr/bin",
    "/usr/sbin",
    "/usr/local/bin",
    "/usr/local/sbin",
    "/System",  # macOS
    "/Library",  # macOS
    "/var",
    "/boot",
    "/root",
    "C:\\Windows",
    "C:\\Program Files",
    "C:\\Program Files (x86)",
}

# Sensitive file patterns that should require approval
SENSITIVE_PATTERNS: Set[str] = {
    ".env",
    ".env.*",
    "*.pem",
    "*.key",
    "*secret*",
    "*credential*",
    "*password*",
    ".ssh/*",
    ".aws/*",
    ".gnupg/*",
}


class WorkspaceBoundaryPolicy(PolicyEngine):
    """Policy that enforces workspace and project root boundaries.
    
    This policy checks that file operations stay within allowed paths:
    1. Workspace root (PENGUIN_WORKSPACE or ~/penguin_workspace)
    2. Project root (PENGUIN_PROJECT_ROOT or detected git root)
    3. Additional allowed_paths from config
    
    The policy respects the current PermissionMode:
    - READ_ONLY: Only read operations allowed
    - WORKSPACE: Read/write within boundaries, deny outside
    - FULL: All operations allowed (but still logs)
    
    Example:
        policy = WorkspaceBoundaryPolicy(
            workspace_root="/home/user/penguin_workspace",
            project_root="/home/user/myproject",
            mode=PermissionMode.WORKSPACE,
        )
        result, reason = policy.check_operation(
            Operation.FILESYSTEM_WRITE,
            "/home/user/myproject/src/main.py"
        )
        # result == PermissionResult.ALLOW
    """
    
    name = "workspace_boundary"
    priority = 100  # High priority - checked early
    
    def __init__(
        self,
        workspace_root: Optional[str] = None,
        project_root: Optional[str] = None,
        mode: PermissionMode = PermissionMode.WORKSPACE,
        allowed_paths: Optional[List[str]] = None,
        denied_paths: Optional[List[str]] = None,
        require_approval: Optional[List[str]] = None,
        follow_symlinks: bool = False,
        config: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the workspace boundary policy.
        
        Args:
            workspace_root: Penguin's workspace directory (default: from env/config)
            project_root: Current project root (default: from env/config)
            mode: Permission mode (READ_ONLY, WORKSPACE, FULL)
            allowed_paths: Additional paths to allow (glob patterns supported)
            denied_paths: Additional paths to deny (glob patterns supported)
            require_approval: Operations that require user approval
            follow_symlinks: If False, deny operations through symlinks pointing outside boundaries
            config: Additional configuration dictionary
        """
        super().__init__(config)
        
        self._mode = mode
        self._follow_symlinks = follow_symlinks
        
        # Resolve workspace root
        if workspace_root:
            self._workspace_root = Path(workspace_root).resolve()
        else:
            from penguin.config import WORKSPACE_PATH
            self._workspace_root = Path(WORKSPACE_PATH).resolve()
        
        # Resolve project root
        if project_root:
            self._project_root = Path(project_root).resolve()
        else:
            # Try environment, then detect from cwd
            env_root = os.environ.get("PENGUIN_PROJECT_ROOT") or os.environ.get("PENGUIN_CWD")
            if env_root:
                self._project_root = Path(env_root).resolve()
            else:
                self._project_root = self._detect_project_root()
        
        # Store allowed/denied patterns
        self._allowed_paths = set(allowed_paths or [])
        self._denied_paths = set(denied_paths or [])
        self._require_approval = set(require_approval or [])
        
        # Add default denied patterns
        self._denied_paths.update(SENSITIVE_PATTERNS)
        
        logger.info(
            f"WorkspaceBoundaryPolicy initialized: "
            f"workspace={self._workspace_root}, project={self._project_root}, mode={mode.value}"
        )
    
    def _detect_project_root(self) -> Path:
        """Detect project root by looking for .git directory."""
        try:
            cwd = Path.cwd().resolve()
        except Exception:
            return Path.home()
        
        path = cwd
        while path != path.parent:
            if (path / ".git").exists():
                return path
            path = path.parent
        
        # No git root found, use cwd
        return cwd
    
    @property
    def mode(self) -> PermissionMode:
        return self._mode
    
    @mode.setter
    def mode(self, value: PermissionMode) -> None:
        logger.info(f"WorkspaceBoundaryPolicy mode changed from {self._mode.value} to {value.value}")
        self._mode = value
    
    def set_project_root(self, path: str) -> None:
        """Update the project root at runtime."""
        self._project_root = Path(path).resolve()
        logger.info(f"WorkspaceBoundaryPolicy project_root updated to {self._project_root}")
    
    def set_workspace_root(self, path: str) -> None:
        """Update the workspace root at runtime."""
        self._workspace_root = Path(path).resolve()
        logger.info(f"WorkspaceBoundaryPolicy workspace_root updated to {self._workspace_root}")
    
    def add_allowed_path(self, pattern: str) -> None:
        """Add a path pattern to the allowlist."""
        self._allowed_paths.add(pattern)
    
    def add_denied_path(self, pattern: str) -> None:
        """Add a path pattern to the denylist."""
        self._denied_paths.add(pattern)
    
    def check_operation(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[PermissionResult, str]:
        """Check if a file operation is allowed within boundaries.
        
        Args:
            operation: The operation being attempted
            resource: The file/directory path
            context: Additional context
        
        Returns:
            Tuple of (PermissionResult, reason_string)
        """
        context = context or {}
        
        # FULL mode allows everything (but we still log)
        if self._mode == PermissionMode.FULL:
            return PermissionResult.ALLOW, "FULL mode - all operations allowed"
        
        # READ_ONLY mode denies all non-read operations
        if self._mode == PermissionMode.READ_ONLY:
            if not Operation.is_read_only(operation):
                # Special case: allow safe execute commands (grep, find, cat, etc.)
                if operation == Operation.PROCESS_EXECUTE:
                    filter_result = is_command_safe(resource)
                    if filter_result.allowed:
                        return PermissionResult.ALLOW, f"READ_ONLY mode - safe command: {filter_result.reason}"
                    else:
                        return PermissionResult.DENY, f"READ_ONLY mode - {filter_result.reason}"
                return PermissionResult.DENY, f"READ_ONLY mode - {operation.value} not allowed"
        
        # For non-filesystem operations, defer to other policies
        if operation.category != "filesystem":
            return PermissionResult.ALLOW, "Non-filesystem operation - deferred to other policies"
        
        # Normalize and resolve the path
        try:
            path = self._normalize_path(resource)
        except ValueError as e:
            return PermissionResult.DENY, str(e)
        
        # Check for system paths (always deny writes)
        if self._is_system_path(path) and not Operation.is_read_only(operation):
            return PermissionResult.DENY, f"System path '{path}' - writes not allowed"
        
        # Check explicit denylist
        if self._matches_pattern(str(path), self._denied_paths):
            if Operation.is_read_only(operation):
                return PermissionResult.ALLOW, "Sensitive path - read allowed"
            return PermissionResult.DENY, f"Path matches denied pattern"
        
        # Check explicit allowlist
        if self._matches_pattern(str(path), self._allowed_paths):
            return PermissionResult.ALLOW, "Path matches allowed pattern"
        
        # Check if within workspace or project boundaries
        within_workspace = self._is_within_boundary(path, self._workspace_root)
        within_project = self._is_within_boundary(path, self._project_root)
        
        if not within_workspace and not within_project:
            if Operation.is_read_only(operation):
                # Allow reads outside boundaries (useful for reading system files)
                return PermissionResult.ALLOW, "Read outside boundaries allowed"
            return PermissionResult.DENY, (
                f"Path '{path}' is outside allowed boundaries. "
                f"Workspace: {self._workspace_root}, Project: {self._project_root}"
            )
        
        # Check if operation requires approval
        if operation.value in self._require_approval:
            return PermissionResult.ASK, f"Operation '{operation.value}' requires approval"
        
        # Delete operations always require approval in WORKSPACE mode
        if operation == Operation.FILESYSTEM_DELETE:
            return PermissionResult.ASK, "File deletion requires approval"
        
        return PermissionResult.ALLOW, "Within allowed boundaries"
    
    def _normalize_path(self, path_str: str) -> Path:
        """Normalize and validate a path.
        
        Handles:
        - Expanding ~ to home directory
        - Resolving to absolute path
        - Detecting path traversal attempts
        - Optionally resolving symlinks
        
        Raises:
            ValueError: If path is invalid or contains traversal attempts
        """
        try:
            path = Path(path_str).expanduser()
            
            # Get the resolved path
            if self._follow_symlinks:
                resolved = path.resolve()
            else:
                # Use resolve() but check for symlink escapes after
                resolved = path.resolve()
                
                # Check if any component is a symlink pointing outside boundaries
                if path.exists():
                    for parent in path.parents:
                        if parent.is_symlink():
                            target = parent.resolve()
                            if not self._is_within_any_boundary(target):
                                raise ValueError(
                                    f"Symlink '{parent}' points outside allowed boundaries"
                                )
            
            return resolved
            
        except (OSError, RuntimeError) as e:
            raise ValueError(f"Invalid path '{path_str}': {e}")
    
    def _is_within_boundary(self, path: Path, boundary: Path) -> bool:
        """Check if path is within a boundary directory."""
        try:
            path.relative_to(boundary)
            return True
        except ValueError:
            return False
    
    def _is_within_any_boundary(self, path: Path) -> bool:
        """Check if path is within workspace or project boundaries."""
        return (
            self._is_within_boundary(path, self._workspace_root) or
            self._is_within_boundary(path, self._project_root)
        )
    
    def _is_system_path(self, path: Path) -> bool:
        """Check if path is a protected system path."""
        path_str = str(path)
        for sys_path in SYSTEM_DENY_PATHS:
            if path_str.startswith(sys_path):
                return True
        return False
    
    def _matches_pattern(self, path_str: str, patterns: Set[str]) -> bool:
        """Check if path matches any glob pattern."""
        import fnmatch
        
        for pattern in patterns:
            # Handle both full paths and basename matching
            if fnmatch.fnmatch(path_str, pattern):
                return True
            if fnmatch.fnmatch(Path(path_str).name, pattern):
                return True
        return False
    
    def get_capabilities_summary(self) -> Dict[str, List[str]]:
        """Return a summary of what this policy allows/denies."""
        if self._mode == PermissionMode.FULL:
            return {
                "can": ["All file operations (FULL mode)"],
                "cannot": [],
                "requires_approval": [],
            }
        
        if self._mode == PermissionMode.READ_ONLY:
            return {
                "can": ["Read files", "List directories"],
                "cannot": ["Write files", "Delete files", "Create directories"],
                "requires_approval": [],
            }
        
        # WORKSPACE mode
        return {
            "can": [
                f"Read/write within workspace ({self._workspace_root})",
                f"Read/write within project ({self._project_root})",
            ],
            "cannot": [
                "Write to system paths (/etc, /bin, etc.)",
                "Write outside workspace/project boundaries",
                "Write to sensitive files (.env, *.key, etc.)",
            ],
            "requires_approval": [
                "File deletion",
            ] + list(self._require_approval),
        }
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize policy configuration for API/config."""
        return {
            "name": self.name,
            "mode": self._mode.value,
            "workspace_root": str(self._workspace_root),
            "project_root": str(self._project_root),
            "allowed_paths": list(self._allowed_paths),
            "denied_paths": list(self._denied_paths),
            "require_approval": list(self._require_approval),
            "follow_symlinks": self._follow_symlinks,
        }

