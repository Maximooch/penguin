"""Tests for durable RuntimeEvent ledger storage."""

from __future__ import annotations

import copy
import math
import sqlite3
import time
from typing import TYPE_CHECKING, Any, Mapping

import pytest

if TYPE_CHECKING:
    from pathlib import Path

from penguin.system.runtime_event_ledger import (
    RuntimeEventLedger,
    RuntimeEventLedgerPolicy,
)
from penguin.system.runtime_events import (
    build_runtime_event,
    reset_runtime_event_sequences,
)


def _ledger(
    tmp_path: Path,
    *,
    max_events: int = 100,
    max_age_seconds: int | None = None,
    max_bytes: int | None = None,
    cleanup_interval_seconds: float = 0,
) -> RuntimeEventLedger:
    policy = RuntimeEventLedgerPolicy(
        max_events=max_events,
        max_age_seconds=max_age_seconds,
        max_bytes=max_bytes,
        cleanup_interval_seconds=cleanup_interval_seconds,
    )
    return RuntimeEventLedger(tmp_path / "runtime_events.db", policy=policy)


def _event(
    session_id: str,
    index: int,
    *,
    event_type: str = "message.updated",
    payload_extra: Mapping[str, Any] | None = None,
    time_ms: int | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
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


def test_ledger_preserves_same_id_with_different_payload(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    original = _event("ses_1", 1)
    changed = copy.deepcopy(original)
    changed["payload"]["role"] = "user"

    assert ledger.append(original) is True
    assert ledger.append(changed) is True
    assert ledger.append(changed) is False

    newest = ledger.newest(limit=10)
    assert len(newest) == 2
    assert newest[0]["id"] == original["id"]
    assert newest[1]["id"].startswith(f"{original['id']}:conflict:")
    assert newest[1]["payload"]["role"] == "user"


def test_ledger_id_survives_reopening_database(tmp_path: Path) -> None:
    first = _ledger(tmp_path)
    ledger_id = first.ledger_id
    assert ledger_id
    assert first.shutdown() is True

    reopened = _ledger(tmp_path)
    assert reopened.ledger_id == ledger_id
    assert reopened.shutdown() is True


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


def test_ledger_replay_filters_session_agent_and_directory(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    directory_one = str(tmp_path / "one")
    directory_two = str(tmp_path / "two")
    first = build_runtime_event(
        event_type="message.updated",
        payload={"id": "msg_1", "role": "assistant"},
        scope={
            "session_id": "ses_1",
            "agent_id": "agent_a",
            "directory": directory_one,
        },
        sequence=1,
    )
    wrong_agent = build_runtime_event(
        event_type="message.updated",
        payload={"id": "msg_2", "role": "assistant"},
        scope={
            "session_id": "ses_1",
            "agent_id": "agent_b",
            "directory": directory_one,
        },
        sequence=2,
    )
    wrong_directory = build_runtime_event(
        event_type="message.updated",
        payload={"id": "msg_3", "role": "assistant"},
        scope={
            "session_id": "ses_1",
            "agent_id": "agent_a",
            "directory": directory_two,
        },
        sequence=3,
    )
    retained = build_runtime_event(
        event_type="message.updated",
        payload={"id": "msg_4", "role": "assistant"},
        scope={
            "session_id": "ses_1",
            "agent_id": "agent_a",
            "directory": directory_one,
        },
        sequence=4,
    )

    assert ledger.extend([first, wrong_agent, wrong_directory, retained]) == 4

    replay = ledger.replay_after(
        first["id"],
        session_id="ses_1",
        agent_id="agent_a",
        directory=directory_one,
    )

    assert replay.found is True
    assert [event["id"] for event in replay.events] == [retained["id"]]


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



def test_policy_from_env_disables_auto_cleanup_for_off_values(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from penguin.system.runtime_event_ledger import policy_from_env

    monkeypatch.setenv("PENGUIN_RUNTIME_EVENT_LEDGER_CLEANUP_INTERVAL_SECONDS", "0")
    assert math.isinf(policy_from_env().cleanup_interval_seconds)

    monkeypatch.setenv("PENGUIN_RUNTIME_EVENT_LEDGER_CLEANUP_INTERVAL_SECONDS", "off")
    assert math.isinf(policy_from_env().cleanup_interval_seconds)


def test_ledger_max_age_cleanup_removes_old_events(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_age_seconds=60)
    old_event = _event("ses_1", 1, time_ms=int((time.time() - 120) * 1000))
    fresh_event = _event("ses_1", 2, time_ms=int(time.time() * 1000))

    assert ledger.extend([old_event, fresh_event]) == 2

    retained = ledger.newest(limit=10)
    assert [event["id"] for event in retained] == [fresh_event["id"]]


def test_ledger_max_bytes_cleanup_removes_oldest_rows(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_bytes=2_500)

    def fake_size(
        self: RuntimeEventLedger,
        conn: sqlite3.Connection,
    ) -> int:
        count = conn.execute("SELECT COUNT(*) AS count FROM runtime_events").fetchone()[
            "count"
        ]
        return int(count) * 1_000

    monkeypatch.setattr(RuntimeEventLedger, "_database_size_bytes", fake_size)
    events = [_event("ses_1", index) for index in range(1, 5)]

    assert ledger.extend(events) == 4

    retained = ledger.newest(limit=10)
    assert [event["id"] for event in retained] == [events[2]["id"], events[3]["id"]]
    replay = ledger.replay_after(events[2]["id"])
    assert replay.found is True
    assert [event["id"] for event in replay.events] == [events[3]["id"]]



def test_append_rolls_back_thread_connection_after_cleanup_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    first = _event("ses_1", 1)
    second = _event("ses_1", 2)

    def fail_cleanup(*, conn: sqlite3.Connection | None = None) -> None:
        raise RuntimeError("cleanup failed")

    monkeypatch.setattr(ledger, "cleanup_if_due", fail_cleanup)
    with pytest.raises(RuntimeError, match="cleanup failed"):
        ledger.append(first)

    monkeypatch.setattr(ledger, "cleanup_if_due", lambda *, conn=None: None)
    assert ledger.append(second) is True
    assert [event["id"] for event in ledger.newest(limit=10)] == [second["id"]]


def test_ledger_checkpoint_below_size_cap_does_not_prune_rows(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_bytes=2_500)
    checkpointed = False

    def fake_size(
        self: RuntimeEventLedger,
        conn: sqlite3.Connection,
    ) -> int:
        return 1_000 if checkpointed else 4_000

    def fake_checkpoint(
        self: RuntimeEventLedger,
        conn: sqlite3.Connection,
    ) -> bool:
        nonlocal checkpointed
        checkpointed = True
        return True

    monkeypatch.setattr(RuntimeEventLedger, "_database_size_bytes", fake_size)
    monkeypatch.setattr(RuntimeEventLedger, "_checkpoint_wal", fake_checkpoint)
    events = [_event("ses_1", index) for index in range(1, 4)]

    assert ledger.extend(events) == 3
    assert checkpointed is True
    assert [event["id"] for event in ledger.newest(limit=10)] == [
        event["id"] for event in events
    ]


def test_ledger_failed_checkpoint_skips_size_pruning(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path, max_bytes=2_500)

    monkeypatch.setattr(
        RuntimeEventLedger,
        "_database_size_bytes",
        lambda self, conn: 4_000,
    )
    monkeypatch.setattr(RuntimeEventLedger, "_checkpoint_wal", lambda self, conn: False)
    events = [_event("ses_1", index) for index in range(1, 4)]

    assert ledger.extend(events) == 3
    assert [event["id"] for event in ledger.newest(limit=10)] == [
        event["id"] for event in events
    ]

def test_ledger_connect_enables_incremental_auto_vacuum(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)

    assert ledger.append(_event("ses_1", 1)) is True

    conn = sqlite3.connect(str(tmp_path / "runtime_events.db"))
    try:
        assert conn.execute("PRAGMA auto_vacuum").fetchone()[0] == 2
    finally:
        conn.close()


def test_ledger_database_size_includes_wal_sidecar(
    tmp_path: Path,
    monkeypatch,
) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    assert ledger.append(_event("ses_1", 1)) is True

    def fake_path_size(path: Path) -> int:
        return 1_234 if path.name.endswith("-wal") else 0

    monkeypatch.setattr(
        "penguin.system.runtime_event_ledger._path_size",
        fake_path_size,
    )
    conn = ledger._connect()
    try:
        page_count = conn.execute("PRAGMA page_count").fetchone()[0]
        page_size = conn.execute("PRAGMA page_size").fetchone()[0]
        logical_size = int(page_count) * int(page_size)
        assert ledger._database_size_bytes(conn) >= logical_size + 1_234
    finally:
        conn.close()


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
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT payload_json, projection_json, event_json FROM runtime_events"
        ).fetchone()
    finally:
        conn.close()

    assert row is not None
    for column in ("payload_json", "projection_json", "event_json"):
        assert "sk-secret" not in row[column]
    assert "[redacted]" in row["payload_json"]
    assert "[redacted]" in row["event_json"]


def test_ledger_rejects_unredacted_runtime_event_fields(tmp_path: Path) -> None:
    reset_runtime_event_sequences()
    ledger = _ledger(tmp_path)
    event = build_runtime_event(
        event_type="provider.auth.updated",
        payload={"sessionID": "ses_1", "api_key": "sk-secret"},
    )
    unsafe_payload = copy.deepcopy(event)
    unsafe_payload["payload"]["api_key"] = "sk-secret"
    unsafe_payload["privacy"] = {
        "classification": "public",
        "redacted": False,
        "redacted_fields": [],
    }
    unsafe_projection = copy.deepcopy(event)
    unsafe_projection["projections"] = {"opencode": {"api_key": "sk-secret"}}

    assert ledger.append(unsafe_payload) is False
    assert ledger.append(unsafe_projection) is False
    assert ledger.newest(limit=10) == []
