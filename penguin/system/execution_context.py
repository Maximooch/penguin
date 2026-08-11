"""Per-request execution context for concurrent web sessions."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

_CURRENT_EXECUTION_CONTEXT: ContextVar[ExecutionContext | None] = ContextVar(
    "penguin_execution_context",
    default=None,
)


@dataclass(frozen=True)
class ExecutionContext:
    """Request-scoped execution state used by tool execution paths."""

    session_id: str | None = None
    conversation_id: str | None = None
    agent_id: str | None = None
    agent_mode: str | None = None
    directory: str | None = None
    project_root: str | None = None
    workspace_root: str | None = None
    request_id: str | None = None
    subagents_enabled: bool | None = None
    permission_mode: str | None = None
    approval_policy: dict[str, Any] | None = None
    request_system_prompt: str | None = None
    request_skills: tuple[str, ...] = ()
    require_registered_agent: bool = False

    def as_dict(self) -> dict[str, Any]:
        """Return a dictionary representation for compatibility with existing APIs."""
        return {
            "session_id": self.session_id,
            "conversation_id": self.conversation_id,
            "agent_id": self.agent_id,
            "agent_mode": self.agent_mode,
            "directory": self.directory,
            "project_root": self.project_root,
            "workspace_root": self.workspace_root,
            "request_id": self.request_id,
            "subagents_enabled": self.subagents_enabled,
            "permission_mode": self.permission_mode,
            "approval_policy": dict(self.approval_policy)
            if isinstance(self.approval_policy, dict)
            else None,
            "request_system_prompt": self.request_system_prompt,
            "request_skills": list(self.request_skills),
            "require_registered_agent": self.require_registered_agent,
        }


def normalize_directory(directory: str | None) -> str | None:
    """Return a resolved directory path when valid, otherwise None."""
    if not directory:
        return None
    try:
        resolved = Path(directory).expanduser().resolve()
    except Exception:
        return None
    if not resolved.exists() or not resolved.is_dir():
        return None
    return str(resolved)


def get_current_execution_context() -> ExecutionContext | None:
    """Get the active execution context, if any."""
    return _CURRENT_EXECUTION_CONTEXT.get()


def get_current_execution_context_dict() -> dict[str, Any]:
    """Get active execution context as a dictionary."""
    context = get_current_execution_context()
    if context is None:
        return {}
    return context.as_dict()


@contextmanager
def execution_context_scope(context: ExecutionContext) -> Iterator[ExecutionContext]:
    """Set a request-scoped execution context for the current task/thread."""
    token: Token[ExecutionContext | None] = _CURRENT_EXECUTION_CONTEXT.set(context)
    try:
        yield context
    finally:
        _CURRENT_EXECUTION_CONTEXT.reset(token)
