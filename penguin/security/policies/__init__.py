"""
Permission Policies for Penguin Security Module.

This package contains concrete policy implementations:
- WorkspaceBoundaryPolicy: Enforces workspace/project root boundaries
- (Future) PatternPolicy: Glob-based allow/deny patterns
- (Future) RateLimitPolicy: Operation rate limiting
"""

from penguin.security.policies.workspace import WorkspaceBoundaryPolicy

__all__ = [
    "WorkspaceBoundaryPolicy",
]

