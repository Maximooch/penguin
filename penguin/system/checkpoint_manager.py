"""
Checkpoint management for Penguin conversation system.

This module implements the conversation plane auto-checkpointing from V2.1 plan:
- Automatic checkpoint creation on every message
- Async worker pattern to prevent UI blocking
- Retention policies for storage management
- Rollback and branching functionality
"""

import asyncio
import copy
import gzip
import json
import logging
import math
import os
import threading
import time
import uuid
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from penguin.system.checkpoint_cleanup import build_checkpoint_cleanup_plan
from penguin.system.checkpoint_executor import BoundedDaemonExecutor
from penguin.system.checkpoint_retention import (
    archive_cleanup_candidates,
    enforce_automatic_retention,
    fsync_directory as _fsync_directory,
    recover_automatic_retention_transactions,
    recover_confirmed_cleanup_archives,
    write_json_atomic as _write_json_atomic,
)
from penguin.system.checkpoint_snapshot import (
    build_flat_session_snapshot,
    preserve_native_tool_adjacency,
)
from penguin.system.runtime_diagnostics import record_runtime_duration
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.storage_safety import StorageSafetyMonitor, StorageSafetyStatus

logger = logging.getLogger(__name__)

__all__ = [
    "CheckpointConfig",
    "CheckpointManager",
    "CheckpointMetadata",
    "CheckpointPersistenceError",
    "CheckpointPersistenceTimeoutError",
    "CheckpointQueueFullError",
    "CheckpointSnapshotBoundary",
    "CheckpointType",
    "CheckpointWorkerCircuitOpenError",
    "CheckpointWorkerOwnershipError",
]


class CheckpointType(Enum):
    """Types of checkpoints that can be created."""

    AUTO = "auto"  # Automatic checkpoint every N messages
    MANUAL = "manual"  # User-created checkpoint with optional name
    BRANCH = "branch"  # Checkpoint created when branching
    ROLLBACK = "rollback"  # Checkpoint created before rollback


class CheckpointWorkerOwnershipError(RuntimeError):
    """Raised when checkpoint work crosses a live worker's event-loop boundary."""


class CheckpointQueueFullError(RuntimeError):
    """Raised when user-requested checkpoint work cannot enter the bounded queue."""


class CheckpointWorkerCircuitOpenError(RuntimeError):
    """Raised when user checkpoint work reaches an unhealthy worker circuit."""


class CheckpointPersistenceError(RuntimeError):
    """Raised when a user-requested checkpoint is not durably persisted."""


class CheckpointPersistenceTimeoutError(CheckpointPersistenceError):
    """Raised when durable checkpoint acknowledgment exceeds its deadline."""


class _CheckpointCommitInvalidatedError(CheckpointPersistenceError):
    """Raised inside an offload after its worker generation was stopped."""


@dataclass
class CheckpointConfig:
    """Configuration for checkpoint behavior."""

    enabled: bool = True
    frequency: int = 1  # Checkpoint every N messages
    planes: Dict[str, bool] = field(
        default_factory=lambda: {
            "conversation": True,
            "tasks": False,  # Will be enabled in Phase 2
            "code": False,  # Will be enabled in Phase 3
        }
    )
    retention: Dict[str, int] = field(
        default_factory=lambda: {
            "keep_all_hours": 24,
            "keep_every_nth": 10,
            "max_age_days": 30,
            "max_bytes": 5 * 1024 * 1024 * 1024,
            "active_session_keep": 1,
        }
    )
    max_auto_checkpoints: int = 1000  # Hard limit on auto checkpoints
    queue_maxsize: int = 32
    enqueue_timeout_seconds: float = 2.0
    shutdown_drain_timeout_seconds: float = 5.0
    worker_max_attempts: int = 3
    worker_retry_base_seconds: float = 0.1
    worker_retry_max_seconds: float = 2.0
    circuit_failure_threshold: int = 3
    circuit_reset_seconds: float = 30.0
    worker_error_log_interval_seconds: float = 30.0
    preparation_attempt_timeout_seconds: float = 60.0
    persistence_attempt_timeout_seconds: float = 60.0
    persistence_ack_timeout_seconds: float = 65.0
    maintenance_interval_seconds: float = 300.0
    foreign_shutdown_timeout_seconds: float = 10.0


@dataclass
class CheckpointMetadata:
    """Metadata for a checkpoint."""

    id: str
    type: CheckpointType
    created_at: str
    session_id: str
    message_id: str
    message_count: int
    name: Optional[str] = None
    description: Optional[str] = None
    parent_checkpoint: Optional[str] = None
    branch_point: Optional[str] = None
    auto: bool = True


@dataclass(frozen=True)
class _CheckpointWorkItem:
    """Immutable checkpoint state captured before it enters the worker queue."""

    metadata: CheckpointMetadata
    session_snapshot: Dict[str, Any]
    generation: int
    commit_token: threading.Event
    completion: Optional[asyncio.Future[bool]] = field(
        default=None,
        compare=False,
        repr=False,
    )


@dataclass(frozen=True)
class CheckpointSnapshotBoundary:
    """Constant-size coalescing boundary captured after bounded admission."""

    message_count: int
    lifecycle_count: int
    tool_call_count: int
    tool_result_count: int
    last_active: str


class CheckpointManager:
    """
    Manages conversation checkpoints with async worker pattern.

    Implements the V2.1 conversation plane checkpointing:
    - Auto-checkpoint every message (configurable frequency)
    - Async workers to prevent UI blocking
    - Retention policies for storage management
    - Rollback and branching functionality
    """

    def __init__(
        self,
        workspace_path: Path,
        session_manager,
        config: Optional[CheckpointConfig] = None,
        storage_safety_monitor: Optional[StorageSafetyMonitor] = None,
    ):
        """
        Initialize the checkpoint manager.

        Args:
            workspace_path: Base workspace directory
            session_manager: SessionManager instance for lineage operations
            config: Checkpoint configuration
            storage_safety_monitor: Optional injected disk-safety monitor
        """
        self.workspace_path = Path(workspace_path)
        self.session_manager = session_manager
        self.config = config or CheckpointConfig()

        # Setup checkpoint storage
        self.checkpoints_path = self.workspace_path / "checkpoints"
        self.checkpoints_path.mkdir(exist_ok=True)

        # Checkpoint index for fast lookups
        self.index_path = self.checkpoints_path / "checkpoint_index.json"
        self._persistence_lock = threading.RLock()
        self.checkpoint_index: Dict[str, CheckpointMetadata] = {}
        self._checkpoint_index_snapshot: Dict[str, CheckpointMetadata] = {}
        self._load_checkpoint_index()
        self._auto_checkpoint_count = 0
        self._pending_auto_checkpoints = 0
        self.refresh_admission_counters()
        self._storage_safety_monitor = storage_safety_monitor or StorageSafetyMonitor(
            self.workspace_path,
            checkpoint_path=self.checkpoints_path,
        )
        self._last_storage_safety_status: Optional[StorageSafetyStatus] = None
        self._checkpoint_block_reason: Optional[str] = None
        self._last_logged_block_reason: Optional[str] = None
        self._checkpoint_bytes = _checkpoint_directory_bytes(self.checkpoints_path)

        # Async worker setup (queues created lazily in the owning event loop)
        self.checkpoint_queue: Optional[asyncio.Queue[_CheckpointWorkItem]] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._owner_thread_id: Optional[int] = None
        self._workers_started = False
        self._workers_stopping = False
        self._stop_task: Optional[asyncio.Task] = None
        self._worker_tasks: List[asyncio.Task] = []
        self._checkpoint_worker_task: Optional[asyncio.Task] = None
        self._maintenance_task: Optional[asyncio.Task] = None
        self._maintenance_lock: Optional[asyncio.Lock] = None
        self._worker_generation = 0
        self._work_capacity_limit = max(1, int(self.config.queue_maxsize))
        self._inflight_checkpoint_work = 0
        self._capacity_available: Optional[asyncio.Event] = None
        self._consecutive_worker_failures = 0
        self._circuit_open_until = 0.0
        self._last_worker_error_code: Optional[str] = None
        self._last_worker_error_log_at = float("-inf")
        self._suppressed_worker_error_logs = 0
        self._rejected_auto_checkpoints = 0
        self._dropped_on_shutdown = 0
        self._background_checkpoint_tasks: Set[asyncio.Task] = set()
        self._offload_executor: Optional[BoundedDaemonExecutor] = None
        self._offload_state_lock = threading.Lock()
        self._active_offloads: Dict[ConcurrentFuture[Any], int] = {}
        self._persistence_context = threading.local()

        self._recover_automatic_retention_transactions()
        self._recover_confirmed_cleanup_archives()
        self._reconcile_checkpoint_storage()
        self._last_storage_safety_status = self._storage_safety_monitor.check(
            force=True,
            checkpoint_bytes=self._checkpoint_bytes,
        )

        # Message counter for frequency control
        self._message_counter = 0

        logger.info(
            "CheckpointManager initialized with %s existing checkpoints",
            len(self.checkpoint_index),
        )

    def __del__(self) -> None:
        """Best-effort bounded release for managers not closed by their owner."""

        try:
            self._shutdown_offload_executor()
        except Exception:
            pass

    async def start_workers(self) -> None:
        """Start one bounded worker owned by the current running event loop.

        Repeated calls on the owner loop are idempotent. A different live loop is
        rejected explicitly; a closed/abandoned owner is reset before restart.
        """

        loop = asyncio.get_running_loop()
        if self._workers_stopping:
            raise CheckpointWorkerOwnershipError(
                "Checkpoint workers are currently stopping"
            )
        if self._workers_started:
            worker_alive = (
                self._checkpoint_worker_task is not None
                and not self._checkpoint_worker_task.done()
            )
            if self._loop is loop and worker_alive:
                return
            if self._loop is loop:
                await self._stop_workers_on_owner_loop()
            elif self._loop is not None and self._loop.is_running() and worker_alive:
                raise CheckpointWorkerOwnershipError(
                    "Checkpoint workers are owned by another live event loop"
                )
            elif self._loop is not None and not self._loop.is_closed():
                raise CheckpointWorkerOwnershipError(
                    "Checkpoint owner loop is stopped but not closed; explicit "
                    "owner-loop shutdown is required before rebinding"
                )
            else:
                self._reset_abandoned_worker_state()

        if self._has_active_offloads():
            deadline = time.monotonic() + min(
                1.0,
                max(0.0, self.config.foreign_shutdown_timeout_seconds),
            )
            while self._has_active_offloads() and time.monotonic() < deadline:
                await asyncio.sleep(0.01)
            if self._has_active_offloads():
                raise CheckpointWorkerOwnershipError(
                    "A detached checkpoint filesystem operation is still active"
                )

        self._loop = loop
        self._owner_thread_id = threading.get_ident()
        self.checkpoint_queue = asyncio.Queue(
            maxsize=max(1, int(self.config.queue_maxsize))
        )
        self._worker_generation += 1
        self._inflight_checkpoint_work = 0
        self._capacity_available = asyncio.Event()
        self._capacity_available.set()
        self._maintenance_lock = asyncio.Lock()
        checkpoint_worker = asyncio.create_task(
            self._checkpoint_worker(self._worker_generation),
            name=f"penguin-checkpoint-worker-{self._worker_generation}",
        )
        self._checkpoint_worker_task = checkpoint_worker
        self._worker_tasks = [checkpoint_worker]
        if self.config.maintenance_interval_seconds > 0:
            self._maintenance_task = asyncio.create_task(
                self._maintenance_loop(self._worker_generation),
                name=f"penguin-checkpoint-maintenance-{self._worker_generation}",
            )
            self._worker_tasks.append(self._maintenance_task)
        self._workers_started = True
        logger.info(
            "Checkpoint worker started generation=%s queue_maxsize=%s",
            self._worker_generation,
            self.checkpoint_queue.maxsize,
        )

    async def stop_workers(self) -> None:
        """Drain and stop workers, including from a foreign caller loop."""

        if not self._workers_started:
            if self._loop is not None and not self._loop.is_closed():
                raise CheckpointWorkerOwnershipError(
                    "Checkpoint owner loop is stopped but not closed"
                )
            self._reset_abandoned_worker_state()
            return

        current_loop = asyncio.get_running_loop()
        owner_loop = self._loop
        if owner_loop is current_loop:
            await self._stop_workers_on_owner_loop()
            return
        if owner_loop is not None and owner_loop.is_running():
            future = asyncio.run_coroutine_threadsafe(
                self._stop_workers_on_owner_loop(),
                owner_loop,
            )
            try:
                await asyncio.wait_for(
                    asyncio.wrap_future(future),
                    timeout=max(
                        0.01,
                        self.config.foreign_shutdown_timeout_seconds,
                    ),
                )
            except asyncio.TimeoutError as exc:
                future.cancel()
                raise CheckpointWorkerOwnershipError(
                    "Timed out waiting for checkpoint owner-loop shutdown"
                ) from exc
            return
        if owner_loop is not None and not owner_loop.is_closed():
            raise CheckpointWorkerOwnershipError(
                "Checkpoint owner loop is stopped but not closed"
            )
        self._reset_abandoned_worker_state()

    async def _stop_workers_on_owner_loop(self) -> None:
        """Await one shared bounded shutdown task on the owner loop."""

        existing = self._stop_task
        if existing is not None:
            await asyncio.shield(existing)
            if self._stop_task is existing and existing.done():
                self._stop_task = None
            return

        task = asyncio.create_task(
            self._perform_stop_workers_on_owner_loop(),
            name=f"penguin-checkpoint-stop-{self._worker_generation}",
        )
        self._stop_task = task
        try:
            await asyncio.shield(task)
        finally:
            if self._stop_task is task and task.done():
                self._stop_task = None

    async def _perform_stop_workers_on_owner_loop(self) -> None:
        """Drain and cancel worker tasks while running on their owner loop."""

        self._workers_stopping = True
        stopping_generation = self._worker_generation
        queue = self.checkpoint_queue
        try:
            background_tasks = list(self._background_checkpoint_tasks)
            for task in background_tasks:
                task.cancel()
            if background_tasks:
                await asyncio.gather(*background_tasks, return_exceptions=True)

            if queue is not None:
                try:
                    await asyncio.wait_for(
                        queue.join(),
                        timeout=max(0.0, self.config.shutdown_drain_timeout_seconds),
                    )
                except asyncio.TimeoutError:
                    # Invalidate the generation before task cancellation. A thread
                    # released after this point must fail its commit guard.
                    self._worker_generation += 1
                    dropped = self._discard_queued_work(queue)
                    self._dropped_on_shutdown += dropped
                    logger.warning(
                        "Checkpoint shutdown drain timed out; dropped=%s "
                        "generation=%s active_offloads=%s",
                        dropped,
                        self._worker_generation - 1,
                        self._active_offload_count(),
                    )

            if self._worker_generation == stopping_generation:
                self._worker_generation += 1

            current_task = asyncio.current_task()
            tasks = [task for task in self._worker_tasks if task is not current_task]
            for task in tasks:
                task.cancel()
            if tasks:
                await asyncio.gather(*tasks, return_exceptions=True)
            self._shutdown_offload_executor()
            detached = self._active_offload_count()
            self._clear_worker_state()
            if detached:
                logger.warning(
                    "Checkpoint asyncio workers stopped with detached filesystem "
                    "operations=%s; restart remains blocked until they finish",
                    detached,
                )
            else:
                logger.info("Checkpoint worker stopped")
        finally:
            self._workers_stopping = False

    def _discard_queued_work(
        self,
        queue: asyncio.Queue[_CheckpointWorkItem],
    ) -> int:
        """Discard queued work after a bounded shutdown timeout."""

        dropped = 0
        while True:
            try:
                item = queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            if item.metadata.type == CheckpointType.AUTO:
                self._pending_auto_checkpoints = max(
                    0,
                    self._pending_auto_checkpoints - 1,
                )
            item.commit_token.clear()
            self._resolve_work_completion(item, False)
            self._release_checkpoint_capacity()
            queue.task_done()
            dropped += 1
        return dropped

    def _reset_abandoned_worker_state(self) -> None:
        """Clear state left by a closed loop, accounting for abandoned work."""

        queue = self.checkpoint_queue
        had_owner_state = self._loop is not None or queue is not None
        if queue is not None:
            dropped = self._discard_queued_work(queue)
            if dropped:
                self._dropped_on_shutdown += dropped
                logger.warning(
                    "Reset abandoned checkpoint worker state; dropped=%s",
                    dropped,
                )
        if had_owner_state:
            self._worker_generation += 1
        self._shutdown_offload_executor()
        self._clear_worker_state()

    def _clear_worker_state(self) -> None:
        """Clear loop-affine worker references after shutdown or abandonment."""

        self._worker_tasks.clear()
        self._checkpoint_worker_task = None
        self._maintenance_task = None
        self._maintenance_lock = None
        self.checkpoint_queue = None
        self._loop = None
        self._owner_thread_id = None
        self._workers_started = False
        self._pending_auto_checkpoints = 0
        self._inflight_checkpoint_work = 0
        self._capacity_available = None
        self._background_checkpoint_tasks.clear()

    def should_checkpoint(self, message: Message) -> bool:
        """
        Determine if this message should trigger a checkpoint.

        Args:
            message: The message to evaluate

        Returns:
            True if a checkpoint should be created
        """
        if not self.config.enabled or not self.config.planes.get("conversation", True):
            return False

        # Skip certain system messages
        if message.category == MessageCategory.SYSTEM:
            # Checkpoint only action results and important system markers.
            important_markers = [
                "action executed",
                "session transition",
                "iteration marker",
            ]
            if not any(
                marker in message.content.lower() for marker in important_markers
            ):
                return False

        # Apply frequency filter
        self._message_counter += 1
        if (self._message_counter % self.config.frequency) != 0:
            return False
        # Admission, storage maintenance, and circuit checks happen inside the
        # bounded async path. Applying the storage floor here would prevent a
        # critically full checkpoint store from ever scheduling the retention
        # work that can recover it.
        return True

    def schedule_auto_checkpoint(
        self,
        session: Session,
        message: Message,
    ) -> bool:
        """Schedule one observed, bounded automatic checkpoint task.

        This synchronous admission guard runs before ``create_task``. Without it,
        a burst of message appends can allocate an unbounded number of coroutine
        tasks before any one of them reaches the async queue reservation.
        """

        if self._workers_stopping:
            self._record_checkpoint_block("worker_stopping")
            return False
        if len(self._background_checkpoint_tasks) >= self._work_capacity_limit:
            self._rejected_auto_checkpoints += 1
            self._record_checkpoint_block("task_capacity_full")
            return False
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return False
        if (
            self._loop is not None
            and self._loop is not loop
            and not self._loop.is_closed()
        ):
            self._record_checkpoint_block("worker_owner_mismatch")
            return False

        task = loop.create_task(
            self.create_checkpoint(
                session,
                message,
            ),
            name="penguin-auto-checkpoint-admission",
        )
        self._background_checkpoint_tasks.add(task)
        task.add_done_callback(self._finish_background_checkpoint_task)
        return True

    def _finish_background_checkpoint_task(self, task: asyncio.Task) -> None:
        """Observe every fire-and-forget checkpoint outcome exactly once."""

        self._background_checkpoint_tasks.discard(task)
        if task.cancelled():
            return
        try:
            task.result()
        except Exception as exc:
            self._record_worker_failure(exc, attempt=1, attempts=1)
            logger.error(
                "Automatic checkpoint task failed before worker completion",
                exc_info=(type(exc), exc, exc.__traceback__),
            )

    async def create_checkpoint(
        self,
        session: Session,
        message: Message,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        name: Optional[str] = None,
        description: Optional[str] = None,
        snapshot_boundary: Optional[CheckpointSnapshotBoundary] = None,
        wait_for_persistence: Optional[bool] = None,
        persistence_timeout_seconds: Optional[float] = None,
    ) -> Optional[str]:
        """
        Create a checkpoint for the current conversation state.

        Args:
            session: Current session to checkpoint
            message: The message that triggered the checkpoint
            checkpoint_type: Type of checkpoint being created
            name: Optional name for manual checkpoints
            description: Optional description

        Returns:
            Checkpoint ID if successful, None otherwise
        """
        if not self.config.enabled:
            return None
        await self.start_workers()
        owner_loop = asyncio.get_running_loop()
        owner_generation = self._worker_generation
        queue = self.checkpoint_queue
        if queue is None:
            raise CheckpointWorkerOwnershipError(
                "Checkpoint worker queue is unavailable"
            )
        reserved = await self._reserve_checkpoint_capacity(checkpoint_type)
        if not reserved:
            return None

        enqueued = False
        item: Optional[_CheckpointWorkItem] = None
        should_wait = (
            checkpoint_type != CheckpointType.AUTO
            if wait_for_persistence is None
            else wait_for_persistence
        )
        try:
            if checkpoint_type == CheckpointType.AUTO:
                if not await self._prepare_auto_checkpoint_admission():
                    return None
            elif self._checkpoint_circuit_is_open():
                raise CheckpointWorkerCircuitOpenError(
                    "Checkpoint worker circuit is open after repeated persistence "
                    "failures"
                )

            self._assert_checkpoint_owner_current(
                owner_loop,
                owner_generation,
                queue,
            )

            checkpoint_id = (
                f"cp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
            )

            boundary = snapshot_boundary or self.capture_snapshot_boundary(session)

            metadata = CheckpointMetadata(
                id=checkpoint_id,
                type=checkpoint_type,
                created_at=datetime.now().isoformat(),
                session_id=session.id,
                message_id=message.id,
                message_count=boundary.message_count,
                name=name,
                description=description,
                auto=(checkpoint_type == CheckpointType.AUTO),
            )

            snapshot_started = time.perf_counter()
            checkpoint_session = session
            if checkpoint_type == CheckpointType.MANUAL:
                checkpoint_session = await self._run_checkpoint_stage_with_retry(
                    "checkpoint.flatten",
                    self._build_flat_snapshot_sync,
                    session,
                    True,
                )
                self._assert_checkpoint_owner_current(
                    owner_loop,
                    owner_generation,
                    queue,
                )
                boundary = self.capture_snapshot_boundary(checkpoint_session)
            session_snapshot = await self._run_checkpoint_stage_with_retry(
                "checkpoint.snapshot",
                self._snapshot_session_at_boundary,
                checkpoint_session,
                boundary,
            )
            self._assert_checkpoint_owner_current(
                owner_loop,
                owner_generation,
                queue,
            )
            record_runtime_duration(
                "checkpoint.snapshot",
                (time.perf_counter() - snapshot_started) * 1000,
            )
            completion = (
                asyncio.get_running_loop().create_future() if should_wait else None
            )
            commit_token = threading.Event()
            commit_token.set()
            item = _CheckpointWorkItem(
                metadata=metadata,
                session_snapshot=session_snapshot,
                generation=owner_generation,
                commit_token=commit_token,
                completion=completion,
            )

            try:
                queue.put_nowait(item)
            except asyncio.QueueFull as exc:
                if checkpoint_type == CheckpointType.AUTO:
                    self._rejected_auto_checkpoints += 1
                    self._record_checkpoint_block("queue_full")
                raise CheckpointQueueFullError(
                    "Checkpoint queue is full after reserved admission"
                ) from exc
            enqueued = True
            logger.debug("Enqueued checkpoint creation: %s", checkpoint_id)

            if completion is not None:
                timeout = (
                    self.config.persistence_ack_timeout_seconds
                    if persistence_timeout_seconds is None
                    else persistence_timeout_seconds
                )
                try:
                    persisted = await asyncio.wait_for(
                        asyncio.shield(completion),
                        timeout=max(0.0, timeout),
                    )
                except asyncio.TimeoutError as exc:
                    item.commit_token.clear()
                    raise CheckpointPersistenceTimeoutError(
                        "Timed out waiting for durable checkpoint persistence"
                    ) from exc
                if not persisted:
                    raise CheckpointPersistenceError(
                        "Checkpoint persistence failed or was dropped before commit"
                    )
            return checkpoint_id
        except asyncio.CancelledError:
            if enqueued and item is not None:
                item.commit_token.clear()
            raise
        except (
            CheckpointPersistenceError,
            CheckpointQueueFullError,
            CheckpointWorkerCircuitOpenError,
            CheckpointWorkerOwnershipError,
        ):
            if checkpoint_type == CheckpointType.AUTO:
                return None
            raise
        except Exception as exc:
            if checkpoint_type == CheckpointType.AUTO:
                logger.warning(
                    "Automatic checkpoint admission failed: %s",
                    type(exc).__name__,
                )
                return None
            raise CheckpointPersistenceError(
                f"Checkpoint preparation failed: {type(exc).__name__}"
            ) from exc
        finally:
            if not enqueued:
                self._release_reserved_checkpoint(checkpoint_type)

    def _assert_checkpoint_owner_current(
        self,
        owner_loop: asyncio.AbstractEventLoop,
        owner_generation: int,
        queue: asyncio.Queue[_CheckpointWorkItem],
    ) -> None:
        """Reject pre-queue work whose owner was stopped during an offload await."""

        if (
            self._workers_stopping
            or not self._workers_started
            or self._loop is not owner_loop
            or self._worker_generation != owner_generation
            or self.checkpoint_queue is not queue
        ):
            raise CheckpointWorkerOwnershipError(
                "Checkpoint worker ownership changed before queue insertion"
            )

    async def _reserve_checkpoint_capacity(
        self,
        checkpoint_type: CheckpointType,
    ) -> bool:
        """Reserve bounded capacity before retention, flattening, or snapshotting."""

        if self._workers_stopping:
            if checkpoint_type == CheckpointType.AUTO:
                self._record_checkpoint_block("worker_stopping")
                return False
            raise CheckpointWorkerOwnershipError("Checkpoint workers are stopping")

        event = self._capacity_available
        if event is None:
            raise CheckpointWorkerOwnershipError(
                "Checkpoint capacity is not owned by a running event loop"
            )

        if checkpoint_type == CheckpointType.AUTO:
            if self._inflight_checkpoint_work >= self._work_capacity_limit:
                self._rejected_auto_checkpoints += 1
                self._record_checkpoint_block("work_capacity_full")
                return False
        else:
            deadline = time.monotonic() + max(
                0.0,
                self.config.enqueue_timeout_seconds,
            )
            while self._inflight_checkpoint_work >= self._work_capacity_limit:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise CheckpointQueueFullError(
                        "Timed out waiting for checkpoint work capacity"
                    )
                try:
                    await asyncio.wait_for(event.wait(), timeout=remaining)
                except asyncio.TimeoutError as exc:
                    raise CheckpointQueueFullError(
                        "Timed out waiting for checkpoint work capacity"
                    ) from exc

        self._inflight_checkpoint_work += 1
        if checkpoint_type == CheckpointType.AUTO:
            self._pending_auto_checkpoints += 1
        if self._inflight_checkpoint_work >= self._work_capacity_limit:
            event.clear()
        return True

    def _release_reserved_checkpoint(
        self,
        checkpoint_type: CheckpointType,
    ) -> None:
        """Release one pre-queue reservation after failure or worker completion."""

        if checkpoint_type == CheckpointType.AUTO:
            self._pending_auto_checkpoints = max(
                0,
                self._pending_auto_checkpoints - 1,
            )
        self._release_checkpoint_capacity()

    def _release_checkpoint_capacity(self) -> None:
        """Release one total-work slot on the owning event loop."""

        self._inflight_checkpoint_work = max(
            0,
            self._inflight_checkpoint_work - 1,
        )
        event = self._capacity_available
        if (
            event is not None
            and self._inflight_checkpoint_work < self._work_capacity_limit
        ):
            event.set()

    async def _run_checkpoint_stage_with_retry(
        self,
        stage: str,
        function,
        *args,
        retry: bool = True,
    ):
        """Run one preparation stage off-loop with bounded retry/circuit behavior."""

        attempts = max(1, int(self.config.worker_max_attempts)) if retry else 1
        for attempt in range(1, attempts + 1):
            commit_token = threading.Event()
            commit_token.set()
            try:
                result = await asyncio.wait_for(
                    self._run_off_loop(
                        function,
                        *args,
                        _commit_token=commit_token,
                    ),
                    timeout=_finite_timeout(
                        self.config.preparation_attempt_timeout_seconds,
                        default=60.0,
                    ),
                )
                return result
            except asyncio.CancelledError:
                commit_token.clear()
                raise
            except asyncio.TimeoutError as exc:
                commit_token.clear()
                timeout_error = CheckpointPersistenceTimeoutError(
                    f"{stage} exceeded its offload deadline"
                )
                self._record_worker_failure(
                    timeout_error,
                    attempt=attempt,
                    attempts=attempts,
                )
                self._force_checkpoint_circuit_open()
                raise timeout_error from exc
            except Exception as exc:
                self._record_worker_failure(exc, attempt=attempt, attempts=attempts)
                if attempt >= attempts or self._checkpoint_circuit_is_open():
                    raise CheckpointPersistenceError(
                        f"{stage} failed after {attempt} attempt(s)"
                    ) from exc
                await asyncio.sleep(self._checkpoint_retry_delay(attempt))
        raise AssertionError("unreachable checkpoint stage retry state")

    async def _run_off_loop(
        self,
        function,
        *args,
        _commit_token: Optional[threading.Event] = None,
    ):
        """Run bounded filesystem/serialization work outside the event loop."""

        generation = self._worker_generation
        executor = self._offload_executor
        if executor is None:
            executor = BoundedDaemonExecutor(
                max_workers=2,
                max_pending=max(4, self._work_capacity_limit * 2),
                thread_name_prefix="penguin-checkpoint-io",
            )
            self._offload_executor = executor
        future = executor.submit(
            self._run_offload_with_generation,
            generation,
            _commit_token,
            function,
            args,
        )
        with self._offload_state_lock:
            self._active_offloads[future] = generation
        future.add_done_callback(self._finish_offload)
        return await asyncio.wrap_future(future)

    def _shutdown_offload_executor(self) -> None:
        """Stop accepting offloads without waiting on an active OS filesystem call."""

        executor = self._offload_executor
        self._offload_executor = None
        if executor is not None:
            executor.shutdown(wait=False, cancel_futures=True)

    def _run_offload_with_generation(
        self,
        generation: int,
        commit_token: Optional[threading.Event],
        function,
        args,
    ):
        """Expose the submitting worker generation to synchronous commit guards."""

        self._persistence_context.generation = generation
        self._persistence_context.commit_token = commit_token
        try:
            return function(*args)
        finally:
            self._persistence_context.generation = None
            self._persistence_context.commit_token = None

    def _finish_offload(self, future: ConcurrentFuture[Any]) -> None:
        """Forget a completed offload, including one detached by cancellation."""

        with self._offload_state_lock:
            self._active_offloads.pop(future, None)

    def _active_offload_count(self) -> int:
        """Return active/queued offloads using a thread-safe snapshot."""

        with self._offload_state_lock:
            return len(self._active_offloads)

    def _has_active_offloads(self) -> bool:
        """Return whether any filesystem thread may still mutate or snapshot."""

        return self._active_offload_count() > 0

    def _checkpoint_retry_delay(self, attempt: int) -> float:
        """Return capped exponential backoff for a completed failed attempt."""

        return min(
            max(0.0, self.config.worker_retry_max_seconds),
            max(0.0, self.config.worker_retry_base_seconds) * (2 ** (attempt - 1)),
        )

    def _resolve_work_completion(
        self,
        item: _CheckpointWorkItem,
        persisted: bool,
    ) -> None:
        """Resolve a durable-ack future without leaking invalid-state errors."""

        completion = item.completion
        if completion is not None and not completion.done():
            completion.set_result(persisted)

    async def run_automatic_maintenance(self) -> int:
        """Run one coalesced retention/reconciliation pass without admitting a write."""

        await self.start_workers()
        return await self._run_automatic_maintenance_owned()

    async def _run_automatic_maintenance_owned(self) -> int:
        """Run maintenance after the caller has established worker ownership."""

        lock = self._maintenance_lock
        if lock is None:
            return 0
        async with lock:
            if self._workers_stopping:
                return 0
            removed = await self._run_checkpoint_stage_with_retry(
                "checkpoint.maintenance",
                self._enforce_automatic_retention_sync,
                self._pending_auto_checkpoints,
            )
            self._reconcile_checkpoint_storage()
            self._last_storage_safety_status = self._storage_safety_monitor.check(
                force=True,
                checkpoint_bytes=self._checkpoint_bytes,
            )
            if self._last_storage_safety_status.allow_background_writes:
                if self._checkpoint_block_reason == "storage_critical":
                    self._checkpoint_block_reason = None
            else:
                self._checkpoint_block_reason = "storage_critical"
            return int(removed)

    async def _maintenance_loop(self, generation: int) -> None:
        """Run retention independently of new checkpoint write admission."""

        while generation == self._worker_generation:
            try:
                await self._run_automatic_maintenance_owned()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.warning(
                    "Checkpoint maintenance pass failed error_type=%s",
                    type(exc).__name__,
                )
            try:
                await asyncio.sleep(max(0.01, self.config.maintenance_interval_seconds))
            except asyncio.CancelledError:
                break

    def capture_snapshot_boundary(
        self,
        session: Session,
    ) -> CheckpointSnapshotBoundary:
        """Capture list limits only after task/capacity admission succeeds."""

        return CheckpointSnapshotBoundary(
            message_count=len(session.messages),
            lifecycle_count=len(session.llm_request_lifecycles),
            tool_call_count=len(session.tool_call_records),
            tool_result_count=len(session.tool_result_records),
            last_active=session.last_active,
        )

    def _snapshot_session_at_boundary(
        self,
        session: Session,
        boundary: CheckpointSnapshotBoundary,
    ) -> Dict[str, Any]:
        """Capture coalesced state off-loop, then enforce trigger list limits."""

        snapshot = copy.deepcopy(session.to_dict())
        snapshot["messages"] = list(snapshot.get("messages", []))[
            : boundary.message_count
        ]
        snapshot["llm_request_lifecycles"] = list(
            snapshot.get("llm_request_lifecycles", [])
        )[: boundary.lifecycle_count]
        snapshot["tool_call_records"] = list(snapshot.get("tool_call_records", []))[
            : boundary.tool_call_count
        ]
        snapshot["tool_result_records"] = list(snapshot.get("tool_result_records", []))[
            : boundary.tool_result_count
        ]
        snapshot["last_active"] = boundary.last_active
        metadata = snapshot.get("metadata")
        if isinstance(metadata, dict):
            metadata["message_count"] = boundary.message_count
        return preserve_native_tool_adjacency(snapshot)

    async def create_checkpoint_and_wait(
        self,
        session: Session,
        message: Message,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        name: Optional[str] = None,
        description: Optional[str] = None,
        snapshot_boundary: Optional[CheckpointSnapshotBoundary] = None,
    ) -> Optional[str]:
        """Create, drain, and stop a checkpoint worker for a transient loop."""

        checkpoint_id: Optional[str] = None
        try:
            checkpoint_id = await self.create_checkpoint(
                session,
                message,
                checkpoint_type,
                name,
                description,
                snapshot_boundary,
                wait_for_persistence=True,
                persistence_timeout_seconds=(
                    self.config.shutdown_drain_timeout_seconds
                ),
            )
        except CheckpointPersistenceError:
            logger.warning(
                "Transient-loop checkpoint did not reach durable persistence",
                exc_info=True,
            )
        finally:
            # ``stop_workers`` owns the bounded drain policy. A separate
            # unbounded ``queue.join`` here would make synchronous callers hang
            # forever when filesystem persistence stalls.
            await self.stop_workers()
        return checkpoint_id

    async def _prepare_auto_checkpoint_admission(self) -> bool:
        """Run automatic retention when needed, then evaluate auto admission."""

        if self._checkpoint_circuit_is_open():
            self._record_checkpoint_block("worker_circuit_open")
            return False
        admitted_count = self._auto_checkpoint_count + self._pending_auto_checkpoints
        status = self._storage_safety_monitor.check(
            checkpoint_bytes=self._checkpoint_bytes,
        )
        self._last_storage_safety_status = status
        if (
            admitted_count > self.config.max_auto_checkpoints
            or not status.allow_background_writes
        ):
            try:
                await self._run_checkpoint_stage_with_retry(
                    "checkpoint.retention",
                    self._enforce_automatic_retention_sync,
                    self._pending_auto_checkpoints,
                )
            except CheckpointPersistenceError:
                self._record_checkpoint_block("retention_failed")
                return False
            self._reconcile_checkpoint_storage()
            self._last_storage_safety_status = self._storage_safety_monitor.check(
                force=True,
                checkpoint_bytes=self._checkpoint_bytes,
            )
        return self._allow_auto_checkpoint(reservation_included=True)

    def refresh_admission_counters(self) -> None:
        """Refresh cached checkpoint counts after index load or test mutation."""

        try:
            snapshot = dict(self.checkpoint_index)
        except RuntimeError:
            snapshot = self._checkpoint_index_snapshot
        else:
            self._checkpoint_index_snapshot = snapshot
        self._auto_checkpoint_count = sum(
            1
            for checkpoint_id, metadata in snapshot.items()
            if metadata.type == CheckpointType.AUTO
            and (self.checkpoints_path / f"{checkpoint_id}.json.gz").exists()
        )

    def get_checkpoint_index_snapshot(self) -> Dict[str, CheckpointMetadata]:
        """Return the last atomically published index without taking the writer lock."""

        return self._checkpoint_index_snapshot

    def _reconcile_checkpoint_storage(self) -> None:
        """Refresh physical-byte and usable-index counters after every mutation."""

        with self._persistence_lock:
            self._checkpoint_bytes = _checkpoint_directory_bytes(self.checkpoints_path)
            self.refresh_admission_counters()

    def _recover_automatic_retention_transactions(self) -> None:
        """Restore or finish crash-interrupted automatic retention transactions."""

        recover_automatic_retention_transactions(
            self,
            metadata_from_manifest=_checkpoint_metadata_from_manifest,
        )

    def _recover_confirmed_cleanup_archives(self) -> None:
        """Reconcile an archive transaction interrupted before its terminal state."""

        recover_confirmed_cleanup_archives(
            self,
            metadata_from_manifest=_checkpoint_metadata_from_manifest,
        )

    def get_storage_safety_status(self) -> Dict[str, Any]:
        """Return current checkpoint admission evidence for diagnostics/UI."""

        status = self._last_storage_safety_status
        payload: Dict[str, Any] = (
            status.to_dict()
            if status is not None
            else {
                "level": "unknown",
                "allow_background_writes": self._checkpoint_block_reason is None,
                "reasons": [],
            }
        )
        payload.update(
            {
                "block_reason": self._checkpoint_block_reason,
                "auto_checkpoint_count": self._auto_checkpoint_count,
                "pending_auto_checkpoints": self._pending_auto_checkpoints,
                "max_auto_checkpoints": self.config.max_auto_checkpoints,
                "checkpoint_bytes": self._checkpoint_bytes,
                "worker": {
                    "started": self._workers_started,
                    "generation": self._worker_generation,
                    "owner_thread_id": self._owner_thread_id,
                    "queue_size": (
                        self.checkpoint_queue.qsize()
                        if self.checkpoint_queue is not None
                        else 0
                    ),
                    "queue_maxsize": max(1, int(self.config.queue_maxsize)),
                    "inflight_work": self._inflight_checkpoint_work,
                    "work_capacity": self._work_capacity_limit,
                    "active_offloads": self._active_offload_count(),
                    "background_tasks": len(self._background_checkpoint_tasks),
                    "maintenance_in_progress": bool(
                        self._maintenance_lock is not None
                        and self._maintenance_lock.locked()
                    ),
                    "consecutive_failures": self._consecutive_worker_failures,
                    "circuit_open": self._checkpoint_circuit_is_open(),
                    "last_error_code": self._last_worker_error_code,
                    "suppressed_error_logs": self._suppressed_worker_error_logs,
                    "rejected_auto_checkpoints": self._rejected_auto_checkpoints,
                    "dropped_on_shutdown": self._dropped_on_shutdown,
                },
            }
        )
        return payload

    def plan_checkpoint_cleanup(
        self,
        *,
        active_session_ids: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
        max_auto_checkpoints: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Return a read-only cleanup plan with no source-data mutation."""

        active_sessions = set(active_session_ids or ())
        current_session = getattr(self.session_manager, "current_session", None)
        current_session_id = getattr(current_session, "id", None)
        if current_session_id:
            active_sessions.add(str(current_session_id))
        retention = self.config.retention
        checkpoint_index = self.get_checkpoint_index_snapshot()
        return build_checkpoint_cleanup_plan(
            self.checkpoints_path,
            checkpoint_index,
            keep_all_hours=retention.get("keep_all_hours", 24),
            keep_every_nth=retention.get("keep_every_nth", 10),
            max_age_days=retention.get("max_age_days", 30),
            max_auto_checkpoints=(
                self.config.max_auto_checkpoints
                if max_auto_checkpoints is None
                else max(0, max_auto_checkpoints)
            ),
            max_checkpoint_bytes=retention.get("max_bytes"),
            active_session_keep=retention.get("active_session_keep", 1),
            active_session_ids=active_sessions,
            now=now,
        ).to_dict()

    def _allow_auto_checkpoint(
        self,
        *,
        check_count: bool = True,
        reservation_included: bool = False,
    ) -> bool:
        """Return whether one new automatic checkpoint may be enqueued."""

        admitted_count = self._auto_checkpoint_count + self._pending_auto_checkpoints
        count_exhausted = (
            admitted_count > self.config.max_auto_checkpoints
            if reservation_included
            else admitted_count >= self.config.max_auto_checkpoints
        )
        if check_count and count_exhausted:
            self._record_checkpoint_block("max_auto_checkpoints")
            return False

        if self._checkpoint_circuit_is_open():
            self._record_checkpoint_block("worker_circuit_open")
            return False

        status = self._storage_safety_monitor.check(
            checkpoint_bytes=self._checkpoint_bytes,
        )
        self._last_storage_safety_status = status
        if not status.allow_background_writes:
            self._record_checkpoint_block("storage_critical")
            return False

        self._checkpoint_block_reason = None
        self._last_logged_block_reason = None
        if status.level.value == "warning":
            logger.warning(
                "Checkpoint storage pressure warning: %s",
                status.to_dict(),
            )
        return True

    def _checkpoint_circuit_is_open(self) -> bool:
        """Return whether repeated worker failures are still in cooldown."""

        if self._circuit_open_until <= 0:
            return False
        now = time.monotonic()
        if now < self._circuit_open_until:
            return True
        self._circuit_open_until = 0.0
        self._consecutive_worker_failures = 0
        self._last_worker_error_code = None
        return False

    def _force_checkpoint_circuit_open(self) -> None:
        """Open the circuit after an indeterminate offload timeout."""

        self._circuit_open_until = time.monotonic() + max(
            0.01,
            self.config.circuit_reset_seconds,
        )
        self._checkpoint_block_reason = "worker_circuit_open"

    def _record_checkpoint_block(self, reason: str) -> None:
        """Record and rate-limit one automatic-checkpoint admission warning."""

        self._checkpoint_block_reason = reason
        if self._last_logged_block_reason == reason:
            return
        self._last_logged_block_reason = reason
        logger.warning(
            "Automatic checkpoint blocked: reason=%s status=%s",
            reason,
            self.get_storage_safety_status(),
        )

    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Rollback conversation to a specific checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to rollback to

        Returns:
            True if successful, False otherwise
        """
        try:
            # Load checkpoint metadata
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"Checkpoint {checkpoint_id} not found in index")
                return False

            # Load the checkpoint session
            checkpoint_session = await self._load_checkpoint_session(checkpoint_id)
            if not checkpoint_session:
                logger.error(f"Failed to load checkpoint session {checkpoint_id}")
                return False

            # Create rollback checkpoint of current state first
            current_session = self.session_manager.current_session
            if current_session:
                # Find the last message for rollback checkpoint
                if current_session.messages:
                    last_message = current_session.messages[-1]
                    await self.create_checkpoint(
                        current_session,
                        last_message,
                        CheckpointType.ROLLBACK,
                        name=f"Before rollback to {checkpoint_id[:8]}",
                    )

            # Restore the checkpoint session
            self.session_manager.current_session = checkpoint_session

            logger.info(f"Rolled back to checkpoint {checkpoint_id}")
            return True

        except Exception as e:
            logger.error(f"Error rolling back to checkpoint {checkpoint_id}: {e}")
            return False

    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None,
    ) -> Optional[str]:
        """
        Create a new branch from a checkpoint.

        Args:
            checkpoint_id: ID of the checkpoint to branch from
            name: Optional name for the branch
            description: Optional description

        Returns:
            New branch checkpoint ID if successful, None otherwise
        """
        try:
            # Load the source checkpoint
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"Checkpoint {checkpoint_id} not found")
                return None

            source_session = await self._load_checkpoint_session(checkpoint_id)
            if not source_session:
                logger.error(f"Failed to load checkpoint session {checkpoint_id}")
                return None

            # Create a new session with flattened snapshot
            branch_session = await self._build_flat_snapshot(source_session)

            # Update metadata for branching
            branch_session.metadata["branched_from"] = checkpoint_id
            branch_session.metadata["branch_point"] = self.checkpoint_index[
                checkpoint_id
            ].message_id
            source_metadata = (
                source_session.metadata
                if isinstance(source_session.metadata, dict)
                else {}
            )
            if isinstance(source_metadata.get("directory"), str):
                branch_session.metadata["directory"] = source_metadata["directory"]
            if isinstance(name, str) and name.strip():
                branch_session.metadata["title"] = name.strip()
            elif (
                isinstance(source_metadata.get("title"), str)
                and source_metadata["title"].strip()
            ):
                branch_session.metadata["title"] = (
                    f"{source_metadata['title'].strip()} (branch)"
                )

            # Create branch checkpoint
            if branch_session.messages:
                last_message = branch_session.messages[-1]
                branch_checkpoint_id = await self.create_checkpoint(
                    branch_session,
                    last_message,
                    CheckpointType.BRANCH,
                    name=name or f"Branch from {checkpoint_id[:8]}",
                    description=description,
                )
                if not branch_checkpoint_id:
                    return None

                # Set as current session
                self.session_manager.current_session = branch_session

                logger.info(
                    "Created branch %s from checkpoint %s",
                    branch_checkpoint_id,
                    checkpoint_id,
                )
                return branch_checkpoint_id

            return None

        except Exception as e:
            logger.error(f"Error branching from checkpoint {checkpoint_id}: {e}")
            return None

    def list_checkpoints(
        self,
        session_id: Optional[str] = None,
        checkpoint_type: Optional[CheckpointType] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """
        List available checkpoints with optional filtering.

        Args:
            session_id: Filter by session ID
            checkpoint_type: Filter by checkpoint type
            limit: Maximum number of checkpoints to return

        Returns:
            List of checkpoint information
        """
        checkpoints = []

        checkpoint_items = list(self.get_checkpoint_index_snapshot().items())
        for cp_id, metadata in checkpoint_items:
            # Apply filters
            if session_id and metadata.session_id != session_id:
                continue
            if checkpoint_type and metadata.type != checkpoint_type:
                continue

            checkpoints.append(
                {
                    "id": cp_id,
                    "type": metadata.type.value,
                    "created_at": metadata.created_at,
                    "session_id": metadata.session_id,
                    "message_count": metadata.message_count,
                    "name": metadata.name,
                    "description": metadata.description,
                    "auto": metadata.auto,
                }
            )

        # Sort by creation time (newest first)
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)

        return checkpoints[:limit]

    async def cleanup_old_checkpoints(
        self,
        *,
        execute: bool = False,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Plan cleanup by default and require explicit confirmation to mutate.

        Args:
            execute: Whether to execute the reviewed retention plan.
            confirmation: Exact resolved workspace path required for execution.

        Returns:
            Dry-run plan or completed cleanup result.

        Raises:
            PermissionError: If destructive execution lacks exact confirmation.
        """

        if not execute:
            plan = self.plan_checkpoint_cleanup()
            return {"status": "dry_run", **plan}

        await self.start_workers()
        plan = self.plan_checkpoint_cleanup()
        expected_confirmation = str(self.workspace_path.expanduser().resolve())
        if confirmation != expected_confirmation:
            raise PermissionError(
                "Checkpoint cleanup execution requires confirmation equal to the "
                f"resolved workspace path: {expected_confirmation}"
            )
        cleaned_count = await self._run_checkpoint_stage_with_retry(
            "checkpoint.confirmed_cleanup",
            self._archive_cleanup_candidates,
            plan,
            retry=False,
        )
        return {
            "status": "completed",
            "dry_run": False,
            "cleaned_count": cleaned_count,
            "reviewed_candidate_count": plan["candidate_count"],
            "reviewed_candidate_bytes": plan["candidate_bytes"],
        }

    def _archive_cleanup_candidates(self, plan: Dict[str, Any]) -> int:
        """Move reviewed candidates to a recoverable archive and update the index."""

        with self._persistence_lock:
            return self._archive_cleanup_candidates_locked(plan)

    def _archive_cleanup_candidates_locked(self, plan: Dict[str, Any]) -> int:
        """Archive reviewed candidates while holding the mutation lock."""

        return archive_cleanup_candidates(
            self,
            plan,
            metadata_to_manifest=_checkpoint_metadata_to_manifest,
        )

    def collect_lineage(self, session_id: str) -> List[str]:
        """
        Collect the full lineage of a session following 'continued_from' links.

        Args:
            session_id: ID of the session to trace

        Returns:
            List of session IDs from root to the given session
        """
        chain = []
        current = session_id

        while current:
            chain.insert(0, current)
            # Get the continued_from link from session index
            session_info = self.session_manager.session_index.get(current, {})
            current = session_info.get("continued_from")

        return chain

    async def _build_flat_snapshot(self, tail_session: Session) -> Session:
        """
        Build a flattened snapshot containing the complete conversation history.

        Args:
            tail_session: The session to build snapshot from

        Returns:
            New session with flattened message history
        """
        return await self._run_checkpoint_stage_with_retry(
            "checkpoint.flatten",
            self._build_flat_snapshot_sync,
            tail_session,
            False,
        )

    def _build_flat_snapshot_sync(
        self,
        tail_session: Session,
        preserve_session_identity: bool = False,
    ) -> Session:
        """Build a flattened session snapshot outside the event-loop thread."""

        lineage = self.collect_lineage(tail_session.id)
        load_session_readonly = getattr(
            self.session_manager,
            "load_session_readonly",
            None,
        )
        if not callable(load_session_readonly):

            def load_session_readonly(_session_id: str) -> Optional[Session]:
                raise CheckpointPersistenceError(
                    "Checkpoint lineage flattening requires a non-mutating "
                    "load_session_readonly() collaborator"
                )

        return build_flat_session_snapshot(
            tail_session,
            lineage=lineage,
            load_session=load_session_readonly,
            preserve_session_identity=preserve_session_identity,
        )

    async def _checkpoint_worker(self, generation: int) -> None:
        """Process immutable checkpoint work with bounded failure behavior."""

        queue = self.checkpoint_queue
        assert queue is not None
        while generation == self._worker_generation:
            remaining = self._circuit_open_until - time.monotonic()
            if remaining > 0:
                try:
                    await asyncio.sleep(remaining)
                except asyncio.CancelledError:
                    break
                continue
            try:
                item = await queue.get()
            except asyncio.CancelledError:
                break
            except Exception as exc:
                await self._handle_worker_loop_error(exc)
                continue

            try:
                persisted = await self._persist_work_item_with_retry(item)
                self._resolve_work_completion(item, persisted)
            except asyncio.CancelledError:
                self._resolve_work_completion(item, False)
                raise
            finally:
                if item.metadata.type == CheckpointType.AUTO:
                    self._pending_auto_checkpoints = max(
                        0,
                        self._pending_auto_checkpoints - 1,
                    )
                self._release_checkpoint_capacity()
                queue.task_done()

    async def _persist_work_item_with_retry(
        self,
        item: _CheckpointWorkItem,
    ) -> bool:
        """Persist one item with bounded exponential backoff and circuit state."""

        attempts = max(1, int(self.config.worker_max_attempts))
        for attempt in range(1, attempts + 1):
            try:
                await asyncio.wait_for(
                    self._run_off_loop(
                        self._persist_checkpoint_work_item,
                        item,
                        _commit_token=item.commit_token,
                    ),
                    timeout=_finite_timeout(
                        self.config.persistence_attempt_timeout_seconds,
                        default=60.0,
                    ),
                )
            except asyncio.CancelledError:
                item.commit_token.clear()
                raise
            except asyncio.TimeoutError:
                item.commit_token.clear()
                timeout_error = CheckpointPersistenceTimeoutError(
                    "Checkpoint persistence attempt exceeded its offload deadline"
                )
                self._record_worker_failure(
                    timeout_error,
                    attempt=attempt,
                    attempts=attempts,
                )
                self._force_checkpoint_circuit_open()
                return False
            except Exception as exc:
                self._record_worker_failure(exc, attempt=attempt, attempts=attempts)
                if attempt >= attempts or self._checkpoint_circuit_is_open():
                    return False
                await asyncio.sleep(self._checkpoint_retry_delay(attempt))
                continue
            self._record_worker_success()
            return True
        return False

    def _persist_checkpoint_work_item(self, item: _CheckpointWorkItem) -> None:
        """Persist one item while preserving compatibility with two-arg test hooks."""

        self._persistence_context.commit_token = item.commit_token
        try:
            self._assert_checkpoint_generation_current(item.generation)
            self._persist_checkpoint_snapshot(item.session_snapshot, item.metadata)
        finally:
            self._persistence_context.commit_token = None

    async def _handle_worker_loop_error(self, exc: BaseException) -> None:
        """Back off after an unexpected queue/worker-loop failure."""

        self._record_worker_failure(exc, attempt=1, attempts=1)
        delay = max(0.01, self.config.worker_retry_base_seconds)
        if self._checkpoint_circuit_is_open():
            delay = max(delay, self.config.circuit_reset_seconds)
        await asyncio.sleep(
            min(delay, max(delay, self.config.worker_retry_max_seconds))
        )

    def _record_worker_failure(
        self,
        exc: BaseException,
        *,
        attempt: int,
        attempts: int,
    ) -> None:
        """Update bounded failure/circuit diagnostics with rate-limited logging."""

        self._consecutive_worker_failures += 1
        self._last_worker_error_code = type(exc).__name__[:64]
        threshold = max(1, int(self.config.circuit_failure_threshold))
        if self._consecutive_worker_failures >= threshold:
            self._circuit_open_until = time.monotonic() + max(
                0.0,
                self.config.circuit_reset_seconds,
            )
            self._checkpoint_block_reason = "worker_circuit_open"

        now = time.monotonic()
        if now - self._last_worker_error_log_at >= max(
            0.0, self.config.worker_error_log_interval_seconds
        ):
            logger.error(
                "Checkpoint worker persistence failed error_type=%s attempt=%s/%s "
                "consecutive=%s circuit_open=%s suppressed=%s",
                self._last_worker_error_code,
                attempt,
                attempts,
                self._consecutive_worker_failures,
                self._circuit_open_until > now,
                self._suppressed_worker_error_logs,
            )
            self._last_worker_error_log_at = now
            self._suppressed_worker_error_logs = 0
        else:
            self._suppressed_worker_error_logs += 1

    def _record_worker_success(self) -> None:
        """Close failure/circuit state after one fully persisted checkpoint."""

        self._consecutive_worker_failures = 0
        self._circuit_open_until = 0.0
        self._last_worker_error_code = None
        if self._checkpoint_block_reason == "worker_circuit_open":
            self._checkpoint_block_reason = None

    def _persist_checkpoint_snapshot(
        self,
        session_snapshot: Dict[str, Any],
        metadata: CheckpointMetadata,
    ) -> None:
        """Serialize, compress, write, index, and retain one immutable snapshot."""

        self._assert_checkpoint_generation_current()
        with self._persistence_lock:
            self._persist_checkpoint_snapshot_locked(session_snapshot, metadata)

    def _assert_checkpoint_generation_current(
        self,
        expected_generation: Optional[int] = None,
    ) -> None:
        """Prevent a filesystem thread from committing after worker shutdown."""

        if expected_generation is None:
            expected_generation = getattr(
                self._persistence_context,
                "generation",
                None,
            )
        if (
            expected_generation is not None
            and expected_generation != self._worker_generation
        ):
            raise _CheckpointCommitInvalidatedError(
                "Checkpoint worker generation was invalidated before commit"
            )
        commit_token = getattr(
            self._persistence_context,
            "commit_token",
            None,
        )
        if isinstance(commit_token, threading.Event) and not commit_token.is_set():
            raise _CheckpointCommitInvalidatedError(
                "Checkpoint offload deadline invalidated this commit"
            )

    def _persist_checkpoint_snapshot_locked(
        self,
        session_snapshot: Dict[str, Any],
        metadata: CheckpointMetadata,
    ) -> None:
        """Persist one snapshot while holding the checkpoint mutation lock."""

        persistence_started = time.perf_counter()
        checkpoint_file = self.checkpoints_path / f"{metadata.id}.json.gz"
        temporary = checkpoint_file.with_name(
            f".{checkpoint_file.name}.{uuid.uuid4().hex}.tmp"
        )
        replaced_new_file = False
        previous_size = 0
        previous_metadata: Optional[CheckpointMetadata] = None
        index_committed = False
        try:
            self._assert_checkpoint_generation_current()
            metadata_dict = metadata.__dict__.copy()
            metadata_dict["type"] = metadata.type.value
            serialization_started = time.perf_counter()
            checkpoint_data = {
                "metadata": metadata_dict,
                "session": session_snapshot,
            }
            compressed_data = gzip.compress(
                json.dumps(checkpoint_data, separators=(",", ":")).encode("utf-8")
            )
            record_runtime_duration(
                "checkpoint.serialization",
                (time.perf_counter() - serialization_started) * 1000,
            )

            previous_size = (
                checkpoint_file.stat().st_size if checkpoint_file.exists() else 0
            )
            write_started = time.perf_counter()
            with temporary.open("wb") as handle:
                handle.write(compressed_data)
                handle.flush()
                os.fsync(handle.fileno())
            self._assert_checkpoint_generation_current()
            temporary.replace(checkpoint_file)
            replaced_new_file = previous_size == 0
            _fsync_directory(self.checkpoints_path)
            self._checkpoint_bytes = _checkpoint_directory_bytes(self.checkpoints_path)
            record_runtime_duration(
                "checkpoint.write",
                (time.perf_counter() - write_started) * 1000,
            )

            previous_metadata = self.checkpoint_index.get(metadata.id)
            self._assert_checkpoint_generation_current()
            self.checkpoint_index[metadata.id] = metadata
            index_started = time.perf_counter()
            try:
                self._save_checkpoint_index_or_raise()
            except Exception:
                if previous_metadata is None:
                    self.checkpoint_index.pop(metadata.id, None)
                else:
                    self.checkpoint_index[metadata.id] = previous_metadata
                if replaced_new_file:
                    checkpoint_file.unlink(missing_ok=True)
                    _fsync_directory(self.checkpoints_path)
                self._reconcile_checkpoint_storage()
                raise
            index_committed = True
            record_runtime_duration(
                "checkpoint.index",
                (time.perf_counter() - index_started) * 1000,
            )
            self.refresh_admission_counters()
            self._checkpoint_bytes = _checkpoint_directory_bytes(self.checkpoints_path)
            self._enforce_automatic_retention_sync()
            logger.debug("Created checkpoint file: %s", metadata.id)
        except _CheckpointCommitInvalidatedError:
            if index_committed:
                # File + index are already durable. A watchdog can cancel
                # post-commit retention, but deleting only the data here would
                # corrupt the committed checkpoint. Keep the durable pair and
                # let the next maintenance pass enforce retention.
                self._reconcile_checkpoint_storage()
                logger.warning(
                    "Checkpoint post-commit maintenance was invalidated id=%s",
                    metadata.id,
                )
                return
            if previous_metadata is None:
                self.checkpoint_index.pop(metadata.id, None)
            else:
                self.checkpoint_index[metadata.id] = previous_metadata
            if replaced_new_file:
                checkpoint_file.unlink(missing_ok=True)
                _fsync_directory(self.checkpoints_path)
            self._reconcile_checkpoint_storage()
            raise
        finally:
            temporary.unlink(missing_ok=True)
            record_runtime_duration(
                "checkpoint.persistence",
                (time.perf_counter() - persistence_started) * 1000,
            )

    def _enforce_automatic_retention_sync(
        self,
        reserve_auto_slots: int = 0,
    ) -> int:
        """Delete only reviewed automatic candidates and persist the index once."""

        with self._persistence_lock:
            return self._enforce_automatic_retention_locked(
                reserve_auto_slots=reserve_auto_slots
            )

    def _enforce_automatic_retention_locked(
        self,
        *,
        reserve_auto_slots: int,
    ) -> int:
        """Enforce automatic retention while holding the mutation lock."""

        return enforce_automatic_retention(
            self,
            reserve_auto_slots=reserve_auto_slots,
            is_auto_checkpoint=_is_automatic_checkpoint,
            metadata_to_manifest=_checkpoint_metadata_to_manifest,
        )

    async def _load_checkpoint_session(self, checkpoint_id: str) -> Optional[Session]:
        """
        Load a session from a checkpoint file.

        Args:
            checkpoint_id: ID of the checkpoint to load

        Returns:
            Session object if successful, None otherwise
        """
        await self.start_workers()
        try:
            return await self._run_checkpoint_stage_with_retry(
                "checkpoint.load",
                self._load_checkpoint_session_sync,
                checkpoint_id,
            )
        except CheckpointPersistenceError as exc:
            logger.error(
                "Error loading checkpoint %s: %s",
                checkpoint_id,
                exc,
            )
            return None

    def _load_checkpoint_session_sync(
        self,
        checkpoint_id: str,
    ) -> Optional[Session]:
        """Load/decompress one checkpoint under the writer lock off-loop."""

        try:
            checkpoint_file = self.checkpoints_path / f"{checkpoint_id}.json.gz"
            with self._persistence_lock:
                self._assert_checkpoint_generation_current()
                if not checkpoint_file.exists():
                    logger.error("Checkpoint file not found: %s", checkpoint_file)
                    return None
                compressed_data = checkpoint_file.read_bytes()
                data = json.loads(gzip.decompress(compressed_data).decode("utf-8"))

            # Extract session data
            session_data = data.get("session", {})
            return Session.from_dict(session_data)

        except Exception as e:
            logger.error("Error loading checkpoint %s: %s", checkpoint_id, e)
            return None

    def _load_checkpoint_index(self) -> None:
        """Load the checkpoint index from disk."""
        try:
            if self.index_path.exists():
                with open(self.index_path) as f:
                    data = json.load(f)

                # Convert dict data back to CheckpointMetadata objects
                for cp_id, metadata_dict in data.items():
                    # Convert type string back to enum
                    metadata_dict["type"] = CheckpointType(metadata_dict["type"])
                    self.checkpoint_index[cp_id] = CheckpointMetadata(**metadata_dict)

        except Exception as e:
            logger.error(f"Error loading checkpoint index: {e}")
            self.checkpoint_index = {}

    def _save_checkpoint_index(self) -> None:
        """Save the checkpoint index to disk."""
        try:
            self._save_checkpoint_index_or_raise()
        except Exception as e:
            logger.error(f"Error saving checkpoint index: {e}")

    def _save_checkpoint_index_or_raise(self) -> None:
        """Persist the full index atomically through a unique temporary file."""

        with self._persistence_lock:
            index_data: Dict[str, Dict[str, Any]] = {}
            for checkpoint_id, metadata in self.checkpoint_index.items():
                metadata_dict = metadata.__dict__.copy()
                metadata_dict["type"] = metadata.type.value
                index_data[checkpoint_id] = metadata_dict
            _write_json_atomic(self.index_path, index_data)


def _checkpoint_directory_bytes(path: Path) -> int:
    """Return current checkpoint file bytes once for cached admission accounting."""

    total = 0
    if not path.exists():
        return total
    for item in path.glob("*.json.gz"):
        try:
            total += item.stat().st_size
        except OSError:
            continue
    return total


def _checkpoint_metadata_from_manifest(
    metadata_payload: Dict[str, Any],
) -> CheckpointMetadata:
    """Rebuild manager-owned metadata from a retention manifest record."""

    restored_metadata = dict(metadata_payload)
    restored_metadata["type"] = CheckpointType(restored_metadata["type"])
    return CheckpointMetadata(**restored_metadata)


def _checkpoint_metadata_to_manifest(
    metadata: CheckpointMetadata,
) -> Dict[str, Any]:
    """Serialize manager-owned metadata for a retention manifest record."""

    return {
        **metadata.__dict__,
        "type": metadata.type.value,
    }


def _is_automatic_checkpoint(metadata: CheckpointMetadata) -> bool:
    """Return whether one metadata record is eligible for automatic retention."""

    return metadata.type == CheckpointType.AUTO


def _finite_timeout(value: float, *, default: float) -> float:
    """Return a finite positive watchdog timeout for checkpoint offloads."""

    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if not math.isfinite(parsed) or parsed <= 0:
        return default
    return parsed
