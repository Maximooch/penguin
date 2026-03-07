"""Per-request execution context for concurrent web sessions."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator, Optional

_CURRENT_EXECUTION_CONTEXT: ContextVar["ExecutionContext | None"] = ContextVar(
    "penguin_execution_context",
    default=None,
)


@dataclass(frozen=True)
class ExecutionContext:
    """Request-scoped execution state used by tool execution paths."""

    session_id: Optional[str] = None
    conversation_id: Optional[str] = None
    agent_id: Optional[str] = None
    agent_mode: Optional[str] = None
    directory: Optional[str] = None
    project_root: Optional[str] = None
    workspace_root: Optional[str] = None
    request_id: Optional[str] = None

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
        }


def normalize_directory(directory: Optional[str]) -> Optional[str]:
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


def get_current_execution_context() -> Optional[ExecutionContext]:
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
