"""OpenCode transcript persistence helpers.

These helpers own the deterministic transcript mutation rules used by
``PenguinCore`` when replaying OpenCode message and part events into session
history.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Callable

from penguin.core_runtime.opencode_bridge import normalize_optional_string
from penguin.system.runtime_events import redact_runtime_payload

TRANSCRIPT_KEY = "_opencode_transcript_v1"
TRANSCRIPT_EVENT_TYPES = frozenset(
    {
        "message.updated",
        "message.part.updated",
        "message.part.removed",
        "message.removed",
    }
)

AssistantInfoFactory = Callable[[str, str], dict[str, Any]]

__all__ = [
    "TRANSCRIPT_EVENT_TYPES",
    "TRANSCRIPT_KEY",
    "AssistantInfoFactory",
    "TranscriptEventResult",
    "apply_transcript_event",
    "resolve_event_session_id",
]


@dataclass(frozen=True)
class TranscriptEventResult:
    """Result of applying an OpenCode transcript event."""

    mark_modified: bool
    should_save: bool


def resolve_event_session_id(
    event_type: str,
    properties: Mapping[str, Any],
) -> str | None:
    """Resolve the session id for an OpenCode transcript event."""

    if event_type not in TRANSCRIPT_EVENT_TYPES:
        return None

    session_id = normalize_optional_string(properties.get("sessionID"))
    part = properties.get("part")
    if not session_id and isinstance(part, Mapping):
        session_id = normalize_optional_string(part.get("sessionID"))

    if not session_id or session_id == "unknown":
        return None
    return session_id


def apply_transcript_event(
    *,
    metadata: Any,
    event_type: str,
    properties: Mapping[str, Any],
    session_id: str,
    assistant_info_factory: AssistantInfoFactory,
) -> TranscriptEventResult:
    """Apply an OpenCode message or part event to session transcript metadata."""

    if event_type not in TRANSCRIPT_EVENT_TYPES or not isinstance(metadata, dict):
        return TranscriptEventResult(mark_modified=False, should_save=False)

    transcript = metadata.get(TRANSCRIPT_KEY)
    if not isinstance(transcript, dict):
        transcript = {"messages": {}, "order": []}
        metadata[TRANSCRIPT_KEY] = transcript

    messages = transcript.get("messages")
    if not isinstance(messages, dict):
        messages = {}
        transcript["messages"] = messages

    order = transcript.get("order")
    if not isinstance(order, list):
        order = []
        transcript["order"] = order

    if event_type == "message.updated":
        return _apply_message_updated(transcript, messages, order, properties)

    if event_type == "message.part.updated":
        return _apply_part_updated(
            messages,
            order,
            properties,
            session_id=session_id,
            assistant_info_factory=assistant_info_factory,
        )

    if event_type == "message.part.removed":
        return _apply_part_removed(messages, properties)

    if event_type == "message.removed":
        return _apply_message_removed(transcript, messages, order, properties)

    return TranscriptEventResult(mark_modified=False, should_save=False)


def _apply_message_updated(
    transcript: dict[str, Any],
    messages: dict[Any, Any],
    order: list[Any],
    properties: Mapping[str, Any],
) -> TranscriptEventResult:
    message_id = properties.get("id")
    if not message_id:
        return TranscriptEventResult(mark_modified=False, should_save=False)

    entry = messages.get(message_id)
    if not isinstance(entry, dict):
        entry = {}
    parts = entry.get("parts")
    if not isinstance(parts, dict):
        parts = {}
    part_order = entry.get("part_order")
    if not isinstance(part_order, list):
        part_order = []

    redacted_properties, _ = redact_runtime_payload(dict(properties))
    if isinstance(redacted_properties, dict):
        entry["info"] = redacted_properties
    else:
        entry["info"] = dict(properties)
    entry["parts"] = parts
    entry["part_order"] = part_order
    messages[message_id] = entry
    if message_id not in order:
        order.append(message_id)
    transcript["order"] = order

    time_data = properties.get("time")
    should_save = isinstance(time_data, dict) and bool(time_data.get("completed"))
    return TranscriptEventResult(mark_modified=True, should_save=should_save)


def _apply_part_updated(
    messages: dict[Any, Any],
    order: list[Any],
    properties: Mapping[str, Any],
    *,
    session_id: str,
    assistant_info_factory: AssistantInfoFactory,
) -> TranscriptEventResult:
    part = properties.get("part")
    if not isinstance(part, Mapping):
        return TranscriptEventResult(mark_modified=False, should_save=False)

    message_id = part.get("messageID")
    part_id = part.get("id")
    if not message_id or not part_id:
        return TranscriptEventResult(mark_modified=False, should_save=False)

    entry = messages.get(message_id)
    if not isinstance(entry, dict):
        entry = {
            "info": assistant_info_factory(str(message_id), session_id),
            "parts": {},
            "part_order": [],
        }
        messages[message_id] = entry
        if message_id not in order:
            order.append(message_id)

    parts = entry.get("parts")
    if not isinstance(parts, dict):
        parts = {}
        entry["parts"] = parts
    part_order = entry.get("part_order")
    if not isinstance(part_order, list):
        part_order = []
        entry["part_order"] = part_order

    redacted_part, _ = redact_runtime_payload(dict(part))
    parts[part_id] = redacted_part if isinstance(redacted_part, dict) else dict(part)
    if part_id not in part_order:
        part_order.append(part_id)

    state = part.get("state")
    should_save = (
        part.get("type") == "tool"
        and isinstance(state, Mapping)
        and state.get("status") in {"completed", "error"}
    )
    return TranscriptEventResult(mark_modified=True, should_save=should_save)


def _apply_part_removed(
    messages: dict[Any, Any],
    properties: Mapping[str, Any],
) -> TranscriptEventResult:
    message_id = properties.get("messageID")
    part_id = properties.get("partID")
    if not message_id or not part_id:
        return TranscriptEventResult(mark_modified=False, should_save=False)

    entry = messages.get(message_id)
    if not isinstance(entry, dict):
        return TranscriptEventResult(mark_modified=False, should_save=False)

    parts = entry.get("parts")
    if isinstance(parts, dict):
        parts.pop(part_id, None)
    part_order = entry.get("part_order")
    if isinstance(part_order, list):
        entry["part_order"] = [item for item in part_order if item != part_id]

    return TranscriptEventResult(mark_modified=True, should_save=False)


def _apply_message_removed(
    transcript: dict[str, Any],
    messages: dict[Any, Any],
    order: list[Any],
    properties: Mapping[str, Any],
) -> TranscriptEventResult:
    message_id = properties.get("messageID")
    if not message_id:
        return TranscriptEventResult(mark_modified=False, should_save=False)

    messages.pop(message_id, None)
    transcript["order"] = [item for item in order if item != message_id]
    return TranscriptEventResult(mark_modified=True, should_save=False)
