"""Tests for OpenCode event normalization helpers."""

from __future__ import annotations

import json

from penguin.web.services.opencode_events import (
    directory_matches,
    extract_event_directory,
    extract_event_session,
    normalize_opencode_event,
    sse_event_frame,
)


def test_normalize_opencode_event_adds_id_time_order_and_correlation(tmp_path):
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
    assert event["id"] == "message.part.updated:ses_1:part_1"
    assert event["order"] == 12
    assert event["time"] == 123456
    assert event["properties"]["sessionID"] == "ses_1"
    assert event["properties"]["directory"] == str(tmp_path)


def test_normalize_opencode_event_rejects_malformed_payloads():
    assert normalize_opencode_event({}, order=1) is None
    assert normalize_opencode_event({"type": ""}, order=1) is None


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
    data_line = [line for line in frame.splitlines() if line.startswith("data: ")][0]
    assert json.loads(data_line.removeprefix("data: ")) == event
