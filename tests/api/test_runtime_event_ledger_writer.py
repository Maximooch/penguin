"""Tests for the bounded asynchronous runtime-event writer."""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

from penguin.system.runtime_event_ledger import (
    RuntimeEventLedger,
    RuntimeEventLedgerPolicy,
)
from penguin.system.runtime_events import build_runtime_event


def _event(index: int) -> dict[str, Any]:
    return build_runtime_event(
        event_type="message.part.updated",
        payload={
            "sessionID": "ses_writer",
            "part": {"id": f"part_{index}", "type": "text"},
            "delta": str(index),
        },
        stream_id="session:ses_writer",
        sequence=index,
        time_ms=1_000 + index,
    )


def _ledger(path: Path, *, queue_max: int = 8) -> RuntimeEventLedger:
    return RuntimeEventLedger(
        path / "runtime_events.db",
        policy=RuntimeEventLedgerPolicy(
            max_events=100,
            max_age_seconds=None,
            max_bytes=None,
            cleanup_interval_seconds=float("inf"),
            writer_queue_max_events=queue_max,
            writer_batch_max_events=8,
            writer_batch_max_delay_seconds=0.01,
            writer_shutdown_timeout_seconds=1.0,
        ),
    )


def test_enqueue_batches_and_flushes_without_per_event_commit(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    events = [_event(index) for index in range(1, 4)]

    assert all(ledger.enqueue(event) for event in events)
    assert ledger.flush(timeout_seconds=1.0) is True
    assert [event["id"] for event in ledger.newest(limit=10)] == [
        event["id"] for event in events
    ]
    assert ledger.shutdown() is True


def test_writer_handles_small_chunk_burst_with_bounded_queue(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, queue_max=2_048)
    events = [_event(index) for index in range(1, 1_001)]

    accepted = sum(ledger.enqueue(event) for event in events)

    assert accepted == len(events)
    assert ledger.flush(timeout_seconds=5.0) is True
    assert len(ledger.newest(limit=1_000)) == len(events)
    assert ledger.shutdown(timeout_seconds=5.0) is True


def test_enqueue_is_nonblocking_when_queue_is_full(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path, queue_max=1)
    # Prevent the worker from consuming the first admission so the second one
    # deterministically exercises overflow without sleeping on SQLite.
    ledger._ensure_writer_started_locked = lambda: None  # type: ignore[method-assign]

    assert ledger.enqueue(_event(1)) is True
    started = time.perf_counter()
    assert ledger.enqueue(_event(2)) is False
    assert (time.perf_counter() - started) < 0.05
    assert ledger.pending_count == 1


def test_shutdown_drain_deadline_does_not_wait_forever(tmp_path: Path) -> None:
    ledger = _ledger(tmp_path)
    entered = threading.Event()
    release = threading.Event()

    def blocked_batch(_events: Any) -> int:
        entered.set()
        release.wait()
        return 0

    ledger._append_batch = blocked_batch  # type: ignore[method-assign]
    assert ledger.enqueue(_event(1)) is True
    assert entered.wait(1.0)
    started = time.perf_counter()
    assert ledger.shutdown(timeout_seconds=0.02) is False
    assert (time.perf_counter() - started) < 0.2
    release.set()
    assert ledger.shutdown(timeout_seconds=1.0) is True
