"""Runtime event ledger flushes are ordered, bounded and back off on failure.

Covers SM-81: flushes ran without a lock, so a later small batch could commit
before an earlier large one and replay (ordered by rowid) skipped or repeated
events; a failing ledger requeued every event with no bound, and past the
batch size every new event retried the whole backlog inside ``emit``.
"""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import pytest

from penguin.web import sse_events
from penguin.web.sse_events import _LEDGER_BATCH_ATTR, _flush_ledger_batch
from tests.api.test_sse_ledger_batching import _make_core, _opencode_message

if TYPE_CHECKING:
    from pathlib import Path


async def _emit(event_bus: Any, index: int) -> None:
    await event_bus.emit(
        "opencode_event",
        _opencode_message(
            {"id": f"msg_{index}", "sessionID": "session_one", "role": "assistant"}
        ),
    )


@pytest.mark.asyncio
async def test_overlapping_flushes_commit_in_emission_order(tmp_path: Path) -> None:
    core, event_bus = _make_core(tmp_path)
    ledger = core._runtime_event_ledger_v1
    real_extend = ledger.extend
    calls: list[int] = []

    def slow_first_extend(events: list[dict[str, Any]]) -> int:
        calls.append(len(events))
        if len(calls) == 1:
            time.sleep(0.2)
        return real_extend(events)

    ledger.extend = slow_first_extend
    for index in range(3):
        await _emit(event_bus, index)
    first_flush = asyncio.create_task(_flush_ledger_batch(core))
    await asyncio.sleep(0.05)
    for index in range(3, 5):
        await _emit(event_bus, index)
    emitted = [event["id"] for event in getattr(core, _LEDGER_BATCH_ATTR)]

    await _flush_ledger_batch(core)
    await first_flush

    replay = ledger.replay_after("evt:session:session_one:00000001")
    assert [event["id"] for event in replay.events] == [
        "evt:session:session_one:00000002",
        "evt:session:session_one:00000003",
        *emitted,
    ]


@pytest.mark.asyncio
async def test_a_failing_ledger_is_not_retried_on_every_event(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sse_events, "_LEDGER_BATCH_MAX_EVENTS", 4)
    monkeypatch.setattr(sse_events, "_LEDGER_PENDING_MAX_EVENTS", 10)
    core, event_bus = _make_core(tmp_path)
    attempts: list[int] = []

    def read_only(events: list[dict[str, Any]]) -> int:
        attempts.append(len(events))
        raise OSError(30, "Read-only file system")

    core._runtime_event_ledger_v1.extend = read_only
    for index in range(30):
        await _emit(event_bus, index)

    assert len(attempts) == 1
    assert len(getattr(core, _LEDGER_BATCH_ATTR)) <= 10


@pytest.mark.asyncio
async def test_the_stream_handler_runs_on_the_event_loop(tmp_path: Path) -> None:
    core, event_bus = _make_core(tmp_path)
    recorder = core._runtime_event_ledger_recorder_v1
    response = await sse_events.events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=None,
        last_event_id_header=None,
    )
    stream = response.body_iterator
    await stream.__anext__()

    try:
        handlers = [
            handler
            for handler in event_bus._handlers["opencode_event"]
            if handler is not recorder
        ]
        # The CLI EventBus runs a sync handler in a worker thread.
        assert handlers
        assert all(asyncio.iscoroutinefunction(handler) for handler in handlers)
    finally:
        await stream.aclose()
