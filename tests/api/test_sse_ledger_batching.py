"""Tests for batched runtime-event ledger persistence behind the SSE stream.

The streaming hot path must never wait on a SQLite commit: event identity is
assigned synchronously, the envelope is appended to a per-core batch, and the
batch is drained to the ledger in a single transaction by the SSE generator.
"""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from penguin.system.runtime_event_ledger import (
    RuntimeEventLedger,
    RuntimeEventLedgerPolicy,
)
from penguin.system.runtime_events import reset_runtime_event_sequences
from penguin.web.sse_events import (
    _LEDGER_BATCH_ATTR,
    _flush_ledger_batch,
    events_sse,
    set_core_instance,
)
from penguin.web.services.opencode_events import record_opencode_event


def _install_test_ledger(core, tmp_path: Path, *, max_events: int = 100) -> None:
    core._runtime_event_ledger_v1 = RuntimeEventLedger(
        tmp_path / f"runtime-events-{id(core)}.db",
        policy=RuntimeEventLedgerPolicy(
            max_events=max_events,
            max_age_seconds=None,
            max_bytes=None,
            cleanup_interval_seconds=0,
        ),
    )


class _EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_name, handler):
        self._handlers.setdefault(event_name, []).append(handler)

    def unsubscribe(self, event_name, handler):
        handlers = self._handlers.get(event_name, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event_name, payload):
        for handler in list(self._handlers.get(event_name, [])):
            result = handler(event_name, payload)
            if asyncio.iscoroutine(result):
                await result


def _make_core(tmp_path: Path, session_id: str = "session_one"):
    reset_runtime_event_sequences()
    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=event_bus,
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    _install_test_ledger(core, tmp_path)
    set_core_instance(core)
    return core, event_bus


def _opencode_message(properties: dict) -> dict:
    return {"type": "message.updated", "properties": properties}


def _ledger_count(core) -> int:
    ledger: RuntimeEventLedger = core._runtime_event_ledger_v1
    with ledger._lock:
        conn = ledger._connect()
        try:
            ledger._ensure_schema(conn)
            return conn.execute("SELECT COUNT(*) FROM runtime_events").fetchone()[0]
        finally:
            conn.close()


def _parse_sse(chunk: str) -> dict:
    for line in chunk.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"Missing data line in SSE chunk: {chunk}")


@pytest.mark.asyncio
async def test_record_opencode_event_persist_false_skips_ledger_write(
    tmp_path: Path,
):
    core, _ = _make_core(tmp_path)
    data = _opencode_message(
        {"id": "msg_1", "sessionID": "session_one", "role": "assistant"}
    )

    runtime_event = record_opencode_event(core, data, persist=False)

    # Identity is assigned synchronously even though the write is deferred.
    assert runtime_event is not None
    assert isinstance(data.get("id"), str)
    assert _ledger_count(core) == 0

    # The default path still persists inline.
    record_opencode_event(
        core,
        _opencode_message({"id": "msg_2", "sessionID": "session_one", "role": "assistant"}),
    )
    assert _ledger_count(core) == 1


@pytest.mark.asyncio
async def test_recorder_batches_events_until_flushed(tmp_path: Path):
    core, event_bus = _make_core(tmp_path)

    await event_bus.emit(
        "opencode_event",
        _opencode_message({"id": "msg_1", "sessionID": "session_one", "role": "assistant"}),
    )
    await event_bus.emit(
        "opencode_event",
        _opencode_message({"id": "msg_2", "sessionID": "session_one", "role": "assistant"}),
    )

    # Emission does not write per event; envelopes sit in the pending batch.
    assert _ledger_count(core) == 0
    assert len(getattr(core, _LEDGER_BATCH_ATTR)) == 2

    # One explicit drain persists the whole batch in a single transaction.
    await _flush_ledger_batch(core)
    assert _ledger_count(core) == 2
    assert getattr(core, _LEDGER_BATCH_ATTR) == []


@pytest.mark.asyncio
async def test_replay_flushes_pending_batch_before_reading(tmp_path: Path):
    core, event_bus = _make_core(tmp_path)

    first = _opencode_message(
        {"id": "msg_1", "sessionID": "session_one", "role": "assistant"}
    )
    second = _opencode_message(
        {"id": "msg_2", "sessionID": "session_one", "role": "assistant"}
    )
    await event_bus.emit("opencode_event", first)
    await event_bus.emit("opencode_event", second)

    # Nothing flushed yet — the reconnect must drain before replay reads.
    assert _ledger_count(core) == 0

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=first["id"],
    )
    stream = response.body_iterator

    _ = _parse_sse(await stream.__anext__())
    replayed = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    assert replayed["id"] == second["id"]
    assert replayed["properties"]["id"] == "msg_2"

    await stream.aclose()
