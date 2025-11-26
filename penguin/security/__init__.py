"""
Penguin Security Module

Provides permission checking and policy enforcement for tool operations.

Components:
- PermissionMode: Operating modes (READ_ONLY, WORKSPACE, FULL)
- PermissionResult: Check outcomes (ALLOW, ASK, DENY)
- PolicyEngine: Base class for permission policies
- PermissionEnforcer: Enforcement wrapper for tool execution
- Path utilities: Secure path handling and validation
"""

from penguin.security.permission_engine import (
    PermissionMode,
    PermissionResult,
    Operation,
    PolicyEngine,
    PermissionEnforcer,
    PermissionDeniedError,
    PermissionCheck,
)
from penguin.security.policies import WorkspaceBoundaryPolicy
from penguin.security.path_utils import (
    PathSecurityError,
    PathTraversalError,
    SymlinkEscapeError,
    normalize_path,
    detect_traversal,
    check_symlink_escape,
    is_within_boundary,
    is_within_any_boundary,
    validate_path_security,
    get_safe_relative_path,
    sanitize_filename,
)

__all__ = [
    # Core permission types
    "PermissionMode",
    "PermissionResult",
    "Operation",
    "PermissionCheck",
    # Engine and policies
    "PolicyEngine",
    "PermissionEnforcer",
    "PermissionDeniedError",
    "WorkspaceBoundaryPolicy",
    # Path security
    "PathSecurityError",
    "PathTraversalError",
    "SymlinkEscapeError",
    "normalize_path",
    "detect_traversal",
    "check_symlink_escape",
    "is_within_boundary",
    "is_within_any_boundary",
    "validate_path_security",
    "get_safe_relative_path",
    "sanitize_filename",
]

