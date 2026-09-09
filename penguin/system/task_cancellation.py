"""Task-scoped abort intent, independent of session cleanup and transport loss."""

import asyncio
from collections.abc import Awaitable, Coroutine
from contextvars import ContextVar
from enum import Enum
from typing import Any, TypeVar
from weakref import WeakKeyDictionary

__all__ = [
    "AbortReason",
    "CancellationTrackingTask",
    "abort_task",
    "cancellation_owner",
    "preserve_cancellation",
    "task_abort_reason",
]

_Result = TypeVar("_Result")
_owners: WeakKeyDictionary[asyncio.Task, asyncio.Task] = WeakKeyDictionary()


def cancellation_owner(task: asyncio.Task) -> asyncio.Task:
    """Resolve the execution boundary for a provider/tool task."""
    return _owners.get(task, task)


class CancellationTrackingTask(asyncio.Task[_Result]):
    """Retain cancellation evidence for one owned execution, including on 3.10.

    Only the durable execution boundary constructs these tasks. Overriding
    cancel captures shutdown initiated by asyncio as well as application calls,
    without installing a process-wide task factory. Evidence is monotonic:
    swallowing CancelledError or calling uncancel cannot establish completion.
    """

    def __init__(self, coroutine: Coroutine[Any, Any, _Result], *, name: str) -> None:
        self._cancellation_requested = False
        super().__init__(coroutine, loop=asyncio.get_running_loop(), name=name)

    @property
    def cancellation_requested(self) -> bool:
        """Whether this execution has ever accepted a cancellation request."""
        return self._cancellation_requested

    def cancel(self, msg: Any = None) -> bool:
        """Record accepted cancellation requests before execution can resume."""
        accepted = super().cancel(msg)
        if accepted:
            self._cancellation_requested = True
        return accepted

    async def run_child(self, awaitable: Awaitable[_Result]) -> _Result:
        """Keep handled SDK cancellation scopes off the execution owner."""

        async def execute() -> _Result:
            return await awaitable

        child = asyncio.create_task(execute(), name=f"{self.get_name()}:execute")
        _owners[child] = self
        try:
            return await child
        finally:
            _owners.pop(child, None)


preserve_cancellation: ContextVar[bool] = ContextVar(
    "preserve_cancellation", default=False
)


class AbortReason(str, Enum):
    """Known runtime reasons for deliberately interrupting a task."""

    USER_INTERRUPTED = "user_interrupted"


_reasons: WeakKeyDictionary[asyncio.Task, AbortReason] = WeakKeyDictionary()


def abort_task(task: asyncio.Task, reason: AbortReason) -> None:
    """Record intent before cancellation; do not reclassify prior cancellation."""
    task = cancellation_owner(task)
    # Durable executions use our monotonic evidence, not version-specific counts.
    # Ordinary tasks retain their legacy best-effort cancellation check.
    pending = (
        task.cancellation_requested
        if isinstance(task, CancellationTrackingTask)
        else getattr(task, "cancelling", task.cancelled)()
    )
    if not task.done() and not pending:
        _reasons[task] = reason
        task.cancel()


def task_abort_reason(task: asyncio.Task) -> AbortReason | None:
    """Read intent even after the session has released its abort bookkeeping."""
    return _reasons.get(cancellation_owner(task))
