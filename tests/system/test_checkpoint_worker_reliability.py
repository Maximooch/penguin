"""Checkpoint worker ownership, backpressure, retry, and retention tests."""

from __future__ import annotations

import asyncio
import gzip
import json
import logging
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

import pytest

from penguin.system.checkpoint_executor import BoundedDaemonExecutor
from penguin.system.checkpoint_manager import (
    CheckpointConfig,
    CheckpointManager,
    CheckpointMetadata,
    CheckpointPersistenceError,
    CheckpointPersistenceTimeoutError,
    CheckpointType,
    CheckpointWorkerOwnershipError,
)
from penguin.system.checkpoint_snapshot import preserve_native_tool_adjacency
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.storage_safety import (
    DiskUsage,
    StorageSafetyMonitor,
    StorageSafetyPolicy,
)

if TYPE_CHECKING:
    from pathlib import Path


class _SessionManager:
    """Minimal lineage/session collaborator."""

    def __init__(self) -> None:
        self.session_index: dict[str, dict[str, Any]] = {}
        self.current_session: Session | None = None
        self.readonly_sessions: dict[str, Session] = {}
        self.readonly_load_thread_ids: list[int] = []

    def load_session(self, _session_id: str) -> Session | None:
        return None

    def load_session_readonly(self, session_id: str) -> Session | None:
        self.readonly_load_thread_ids.append(threading.get_ident())
        return self.readonly_sessions.get(session_id)


def _healthy_monitor(tmp_path: Path) -> StorageSafetyMonitor:
    """Return a deterministic storage monitor that permits background writes."""

    return StorageSafetyMonitor(
        tmp_path,
        policy=StorageSafetyPolicy(
            warning_free_bytes=10,
            critical_free_bytes=5,
            warning_free_fraction=0.01,
            critical_free_fraction=0.001,
            max_checkpoint_bytes=None,
        ),
        disk_usage_provider=lambda _path: DiskUsage(
            total=10_000,
            used=100,
            free=9_900,
        ),
    )


def _session(*, session_id: str = "session", content: str = "message") -> Session:
    """Return one checkpointable session."""

    session = Session(id=session_id)
    session.add_message(
        Message(
            role="user",
            content=content,
            category=MessageCategory.DIALOG,
        )
    )
    return session


@pytest.mark.asyncio
async def test_snapshot_and_persistence_run_off_loop_with_safe_coalesced_boundary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Coalesced state stays bounded and drops native tool units crossing its edge."""

    session_manager = _SessionManager()
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        CheckpointConfig(queue_maxsize=2),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    session = _session(content="state-at-trigger")
    session_manager.current_session = session
    loop_thread_id = threading.get_ident()
    snapshot_threads: list[int] = []
    persistence_threads: list[int] = []
    worker_entered = threading.Event()
    worker_release = threading.Event()

    original_snapshot = manager._snapshot_session_at_boundary

    def tracked_snapshot(
        snapshot_session: Session,
        boundary,
    ) -> dict[str, Any]:
        snapshot_threads.append(threading.get_ident())
        return original_snapshot(snapshot_session, boundary)

    monkeypatch.setattr(manager, "_snapshot_session_at_boundary", tracked_snapshot)
    original_persist = manager._persist_checkpoint_snapshot

    def gated_persist(
        snapshot: dict[str, Any],
        metadata: CheckpointMetadata,
    ) -> None:
        persistence_threads.append(threading.get_ident())
        worker_entered.set()
        assert worker_release.wait(timeout=5)
        original_persist(snapshot, metadata)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", gated_persist)

    trigger_message = session.messages[-1]
    boundary = manager.capture_snapshot_boundary(session)
    checkpoint_task = asyncio.create_task(
        manager.create_checkpoint(
            session,
            trigger_message,
            snapshot_boundary=boundary,
        )
    )
    trigger_message.content = "post-trigger mutation"
    trigger_message.metadata["tool_calls"] = [
        {
            "id": "call_late",
            "type": "function",
            "function": {"name": "read_file", "arguments": "{}"},
        }
    ]
    session.add_tool_call_record(
        {"call_id": "call_late", "name": "read_file", "arguments": "{}"}
    )
    session.add_tool_result_record(
        {"call_id": "call_late", "status": "completed", "output": "late"}
    )
    session.add_message(
        Message(
            role="user",
            content="mutation-before-checkpoint-task-starts",
            category=MessageCategory.DIALOG,
        )
    )
    checkpoint_id = await checkpoint_task
    assert checkpoint_id is not None
    assert await asyncio.to_thread(worker_entered.wait, 5)
    worker_release.set()
    assert manager.checkpoint_queue is not None
    await manager.checkpoint_queue.join()
    await manager.stop_workers()

    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    payload = json.loads(gzip.decompress(checkpoint_file.read_bytes()))
    contents = [message["content"] for message in payload["session"]["messages"]]
    assert contents == ["post-trigger mutation"]
    assert "tool_calls" not in payload["session"]["messages"][0]["metadata"]
    assert payload["session"]["tool_call_records"] == []
    assert payload["session"]["tool_result_records"] == []
    assert snapshot_threads and snapshot_threads[0] != loop_thread_id
    assert persistence_threads and persistence_threads[0] != loop_thread_id


@pytest.mark.asyncio
async def test_auto_checkpoint_trigger_state_never_splits_native_tool_pair(
    tmp_path: Path,
) -> None:
    """A later tool mutation cannot leak into its earlier assistant checkpoint."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    conversation = ConversationSystem(checkpoint_manager=manager)
    conversation.add_assistant_message("I will inspect the file")
    conversation.add_action_result(
        "read_file",
        "contents",
        tool_call_id="call_pair",
        tool_arguments='{"path":"README.md"}',
    )

    while manager._background_checkpoint_tasks:
        await asyncio.gather(
            *list(manager._background_checkpoint_tasks),
            return_exceptions=True,
        )
    assert manager.checkpoint_queue is not None
    await manager.checkpoint_queue.join()
    await manager.stop_workers()

    checkpoint_files = sorted(manager.checkpoints_path.glob("*.json.gz"))
    assert len(checkpoint_files) == 2
    for checkpoint_file in checkpoint_files:
        payload = json.loads(gzip.decompress(checkpoint_file.read_bytes()))["session"]
        call_ids = {
            tool_call["id"]
            for message in payload["messages"]
            for tool_call in message.get("metadata", {}).get("tool_calls", [])
        }
        result_ids = {
            message.get("metadata", {}).get("tool_call_id")
            for message in payload["messages"]
            if message.get("role") == "tool"
        }
        assert call_ids == result_ids
        for call_id in call_ids:
            assistant_index = next(
                index
                for index, message in enumerate(payload["messages"])
                if call_id
                in {
                    tool_call.get("id")
                    for tool_call in message.get("metadata", {}).get("tool_calls", [])
                }
            )
            tool_index = next(
                index
                for index, message in enumerate(payload["messages"])
                if message.get("role") == "tool"
                and message.get("metadata", {}).get("tool_call_id") == call_id
            )
            assert assistant_index < tool_index
            assert all(
                message.get("role") == "tool"
                for message in payload["messages"][assistant_index + 1 : tool_index + 1]
            )


def test_tool_adjacency_sanitizer_requires_message_level_pair() -> None:
    """Side records cannot make an orphan native assistant/tool message valid."""

    assistant_only = {
        "messages": [
            {
                "role": "assistant",
                "metadata": {"tool_calls": [{"id": "call_one"}]},
            }
        ],
        "tool_call_records": [{"call_id": "call_one"}],
        "tool_result_records": [{"call_id": "call_one"}],
    }
    tool_only = {
        "messages": [
            {
                "role": "tool",
                "metadata": {"tool_call_id": "call_two"},
            }
        ],
        "tool_call_records": [{"call_id": "call_two"}],
        "tool_result_records": [{"call_id": "call_two"}],
    }

    sanitized_assistant = preserve_native_tool_adjacency(assistant_only)
    sanitized_tool = preserve_native_tool_adjacency(tool_only)

    assert sanitized_assistant["messages"][0]["metadata"] == {}
    assert sanitized_assistant["tool_call_records"] == []
    assert sanitized_assistant["tool_result_records"] == []
    assert sanitized_tool["messages"] == []
    assert sanitized_tool["tool_call_records"] == []
    assert sanitized_tool["tool_result_records"] == []


def test_tool_adjacency_sanitizer_rejects_interleaved_native_pair() -> None:
    """A user/system message between a call and result invalidates the whole unit."""

    snapshot = {
        "messages": [
            {
                "role": "assistant",
                "metadata": {"tool_calls": [{"id": "call_interleaved"}]},
            },
            {"role": "user", "content": "Do not continue that tool call."},
            {
                "role": "tool",
                "metadata": {"tool_call_id": "call_interleaved"},
            },
        ],
        "tool_call_records": [{"call_id": "call_interleaved"}],
        "tool_result_records": [{"call_id": "call_interleaved"}],
    }

    sanitized = preserve_native_tool_adjacency(snapshot)

    assert [message["role"] for message in sanitized["messages"]] == [
        "assistant",
        "user",
    ]
    assert sanitized["messages"][0]["metadata"] == {}
    assert sanitized["tool_call_records"] == []
    assert sanitized["tool_result_records"] == []


@pytest.mark.asyncio
async def test_bounded_queue_rejects_new_auto_checkpoint_without_blocking(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Queue pressure has explicit reject-new-auto behavior and bounded memory."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(queue_maxsize=2, max_auto_checkpoints=100),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", blocked_persist)
    first = _session(session_id="one")
    second = _session(session_id="two")
    third = _session(session_id="three")

    assert await manager.create_checkpoint(first, first.messages[-1]) is not None
    assert await asyncio.to_thread(entered.wait, 5)
    assert await manager.create_checkpoint(second, second.messages[-1]) is not None
    rejected = await asyncio.wait_for(
        manager.create_checkpoint(third, third.messages[-1]),
        timeout=0.5,
    )

    assert rejected is None
    assert manager.checkpoint_queue is not None
    assert manager.checkpoint_queue.maxsize == 2
    assert manager.checkpoint_queue.qsize() == 1
    status = manager.get_storage_safety_status()["worker"]
    assert status["rejected_auto_checkpoints"] == 1

    release.set()
    await manager.checkpoint_queue.join()
    await manager.stop_workers()


def test_worker_restarts_after_owner_loop_closes(tmp_path: Path) -> None:
    """A stale loop/queue cannot leave future checkpoint work silently dead."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )

    asyncio.run(manager.start_workers())
    first_generation = manager._worker_generation

    async def restart_and_stop() -> None:
        await manager.start_workers()
        await manager.start_workers()
        assert manager._worker_generation > first_generation
        await manager.stop_workers()
        await manager.stop_workers()

    asyncio.run(restart_and_stop())
    assert manager._workers_started is False
    assert manager.checkpoint_queue is None


@pytest.mark.asyncio
async def test_cancelled_checkpoint_worker_is_not_masked_by_maintenance_task(
    tmp_path: Path,
) -> None:
    """Worker health is based on the queue consumer, not any sibling task."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(maintenance_interval_seconds=60),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    await manager.start_workers()
    original_worker = manager._checkpoint_worker_task
    assert original_worker is not None
    original_generation = manager._worker_generation
    original_worker.cancel()
    await asyncio.gather(original_worker, return_exceptions=True)

    await manager.start_workers()

    assert manager._worker_generation > original_generation
    assert manager._checkpoint_worker_task is not original_worker
    assert manager._checkpoint_worker_task is not None
    assert not manager._checkpoint_worker_task.done()
    session = _session()
    checkpoint_id = await manager.create_checkpoint(
        session,
        session.messages[-1],
        CheckpointType.MANUAL,
    )
    assert checkpoint_id in manager.checkpoint_index
    await manager.stop_workers()


def test_sync_conversation_path_drains_transient_worker_loop(tmp_path: Path) -> None:
    """A synchronous caller cannot leave work attached to an `asyncio.run` loop."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    conversation = ConversationSystem(checkpoint_manager=manager)

    conversation.add_message(
        "user",
        "sync checkpoint",
        MessageCategory.DIALOG,
    )

    checkpoint_files = list(manager.checkpoints_path.glob("*.json.gz"))
    assert len(checkpoint_files) == 1
    assert manager._workers_started is False
    assert manager.checkpoint_queue is None


def test_sync_conversation_returns_when_filesystem_thread_is_blocked(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`asyncio.run` teardown never waits for the detached checkpoint executor."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            shutdown_drain_timeout_seconds=0.02,
            maintenance_interval_seconds=0,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        release.wait(timeout=5)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", blocked_persist)
    conversation = ConversationSystem(checkpoint_manager=manager)
    finished = threading.Event()

    def add_message() -> None:
        conversation.add_message(
            "user",
            "bounded sync checkpoint",
            MessageCategory.DIALOG,
        )
        finished.set()

    caller = threading.Thread(target=add_message, daemon=True)
    caller.start()
    assert entered.wait(timeout=2)
    try:
        assert finished.wait(timeout=0.5)
    finally:
        release.set()
        caller.join(timeout=2)
    assert not caller.is_alive()


@pytest.mark.asyncio
async def test_transient_loop_shutdown_is_bounded_when_persistence_blocks(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The synchronous compatibility path cannot wait forever on queue.join()."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(shutdown_drain_timeout_seconds=0.02),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        release.wait(timeout=2)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", blocked_persist)
    session = _session()
    create_task = asyncio.create_task(
        manager.create_checkpoint_and_wait(session, session.messages[-1])
    )
    assert await asyncio.to_thread(entered.wait, 1)
    try:
        checkpoint_id = await asyncio.wait_for(create_task, timeout=0.25)
    finally:
        release.set()
        if manager._workers_started:
            await manager.stop_workers()

    assert checkpoint_id is None
    assert manager._workers_started is False
    assert manager.checkpoint_queue is None


@pytest.mark.asyncio
async def test_shutdown_during_prequeue_snapshot_cannot_enqueue_false_success(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership changes during snapshot reject the captured orphan queue."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            shutdown_drain_timeout_seconds=0.02,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()
    original_snapshot = manager._snapshot_session_at_boundary

    def gated_snapshot(session: Session, boundary) -> dict[str, Any]:
        entered.set()
        assert release.wait(timeout=5)
        return original_snapshot(session, boundary)

    monkeypatch.setattr(manager, "_snapshot_session_at_boundary", gated_snapshot)
    session = _session()
    create_task = asyncio.create_task(
        manager.create_checkpoint(session, session.messages[-1])
    )
    assert await asyncio.to_thread(entered.wait, 2)

    await manager.stop_workers()
    release.set()
    result = await asyncio.wait_for(create_task, timeout=2)

    assert result is None
    assert manager.checkpoint_queue is None
    assert manager.checkpoint_index == {}
    assert not list(manager.checkpoints_path.glob("*.json.gz"))


@pytest.mark.asyncio
async def test_snapshot_watchdog_opens_circuit_without_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A never-returning snapshot cannot hold admission forever."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            preparation_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_snapshot(
        _session: Session,
        _boundary,
    ) -> dict[str, Any]:
        entered.set()
        release.wait(timeout=5)
        return {}

    monkeypatch.setattr(manager, "_snapshot_session_at_boundary", blocked_snapshot)
    session = _session()
    started_at = asyncio.get_running_loop().time()
    result = await manager.create_checkpoint(session, session.messages[-1])

    assert result is None
    assert asyncio.get_running_loop().time() - started_at < 0.5
    assert entered.is_set()
    status = manager.get_storage_safety_status()["worker"]
    assert status["circuit_open"] is True
    assert status["inflight_work"] == 0
    assert status["active_offloads"] == 1

    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_persistence_watchdog_invalidates_late_commit_without_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A timed-out persistence thread cannot commit when it eventually returns."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            persistence_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()
    original_persist = manager._persist_checkpoint_snapshot

    def gated_persist(
        snapshot: dict[str, Any],
        metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        assert release.wait(timeout=5)
        original_persist(snapshot, metadata)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", gated_persist)
    session = _session()
    checkpoint_id = await manager.create_checkpoint(session, session.messages[-1])
    assert checkpoint_id is not None
    assert await asyncio.to_thread(entered.wait, 2)
    assert manager.checkpoint_queue is not None
    await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=0.5)
    assert manager.get_storage_safety_status()["worker"]["circuit_open"] is True

    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)

    assert checkpoint_id not in manager.checkpoint_index
    assert not (manager.checkpoints_path / f"{checkpoint_id}.json.gz").exists()
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_hung_writer_lock_cannot_block_checkpoint_read_surfaces(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """List/stats planning reads use the published index, never the writer RLock."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            persistence_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def hold_writer_lock(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        with manager._persistence_lock:
            entered.set()
            release.wait(timeout=5)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", hold_writer_lock)
    session = _session()
    assert await manager.create_checkpoint(session, session.messages[-1]) is not None
    assert await asyncio.to_thread(entered.wait, 2)
    assert manager.checkpoint_queue is not None
    await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=0.5)

    started_at = time.monotonic()
    assert isinstance(manager.list_checkpoints(), list)
    assert isinstance(manager.plan_checkpoint_cleanup(), dict)
    assert time.monotonic() - started_at < 0.15

    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_confirmed_cleanup_is_bounded_when_writer_lock_is_held(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Confirmed cleanup surfaces a timeout instead of joining a blocked writer."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            preparation_attempt_timeout_seconds=0.02,
            persistence_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
            retention={
                "keep_all_hours": 0,
                "keep_every_nth": 10,
                "max_age_days": 1,
                "max_bytes": 10_000,
                "active_session_keep": 1,
            },
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    old_id = "cleanup-old"
    old_file = manager.checkpoints_path / f"{old_id}.json.gz"
    old_file.write_bytes(b"old checkpoint")
    manager.checkpoint_index[old_id] = CheckpointMetadata(
        id=old_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager._save_checkpoint_index_or_raise()
    manager.refresh_admission_counters()

    entered = threading.Event()
    release = threading.Event()

    def hold_writer_lock(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        with manager._persistence_lock:
            entered.set()
            release.wait(timeout=5)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", hold_writer_lock)
    session = _session()
    assert await manager.create_checkpoint(session, session.messages[-1]) is not None
    assert await asyncio.to_thread(entered.wait, 2)
    assert manager.checkpoint_queue is not None
    await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=0.5)

    with pytest.raises(CheckpointPersistenceTimeoutError):
        await manager.cleanup_old_checkpoints(
            execute=True,
            confirmation=str(tmp_path.resolve()),
        )
    assert old_file.exists()

    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    await manager.stop_workers()


def test_confirmed_cleanup_precommit_failure_restores_checkpoint_pair(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalidated archive transaction cannot strand a file from its index."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            preparation_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
            retention={
                "keep_all_hours": 0,
                "keep_every_nth": 10,
                "max_age_days": 1,
                "max_bytes": 10_000,
                "active_session_keep": 1,
            },
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    checkpoint_id = "cleanup-timeout-after-move"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"checkpoint")
    manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager._save_checkpoint_index_or_raise()
    manager.refresh_admission_counters()

    def fail_index_commit() -> None:
        raise CheckpointPersistenceTimeoutError("forced precommit timeout")

    monkeypatch.setattr(manager, "_save_checkpoint_index_or_raise", fail_index_commit)
    with pytest.raises(CheckpointPersistenceTimeoutError):
        manager._archive_cleanup_candidates(manager.plan_checkpoint_cleanup())

    assert checkpoint_file.exists()
    assert checkpoint_id in manager.checkpoint_index
    assert checkpoint_id in json.loads(manager.index_path.read_text())
    recovered = CheckpointManager(
        tmp_path,
        _SessionManager(),
        manager.config,
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    assert checkpoint_file.exists()
    assert checkpoint_id in recovered.checkpoint_index


def test_startup_recovers_incomplete_confirmed_cleanup_archive(tmp_path: Path) -> None:
    """A crash between archive move and index commit restores the source pair."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    checkpoint_id = "cleanup-recovery"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"checkpoint")
    metadata = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager.checkpoint_index[checkpoint_id] = metadata
    manager._save_checkpoint_index_or_raise()
    archive_path = manager.checkpoints_path / "archive" / "incomplete"
    archive_path.mkdir(parents=True)
    archived_file = archive_path / checkpoint_file.name
    checkpoint_file.replace(archived_file)
    (archive_path / "manifest.json").write_text(
        json.dumps(
            {
                "state": "partial",
                "candidates": [
                    {
                        "checkpoint_id": checkpoint_id,
                        "source": str(checkpoint_file),
                        "archive_path": str(archived_file),
                        "metadata": {**metadata.__dict__, "type": metadata.type.value},
                    }
                ],
                "moved": [],
            }
        )
    )

    recovered = CheckpointManager(
        tmp_path,
        _SessionManager(),
        manager.config,
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )

    assert checkpoint_file.exists()
    assert not archived_file.exists()
    assert checkpoint_id in recovered.checkpoint_index
    manifest = json.loads((archive_path / "manifest.json").read_text())
    assert manifest["state"] == "rolled_back"


@pytest.mark.asyncio
async def test_timeout_after_index_commit_keeps_file_and_index_consistent(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Post-commit timeout keeps a durable checkpoint file/index pair intact."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            persistence_attempt_timeout_seconds=0.02,
            circuit_reset_seconds=60,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    committed = threading.Event()
    release = threading.Event()
    original_save = manager._save_checkpoint_index_or_raise

    def save_then_block() -> None:
        original_save()
        committed.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(manager, "_save_checkpoint_index_or_raise", save_then_block)
    session = _session()
    checkpoint_id = await manager.create_checkpoint(session, session.messages[-1])
    assert checkpoint_id is not None
    assert await asyncio.to_thread(committed.wait, 2)
    assert manager.checkpoint_queue is not None
    await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=0.5)

    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)

    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    disk_index = json.loads(manager.index_path.read_text())
    assert checkpoint_file.exists()
    assert checkpoint_id in manager.checkpoint_index
    assert checkpoint_id in disk_index
    await manager.stop_workers()


def test_foreign_live_loop_is_rejected_but_can_request_shutdown(tmp_path: Path) -> None:
    """Ownership crosses loops only through the explicit shutdown bridge."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    ready = threading.Event()
    owner_loop: list[asyncio.AbstractEventLoop] = []

    def run_owner() -> None:
        loop = asyncio.new_event_loop()
        owner_loop.append(loop)
        asyncio.set_event_loop(loop)

        async def start() -> None:
            await manager.start_workers()
            ready.set()

        start_task = loop.create_task(start())
        loop.run_forever()
        start_task.result()
        loop.close()

    thread = threading.Thread(target=run_owner, daemon=True)
    thread.start()
    assert ready.wait(timeout=5)
    try:
        with pytest.raises(CheckpointWorkerOwnershipError):
            asyncio.run(manager.start_workers())
        asyncio.run(manager.stop_workers())
        assert manager._workers_started is False
    finally:
        if owner_loop and owner_loop[0].is_running():
            owner_loop[0].call_soon_threadsafe(owner_loop[0].stop)
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_stopped_but_open_owner_loop_cannot_be_rebound(tmp_path: Path) -> None:
    """A paused owner loop retains ownership until it explicitly drains/closes."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    ready = threading.Event()
    release = threading.Event()

    def own_manager() -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        loop.run_until_complete(manager.start_workers())
        ready.set()
        assert release.wait(timeout=5)
        loop.run_until_complete(manager.stop_workers())
        loop.close()

    thread = threading.Thread(target=own_manager, daemon=True)
    thread.start()
    assert ready.wait(timeout=5)
    try:
        with pytest.raises(
            CheckpointWorkerOwnershipError, match="stopped but not closed"
        ):
            asyncio.run(manager.start_workers())
    finally:
        release.set()
        thread.join(timeout=5)
    assert not thread.is_alive()


def test_foreign_shutdown_has_deadline_when_owner_loop_is_blocked(
    tmp_path: Path,
) -> None:
    """A blocked foreign owner loop cannot hang shutdown's caller indefinitely."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            foreign_shutdown_timeout_seconds=0.05,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    started = threading.Event()
    blocked = threading.Event()
    release = threading.Event()
    owner_loop: list[asyncio.AbstractEventLoop] = []

    def run_owner() -> None:
        loop = asyncio.new_event_loop()
        owner_loop.append(loop)
        asyncio.set_event_loop(loop)

        async def start() -> None:
            await manager.start_workers()
            started.set()

        def block_loop() -> None:
            blocked.set()
            assert release.wait(timeout=5)

        loop.run_until_complete(start())
        loop.call_soon(block_loop)
        loop.run_forever()
        loop.close()

    thread = threading.Thread(target=run_owner, daemon=True)
    thread.start()
    assert started.wait(timeout=5)
    assert blocked.wait(timeout=5)
    try:
        started_at = time.monotonic()
        with pytest.raises(
            CheckpointWorkerOwnershipError,
            match="Timed out waiting",
        ):
            asyncio.run(manager.stop_workers())
        assert time.monotonic() - started_at < 0.5
    finally:
        release.set()

    asyncio.run(manager.stop_workers())
    owner_loop[0].call_soon_threadsafe(owner_loop[0].stop)
    thread.join(timeout=5)
    assert not thread.is_alive()


@pytest.mark.asyncio
async def test_worker_failure_retries_are_bounded_and_open_circuit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Repeated write failures cannot become a CPU, disk, or logging storm."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            worker_max_attempts=3,
            worker_retry_base_seconds=0.001,
            worker_retry_max_seconds=0.002,
            circuit_failure_threshold=2,
            circuit_reset_seconds=0.05,
            worker_error_log_interval_seconds=60,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    calls = 0

    def fail_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        nonlocal calls
        calls += 1
        raise OSError("deterministic persistence fault")

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", fail_persist)
    session = _session()
    with caplog.at_level(logging.ERROR, logger="penguin.system.checkpoint_manager"):
        assert (
            await manager.create_checkpoint(session, session.messages[-1]) is not None
        )
        assert manager.checkpoint_queue is not None
        await manager.checkpoint_queue.join()

    assert calls == 2
    status = manager.get_storage_safety_status()["worker"]
    assert status["circuit_open"] is True
    assert status["last_error_code"] == "OSError"
    error_logs = [
        record
        for record in caplog.records
        if "Checkpoint worker persistence failed" in record.message
    ]
    assert len(error_logs) == 1
    assert await manager.create_checkpoint(session, session.messages[-1]) is None

    await asyncio.sleep(0.06)
    monkeypatch.setattr(
        manager,
        "_persist_checkpoint_snapshot",
        lambda _snapshot, _metadata: None,
    )
    assert await manager.create_checkpoint(session, session.messages[-1]) is not None
    assert manager.checkpoint_queue is not None
    await manager.checkpoint_queue.join()
    assert manager.get_storage_safety_status()["worker"]["circuit_open"] is False
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_manual_checkpoint_reports_only_durable_persistence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A manual checkpoint cannot report queue admission as creation success."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            worker_max_attempts=2,
            worker_retry_base_seconds=0,
            circuit_failure_threshold=10,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )

    def fail_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        raise OSError("index persistence failed")

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", fail_persist)
    session = _session()

    with pytest.raises(CheckpointPersistenceError):
        await manager.create_checkpoint(
            session,
            session.messages[-1],
            CheckpointType.MANUAL,
        )

    assert not list(manager.checkpoints_path.glob("*.json.gz"))
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_branch_checkpoint_persists_the_installed_branch_exactly_once(
    tmp_path: Path,
) -> None:
    """Branch durability preserves the new session identity and branch metadata."""

    session_manager = _SessionManager()
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        CheckpointConfig(maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    source = _session(session_id="source-session")
    source.metadata.update({"directory": "/workspace/project", "title": "Source"})
    session_manager.current_session = source
    source_checkpoint_id = await manager.create_checkpoint(
        source,
        source.messages[-1],
        CheckpointType.MANUAL,
    )
    assert source_checkpoint_id is not None

    branch_checkpoint_id = await manager.branch_from_checkpoint(
        source_checkpoint_id,
        name="Review branch",
    )
    assert branch_checkpoint_id is not None
    installed = session_manager.current_session
    assert installed is not None
    payload = json.loads(
        gzip.decompress(
            (manager.checkpoints_path / f"{branch_checkpoint_id}.json.gz").read_bytes()
        )
    )
    persisted = payload["session"]

    assert persisted["id"] == installed.id
    assert payload["metadata"]["session_id"] == installed.id
    assert persisted["metadata"]["branched_from"] == source_checkpoint_id
    assert persisted["metadata"]["branch_point"] == source.messages[-1].id
    assert persisted["metadata"]["directory"] == "/workspace/project"
    assert persisted["metadata"]["title"] == "Review branch"
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_manual_flatten_uses_readonly_lineage_and_preserves_all_records(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lineage flattening cannot change the active session or lose ancestor state."""

    session_manager = _SessionManager()
    parent = _session(session_id="parent", content="parent message")
    parent.add_llm_request_lifecycle({"request_id": "parent-request"})
    parent.add_tool_call_record({"call_id": "parent-call", "name": "read_file"})
    parent.add_tool_result_record({"call_id": "parent-call", "status": "completed"})
    parent.add_message(
        Message(
            role="assistant",
            content="",
            category=MessageCategory.DIALOG,
            metadata={"tool_calls": [{"id": "parent-call"}]},
        )
    )
    parent.add_message(
        Message(
            role="tool",
            content="parent result",
            category=MessageCategory.SYSTEM_OUTPUT,
            metadata={"tool_call_id": "parent-call"},
        )
    )
    tail = _session(session_id="tail", content="tail message")
    tail.metadata["continued_from"] = parent.id
    tail.add_llm_request_lifecycle({"request_id": "tail-request"})
    tail.add_tool_call_record({"call_id": "tail-call", "name": "list_files"})
    tail.add_tool_result_record({"call_id": "tail-call", "status": "completed"})
    tail.add_message(
        Message(
            role="assistant",
            content="",
            category=MessageCategory.DIALOG,
            metadata={"tool_calls": [{"id": "tail-call"}]},
        )
    )
    tail.add_message(
        Message(
            role="tool",
            content="tail result",
            category=MessageCategory.SYSTEM_OUTPUT,
            metadata={"tool_call_id": "tail-call"},
        )
    )
    session_manager.current_session = tail
    session_manager.session_index = {
        parent.id: {},
        tail.id: {"continued_from": parent.id},
    }
    session_manager.readonly_sessions[parent.id] = parent

    def forbidden_stateful_load(_session_id: str) -> Session | None:
        raise AssertionError("manual flatten must not use stateful load_session")

    monkeypatch.setattr(session_manager, "load_session", forbidden_stateful_load)
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        CheckpointConfig(maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    loop_thread_id = threading.get_ident()

    checkpoint_id = await manager.create_checkpoint(
        tail,
        tail.messages[-1],
        CheckpointType.MANUAL,
    )

    assert checkpoint_id is not None
    assert session_manager.current_session is tail
    assert session_manager.readonly_load_thread_ids
    assert session_manager.readonly_load_thread_ids[0] != loop_thread_id
    payload = json.loads(
        gzip.decompress(
            (manager.checkpoints_path / f"{checkpoint_id}.json.gz").read_bytes()
        )
    )["session"]
    assert {message["content"] for message in payload["messages"]} == {
        "parent message",
        "parent result",
        "tail message",
        "tail result",
        "",
    }
    assert {record["request_id"] for record in payload["llm_request_lifecycles"]} == {
        "parent-request",
        "tail-request",
    }
    assert {record["call_id"] for record in payload["tool_call_records"]} == {
        "parent-call",
        "tail-call",
    }
    assert {record["call_id"] for record in payload["tool_result_records"]} == {
        "parent-call",
        "tail-call",
    }
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_snapshot_burst_is_bounded_before_queue_insertion(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Snapshot conversion cannot bypass the total checkpoint work capacity."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(queue_maxsize=1, maintenance_interval_seconds=0),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()
    state_lock = threading.Lock()
    active = 0
    maximum_active = 0
    original_snapshot = manager._snapshot_session_at_boundary

    def blocked_snapshot(
        session: Session,
        boundary,
    ) -> dict[str, Any]:
        nonlocal active, maximum_active
        with state_lock:
            active += 1
            maximum_active = max(maximum_active, active)
            if active == manager._work_capacity_limit:
                entered.set()
        try:
            assert release.wait(timeout=5)
            return original_snapshot(session, boundary)
        finally:
            with state_lock:
                active -= 1

    monkeypatch.setattr(manager, "_snapshot_session_at_boundary", blocked_snapshot)
    sessions = [_session(session_id=f"burst-{index}") for index in range(20)]
    tasks = [
        asyncio.create_task(manager.create_checkpoint(session, session.messages[-1]))
        for session in sessions
    ]
    assert await asyncio.to_thread(entered.wait, 2)
    await asyncio.sleep(0)
    assert manager._inflight_checkpoint_work == manager._work_capacity_limit
    assert maximum_active <= manager._work_capacity_limit

    release.set()
    results = await asyncio.gather(*tasks)
    accepted = [result for result in results if result is not None]
    assert len(accepted) <= manager._work_capacity_limit
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_late_filesystem_release_cannot_commit_after_bounded_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A detached persistence thread observes generation invalidation before commit."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            shutdown_drain_timeout_seconds=0.02,
            maintenance_interval_seconds=0,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()
    original_persist = manager._persist_checkpoint_snapshot

    def gated_persist(
        snapshot: dict[str, Any],
        metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        assert release.wait(timeout=5)
        original_persist(snapshot, metadata)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", gated_persist)
    session = _session()
    checkpoint_id = await manager.create_checkpoint(session, session.messages[-1])
    assert checkpoint_id is not None
    assert await asyncio.to_thread(entered.wait, 2)

    await manager.stop_workers()
    release.set()
    deadline = asyncio.get_running_loop().time() + 2
    while (
        manager._active_offload_count() and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)

    assert manager._active_offload_count() == 0
    assert checkpoint_id not in manager.checkpoint_index
    assert not (manager.checkpoints_path / f"{checkpoint_id}.json.gz").exists()


@pytest.mark.asyncio
async def test_concurrent_stop_callers_await_the_same_shutdown(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Repeated stop is idempotent without returning before the shared drain ends."""

    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=0,
            shutdown_drain_timeout_seconds=1,
        ),
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    entered = threading.Event()
    release = threading.Event()

    def blocked_persist(
        _snapshot: dict[str, Any],
        _metadata: CheckpointMetadata,
    ) -> None:
        entered.set()
        assert release.wait(timeout=5)

    monkeypatch.setattr(manager, "_persist_checkpoint_snapshot", blocked_persist)
    session = _session()
    assert await manager.create_checkpoint(session, session.messages[-1]) is not None
    assert await asyncio.to_thread(entered.wait, 2)

    first_stop = asyncio.create_task(manager.stop_workers())
    await asyncio.sleep(0)
    second_stop = asyncio.create_task(manager.stop_workers())
    await asyncio.sleep(0.02)
    assert not first_stop.done()
    assert not second_stop.done()

    release.set()
    await asyncio.gather(first_stop, second_stop)
    assert manager._workers_started is False
    assert manager._workers_stopping is False
    assert manager.checkpoint_queue is None


@pytest.mark.asyncio
async def test_automatic_retention_makes_room_and_protects_key_checkpoints(
    tmp_path: Path,
) -> None:
    """Count retention is automatic and preserves newest-active/manual/branch data."""

    session_manager = _SessionManager()
    active = _session(session_id="active", content="new request")
    session_manager.current_session = active
    config = CheckpointConfig(
        max_auto_checkpoints=3,
        retention={
            "keep_all_hours": 0,
            "keep_every_nth": 1,
            "max_age_days": 3650,
            "max_bytes": 10_000_000,
            "active_session_keep": 1,
        },
    )
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        config,
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    now = datetime.now(timezone.utc)
    fixtures = [
        ("active-new", CheckpointType.AUTO, "active", now - timedelta(days=1)),
        ("active-old", CheckpointType.AUTO, "active", now - timedelta(days=8)),
        ("inactive-new", CheckpointType.AUTO, "inactive", now - timedelta(days=2)),
        ("inactive-old", CheckpointType.AUTO, "inactive", now - timedelta(days=9)),
        ("manual", CheckpointType.MANUAL, "inactive", now - timedelta(days=20)),
        ("branch", CheckpointType.BRANCH, "inactive", now - timedelta(days=20)),
    ]
    for checkpoint_id, checkpoint_type, session_id, created_at in fixtures:
        path = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
        path.write_bytes((checkpoint_id * 10).encode())
        manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
            id=checkpoint_id,
            type=checkpoint_type,
            created_at=created_at.isoformat(),
            session_id=session_id,
            message_id=f"message-{checkpoint_id}",
            message_count=1,
            auto=checkpoint_type == CheckpointType.AUTO,
        )
    manager.refresh_admission_counters()
    manager._checkpoint_bytes = sum(
        path.stat().st_size for path in manager.checkpoints_path.glob("*.json.gz")
    )

    checkpoint_id = await manager.create_checkpoint(active, active.messages[-1])
    assert checkpoint_id is not None
    assert manager.checkpoint_queue is not None
    await manager.checkpoint_queue.join()
    await manager.stop_workers()

    remaining_auto = {
        item.id
        for item in manager.checkpoint_index.values()
        if item.type == CheckpointType.AUTO
    }
    assert checkpoint_id in remaining_auto
    assert "active-new" in remaining_auto
    assert len(remaining_auto) <= 3
    assert "manual" in manager.checkpoint_index
    assert "branch" in manager.checkpoint_index
    assert not (manager.checkpoints_path / "active-old.json.gz").exists()
    assert not (manager.checkpoints_path / "inactive-old.json.gz").exists()


@pytest.mark.asyncio
async def test_startup_maintenance_recovers_checkpoint_size_pressure_without_write(
    tmp_path: Path,
) -> None:
    """Retention runs independently even when storage admission rejects writes."""

    monitor = StorageSafetyMonitor(
        tmp_path,
        checkpoint_path=tmp_path / "checkpoints",
        policy=StorageSafetyPolicy(
            warning_free_bytes=10,
            critical_free_bytes=5,
            warning_free_fraction=0.01,
            critical_free_fraction=0.001,
            max_checkpoint_bytes=50,
        ),
        probe_interval_seconds=60,
        disk_usage_provider=lambda _path: DiskUsage(
            total=10_000,
            used=100,
            free=9_900,
        ),
    )
    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(
            maintenance_interval_seconds=60,
            retention={
                "keep_all_hours": 0,
                "keep_every_nth": 10,
                "max_age_days": 1,
                "max_bytes": 50,
                "active_session_keep": 1,
            },
        ),
        storage_safety_monitor=monitor,
    )
    checkpoint_id = "oversized-old-auto"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"x" * 100)
    manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager._save_checkpoint_index_or_raise()
    manager._reconcile_checkpoint_storage()
    assert (
        monitor.check(
            force=True,
            checkpoint_bytes=manager._checkpoint_bytes,
        ).allow_background_writes
        is False
    )

    await manager.start_workers()
    deadline = asyncio.get_running_loop().time() + 2
    while checkpoint_file.exists() and asyncio.get_running_loop().time() < deadline:
        await asyncio.sleep(0.01)
    await manager.run_automatic_maintenance()

    assert not checkpoint_file.exists()
    status = manager.get_storage_safety_status()
    assert status["allow_background_writes"] is True
    assert status["checkpoint_bytes"] == 0
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_protected_active_checkpoint_stays_safe_under_size_pressure(
    tmp_path: Path,
) -> None:
    """Maintenance rejects a new auto write rather than deleting active recovery."""

    session_manager = _SessionManager()
    active_session = _session(session_id="active")
    session_manager.current_session = active_session
    monitor = StorageSafetyMonitor(
        tmp_path,
        checkpoint_path=tmp_path / "checkpoints",
        policy=StorageSafetyPolicy(
            warning_free_bytes=10,
            critical_free_bytes=5,
            warning_free_fraction=0.01,
            critical_free_fraction=0.001,
            max_checkpoint_bytes=50,
        ),
        probe_interval_seconds=60,
        disk_usage_provider=lambda _path: DiskUsage(
            total=10_000,
            used=100,
            free=9_900,
        ),
    )
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        CheckpointConfig(
            maintenance_interval_seconds=0,
            retention={
                "keep_all_hours": 0,
                "keep_every_nth": 10,
                "max_age_days": 1,
                "max_bytes": 50,
                "active_session_keep": 1,
            },
        ),
        storage_safety_monitor=monitor,
    )
    checkpoint_id = "active-recovery"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"x" * 100)
    manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="active",
        message_id="message",
        message_count=1,
    )
    manager._save_checkpoint_index_or_raise()
    manager._reconcile_checkpoint_storage()

    assert await manager.run_automatic_maintenance() == 0
    result = await manager.create_checkpoint(
        active_session,
        active_session.messages[-1],
    )

    assert result is None
    assert checkpoint_file.exists()
    assert manager.get_storage_safety_status()["block_reason"] == "storage_critical"
    await manager.stop_workers()


def test_retention_index_failure_restores_files_and_recovers_transaction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failed reduced-index commit cannot strand or delete checkpoint data."""

    config = CheckpointConfig(
        maintenance_interval_seconds=0,
        retention={
            "keep_all_hours": 0,
            "keep_every_nth": 10,
            "max_age_days": 1,
            "max_bytes": 10_000,
            "active_session_keep": 1,
        },
    )
    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        config,
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    checkpoint_id = "retention-fault"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"checkpoint")
    manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00+00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager._save_checkpoint_index_or_raise()
    manager._reconcile_checkpoint_storage()

    def fail_index() -> None:
        raise OSError("atomic index replace failed")

    monkeypatch.setattr(manager, "_save_checkpoint_index_or_raise", fail_index)
    with pytest.raises(OSError, match="atomic index replace failed"):
        manager._enforce_automatic_retention_sync()

    assert checkpoint_file.exists()
    assert checkpoint_id in manager.checkpoint_index

    recovered = CheckpointManager(
        tmp_path,
        _SessionManager(),
        config,
        storage_safety_monitor=_healthy_monitor(tmp_path),
    )
    assert checkpoint_file.exists()
    assert checkpoint_id in recovered.checkpoint_index
    assert not (recovered.checkpoints_path / ".automatic-retention").exists()


@pytest.mark.asyncio
async def test_stopped_managers_release_checkpoint_executor_threads(
    tmp_path: Path,
) -> None:
    """Repeated manager lifecycles do not leak daemon I/O workers."""

    def checkpoint_threads() -> int:
        return sum(
            thread.name.startswith("penguin-checkpoint-io-")
            for thread in threading.enumerate()
        )

    baseline = checkpoint_threads()
    for index in range(10):
        workspace = tmp_path / f"workspace-{index}"
        workspace.mkdir()
        manager = CheckpointManager(
            workspace,
            _SessionManager(),
            CheckpointConfig(maintenance_interval_seconds=0),
            storage_safety_monitor=_healthy_monitor(workspace),
        )
        await manager.run_automatic_maintenance()
        await manager.stop_workers()

    deadline = asyncio.get_running_loop().time() + 2
    while (
        checkpoint_threads() > baseline and asyncio.get_running_loop().time() < deadline
    ):
        await asyncio.sleep(0.01)
    assert checkpoint_threads() <= baseline


def test_bounded_executor_shutdown_drains_a_full_pending_queue() -> None:
    """Default executor shutdown cannot lose its worker-exit signal under load."""

    executor = BoundedDaemonExecutor(
        max_workers=1,
        max_pending=1,
        thread_name_prefix="checkpoint-executor-test",
    )
    started = threading.Event()
    release = threading.Event()
    shutdown_done = threading.Event()

    def blocked_work() -> str:
        started.set()
        assert release.wait(timeout=5)
        return "first"

    first = executor.submit(blocked_work)
    assert started.wait(timeout=2)
    second = executor.submit(lambda: "second")

    shutdown_thread = threading.Thread(
        target=lambda: (executor.shutdown(), shutdown_done.set()),
        daemon=True,
    )
    shutdown_thread.start()
    release.set()

    assert shutdown_done.wait(timeout=2)
    assert first.result(timeout=0.1) == "first"
    assert second.result(timeout=0.1) == "second"
