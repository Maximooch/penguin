"""Tests for Penguin RuntimeEvent envelope construction."""

from __future__ import annotations

import json
from pathlib import Path

from penguin.system.runtime_events import (
    RUNTIME_EVENT_CATEGORIES,
    RUNTIME_EVENT_SCHEMA_VERSION,
    build_runtime_event,
    event_category,
    opencode_payload_from_runtime_event,
    reset_runtime_event_sequences,
    runtime_event_from_opencode,
    wrap_opencode_event,
)


def test_runtime_event_builds_stable_envelope_with_scope(tmp_path: Path) -> None:
    reset_runtime_event_sequences()

    event = build_runtime_event(
        event_type="message.part.updated",
        payload={
            "part": {
                "id": "part_1",
                "messageID": "msg_1",
                "sessionID": "ses_1",
                "type": "text",
            },
            "directory": str(tmp_path),
        },
        time_ms=123,
    )

    assert event["schema_version"] == RUNTIME_EVENT_SCHEMA_VERSION
    assert event["id"] == "evt:session:ses_1:00000001"
    assert event["category"] == "stream_chunk"
    assert event["time"] == 123
    assert event["stream_id"] == "session:ses_1"
    assert event["sequence"] == 1
    assert event["scope"]["session_id"] == "ses_1"
    assert event["scope"]["directory"] == str(tmp_path.resolve())
    assert event["privacy"] == {
        "classification": "public",
        "redacted": False,
        "redacted_fields": [],
    }


def test_runtime_event_redacts_public_payload_secrets() -> None:
    reset_runtime_event_sequences()

    event = build_runtime_event(
        event_type="provider.auth.updated",
        payload={
            "sessionID": "ses_1",
            "OPENAI_API_KEY": "sk-real",
            "api_keys": ["sk-other"],
            "nested": {
                "aws_secret_access_key": "aws-secret",
                "client_secret": "secret-value",
                "private_key": "private-value",
                "secret_key": "secret-key-value",
            },
        },
    )

    assert event["category"] == "provider_model_state"
    assert event["privacy"]["classification"] == "sensitive"
    assert event["privacy"]["redacted_fields"] == [
        "OPENAI_API_KEY",
        "api_keys",
        "nested.aws_secret_access_key",
        "nested.client_secret",
        "nested.private_key",
        "nested.secret_key",
    ]
    assert event["payload"]["OPENAI_API_KEY"] == "[redacted]"
    assert event["payload"]["api_keys"] == "[redacted]"
    assert event["payload"]["nested"]["aws_secret_access_key"] == "[redacted]"
    assert event["payload"]["nested"]["client_secret"] == "[redacted]"
    assert event["payload"]["nested"]["private_key"] == "[redacted]"
    assert event["payload"]["nested"]["secret_key"] == "[redacted]"


def test_runtime_event_redacts_suffix_style_credentials() -> None:
    # Regression: password/secret/authorization credential names whose sensitive
    # word is a non-trailing or prefixed segment must still be redacted, without
    # touching token telemetry whose keys never contain those words.
    reset_runtime_event_sequences()

    event = build_runtime_event(
        event_type="provider.auth.updated",
        payload={
            "sessionID": "ses_1",
            "db_password": "hunter2",
            "webhook_secret": "whsec_live",
            "proxy_authorization": "Bearer xyz",
            "oauth_client_secret": "cs_live",
            "nested": {"admin_password": "root"},
            # Telemetry that must remain visible.
            "tokens": 12,
            "token_usage": {"input_tokens": 3, "output_tokens": 9},
            "input_tokens": 3,
        },
    )

    payload = event["payload"]
    assert payload["db_password"] == "[redacted]"
    assert payload["webhook_secret"] == "[redacted]"
    assert payload["proxy_authorization"] == "[redacted]"
    assert payload["oauth_client_secret"] == "[redacted]"
    assert payload["nested"]["admin_password"] == "[redacted]"

    assert payload["tokens"] == 12
    assert payload["token_usage"] == {"input_tokens": 3, "output_tokens": 9}
    assert payload["input_tokens"] == 3

    assert event["privacy"]["classification"] == "sensitive"
    assert set(event["privacy"]["redacted_fields"]) == {
        "db_password",
        "webhook_secret",
        "proxy_authorization",
        "oauth_client_secret",
        "nested.admin_password",
    }


def test_runtime_event_preserves_token_usage_telemetry() -> None:
    reset_runtime_event_sequences()

    event = build_runtime_event(
        event_type="token.usage.updated",
        payload={
            "sessionID": "ses_1",
            "tokens": 42,
            "token_usage": {"input_tokens": 10, "output_tokens": 32},
            "context_window": {"used_tokens": 4000, "max_tokens": 128000},
            "access_token": "secret-access-token",
        },
    )

    assert event["category"] == "cwm_token_usage"
    assert event["privacy"]["redacted_fields"] == ["access_token"]
    assert event["payload"]["tokens"] == 42
    assert event["payload"]["token_usage"] == {
        "input_tokens": 10,
        "output_tokens": 32,
    }
    assert event["payload"]["context_window"] == {
        "used_tokens": 4000,
        "max_tokens": 128000,
    }
    assert event["payload"]["access_token"] == "[redacted]"


def test_runtime_event_category_inventory_covers_phase_11_categories() -> None:
    assert {
        event_category("session.created"),
        event_category("message.updated"),
        event_category("message.part.updated", {"part": {"type": "text"}}),
        event_category("message.part.updated", {"part": {"type": "tool"}}),
        event_category("session.diff"),
        event_category("task.updated"),
        event_category("provider.auth.updated"),
        event_category("token.usage.updated"),
        event_category("notification.sent"),
        event_category("session.error"),
        event_category("permission.asked"),
    } == RUNTIME_EVENT_CATEGORIES


def test_opencode_runtime_projection_preserves_compat_shape(tmp_path: Path) -> None:
    reset_runtime_event_sequences()

    event = runtime_event_from_opencode(
        {
            "type": "question.asked",
            "properties": {
                "id": "question_1",
                "sessionID": "ses_1",
                "question": "Continue?",
                "directory": str(tmp_path),
            },
        },
        now_ms=456,
    )

    assert event is not None
    assert event["category"] == "user_input_approval"
    projected = opencode_payload_from_runtime_event(event)
    assert projected == {
        "id": "evt:session:ses_1:00000001",
        "order": 1,
        "time": 456,
        "type": "question.asked",
        "properties": {
            "id": "question_1",
            "sessionID": "ses_1",
            "question": "Continue?",
            "directory": str(tmp_path.resolve()),
        },
    }


def test_wrap_opencode_event_assigns_runtime_event_before_sse_projection() -> None:
    reset_runtime_event_sequences()

    payload = wrap_opencode_event(
        "session.status",
        {
            "sessionID": "ses_1",
            "status": {"type": "idle"},
        },
        now_ms=789,
    )

    runtime_event = payload["runtime_event"]
    assert runtime_event["id"] == "evt:session:ses_1:00000001"
    assert runtime_event["type"] == "session.status"
    assert payload["id"] == "evt:session:ses_1:00000001"
    assert payload["order"] == 1
    assert payload["time"] == 789


def test_wrap_opencode_event_projects_redacted_properties() -> None:
    reset_runtime_event_sequences()

    payload = wrap_opencode_event(
        "provider.auth.updated",
        {
            "sessionID": "ses_1",
            "aws_secret_access_key": "aws-secret",
            "tokens": 12,
        },
    )

    assert payload["properties"]["aws_secret_access_key"] == "[redacted]"
    assert payload["properties"]["tokens"] == 12
    assert payload["runtime_event"]["payload"]["aws_secret_access_key"] == "[redacted]"


def test_runtime_event_fixtures_project_to_opencode_shape() -> None:
    fixture_dir = Path(__file__).parents[1] / "fixtures" / "runtime_events"

    fixtures = sorted(fixture_dir.glob("*.json"))
    assert fixtures
    for fixture_path in fixtures:
        fixture = json.loads(fixture_path.read_text())
        assert (
            opencode_payload_from_runtime_event(fixture["runtime_event"])
            == fixture["opencode"]
        ), fixture_path.name
