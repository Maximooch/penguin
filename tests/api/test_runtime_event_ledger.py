"""Tests for durable RuntimeEvent ledger storage."""

from __future__ import annotations

import sqlite3
import time
from pathlib import Path

from penguin.system.runtime_event_ledger import (
    RuntimeEventLedger,
    RuntimeEventLedgerPolicy,
)
from penguin.system.runtime_events import (
    build_runtime_event,
    reset_runtime_event_sequences,
)


def _ledger(tmp_path: Path, **policy_kwargs) -> RuntimeEventLedger:
    policy = RuntimeEventLedgerPolicy(
        max_events=policy_kwargs.pop("max_events", 100),
        max_age_seconds=policy_kwargs.pop("max_age_seconds", None),
        max_bytes=policy_kwargs.pop("max_bytes", None),
        cleanup_interval_seconds=policy_kwargs.pop("cleanup_interval_seconds", 0),
        **policy_kwargs,
    )
    return RuntimeEventLedger(tmp_path / "runtime_events.db", policy=policy)


def _event(
    session_id: str,
    index: int,
    *,
    event_type: str = "message.updated",
    payload_extra: dict | None = None,
    time_ms: int | None = None,
) -> dict:
    payload = {
        "id": f"msg_{index}",
        "sessionID": session_id,
        "role": "assistant",
    }
    if payload_extra:
        payload.update(payload_extra)
    return build_runtime_event(
        event_type=event_type,
        payload=payload,
        sequence=index,
        time_ms=time_ms or 1_000 + index,
    )


def test_ledger_appends_and_replays_after_last_event_id(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    first = _event("ses_1", 1)
    second = _event("ses_1", 2)

    assert ledger.append(first) is True
    assert ledger.append(second) is True

    replay = ledger.replay_after(first["id"])

    assert replay.found is True
    assert [event["id"] for event in replay.events] == [second["id"]]
    assert replay.oldest_event_id == first["id"]
    assert replay.newest_event_id == second["id"]


def test_ledger_suppresses_duplicate_runtime_event_ids(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    event = _event("ses_1", 1)

    assert ledger.append(event) is True
    assert ledger.append(event) is False

    assert [item["id"] for item in ledger.newest(limit=10)] == [event["id"]]


def test_ledger_keeps_repeated_part_deltas_as_distinct_events(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    first = _event(
        "ses_1",
        1,
        event_type="message.part.updated",
        payload_extra={
            "part": {
                "id": "part_1",
                "messageID": "msg_1",
                "sessionID": "ses_1",
                "type": "text",
            },
            "delta": "Hel",
        },
    )
    second = _event(
        "ses_1",
        2,
        event_type="message.part.updated",
        payload_extra={
            "part": {
                "id": "part_1",
                "messageID": "msg_1",
                "sessionID": "ses_1",
                "type": "text",
            },
            "delta": "lo",
        },
    )

    assert ledger.extend([first, second]) == 2

    newest = ledger.newest(limit=10)
    assert [event["payload"]["delta"] for event in newest] == ["Hel", "lo"]
    assert newest[0]["id"] != newest[1]["id"]


def test_ledger_max_events_cleanup_removes_oldest_rows(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_events=2)
    events = [_event("ses_1", index) for index in range(1, 4)]

    assert ledger.extend(events) == 3

    retained = ledger.newest(limit=10)
    assert [event["id"] for event in retained] == [events[1]["id"], events[2]["id"]]
    replay = ledger.replay_after(events[0]["id"])
    assert replay.found is False
    assert replay.oldest_event_id == events[1]["id"]
    assert replay.newest_event_id == events[2]["id"]


def test_ledger_max_age_cleanup_removes_old_events(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_age_seconds=60)
    old_event = _event("ses_1", 1, time_ms=int((time.time() - 120) * 1000))
    fresh_event = _event("ses_1", 2, time_ms=int(time.time() * 1000))

    assert ledger.extend([old_event, fresh_event]) == 2

    retained = ledger.newest(limit=10)
    assert [event["id"] for event in retained] == [fresh_event["id"]]


def test_ledger_persists_only_redacted_public_payload(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    event = build_runtime_event(
        event_type="provider.auth.updated",
        payload={
            "sessionID": "ses_1",
            "api_key": "sk-secret",
            "tokens": 42,
        },
    )

    assert ledger.append(event) is True

    stored = ledger.newest(limit=1)[0]
    assert stored["payload"]["api_key"] == "[redacted]"
    assert stored["payload"]["tokens"] == 42
    assert stored["privacy"]["redacted"] is True

    conn = sqlite3.connect(str(tmp_path / "runtime_events.db"))
    try:
        raw = conn.execute("SELECT event_json FROM runtime_events").fetchone()[0]
    finally:
        conn.close()
    assert "sk-secret" not in raw
    assert "[redacted]" in raw
