"""Approval flow for permission requests requiring user confirmation.

This module implements the approval queue and manager for handling ASK
permission results. When a tool operation requires approval, an ApprovalRequest
is created and stored until the user approves or denies it.

Key concepts:
- ApprovalRequest: A pending request for user approval
- ApprovalScope: How broadly an approval applies (once, session, pattern)
- ApprovalManager: Singleton managing all pending and resolved approvals
- Session approvals: Pre-approvals that apply to a conversation/connection
- Pattern approvals: Glob-based approvals (e.g., "*.py")
"""

from __future__ import annotations

import fnmatch
import logging
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, Set

logger = logging.getLogger(__name__)


class ApprovalScope(Enum):
    """Scope of an approval decision."""
    
    ONCE = "once"  # Just this specific request
    SESSION = "session"  # All similar operations this session
    PATTERN = "pattern"  # Match a glob pattern (e.g., "*.py")


class ApprovalStatus(Enum):
    """Status of an approval request."""
    
    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"


@dataclass
class ApprovalRequest:
    """A request for user approval of a tool operation.
    
    Attributes:
        id: Unique identifier for this request
        tool_name: Name of the tool requesting approval
        operation: Operation type (e.g., "filesystem.write")
        resource: Resource being accessed (e.g., file path)
        reason: Human-readable reason for requiring approval
        context: Additional context (agent_id, tool_input, etc.)
        session_id: Session this request belongs to (if any)
        status: Current status of the request
        created_at: When the request was created
        resolved_at: When the request was resolved (if resolved)
        resolution_scope: Scope of approval if approved
        expires_at: When this request expires (auto-deny)
    """
    
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    tool_name: str = ""
    operation: str = ""
    resource: str = ""
    reason: str = ""
    context: Dict[str, Any] = field(default_factory=dict)
    session_id: Optional[str] = None
    status: ApprovalStatus = ApprovalStatus.PENDING
    created_at: datetime = field(default_factory=datetime.utcnow)
    resolved_at: Optional[datetime] = None
    resolution_scope: Optional[ApprovalScope] = None
    expires_at: Optional[datetime] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary for API responses."""
        return {
            "id": self.id,
            "tool_name": self.tool_name,
            "operation": self.operation,
            "resource": self.resource,
            "reason": self.reason,
            "context": self.context,
            "session_id": self.session_id,
            "status": self.status.value,
            "created_at": self.created_at.isoformat(),
            "resolved_at": self.resolved_at.isoformat() if self.resolved_at else None,
            "resolution_scope": self.resolution_scope.value if self.resolution_scope else None,
            "expires_at": self.expires_at.isoformat() if self.expires_at else None,
        }
    
    def is_expired(self) -> bool:
        """Check if this request has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


@dataclass
class SessionApproval:
    """A session-level approval that applies to multiple requests.
    
    Attributes:
        operation: Operation type this approval covers
        pattern: Optional glob pattern for resource matching
        session_id: Session this approval belongs to
        created_at: When this approval was granted
        expires_at: When this approval expires
    """
    
    operation: str
    pattern: Optional[str] = None  # Glob pattern for resource
    session_id: str = ""
    created_at: datetime = field(default_factory=datetime.utcnow)
    expires_at: Optional[datetime] = None
    
    def matches(self, operation: str, resource: str) -> bool:
        """Check if this approval matches the given operation and resource."""
        if self.operation != operation and self.operation != "*":
            return False
        if self.pattern is None:
            return True
        return fnmatch.fnmatch(resource, self.pattern)
    
    def is_expired(self) -> bool:
        """Check if this approval has expired."""
        if self.expires_at is None:
            return False
        return datetime.utcnow() > self.expires_at


class ApprovalManager:
    """Manages approval requests and session approvals.
    
    This is designed as a singleton that handles:
    - Creating and storing approval requests
    - Resolving requests (approve/deny)
    - Session-level and pattern-based pre-approvals
    - Expiration handling
    - Notification callbacks for WebSocket integration
    
    Thread-safe for use in async web contexts.
    """
    
    _instance: Optional["ApprovalManager"] = None
    _lock = threading.Lock()
    
    def __new__(cls) -> "ApprovalManager":
        """Singleton pattern - ensure only one instance exists."""
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance
    
    def __init__(
        self,
        default_ttl_seconds: int = 300,  # 5 minutes
    ):
        """Initialize the approval manager.
        
        Args:
            default_ttl_seconds: Default time-to-live for approval requests
        """
        # Only initialize once (singleton)
        if getattr(self, "_initialized", False):
            return
        
        self._default_ttl = timedelta(seconds=default_ttl_seconds)
        
        # Pending approval requests by ID
        self._pending: Dict[str, ApprovalRequest] = {}
        
        # Resolved requests (kept for history/audit)
        self._resolved: Dict[str, ApprovalRequest] = {}
        
        # Session approvals by session_id
        self._session_approvals: Dict[str, List[SessionApproval]] = {}
        
        # Global pre-approvals (apply to all sessions)
        self._global_approvals: List[SessionApproval] = []
        
        # Callbacks for notification (WebSocket integration)
        self._on_request_created: List[Callable[[ApprovalRequest], None]] = []
        self._on_request_resolved: List[Callable[[ApprovalRequest], None]] = []
        
        # Lock for thread-safe operations
        self._data_lock = threading.RLock()
        
        self._initialized = True
        logger.info(f"ApprovalManager initialized with TTL={default_ttl_seconds}s")
    
    def reset(self) -> None:
        """Reset the manager state. Mainly for testing."""
        with self._data_lock:
            self._pending.clear()
            self._resolved.clear()
            self._session_approvals.clear()
            self._global_approvals.clear()
    
    # --- Request Creation ---
    
    def create_request(
        self,
        tool_name: str,
        operation: str,
        resource: str,
        reason: str,
        session_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
        ttl_seconds: Optional[int] = None,
    ) -> ApprovalRequest:
        """Create a new approval request.
        
        Args:
            tool_name: Name of the tool requiring approval
            operation: Operation type (e.g., "filesystem.delete")
            resource: Resource being accessed
            reason: Human-readable reason
            session_id: Session this request belongs to
            context: Additional context
            ttl_seconds: Custom TTL (uses default if None)
            
        Returns:
            The created ApprovalRequest
        """
        ttl = timedelta(seconds=ttl_seconds) if ttl_seconds else self._default_ttl
        
        request = ApprovalRequest(
            tool_name=tool_name,
            operation=operation,
            resource=resource,
            reason=reason,
            session_id=session_id,
            context=context or {},
            expires_at=datetime.utcnow() + ttl,
        )
        
        with self._data_lock:
            self._pending[request.id] = request
        
        logger.info(
            f"Approval request created: id={request.id}, "
            f"tool={tool_name}, op={operation}, resource={resource}"
        )
        
        # Notify listeners
        for callback in self._on_request_created:
            try:
                callback(request)
            except Exception as e:
                logger.error(f"Error in approval created callback: {e}")
        
        return request
    
    # --- Request Resolution ---
    
    def approve(
        self,
        request_id: str,
        scope: ApprovalScope = ApprovalScope.ONCE,
        pattern: Optional[str] = None,
    ) -> Optional[ApprovalRequest]:
        """Approve a pending request.
        
        Args:
            request_id: ID of the request to approve
            scope: How broadly this approval applies
            pattern: Glob pattern if scope is PATTERN
            
        Returns:
            The resolved request, or None if not found/already resolved
        """
        with self._data_lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                logger.warning(f"Approval request not found or already resolved: {request_id}")
                return None
            
            request.status = ApprovalStatus.APPROVED
            request.resolved_at = datetime.utcnow()
            request.resolution_scope = scope
            
            self._resolved[request_id] = request
            
            # Create session/pattern approval if scope warrants
            if scope == ApprovalScope.SESSION and request.session_id:
                self._add_session_approval(
                    request.session_id,
                    request.operation,
                    pattern=None,
                )
            elif scope == ApprovalScope.PATTERN and pattern:
                session_id = request.session_id or "__global__"
                self._add_session_approval(
                    session_id,
                    request.operation,
                    pattern=pattern,
                )
        
        logger.info(f"Approval granted: id={request_id}, scope={scope.value}")
        
        # Notify listeners
        for callback in self._on_request_resolved:
            try:
                callback(request)
            except Exception as e:
                logger.error(f"Error in approval resolved callback: {e}")
        
        return request
    
    def deny(self, request_id: str) -> Optional[ApprovalRequest]:
        """Deny a pending request.
        
        Args:
            request_id: ID of the request to deny
            
        Returns:
            The resolved request, or None if not found/already resolved
        """
        with self._data_lock:
            request = self._pending.pop(request_id, None)
            if request is None:
                logger.warning(f"Approval request not found or already resolved: {request_id}")
                return None
            
            request.status = ApprovalStatus.DENIED
            request.resolved_at = datetime.utcnow()
            
            self._resolved[request_id] = request
        
        logger.info(f"Approval denied: id={request_id}")
        
        # Notify listeners
        for callback in self._on_request_resolved:
            try:
                callback(request)
            except Exception as e:
                logger.error(f"Error in approval resolved callback: {e}")
        
        return request
    
    # --- Pre-approval & Session Approvals ---
    
    def _add_session_approval(
        self,
        session_id: str,
        operation: str,
        pattern: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> SessionApproval:
        """Add a session-level approval."""
        expires_at = None
        if ttl_seconds:
            expires_at = datetime.utcnow() + timedelta(seconds=ttl_seconds)
        
        approval = SessionApproval(
            operation=operation,
            pattern=pattern,
            session_id=session_id,
            expires_at=expires_at,
        )
        
        with self._data_lock:
            if session_id == "__global__":
                self._global_approvals.append(approval)
            else:
                if session_id not in self._session_approvals:
                    self._session_approvals[session_id] = []
                self._session_approvals[session_id].append(approval)
        
        logger.debug(
            f"Session approval added: session={session_id}, "
            f"op={operation}, pattern={pattern}"
        )
        return approval
    
    def pre_approve(
        self,
        operation: str,
        pattern: Optional[str] = None,
        session_id: Optional[str] = None,
        ttl_seconds: Optional[int] = None,
    ) -> SessionApproval:
        """Pre-approve an operation for a session or globally.
        
        Args:
            operation: Operation type to approve (e.g., "filesystem.write")
            pattern: Optional glob pattern for resource matching
            session_id: Session to apply to (None for global)
            ttl_seconds: Optional expiration
            
        Returns:
            The created SessionApproval
        """
        target_session = session_id or "__global__"
        return self._add_session_approval(
            target_session,
            operation,
            pattern=pattern,
            ttl_seconds=ttl_seconds,
        )
    
    def check_pre_approved(
        self,
        operation: str,
        resource: str,
        session_id: Optional[str] = None,
    ) -> bool:
        """Check if an operation is pre-approved.
        
        Args:
            operation: Operation type
            resource: Resource being accessed
            session_id: Session to check
            
        Returns:
            True if pre-approved, False otherwise
        """
        with self._data_lock:
            # Check global approvals
            for approval in self._global_approvals:
                if not approval.is_expired() and approval.matches(operation, resource):
                    logger.debug(f"Operation pre-approved (global): {operation} on {resource}")
                    return True
            
            # Check session approvals
            if session_id and session_id in self._session_approvals:
                for approval in self._session_approvals[session_id]:
                    if not approval.is_expired() and approval.matches(operation, resource):
                        logger.debug(
                            f"Operation pre-approved (session={session_id}): "
                            f"{operation} on {resource}"
                        )
                        return True
        
        return False
    
    def clear_session_approvals(self, session_id: str) -> int:
        """Clear all approvals for a session.
        
        Args:
            session_id: Session to clear
            
        Returns:
            Number of approvals cleared
        """
        with self._data_lock:
            approvals = self._session_approvals.pop(session_id, [])
            count = len(approvals)
        
        if count > 0:
            logger.info(f"Cleared {count} session approvals for session={session_id}")
        return count
    
    # --- Query Methods ---
    
    def get_pending(self, session_id: Optional[str] = None) -> List[ApprovalRequest]:
        """Get all pending approval requests.
        
        Args:
            session_id: Filter by session (None for all)
            
        Returns:
            List of pending requests
        """
        self._expire_old_requests()
        
        with self._data_lock:
            if session_id:
                return [
                    r for r in self._pending.values()
                    if r.session_id == session_id
                ]
            return list(self._pending.values())
    
    def get_request(self, request_id: str) -> Optional[ApprovalRequest]:
        """Get a specific request by ID.
        
        Args:
            request_id: Request ID
            
        Returns:
            The request, or None if not found
        """
        with self._data_lock:
            if request_id in self._pending:
                return self._pending[request_id]
            return self._resolved.get(request_id)
    
    def get_session_approvals(self, session_id: str) -> List[SessionApproval]:
        """Get all active approvals for a session.
        
        Args:
            session_id: Session ID
            
        Returns:
            List of active session approvals
        """
        with self._data_lock:
            approvals = self._session_approvals.get(session_id, [])
            # Filter out expired
            return [a for a in approvals if not a.is_expired()]
    
    # --- Expiration Handling ---
    
    def _expire_old_requests(self) -> int:
        """Expire old pending requests. Returns count of expired."""
        expired_ids = []
        
        with self._data_lock:
            for request_id, request in self._pending.items():
                if request.is_expired():
                    expired_ids.append(request_id)
            
            for request_id in expired_ids:
                request = self._pending.pop(request_id)
                request.status = ApprovalStatus.EXPIRED
                request.resolved_at = datetime.utcnow()
                self._resolved[request_id] = request
                
                # Notify listeners
                for callback in self._on_request_resolved:
                    try:
                        callback(request)
                    except Exception as e:
                        logger.error(f"Error in approval expired callback: {e}")
        
        if expired_ids:
            logger.info(f"Expired {len(expired_ids)} approval requests")
        
        return len(expired_ids)
    
    def cleanup_expired_sessions(self) -> int:
        """Clean up expired session approvals. Returns count removed."""
        removed = 0
        
        with self._data_lock:
            # Clean global approvals
            self._global_approvals = [
                a for a in self._global_approvals if not a.is_expired()
            ]
            
            # Clean session approvals
            for session_id in list(self._session_approvals.keys()):
                before = len(self._session_approvals[session_id])
                self._session_approvals[session_id] = [
                    a for a in self._session_approvals[session_id]
                    if not a.is_expired()
                ]
                removed += before - len(self._session_approvals[session_id])
                
                # Remove empty sessions
                if not self._session_approvals[session_id]:
                    del self._session_approvals[session_id]
        
        return removed
    
    # --- Notification Callbacks ---
    
    def on_request_created(self, callback: Callable[[ApprovalRequest], None]) -> None:
        """Register a callback for when requests are created.
        
        Used for WebSocket notifications.
        """
        self._on_request_created.append(callback)
    
    def on_request_resolved(self, callback: Callable[[ApprovalRequest], None]) -> None:
        """Register a callback for when requests are resolved.
        
        Used for WebSocket notifications.
        """
        self._on_request_resolved.append(callback)
    
    def remove_callback(self, callback: Callable) -> None:
        """Remove a callback."""
        if callback in self._on_request_created:
            self._on_request_created.remove(callback)
        if callback in self._on_request_resolved:
            self._on_request_resolved.remove(callback)


# Singleton accessor
def get_approval_manager() -> ApprovalManager:
    """Get the singleton ApprovalManager instance."""
    return ApprovalManager()

