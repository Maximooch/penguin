"""Session fork helpers for OpenCode-compatible TUI flows."""

from __future__ import annotations

import copy
from datetime import datetime
import uuid
from typing import Any, Optional

from penguin.system.state import Message, MessageCategory
from penguin.web.services.session_view import (
    AGENT_MODE_KEY,
    TRANSCRIPT_KEY,
    _build_session_info,
    _find_session,
    _normalize_agent_mode,
    _session_directory,
    get_session_messages,
)


def _fork_title(title: str) -> str:
    stripped = title.strip()
    if stripped.endswith(")") and " (fork #" in stripped:
        prefix, suffix = stripped.rsplit(" (fork #", 1)
        number = suffix[:-1]
        if number.isdigit():
            return f"{prefix} (fork #{int(number) + 1})"
    return f"{stripped} (fork #1)"


def _new_message_id() -> str:
    return f"msg_{uuid.uuid4().hex[:8]}"


def _new_part_id() -> str:
    return f"part_{uuid.uuid4().hex[:8]}"


def _row_message(row: dict[str, Any], message_id: str) -> Message:
    info = row.get("info") if isinstance(row, dict) else None
    parts = row.get("parts") if isinstance(row, dict) else None
    role = str(info.get("role") if isinstance(info, dict) else "assistant")
    text = ""
    if isinstance(parts, list):
        text = "".join(
            str(part.get("text", ""))
            for part in parts
            if isinstance(part, dict) and part.get("type") == "text"
        )
    if not text and isinstance(info, dict):
        text = str(info.get("id", ""))

    category = MessageCategory.DIALOG
    if role == "system":
        category = MessageCategory.SYSTEM
    elif role == "tool":
        category = MessageCategory.SYSTEM_OUTPUT

    timestamp_ms = 0
    if isinstance(info, dict):
        time_data = info.get("time")
        if isinstance(time_data, dict) and isinstance(time_data.get("created"), int):
            timestamp_ms = int(time_data["created"])

    timestamp = (
        datetime.fromtimestamp(timestamp_ms / 1000).isoformat()
        if timestamp_ms > 0
        else datetime.now().isoformat()
    )

    return Message(
        id=message_id,
        role=role,
        content=text,
        category=category,
        timestamp=timestamp,
        metadata={
            "opencode_info": copy.deepcopy(info) if isinstance(info, dict) else {}
        },
    )


def fork_session(
    core: Any,
    session_id: str,
    *,
    message_id: str | None = None,
    directory: str | None = None,
) -> Optional[dict[str, Any]]:
    """Clone one session into a new session up to an optional message boundary."""
    source, manager = _find_session(core, session_id)
    if source is None or manager is None:
        return None

    rows = get_session_messages(core, session_id)
    if rows is None:
        return None

    selected: list[dict[str, Any]] = []
    for row in rows:
        info = row.get("info") if isinstance(row, dict) else None
        row_id = info.get("id") if isinstance(info, dict) else None
        if isinstance(message_id, str) and message_id.strip() and row_id == message_id:
            break
        selected.append(row)

    session = manager.create_session()
    metadata = session.metadata if isinstance(session.metadata, dict) else {}
    session.metadata = metadata

    source_metadata = source.metadata if isinstance(source.metadata, dict) else {}
    source_title = str(
        source_metadata.get("title")
        or _build_session_info(core, source, manager)["title"]
    )
    metadata["title"] = _fork_title(source_title)
    metadata["forked_from_session_id"] = str(session_id)
    if isinstance(message_id, str) and message_id.strip():
        metadata["forked_from_message_id"] = message_id.strip()

    source_directory = directory or _session_directory(core, source)
    if isinstance(source_directory, str) and source_directory.strip():
        metadata["directory"] = source_directory.strip()

    permission = source_metadata.get("permission")
    if isinstance(permission, list):
        metadata["permission"] = copy.deepcopy(permission)

    agent_mode = _normalize_agent_mode(
        source_metadata.get(AGENT_MODE_KEY) or source_metadata.get("agent_mode")
    )
    if agent_mode:
        metadata[AGENT_MODE_KEY] = agent_mode

    id_map: dict[str, str] = {}
    transcript_messages: dict[str, dict[str, Any]] = {}
    transcript_order: list[str] = []

    for row in selected:
        info = row.get("info") if isinstance(row, dict) else None
        if not isinstance(info, dict):
            continue

        old_id = str(info.get("id") or "")
        if not old_id:
            continue
        new_id = _new_message_id()
        id_map[old_id] = new_id
        transcript_order.append(new_id)

        new_info = copy.deepcopy(info)
        new_info["id"] = new_id
        new_info["sessionID"] = session.id
        parent_id = new_info.get("parentID")
        if isinstance(parent_id, str) and parent_id in id_map:
            new_info["parentID"] = id_map[parent_id]

        parts = row.get("parts") if isinstance(row, dict) else None
        part_order: list[str] = []
        parts_map: dict[str, dict[str, Any]] = {}
        if isinstance(parts, list):
            for part in parts:
                if not isinstance(part, dict):
                    continue
                new_part = copy.deepcopy(part)
                new_part_id = _new_part_id()
                new_part["id"] = new_part_id
                new_part["sessionID"] = session.id
                new_part["messageID"] = new_id
                part_order.append(new_part_id)
                parts_map[new_part_id] = new_part

        transcript_messages[new_id] = {
            "info": new_info,
            "part_order": part_order,
            "parts": parts_map,
        }

    metadata[TRANSCRIPT_KEY] = {
        "order": transcript_order,
        "messages": transcript_messages,
    }

    legacy_source = getattr(source, "messages", [])
    source_by_id = {
        str(message.id): message
        for message in legacy_source
        if isinstance(message, Message)
    }
    cloned_messages: list[Message] = []
    for row in selected:
        info = row.get("info") if isinstance(row, dict) else None
        old_id = str(info.get("id") or "") if isinstance(info, dict) else ""
        new_id = id_map.get(old_id)
        if not new_id:
            continue
        source_message = source_by_id.get(old_id)
        if source_message is not None:
            cloned = copy.deepcopy(source_message)
            cloned.id = new_id
            cloned_messages.append(cloned)
            continue
        cloned_messages.append(_row_message(row, new_id))

    session.messages = cloned_messages
    manager.mark_session_modified(session.id)
    manager.save_session(session)

    session_dirs = getattr(core, "_opencode_session_directories", None)
    if (
        isinstance(session_dirs, dict)
        and isinstance(source_directory, str)
        and source_directory.strip()
    ):
        session_dirs[session.id] = source_directory.strip()

    return _build_session_info(core, session, manager)
