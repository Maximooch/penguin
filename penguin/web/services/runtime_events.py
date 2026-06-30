"""Canonical runtime event envelope helpers.

The runtime envelope is Penguin-owned. OpenCode-shaped SSE payloads, TUI
notifications, future Link projections, logs, and analytics should be derived
from this shape instead of inferring state from UI-specific payloads.
"""

from __future__ import annotations

import hashlib
import itertools
import re
import threading
import time
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, MutableMapping

RUNTIME_EVENT_SCHEMA_VERSION = "penguin.runtime_event.v1"

RUNTIME_EVENT_CATEGORIES = {
    "session_lifecycle",
    "message_lifecycle",
    "stream_chunk",
    "tool_action_lifecycle",
    "file_diff",
    "task_run_state",
    "provider_model_state",
    "cwm_token_usage",
    "notification",
    "error",
    "user_input_approval",
}

_SECRET_KEY_NAMES = {
    "authorization",
    "bearer_token",
    "client_secret",
    "id_token",
    "password",
    "private_key",
    "refresh_token",
    "secret",
    "secret_key",
    "token",
}
_SEQUENCE_LOCK = threading.Lock()
_SEQUENCE_COUNTERS: dict[str, itertools.count[int]] = {}


def reset_runtime_event_sequences() -> None:
    """Reset per-stream counters for deterministic tests."""
    with _SEQUENCE_LOCK:
        _SEQUENCE_COUNTERS.clear()


def event_category(event_type: str, payload: Mapping[str, Any] | None = None) -> str:
    """Return the canonical runtime category for an event type."""
    payload = payload or {}
    if event_type in {"permission.asked", "permission.replied"}:
        return "user_input_approval"
    if event_type in {"question.asked", "question.replied", "question.rejected"}:
        return "user_input_approval"
    if event_type in {"message.part.updated", "message.part.removed"}:
        part = payload.get("part") if isinstance(payload, Mapping) else None
        if isinstance(part, Mapping) and part.get("type") in {"text", "reasoning"}:
            return "stream_chunk"
        return "tool_action_lifecycle"
    if event_type.startswith("message."):
        return "message_lifecycle"
    if event_type.startswith("session.diff") or event_type.startswith("vcs."):
        return "file_diff"
    if event_type.startswith("session.error") or event_type.endswith(".error"):
        return "error"
    if event_type.startswith("session."):
        return "session_lifecycle"
    if event_type.startswith(("tool.", "tool_", "action.", "todo.")):
        return "tool_action_lifecycle"
    if event_type.startswith(("task.", "run.")):
        return "task_run_state"
    if event_type.startswith(("provider.", "model.")):
        return "provider_model_state"
    if event_type.startswith(("token.", "usage.", "context_window.", "cwm.")):
        return "cwm_token_usage"
    if event_type.startswith("notification."):
        return "notification"
    if event_type.startswith(("file.", "lsp.")):
        return "file_diff"
    return "session_lifecycle"


def normalize_event_directory(directory: str | None) -> str | None:
    """Return a resolved directory string when one can be trusted."""
    if not isinstance(directory, str) or not directory.strip():
        return None
    try:
        return str(Path(directory).expanduser().resolve())
    except Exception:
        return None


def extract_runtime_scope(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Extract common correlation/scope fields from a runtime payload."""
    scope: dict[str, Any] = {}
    for target, keys in {
        "session_id": ("sessionID", "session_id", "conversation_id"),
        "conversation_id": ("conversation_id", "sessionID", "session_id"),
        "agent_id": ("agentID", "agent_id"),
        "task_id": ("taskID", "task_id", "task"),
        "run_id": ("runID", "run_id"),
        "project_id": ("projectID", "project_id"),
        "provider_id": ("providerID", "provider_id"),
        "model_id": ("modelID", "model_id"),
    }.items():
        value = _first_string(payload, keys)
        if value:
            scope[target] = value

    for parent_key in ("part", "info", "status"):
        nested = payload.get(parent_key)
        if not isinstance(nested, Mapping):
            continue
        nested_scope = extract_runtime_scope(nested)
        for key, value in nested_scope.items():
            scope.setdefault(key, value)

    directory = _extract_directory(payload)
    if directory:
        scope["directory"] = directory
        scope["workspace"] = directory
    return scope


def build_runtime_event(
    *,
    event_type: str,
    payload: Mapping[str, Any],
    actor: Mapping[str, Any] | None = None,
    category: str | None = None,
    correlation: Mapping[str, Any] | None = None,
    event_id: str | None = None,
    projections: Mapping[str, Any] | None = None,
    scope: Mapping[str, Any] | None = None,
    sequence: int | None = None,
    source: str = "penguin.backend",
    stream_id: str | None = None,
    subject: str | None = None,
    time_ms: int | None = None,
) -> dict[str, Any]:
    """Build a canonical, public-safe runtime event envelope."""
    payload_copy = _safe_deepcopy(dict(payload))
    redacted_payload, redacted_fields = redact_runtime_payload(payload_copy)
    runtime_scope = dict(extract_runtime_scope(redacted_payload))
    if scope:
        runtime_scope.update(
            {key: value for key, value in scope.items() if value is not None}
        )

    resolved_stream_id = stream_id or _default_stream_id(runtime_scope)
    resolved_sequence = (
        sequence if sequence is not None else _next_sequence(resolved_stream_id)
    )
    resolved_subject = subject or _default_subject(
        event_type, runtime_scope, redacted_payload
    )
    resolved_id = event_id or f"evt:{_slug(resolved_stream_id)}:{resolved_sequence:08d}"

    privacy = {
        "classification": "sensitive" if redacted_fields else "public",
        "redacted": bool(redacted_fields),
        "redacted_fields": redacted_fields,
    }
    return {
        "id": resolved_id,
        "schema_version": RUNTIME_EVENT_SCHEMA_VERSION,
        "type": event_type,
        "category": category or event_category(event_type, redacted_payload),
        "source": source,
        "subject": resolved_subject,
        "time": time_ms if time_ms is not None else int(time.time() * 1000),
        "stream_id": resolved_stream_id,
        "sequence": resolved_sequence,
        "scope": runtime_scope,
        "correlation": _normalized_correlation(redacted_payload, correlation),
        "actor": dict(actor or {}),
        "privacy": privacy,
        "payload": redacted_payload,
        "projections": dict(projections or {}),
    }


def runtime_event_from_opencode(
    data: Mapping[str, Any],
    *,
    default_agent_id: str | None = None,
    default_directory: str | None = None,
    default_session_id: str | None = None,
    now_ms: int | None = None,
    sequence: int | None = None,
) -> dict[str, Any] | None:
    """Build a RuntimeEvent from a Phase 10 OpenCode-compatible payload."""
    event_type = data.get("type")
    existing = data.get("runtime_event")
    if not isinstance(event_type, str) or not event_type:
        if isinstance(existing, Mapping):
            event_type = existing.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None

    raw_properties = data.get("properties")
    properties = dict(raw_properties) if isinstance(raw_properties, Mapping) else {}
    if default_session_id and not _first_string(
        properties, ("sessionID", "session_id")
    ):
        properties["sessionID"] = default_session_id
    if default_agent_id and not _first_string(properties, ("agentID", "agent_id")):
        properties["agentID"] = default_agent_id

    directory = _extract_directory(properties) or default_directory
    normalized_directory = normalize_event_directory(directory)
    if normalized_directory:
        properties["directory"] = normalized_directory

    if isinstance(existing, Mapping):
        normalized = normalize_runtime_event(
            existing,
            default_agent_id=default_agent_id,
            default_directory=normalized_directory or default_directory,
            default_session_id=default_session_id,
            now_ms=now_ms,
            overlay_payload=properties,
            sequence=sequence,
        )
        if normalized:
            return normalized

    source_id = _extract_source_id(properties)
    projection_id = data.get("id")
    needs_sequence_projection_id = False
    if not isinstance(projection_id, str) or not projection_id:
        session_id = _first_string(
            properties, ("sessionID", "session_id", "conversation_id")
        )
        if source_id:
            projection_id = f"{event_type}:{session_id or '-'}:{source_id}"
        else:
            needs_sequence_projection_id = True
            projection_id = f"{event_type}:{session_id or '-'}:pending"

    event = build_runtime_event(
        event_type=event_type,
        payload=properties,
        projections={
            "opencode": {
                "id": projection_id,
                "type": event_type,
            }
        },
        sequence=sequence,
        time_ms=now_ms,
    )
    if needs_sequence_projection_id:
        session_id = (
            event["scope"].get("session_id")
            if isinstance(event.get("scope"), dict)
            else None
        )
        event["projections"]["opencode"]["id"] = (
            f"{event_type}:{session_id or '-'}:{event['sequence']}"
        )
    return event


def normalize_runtime_event(
    value: Mapping[str, Any],
    *,
    default_agent_id: str | None = None,
    default_directory: str | None = None,
    default_session_id: str | None = None,
    now_ms: int | None = None,
    overlay_payload: Mapping[str, Any] | None = None,
    sequence: int | None = None,
) -> dict[str, Any] | None:
    """Return a runtime event dict if the incoming shape is usable."""
    event_type = value.get("type")
    if not isinstance(event_type, str) or not event_type:
        return None
    event_id = value.get("id")
    if not isinstance(event_id, str) or not event_id:
        return None
    payload = value.get("payload")
    if not isinstance(payload, Mapping):
        return None

    merged_payload = _safe_deepcopy(dict(payload))
    if isinstance(overlay_payload, Mapping):
        for key, item in overlay_payload.items():
            try:
                copied_item = deepcopy(item)
            except Exception:
                copied_item = item
            merged_payload.setdefault(str(key), copied_item)

    if default_session_id and not _first_string(
        merged_payload, ("sessionID", "session_id", "conversation_id")
    ):
        merged_payload["sessionID"] = default_session_id
    if default_agent_id and not _first_string(merged_payload, ("agentID", "agent_id")):
        merged_payload["agentID"] = default_agent_id

    directory = _extract_directory(merged_payload) or default_directory
    normalized_directory = normalize_event_directory(directory)
    if normalized_directory:
        merged_payload.setdefault("directory", normalized_directory)

    redacted_payload, redacted_fields = redact_runtime_payload(merged_payload)
    runtime_scope = dict(extract_runtime_scope(redacted_payload))
    existing_scope = value.get("scope")
    if isinstance(existing_scope, Mapping):
        runtime_scope.update(
            {key: item for key, item in existing_scope.items() if item is not None}
        )
    default_stream_id = _default_stream_id(runtime_scope)
    existing_stream_id = value.get("stream_id")
    if not isinstance(existing_stream_id, str) or (
        existing_stream_id == "global" and default_stream_id != "global"
    ):
        existing_stream_id = default_stream_id

    existing_sequence = value.get("sequence")
    if not isinstance(existing_sequence, int) or existing_sequence <= 0:
        existing_sequence = sequence if sequence is not None else 0

    existing_subject = value.get("subject")
    default_subject = _default_subject(event_type, runtime_scope, redacted_payload)
    if not isinstance(existing_subject, str) or not existing_subject:
        existing_subject = default_subject

    existing_time = value.get("time")
    if not isinstance(existing_time, int):
        existing_time = now_ms if now_ms is not None else int(time.time() * 1000)

    projections = value.get("projections")
    if not isinstance(projections, Mapping):
        projections = {}
    existing_correlation = value.get("correlation")
    if not isinstance(existing_correlation, Mapping):
        existing_correlation = None
    existing_privacy = value.get("privacy")

    event = dict(value)
    event["schema_version"] = (
        event.get("schema_version") or RUNTIME_EVENT_SCHEMA_VERSION
    )
    event["category"] = event.get("category") or event_category(
        event_type,
        redacted_payload,
    )
    event["source"] = event.get("source") or "penguin.backend"
    event["subject"] = existing_subject
    event["time"] = existing_time
    event["stream_id"] = existing_stream_id
    event["sequence"] = existing_sequence
    event["scope"] = runtime_scope
    event["correlation"] = _normalized_correlation(
        redacted_payload,
        existing_correlation,
    )
    event["actor"] = dict(event.get("actor") or {})
    if redacted_fields:
        event["privacy"] = {
            "classification": "sensitive",
            "redacted": True,
            "redacted_fields": redacted_fields,
        }
    elif isinstance(existing_privacy, Mapping):
        event["privacy"] = dict(existing_privacy)
    else:
        event["privacy"] = {
            "classification": "public",
            "redacted": False,
            "redacted_fields": [],
        }
    event["payload"] = redacted_payload
    event["projections"] = dict(projections)
    return event


def opencode_payload_from_runtime_event(event: Mapping[str, Any]) -> dict[str, Any]:
    """Project RuntimeEvent into the Phase 10 OpenCode-compatible payload."""
    payload = event.get("payload")
    properties = dict(payload) if isinstance(payload, Mapping) else {}
    scope = event.get("scope")
    if isinstance(scope, Mapping):
        if scope.get("session_id") and not isinstance(properties.get("sessionID"), str):
            properties["sessionID"] = scope["session_id"]
        if scope.get("agent_id") and not isinstance(properties.get("agentID"), str):
            properties["agentID"] = scope["agent_id"]
        if scope.get("directory") and not isinstance(properties.get("directory"), str):
            properties["directory"] = scope["directory"]

    projection = event.get("projections")
    opencode = projection.get("opencode") if isinstance(projection, Mapping) else None
    opencode_id = opencode.get("id") if isinstance(opencode, Mapping) else None
    opencode_type = opencode.get("type") if isinstance(opencode, Mapping) else None
    event_id = event.get("id")

    return {
        "id": event_id if isinstance(event_id, str) else opencode_id,
        "order": event.get("sequence", 0),
        "time": event.get("time", int(time.time() * 1000)),
        "type": opencode_type if isinstance(opencode_type, str) else event.get("type"),
        "properties": properties,
    }


def wrap_opencode_event(
    event_type: str,
    properties: Mapping[str, Any],
    *,
    default_agent_id: str | None = None,
    default_directory: str | None = None,
    default_session_id: str | None = None,
    now_ms: int | None = None,
) -> dict[str, Any]:
    """Return an EventBus payload that includes its RuntimeEvent envelope."""
    data = {
        "type": event_type,
        "properties": dict(properties),
    }
    runtime_event = runtime_event_from_opencode(
        data,
        default_agent_id=default_agent_id,
        default_directory=default_directory,
        default_session_id=default_session_id,
        now_ms=now_ms,
    )
    if runtime_event is not None:
        data["runtime_event"] = runtime_event
        projected = opencode_payload_from_runtime_event(runtime_event)
        data["id"] = projected.get("id")
        data["time"] = projected.get("time")
        data["order"] = projected.get("order")
        projected_properties = projected.get("properties")
        if isinstance(projected_properties, Mapping):
            data["properties"] = dict(projected_properties)
    return data


def redact_runtime_payload(value: Any, path: str = "") -> tuple[Any, list[str]]:
    """Return a redacted copy of a payload and the redacted field paths."""
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        redacted: list[str] = []
        for key, item in value.items():
            key_text = str(key)
            child_path = f"{path}.{key_text}" if path else key_text
            if _is_secret_key(key_text):
                result[key_text] = "[redacted]"
                redacted.append(child_path)
                continue
            child, child_redacted = redact_runtime_payload(item, child_path)
            result[key_text] = child
            redacted.extend(child_redacted)
        return result, redacted
    if isinstance(value, list):
        result_list = []
        redacted = []
        for index, item in enumerate(value):
            child, child_redacted = redact_runtime_payload(item, f"{path}[{index}]")
            result_list.append(child)
            redacted.extend(child_redacted)
        return result_list, redacted
    return value, []


def _is_secret_key(key: str) -> bool:
    """Return whether a payload key names a credential, not token telemetry."""
    normalized = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", key).replace("-", "_")
    normalized = re.sub(r"[^A-Za-z0-9_]+", "_", normalized).strip("_").lower()
    if not normalized:
        return False
    if normalized in _SECRET_KEY_NAMES:
        return True

    segments = [item for item in normalized.split("_") if item]
    if not segments:
        return False

    key_tokens = {"key", "keys"}
    if "api" in segments and key_tokens.intersection(segments):
        return True
    if "secret" in segments and key_tokens.intersection(segments):
        return True
    if "private" in segments and key_tokens.intersection(segments):
        return True

    credential_pairs = {
        ("access", "token"),
        ("auth", "token"),
        ("bearer", "token"),
        ("client", "secret"),
        ("id", "token"),
        ("refresh", "token"),
        ("session", "token"),
    }
    return any(
        (segments[index], segments[index + 1]) in credential_pairs
        for index in range(len(segments) - 1)
    )


def _first_string(payload: Mapping[str, Any], keys: tuple[str, ...]) -> str | None:
    for key in keys:
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _extract_directory(payload: Mapping[str, Any]) -> str | None:
    value = payload.get("directory")
    if isinstance(value, str) and value:
        return normalize_event_directory(value)
    for parent_key in ("info", "path", "part"):
        nested = payload.get(parent_key)
        if not isinstance(nested, Mapping):
            continue
        value = nested.get("directory")
        if isinstance(value, str) and value:
            return normalize_event_directory(value)
        path = nested.get("path")
        if isinstance(path, Mapping):
            cwd = path.get("cwd")
            if isinstance(cwd, str) and cwd:
                return normalize_event_directory(cwd)
        cwd = nested.get("cwd")
        if isinstance(cwd, str) and cwd:
            return normalize_event_directory(cwd)
    return None


def _extract_source_id(properties: Mapping[str, Any]) -> str | None:
    for key in ("id", "requestID", "messageID", "partID"):
        value = properties.get(key)
        if isinstance(value, str) and value:
            return value
    for parent_key in ("part", "info"):
        nested = properties.get(parent_key)
        if not isinstance(nested, Mapping):
            continue
        for key in ("id", "messageID", "partID"):
            value = nested.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _normalized_correlation(
    payload: Mapping[str, Any],
    explicit: Mapping[str, Any] | None,
) -> dict[str, Any]:
    result = dict(explicit or {})
    for target, keys in {
        "request_id": ("requestID", "request_id"),
        "trace_id": ("traceID", "trace_id"),
        "parent_event_id": ("parentEventID", "parent_event_id"),
    }.items():
        value = result.get(target) or _first_string(payload, keys)
        if value:
            result[target] = value
    return result


def _default_stream_id(scope: Mapping[str, Any] | None) -> str:
    if isinstance(scope, Mapping):
        for key, prefix in (
            ("session_id", "session"),
            ("run_id", "run"),
            ("task_id", "task"),
            ("directory", "workspace"),
            ("workspace", "workspace"),
        ):
            value = scope.get(key)
            if isinstance(value, str) and value:
                if key in {"directory", "workspace"}:
                    return f"{prefix}:{_short_hash(value)}"
                return f"{prefix}:{value}"
    return "global"


def _default_subject(
    event_type: str,
    scope: Mapping[str, Any],
    payload: Mapping[str, Any],
) -> str:
    for key in ("session_id", "task_id", "run_id", "agent_id"):
        value = scope.get(key)
        if isinstance(value, str) and value:
            return f"{key}:{value}"
    source_id = _extract_source_id(payload)
    if source_id:
        return f"{event_type}:{source_id}"
    return event_type


def _next_sequence(stream_id: str) -> int:
    with _SEQUENCE_LOCK:
        counter = _SEQUENCE_COUNTERS.get(stream_id)
        if counter is None:
            counter = itertools.count(1)
            _SEQUENCE_COUNTERS[stream_id] = counter
        return next(counter)


def _slug(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9_.:-]+", "-", value).strip("-")
    if len(cleaned) <= 80:
        return cleaned or "global"
    return f"{cleaned[:48]}-{_short_hash(cleaned)}"


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _safe_deepcopy(value: MutableMapping[str, Any]) -> dict[str, Any]:
    try:
        return deepcopy(value)
    except Exception:
        return dict(value)


__all__ = [
    "RUNTIME_EVENT_CATEGORIES",
    "RUNTIME_EVENT_SCHEMA_VERSION",
    "build_runtime_event",
    "event_category",
    "extract_runtime_scope",
    "normalize_event_directory",
    "normalize_runtime_event",
    "opencode_payload_from_runtime_event",
    "redact_runtime_payload",
    "reset_runtime_event_sequences",
    "runtime_event_from_opencode",
    "wrap_opencode_event",
]
