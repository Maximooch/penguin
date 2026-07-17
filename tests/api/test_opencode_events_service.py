"""Tests for OpenCode event normalization helpers."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

import pytest

from penguin.web.services.opencode_events import (
    directory_matches,
    emit_opencode_event,
    extract_event_directory,
    extract_event_session,
    normalize_opencode_event,
    record_opencode_event,
    schedule_opencode_event,
    sse_event_frame,
)
from penguin.system.runtime_events import reset_runtime_event_sequences


def test_normalize_opencode_event_adds_id_time_order_and_correlation(tmp_path):
    reset_runtime_event_sequences()
    event = normalize_opencode_event(
        {
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_1",
                    "messageID": "msg_1",
                    "sessionID": "ses_1",
                    "type": "text",
                }
            },
        },
        order=12,
        default_directory=str(tmp_path),
        now_ms=123456,
    )

    assert event is not None
    assert event["id"] == "evt:session:ses_1:00000012"
    assert event["order"] == 12
    assert event["time"] == 123456
    assert event["properties"]["sessionID"] == "ses_1"
    assert event["properties"]["directory"] == str(tmp_path)
    assert event["properties"]["part"]["id"] == "part_1"


def test_repeated_part_updates_get_unique_sse_ids(tmp_path):
    reset_runtime_event_sequences()

    first = normalize_opencode_event(
        {
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_1",
                    "messageID": "msg_1",
                    "sessionID": "ses_1",
                    "type": "text",
                },
                "delta": "Hel",
            },
        },
        order=1,
        default_directory=str(tmp_path),
        now_ms=100,
    )
    second = normalize_opencode_event(
        {
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_1",
                    "messageID": "msg_1",
                    "sessionID": "ses_1",
                    "type": "text",
                },
                "delta": "lo",
            },
        },
        order=2,
        default_directory=str(tmp_path),
        now_ms=101,
    )

    assert first is not None
    assert second is not None
    assert first["id"] == "evt:session:ses_1:00000001"
    assert second["id"] == "evt:session:ses_1:00000002"
    assert first["id"] != second["id"]
    assert first["properties"]["part"]["id"] == "part_1"
    assert second["properties"]["part"]["id"] == "part_1"


def test_existing_runtime_event_receives_sse_defaults_and_order(tmp_path):
    reset_runtime_event_sequences()

    event = normalize_opencode_event(
        {
            "type": "session.status",
            "properties": {},
            "runtime_event": {
                "id": "evt:global:prebuilt",
                "type": "session.status",
                "payload": {"status": {"type": "idle"}},
            },
        },
        order=7,
        default_agent_id="agent_1",
        default_directory=str(tmp_path),
        default_session_id="ses_1",
        now_ms=123,
    )

    assert event is not None
    assert event["id"] == "evt:global:prebuilt"
    assert event["order"] == 7
    assert event["time"] == 123
    assert event["properties"]["sessionID"] == "ses_1"
    assert event["properties"]["agentID"] == "agent_1"
    assert event["properties"]["directory"] == str(tmp_path.resolve())


def test_normalize_opencode_event_canonicalizes_existing_directory(
    tmp_path,
    monkeypatch,
):
    reset_runtime_event_sequences()
    monkeypatch.chdir(tmp_path)

    event = normalize_opencode_event(
        {
            "type": "session.status",
            "properties": {
                "directory": ".",
                "sessionID": "ses_1",
            },
        },
        order=1,
        now_ms=100,
    )

    assert event is not None
    assert event["properties"]["directory"] == str(tmp_path.resolve())


def test_normalize_opencode_event_rejects_malformed_payloads():
    assert normalize_opencode_event({}, order=1) is None
    assert normalize_opencode_event({"type": ""}, order=1) is None


def test_normalize_opencode_event_redacts_secret_fields():
    reset_runtime_event_sequences()
    event = normalize_opencode_event(
        {
            "type": "provider.auth.updated",
            "properties": {
                "sessionID": "ses_1",
                "OPENAI_API_KEY": "sk-live",
            },
        },
        order=1,
    )

    assert event is not None
    assert event["properties"]["OPENAI_API_KEY"] == "[redacted]"


def test_event_extraction_helpers_read_nested_payloads(tmp_path):
    payload = {
        "info": {
            "session_id": "ses_info",
            "path": {
                "cwd": str(tmp_path),
            },
        }
    }

    assert extract_event_session(payload) == "ses_info"
    assert extract_event_directory(payload) == str(tmp_path)
    assert directory_matches(str(tmp_path), str(tmp_path.resolve()))


def test_sse_event_frame_includes_sse_id_and_json_data():
    event = {
        "id": "session.status:ses_1:1",
        "order": 1,
        "time": 100,
        "type": "session.status",
        "properties": {"sessionID": "ses_1"},
    }

    frame = sse_event_frame(event)

    assert frame.startswith("id: session.status:ses_1:1\n")
    assert frame.endswith("\n\n")
    data_line = next(line for line in frame.splitlines() if line.startswith("data: "))
    assert json.loads(data_line.removeprefix("data: ")) == event


def test_sse_control_frame_can_omit_cursor_id():
    frame = sse_event_frame(
        {"type": "server.replay_complete", "properties": {}},
        include_id=False,
    )

    assert not frame.startswith("id:")
    assert '"type": "server.replay_complete"' in frame


def test_record_opencode_event_coalesces_unchanged_busy_heartbeats(monkeypatch):
    reset_runtime_event_sequences()
    recorded: list[dict[str, object]] = []

    class Ledger:
        def enqueue(self, event):
            recorded.append(dict(event))
            return True

    monkeypatch.setattr(
        "penguin.system.runtime_event_ledger.get_runtime_event_ledger",
        lambda _core: Ledger(),
    )
    core = SimpleNamespace()

    for status in ("busy", "busy", "idle", "busy"):
        record_opencode_event(
            core,
            {
                "type": "session.status",
                "properties": {
                    "sessionID": "ses_1",
                    "status": {"type": status},
                },
            },
        )

    assert [event["payload"]["status"]["type"] for event in recorded] == [
        "busy",
        "idle",
        "busy",
    ]


@pytest.mark.asyncio
async def test_emit_opencode_event_uses_runtime_event_bus():
    reset_runtime_event_sequences()
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeEventBus:
        async def emit(self, event_type: str, payload: dict[str, object]) -> None:
            calls.append((event_type, payload))

    await emit_opencode_event(
        SimpleNamespace(event_bus=FakeEventBus()),
        "question.asked",
        {"sessionID": "ses_1"},
    )

    assert len(calls) == 1
    event_type, payload = calls[0]
    assert event_type == "opencode_event"
    assert payload["type"] == "question.asked"
    assert payload["properties"] == {"sessionID": "ses_1"}
    runtime_event = payload["runtime_event"]
    assert runtime_event["schema_version"] == "penguin.runtime_event.v1"
    assert runtime_event["category"] == "user_input_approval"
    assert runtime_event["scope"]["session_id"] == "ses_1"
    assert payload["id"] == "evt:session:ses_1:00000001"


def test_schedule_opencode_event_works_from_sync_context():
    reset_runtime_event_sequences()
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeEventBus:
        async def emit(self, event_type: str, payload: dict[str, object]) -> None:
            calls.append((event_type, payload))

    schedule_opencode_event(
        lambda: SimpleNamespace(event_bus=FakeEventBus()),
        "session.error",
        {"sessionID": "ses_1"},
    )

    assert len(calls) == 1
    event_type, payload = calls[0]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.error"
    assert payload["properties"] == {"sessionID": "ses_1"}
    assert payload["runtime_event"]["category"] == "error"


@pytest.mark.asyncio
async def test_schedule_opencode_event_works_from_async_context():
    reset_runtime_event_sequences()
    calls: list[tuple[str, dict[str, object]]] = []

    class FakeEventBus:
        async def emit(self, event_type: str, payload: dict[str, object]) -> None:
            calls.append((event_type, payload))

    schedule_opencode_event(
        lambda: SimpleNamespace(event_bus=FakeEventBus()),
        "permission.asked",
        {"sessionID": "ses_1"},
    )

    await asyncio.sleep(0)

    assert len(calls) == 1
    event_type, payload = calls[0]
    assert event_type == "opencode_event"
    assert payload["type"] == "permission.asked"
    assert payload["properties"] == {"sessionID": "ses_1"}
    assert payload["runtime_event"]["category"] == "user_input_approval"
