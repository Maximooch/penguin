"""
Penguin Security Module

Provides permission checking and policy enforcement for tool operations.

Components:
- PermissionMode: Operating modes (READ_ONLY, WORKSPACE, FULL)
- PermissionResult: Check outcomes (ALLOW, ASK, DENY)
- PolicyEngine: Base class for permission policies
- PermissionEnforcer: Enforcement wrapper for tool execution
- Path utilities: Secure path handling and validation
- Approval flow: User approval for ASK permission results
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
from penguin.security.prompt_integration import (
    get_permission_section,
    get_permission_summary,
    get_capabilities_for_prompt,
)
from penguin.security.approval import (
    ApprovalScope,
    ApprovalStatus,
    ApprovalRequest,
    SessionApproval,
    ApprovalManager,
    get_approval_manager,
)
from penguin.security.agent_permissions import (
    AgentPermissionConfig,
    AgentPermissionPolicy,
    register_agent_policy,
    get_agent_policy,
    unregister_agent_policy,
    clear_agent_policies,
)
from penguin.security.audit import (
    AuditEntry,
    PermissionAuditLogger,
    get_audit_logger,
    configure_audit_logger,
    configure_from_config,
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
    # Prompt integration
    "get_permission_section",
    "get_permission_summary",
    "get_capabilities_for_prompt",
    # Approval flow
    "ApprovalScope",
    "ApprovalStatus",
    "ApprovalRequest",
    "SessionApproval",
    "ApprovalManager",
    "get_approval_manager",
    # Agent permissions
    "AgentPermissionConfig",
    "AgentPermissionPolicy",
    "register_agent_policy",
    "get_agent_policy",
    "unregister_agent_policy",
    "clear_agent_policies",
    # Audit logging
    "AuditEntry",
    "PermissionAuditLogger",
    "get_audit_logger",
    "configure_audit_logger",
    "configure_from_config",
]

