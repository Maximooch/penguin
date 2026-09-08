"""Task-scoped abort intent, independent of session cleanup and transport loss."""

import asyncio
from contextvars import ContextVar
from enum import Enum
from weakref import WeakKeyDictionary

__all__ = ["AbortReason", "abort_task", "preserve_cancellation", "task_abort_reason"]

preserve_cancellation: ContextVar[bool] = ContextVar(
    "preserve_cancellation", default=False
)


class AbortReason(str, Enum):
    """Known runtime reasons for deliberately interrupting a task."""

    USER_INTERRUPTED = "user_interrupted"


_reasons: WeakKeyDictionary[asyncio.Task, AbortReason] = WeakKeyDictionary()


def abort_task(task: asyncio.Task, reason: AbortReason) -> None:
    """Record intent before cancellation; do not reclassify prior cancellation."""
    if not task.done() and not getattr(task, "cancelling", lambda: 0)():
        _reasons[task] = reason
        task.cancel()


def task_abort_reason(task: asyncio.Task) -> AbortReason | None:
    """Read intent even after the session has released its abort bookkeeping."""
    return _reasons.get(task)
