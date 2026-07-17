"""Fail-closed validation for native assistant/tool transcript units.

Native tool providers require an assistant declaration and every corresponding
tool result to remain adjacent.  Session persistence and category trimming can
otherwise leave an orphaned call, result, or duplicate call id that providers
try to replay.  This module deliberately handles only that integrity boundary;
it does not make context-window budgeting decisions.
"""

from __future__ import annotations

import copy
from typing import Any, Iterable

from penguin.system.state import Message, Session

__all__ = [
    "preserve_native_tool_adjacency",
    "sanitize_native_tool_messages",
    "sanitize_native_tool_session",
]


def _copy_value(value: Any) -> Any:
    """Copy provider-bound data without allowing sanitizer mutation to leak."""

    try:
        return copy.deepcopy(value)
    except Exception:
        if isinstance(value, dict):
            copied = dict(value)
            metadata = copied.get("metadata")
            if isinstance(metadata, dict):
                copied["metadata"] = dict(metadata)
            return copied
        return value


def _message_role(message: Any) -> str:
    """Return a normalized role for one dictionary-shaped message."""

    if not isinstance(message, dict):
        return ""
    return str(message.get("role") or "").strip().lower()


def _tool_call_locations(message: dict[str, Any]) -> list[tuple[str, Any]]:
    """Return every native tool-call container carried by one assistant item."""

    locations: list[tuple[str, Any]] = []
    if "tool_calls" in message:
        locations.append(("top_level", message.get("tool_calls")))
    metadata = message.get("metadata")
    if isinstance(metadata, dict) and "tool_calls" in metadata:
        locations.append(("metadata", metadata.get("tool_calls")))
    return locations


def _declared_tool_call_ids(message: dict[str, Any]) -> tuple[list[str], bool]:
    """Return declared ids and whether the declaration is structurally valid."""

    locations = _tool_call_locations(message)
    if not locations:
        return [], True
    # A message carrying both canonical forms is ambiguous.  Do not select one
    # arbitrarily because a later provider-specific adapter could see the other.
    if len(locations) != 1:
        return [], False

    _location, tool_calls = locations[0]
    if not isinstance(tool_calls, list) or not tool_calls:
        return [], False

    ids: list[str] = []
    for tool_call in tool_calls:
        if not isinstance(tool_call, dict):
            return [], False
        call_id = str(tool_call.get("id") or "").strip()
        if not call_id:
            return [], False
        ids.append(call_id)
    return ids, len(ids) == len(set(ids))


def _tool_result_call_id(message: dict[str, Any]) -> str:
    """Read one tool result id, refusing conflicting canonical fields."""

    top_level = str(message.get("tool_call_id") or "").strip()
    metadata = message.get("metadata")
    metadata_id = (
        str(metadata.get("tool_call_id") or "").strip()
        if isinstance(metadata, dict)
        else ""
    )
    if top_level and metadata_id and top_level != metadata_id:
        return ""
    return top_level or metadata_id


def _remove_tool_calls(message: dict[str, Any]) -> None:
    """Strip every native tool declaration form from an invalid assistant."""

    message.pop("tool_calls", None)
    metadata = message.get("metadata")
    if isinstance(metadata, dict):
        metadata.pop("tool_calls", None)


def sanitize_native_tool_messages(messages: Iterable[Any]) -> list[Any]:
    """Keep only complete, unique, consecutive native assistant/tool units.

    A valid unit contains one assistant declaration followed immediately by one
    ``tool`` message for every declared id, exactly once.  The assistant's text
    can be empty; that is the normal native streaming-tool shape.  Any partial,
    interleaved, malformed, or duplicate unit is flattened to ordinary
    assistant text and its tool results are omitted.
    """

    copied_messages = [_copy_value(message) for message in messages]
    valid_tool_indexes: set[int] = set()
    invalid_declaration_indexes: set[int] = set()
    seen_call_ids: set[str] = set()

    for assistant_index, assistant in enumerate(copied_messages):
        if _message_role(assistant) != "assistant" or not isinstance(assistant, dict):
            continue

        locations = _tool_call_locations(assistant)
        if not locations:
            continue
        declared_ids, structurally_valid = _declared_tool_call_ids(assistant)
        if not structurally_valid or not declared_ids:
            invalid_declaration_indexes.add(assistant_index)
            continue
        if seen_call_ids.intersection(declared_ids):
            invalid_declaration_indexes.add(assistant_index)
            continue
        # A call id is globally single-use for the transcript, even if the
        # first declaration is later rejected for missing/interleaved results.
        # Allowing a second declaration to claim it would make recovery replay
        # a logically ambiguous tool action.
        seen_call_ids.update(declared_ids)

        result_indexes: list[int] = []
        result_ids: list[str] = []
        cursor = assistant_index + 1
        while cursor < len(copied_messages):
            candidate = copied_messages[cursor]
            if _message_role(candidate) != "tool" or not isinstance(candidate, dict):
                break
            result_indexes.append(cursor)
            result_ids.append(_tool_result_call_id(candidate))
            cursor += 1

        # Native providers receive a declaration as a single batch.  Preserve
        # it only when all declared results survived contiguously and uniquely.
        if (
            len(result_ids) != len(declared_ids)
            or any(not call_id for call_id in result_ids)
            or len(result_ids) != len(set(result_ids))
            or set(result_ids) != set(declared_ids)
        ):
            invalid_declaration_indexes.add(assistant_index)
            continue

        valid_tool_indexes.update(result_indexes)

    sanitized: list[Any] = []
    for index, message in enumerate(copied_messages):
        role = _message_role(message)
        if role == "tool" and index not in valid_tool_indexes:
            continue
        if role != "assistant" and isinstance(message, dict):
            # Only assistant messages may declare native function calls.  Do
            # not leave metadata-shaped calls on user/system history where a
            # provider adapter might interpret them inconsistently.
            _remove_tool_calls(message)
        if index in invalid_declaration_indexes and isinstance(message, dict):
            _remove_tool_calls(message)
        sanitized.append(message)
    return sanitized


def _complete_call_ids(messages: Iterable[Any]) -> set[str]:
    """Return ids from a sequence already shaped by the strict sanitizer."""

    complete_ids: set[str] = set()
    materialized = list(messages)
    for index, message in enumerate(materialized):
        if _message_role(message) != "assistant" or not isinstance(message, dict):
            continue
        declared_ids, valid = _declared_tool_call_ids(message)
        if not valid or not declared_ids:
            continue
        following_ids: list[str] = []
        cursor = index + 1
        while cursor < len(materialized):
            candidate = materialized[cursor]
            if _message_role(candidate) != "tool" or not isinstance(candidate, dict):
                break
            following_ids.append(_tool_result_call_id(candidate))
            cursor += 1
        if (
            len(following_ids) == len(declared_ids)
            and len(following_ids) == len(set(following_ids))
            and set(following_ids) == set(declared_ids)
        ):
            complete_ids.update(declared_ids)
    return complete_ids


def _filter_tool_records(records: Any, complete_ids: set[str]) -> list[Any]:
    """Keep unscoped records and records linked to a complete native unit."""

    if not isinstance(records, list):
        return []
    filtered: list[Any] = []
    for record in records:
        if not isinstance(record, dict):
            filtered.append(_copy_value(record))
            continue
        call_id = str(record.get("call_id") or "").strip()
        if not call_id or call_id in complete_ids:
            filtered.append(_copy_value(record))
    return filtered


def preserve_native_tool_adjacency(snapshot: dict[str, Any]) -> dict[str, Any]:
    """Mutate a persisted session snapshot into a safe native replay shape."""

    raw_messages = snapshot.get("messages")
    messages = raw_messages if isinstance(raw_messages, list) else []
    sanitized_messages = sanitize_native_tool_messages(messages)
    complete_ids = _complete_call_ids(sanitized_messages)

    snapshot["messages"] = sanitized_messages
    snapshot["tool_call_records"] = _filter_tool_records(
        snapshot.get("tool_call_records"),
        complete_ids,
    )
    snapshot["tool_result_records"] = _filter_tool_records(
        snapshot.get("tool_result_records"),
        complete_ids,
    )
    metadata = snapshot.get("metadata")
    if isinstance(metadata, dict):
        metadata["message_count"] = len(sanitized_messages)
        metadata["tool_call_record_count"] = len(snapshot["tool_call_records"])
        metadata["tool_result_record_count"] = len(snapshot["tool_result_records"])
    return snapshot


def sanitize_native_tool_session(session: Session) -> Session:
    """Sanitize a live session in place while preserving its object identity."""

    original_messages = [message.to_dict() for message in session.messages]
    original_call_records = [
        _copy_value(record) for record in session.tool_call_records
    ]
    original_result_records = [
        _copy_value(record) for record in session.tool_result_records
    ]
    snapshot = {
        "messages": _copy_value(original_messages),
        "tool_call_records": _copy_value(original_call_records),
        "tool_result_records": _copy_value(original_result_records),
        "metadata": _copy_value(session.metadata),
    }
    preserve_native_tool_adjacency(snapshot)

    sanitized_messages = snapshot["messages"]
    if sanitized_messages != original_messages:
        session.messages = [
            Message.from_dict(_copy_value(message))
            for message in sanitized_messages
            if isinstance(message, dict)
        ]
    if snapshot["tool_call_records"] != original_call_records:
        session.tool_call_records = [
            _copy_value(record)
            for record in snapshot["tool_call_records"]
            if isinstance(record, dict)
        ]
    if snapshot["tool_result_records"] != original_result_records:
        session.tool_result_records = [
            _copy_value(record)
            for record in snapshot["tool_result_records"]
            if isinstance(record, dict)
        ]
    if isinstance(session.metadata, dict):
        session.metadata["message_count"] = len(session.messages)
        session.metadata["tool_call_record_count"] = len(session.tool_call_records)
        session.metadata["tool_result_record_count"] = len(session.tool_result_records)
    return session
