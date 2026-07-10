"""Bounded daemon executor for checkpoint filesystem work.

Checkpoint persistence can block inside an operating-system filesystem call.  An
``asyncio`` task can stop waiting for that call, but it cannot cancel the thread
that is already inside it.  The standard loop executor is therefore a poor fit
for checkpoint work: ``asyncio.run`` waits for that executor during teardown and
can turn a bounded worker shutdown into a multi-minute process hang.

This small executor keeps both worker and queued work bounded.  Its threads are
daemon threads so an irrecoverably blocked filesystem call cannot prevent process
exit.  Callers still track every submitted future and must treat an unfinished
future as detached work; daemon threads are a last-resort shutdown property, not
a substitute for truthful lifecycle state.
"""

from __future__ import annotations

import queue
import threading
from concurrent.futures import Executor, Future
from dataclasses import dataclass
from typing import Any, Callable, Generic, TypeVar

__all__ = [
    "BoundedDaemonExecutor",
    "CheckpointOffloadSaturatedError",
]


_ResultT = TypeVar("_ResultT")


class CheckpointOffloadSaturatedError(RuntimeError):
    """Raised when bounded checkpoint offload capacity is exhausted."""


@dataclass(frozen=True)
class _WorkItem(Generic[_ResultT]):
    """One function invocation owned by the executor queue."""

    future: Future[_ResultT]
    function: Callable[..., _ResultT]
    args: tuple[Any, ...]
    kwargs: dict[str, Any]


class BoundedDaemonExecutor(Executor):
    """A minimal fixed-size executor with a bounded pending queue."""

    def __init__(
        self,
        *,
        max_workers: int,
        max_pending: int,
        thread_name_prefix: str,
    ) -> None:
        if max_workers <= 0:
            raise ValueError("max_workers must be positive")
        if max_pending <= 0:
            raise ValueError("max_pending must be positive")

        self._queue: queue.Queue[_WorkItem[Any] | None] = queue.Queue(
            maxsize=max_pending
        )
        self._state_lock = threading.Lock()
        self._shutdown = False
        self._shutdown_event = threading.Event()
        self._threads = [
            threading.Thread(
                target=self._worker,
                name=f"{thread_name_prefix}-{index + 1}",
                daemon=True,
            )
            for index in range(max_workers)
        ]
        for thread in self._threads:
            thread.start()

    def submit(
        self,
        fn: Callable[..., _ResultT],
        /,
        *args: Any,
        **kwargs: Any,
    ) -> Future[_ResultT]:
        """Submit work without ever blocking the caller on queue capacity."""

        future: Future[_ResultT] = Future()
        item = _WorkItem(
            future=future,
            function=fn,
            args=args,
            kwargs=kwargs,
        )
        with self._state_lock:
            if self._shutdown:
                raise RuntimeError("checkpoint offload executor is shut down")
            try:
                self._queue.put_nowait(item)
            except queue.Full as exc:
                raise CheckpointOffloadSaturatedError(
                    "checkpoint offload executor capacity is exhausted"
                ) from exc
        return future

    def shutdown(
        self,
        wait: bool = True,
        *,
        cancel_futures: bool = False,
    ) -> None:
        """Stop accepting work and optionally wait for daemon workers."""

        with self._state_lock:
            if self._shutdown:
                return
            self._shutdown = True
            self._shutdown_event.set()
            if cancel_futures:
                self._cancel_pending_locked()
        if wait:
            for thread in self._threads:
                thread.join()

    def _cancel_pending_locked(self) -> None:
        """Cancel queued work while the executor state lock is held."""

        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                break
            try:
                if item is not None:
                    item.future.cancel()
            finally:
                self._queue.task_done()

    def _worker(self) -> None:
        """Execute queued functions until shutdown has drained pending work."""

        while True:
            try:
                item = self._queue.get(timeout=0.1)
            except queue.Empty:
                if self._shutdown_event.is_set():
                    return
                continue
            try:
                if not item.future.set_running_or_notify_cancel():
                    continue
                try:
                    result = item.function(*item.args, **item.kwargs)
                except BaseException as exc:
                    item.future.set_exception(exc)
                else:
                    item.future.set_result(result)
            finally:
                self._queue.task_done()
