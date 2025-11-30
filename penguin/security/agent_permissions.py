"""
Agent-Scoped Permission Configuration and Enforcement.

Provides per-agent permission restrictions that refine the global security policy.
Implements permission inheritance with refinement semantics: child agents can only
narrow permissions, never expand beyond parent bounds.

Key concepts:
- AgentPermissionConfig: Declarative permission spec for an agent
- AgentPermissionPolicy: PolicyEngine that enforces agent restrictions
- Permission inheritance: Child ≤ Parent (refinement only)
"""

from __future__ import annotations

import fnmatch
import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from penguin.security.permission_engine import (
    Operation,
    PermissionMode,
    PermissionResult,
    PolicyEngine,
)

logger = logging.getLogger(__name__)


@dataclass
class AgentPermissionConfig:
    """Permission configuration for a specific agent.
    
    Defines what an agent is allowed to do. These permissions are
    enforced as restrictions on top of the global security policy.
    
    Attributes:
        mode: Permission mode override for this agent (None = inherit from global)
        operations: Allowed operations (e.g., ["filesystem.read", "memory.*"])
        allowed_paths: Additional paths this agent can access (glob patterns)
        denied_paths: Paths this agent cannot access (glob patterns)
        require_approval: Operations requiring approval for this agent
        inherit_from: Parent agent ID to inherit permissions from (refinement only)
    
    Example config:
        ```yaml
        agents:
          analyzer:
            permissions:
              mode: read_only
              operations: [filesystem.read, memory.read]
              allowed_paths: ["src/", "tests/"]
          implementer:
            permissions:
              operations: [filesystem.read, filesystem.write, process.execute]
              denied_paths: ["**/.env*", "**/secrets/**"]
        ```
    """
    
    # Mode override (None = inherit from global)
    mode: Optional[str] = None
    
    # Allowed operations (None = all operations per global policy)
    # Supports wildcards: "filesystem.*", "memory.*"
    operations: Optional[List[str]] = None
    
    # Path restrictions (additive to global policy)
    allowed_paths: List[str] = field(default_factory=list)
    denied_paths: List[str] = field(default_factory=list)
    
    # Operations requiring approval (additive to global policy)
    require_approval: List[str] = field(default_factory=list)
    
    # Parent agent to inherit from (refinement only)
    inherit_from: Optional[str] = None
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "AgentPermissionConfig":
        """Create from config dictionary."""
        if not isinstance(data, dict):
            return cls()
        
        return cls(
            mode=data.get("mode"),
            operations=list(data.get("operations", [])) if data.get("operations") else None,
            allowed_paths=list(data.get("allowed_paths", [])),
            denied_paths=list(data.get("denied_paths", [])),
            require_approval=list(data.get("require_approval", [])),
            inherit_from=data.get("inherit_from"),
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Serialize to dictionary."""
        result: Dict[str, Any] = {}
        if self.mode is not None:
            result["mode"] = self.mode
        if self.operations is not None:
            result["operations"] = list(self.operations)
        if self.allowed_paths:
            result["allowed_paths"] = list(self.allowed_paths)
        if self.denied_paths:
            result["denied_paths"] = list(self.denied_paths)
        if self.require_approval:
            result["require_approval"] = list(self.require_approval)
        if self.inherit_from:
            result["inherit_from"] = self.inherit_from
        return result
    
    def refine(self, child: "AgentPermissionConfig") -> "AgentPermissionConfig":
        """Create a refined (more restricted) permission config.
        
        Child permissions can only narrow, never expand:
        - Mode: Child can be more restrictive (read_only < workspace < full)
        - Operations: Child operations must be subset of parent
        - Allowed paths: Child paths must be within parent paths
        - Denied paths: Merged (child adds more denials)
        - Require approval: Merged (child adds more approvals)
        
        Args:
            child: Child permission config to refine with
            
        Returns:
            New AgentPermissionConfig representing the refined permissions
        """
        # Mode refinement (more restrictive wins)
        refined_mode = self._refine_mode(self.mode, child.mode)
        
        # Operations: intersection (child cannot add operations)
        refined_ops = self._refine_operations(self.operations, child.operations)
        
        # Allowed paths: intersection-like (child paths must be within parent)
        refined_allowed = self._refine_allowed_paths(self.allowed_paths, child.allowed_paths)
        
        # Denied paths: union (child adds more denials)
        refined_denied = list(dict.fromkeys(self.denied_paths + child.denied_paths))
        
        # Require approval: union (child adds more approvals)
        refined_approval = list(dict.fromkeys(self.require_approval + child.require_approval))
        
        return AgentPermissionConfig(
            mode=refined_mode,
            operations=refined_ops,
            allowed_paths=refined_allowed,
            denied_paths=refined_denied,
            require_approval=refined_approval,
            inherit_from=None,  # Resolved, no further inheritance
        )
    
    @staticmethod
    def _refine_mode(parent: Optional[str], child: Optional[str]) -> Optional[str]:
        """Refine mode - more restrictive wins."""
        if parent is None and child is None:
            return None
        
        mode_order = {"read_only": 0, "workspace": 1, "full": 2}
        parent_level = mode_order.get(parent, 1) if parent else 2
        child_level = mode_order.get(child, 2) if child else 2
        
        # Take the more restrictive (lower level)
        if child_level < parent_level:
            return child
        return parent
    
    @staticmethod
    def _refine_operations(
        parent: Optional[List[str]], 
        child: Optional[List[str]]
    ) -> Optional[List[str]]:
        """Refine operations - intersection with parent."""
        if parent is None:
            # Parent allows all, use child's restrictions
            return child
        if child is None:
            # Child doesn't restrict, use parent's
            return parent
        
        # Intersection: child ops must match parent patterns
        refined = []
        for child_op in child:
            for parent_op in parent:
                if fnmatch.fnmatch(child_op, parent_op) or fnmatch.fnmatch(parent_op, child_op):
                    refined.append(child_op)
                    break
        
        return refined if refined else []
    
    @staticmethod
    def _refine_allowed_paths(parent: List[str], child: List[str]) -> List[str]:
        """Refine allowed paths - child must be within parent bounds."""
        if not parent:
            # Parent has no explicit allowlist, use child's
            return child
        if not child:
            # Child has no explicit allowlist, use parent's
            return parent
        
        # For each child path, check if it's within any parent path
        # This is a simplified check; true containment would need path resolution
        refined = []
        for child_path in child:
            for parent_path in parent:
                # Child path is allowed if it starts with parent or matches glob
                if (child_path.startswith(parent_path.rstrip("/*")) or 
                    fnmatch.fnmatch(child_path, parent_path)):
                    refined.append(child_path)
                    break
        
        return refined if refined else parent  # Fall back to parent if no refinement
    
    def is_operation_allowed(self, operation: str) -> bool:
        """Check if an operation is in the allowed list.
        
        Args:
            operation: Operation string (e.g., "filesystem.read")
            
        Returns:
            True if operation is allowed by this config
        """
        if self.operations is None:
            return True  # No restriction
        
        for pattern in self.operations:
            if fnmatch.fnmatch(operation, pattern):
                return True
        return False
    
    def is_path_allowed(self, path: str) -> Tuple[bool, str]:
        """Check if a path is allowed by this config.
        
        Args:
            path: Path to check
            
        Returns:
            Tuple of (is_allowed, reason)
        """
        # Check denials first (denials take precedence)
        for pattern in self.denied_paths:
            if fnmatch.fnmatch(path, pattern):
                return False, f"Path matches denied pattern: {pattern}"
        
        # If there's an allowlist, path must match
        if self.allowed_paths:
            for pattern in self.allowed_paths:
                if fnmatch.fnmatch(path, pattern) or path.startswith(pattern.rstrip("/*")):
                    return True, "Path in allowed list"
            return False, "Path not in allowed list"
        
        return True, "No path restrictions"
    
    def requires_approval(self, operation: str) -> bool:
        """Check if an operation requires approval.
        
        Args:
            operation: Operation string
            
        Returns:
            True if operation requires approval
        """
        for pattern in self.require_approval:
            if fnmatch.fnmatch(operation, pattern):
                return True
        return False


class AgentPermissionPolicy(PolicyEngine):
    """Policy that enforces agent-specific permission restrictions.
    
    This policy is instantiated per-agent and checks operations against
    the agent's permission configuration. It should be added to the
    PermissionEnforcer's policy chain when an agent context is active.
    
    The policy implements refinement semantics: it can only deny or ask,
    never override a global denial to allow.
    """
    
    def __init__(
        self,
        agent_id: str,
        config: AgentPermissionConfig,
        parent_config: Optional[AgentPermissionConfig] = None,
        priority: int = 100,  # High priority to check agent restrictions first
    ):
        """Initialize agent permission policy.
        
        Args:
            agent_id: The agent this policy applies to
            config: Agent's permission configuration
            parent_config: Parent agent's config for inheritance
            priority: Policy priority (higher = checked first)
        """
        super().__init__()
        self.name = f"agent:{agent_id}"
        self.priority = priority
        self.agent_id = agent_id
        
        # Resolve inheritance
        if parent_config is not None:
            self._agent_config = parent_config.refine(config)
            logger.debug(f"Agent '{agent_id}' permissions refined from parent")
        else:
            self._agent_config = config
        
        logger.info(
            f"AgentPermissionPolicy created for '{agent_id}': "
            f"mode={self._agent_config.mode}, ops={self._agent_config.operations}"
        )
    
    @property
    def agent_config(self) -> AgentPermissionConfig:
        """Get the resolved agent permission config."""
        return self._agent_config
    
    def check_operation(
        self,
        operation: Operation,
        resource: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[PermissionResult, str]:
        """Check if the agent is allowed to perform the operation.
        
        Args:
            operation: The operation being attempted
            resource: The resource being accessed
            context: Additional context (should include agent_id)
            
        Returns:
            Tuple of (PermissionResult, reason_string)
        """
        context = context or {}
        
        # Only apply to matching agent
        ctx_agent_id = context.get("agent_id")
        if ctx_agent_id and ctx_agent_id != self.agent_id:
            # Not our agent, let other policies decide
            return PermissionResult.ALLOW, "Agent policy not applicable"
        
        op_str = operation.value
        
        # Check mode restrictions
        if self._agent_config.mode:
            mode = PermissionMode(self._agent_config.mode)
            if mode == PermissionMode.READ_ONLY:
                # Only allow read operations
                if not op_str.endswith(".read") and not op_str.endswith(".list"):
                    return PermissionResult.DENY, f"Agent '{self.agent_id}' is read-only"
        
        # Check operation allowlist
        if not self._agent_config.is_operation_allowed(op_str):
            return PermissionResult.DENY, (
                f"Operation '{op_str}' not allowed for agent '{self.agent_id}'"
            )
        
        # Check path restrictions
        if resource:
            allowed, reason = self._agent_config.is_path_allowed(resource)
            if not allowed:
                return PermissionResult.DENY, (
                    f"Agent '{self.agent_id}': {reason}"
                )
        
        # Check if approval required
        if self._agent_config.requires_approval(op_str):
            return PermissionResult.ASK, (
                f"Operation '{op_str}' requires approval for agent '{self.agent_id}'"
            )
        
        return PermissionResult.ALLOW, f"Agent '{self.agent_id}' allowed"
    
    def get_capabilities_summary(self) -> Dict[str, List[str]]:
        """Return summary of agent capabilities."""
        can = []
        cannot = []
        requires_approval = list(self._agent_config.require_approval)
        
        if self._agent_config.operations:
            can.extend([f"Operation: {op}" for op in self._agent_config.operations])
        else:
            can.append("All operations (per global policy)")
        
        if self._agent_config.allowed_paths:
            can.append(f"Paths: {', '.join(self._agent_config.allowed_paths)}")
        
        if self._agent_config.denied_paths:
            cannot.extend([f"Path: {p}" for p in self._agent_config.denied_paths])
        
        if self._agent_config.mode == "read_only":
            cannot.append("Write operations")
        
        return {
            "can": can,
            "cannot": cannot,
            "requires_approval": requires_approval,
        }


# Registry of agent permission policies
_agent_policies: Dict[str, AgentPermissionPolicy] = {}


def register_agent_policy(
    agent_id: str,
    config: AgentPermissionConfig,
    parent_agent_id: Optional[str] = None,
) -> AgentPermissionPolicy:
    """Register a permission policy for an agent.
    
    Args:
        agent_id: Agent ID to register
        config: Agent's permission configuration
        parent_agent_id: Parent agent ID for inheritance
        
    Returns:
        The created AgentPermissionPolicy
    """
    parent_config = None
    if parent_agent_id and parent_agent_id in _agent_policies:
        parent_config = _agent_policies[parent_agent_id].agent_config
    
    policy = AgentPermissionPolicy(
        agent_id=agent_id,
        config=config,
        parent_config=parent_config,
    )
    _agent_policies[agent_id] = policy
    logger.info(f"Registered agent permission policy: {agent_id}")
    return policy


def get_agent_policy(agent_id: str) -> Optional[AgentPermissionPolicy]:
    """Get the permission policy for an agent."""
    return _agent_policies.get(agent_id)


def unregister_agent_policy(agent_id: str) -> bool:
    """Unregister an agent's permission policy."""
    if agent_id in _agent_policies:
        del _agent_policies[agent_id]
        logger.info(f"Unregistered agent permission policy: {agent_id}")
        return True
    return False


def clear_agent_policies() -> None:
    """Clear all agent permission policies."""
    _agent_policies.clear()
    logger.info("Cleared all agent permission policies")

