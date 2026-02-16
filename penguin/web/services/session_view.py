"""OpenCode-shaped session and message view adapters."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from penguin import __version__

TRANSCRIPT_KEY = "_opencode_transcript_v1"


def _iso_to_ms(value: Optional[str]) -> int:
    """Convert ISO timestamp to epoch milliseconds."""
    if not value:
        return 0
    try:
        return int(datetime.fromisoformat(value).timestamp() * 1000)
    except Exception:
        return 0


def _iter_session_managers(core: Any) -> list[Any]:
    """Return unique session manager instances across default + agents."""
    conversation_manager = getattr(core, "conversation_manager", None)
    if conversation_manager is None:
        return []

    candidates: list[Any] = []
    default_manager = getattr(conversation_manager, "session_manager", None)
    if default_manager is not None:
        candidates.append(default_manager)

    agent_managers = getattr(conversation_manager, "agent_session_managers", {})
    if isinstance(agent_managers, dict):
        candidates.extend(agent_managers.values())

    unique: list[Any] = []
    seen: set[int] = set()
    for manager in candidates:
        manager_id = id(manager)
        if manager_id in seen:
            continue
        seen.add(manager_id)
        unique.append(manager)
    return unique


def _find_session(core: Any, session_id: str) -> tuple[Optional[Any], Optional[Any]]:
    """Find a session and its manager by id."""
    for manager in _iter_session_managers(core):
        cached = getattr(manager, "sessions", {})
        if isinstance(cached, dict) and session_id in cached:
            return cached[session_id][0], manager

        index = getattr(manager, "session_index", {})
        if isinstance(index, dict) and session_id in index:
            try:
                session = manager.load_session(session_id)
            except Exception:
                session = None
            if session is not None:
                return session, manager
    return None, None


def _infer_title(session: Any) -> str:
    """Derive a usable title for a session."""
    metadata = getattr(session, "metadata", {})
    if isinstance(metadata, dict) and isinstance(metadata.get("title"), str):
        title = metadata["title"].strip()
        if title:
            return title

    messages = getattr(session, "messages", [])
    for item in messages:
        if getattr(item, "role", None) != "user":
            continue
        content = getattr(item, "content", "")
        if isinstance(content, str):
            line = content.split("\n", 1)[0].strip()
            if line:
                return line[:64]
    return f"Session {str(getattr(session, 'id', 'unknown'))[-8:]}"


def _build_session_info(core: Any, session: Any, manager: Any) -> dict[str, Any]:
    """Build OpenCode-compatible Session.Info payload."""
    runtime = getattr(core, "runtime_config", None)
    runtime_dir = getattr(runtime, "active_root", None) or getattr(
        runtime, "project_root", None
    )
    metadata = getattr(session, "metadata", {})

    directory = ""
    if isinstance(metadata, dict) and isinstance(metadata.get("directory"), str):
        directory = metadata["directory"]
    if not directory and runtime_dir:
        directory = str(runtime_dir)
    if not directory:
        directory = str(Path.cwd())

    created = _iso_to_ms(getattr(session, "created_at", None))
    updated = _iso_to_ms(getattr(session, "last_active", None))
    now = int(datetime.now().timestamp() * 1000)

    if created <= 0:
        created = now
    if updated <= 0:
        updated = created

    return {
        "id": str(session.id),
        "slug": str(session.id),
        "projectID": "penguin",
        "directory": directory,
        "title": _infer_title(session),
        "version": __version__,
        "time": {
            "created": created,
            "updated": updated,
        },
    }


def list_session_infos(
    core: Any,
    *,
    start: Optional[int] = None,
    search: Optional[str] = None,
    limit: Optional[int] = None,
    directory: Optional[str] = None,
    roots: bool = False,
) -> list[dict[str, Any]]:
    """List sessions in OpenCode Session.Info shape."""
    results: list[dict[str, Any]] = []
    lowered_search = search.lower() if search else None

    for manager in _iter_session_managers(core):
        index = getattr(manager, "session_index", {})
        if not isinstance(index, dict):
            continue

        for session_id in index:
            session = None
            cached = getattr(manager, "sessions", {})
            if isinstance(cached, dict) and session_id in cached:
                session = cached[session_id][0]
            if session is None:
                try:
                    session = manager.load_session(session_id)
                except Exception:
                    session = None
            if session is None:
                continue

            info = _build_session_info(core, session, manager)

            if roots and info.get("parentID"):
                continue
            if directory and info.get("directory") != directory:
                continue
            if start is not None and info["time"]["updated"] < start:
                continue
            if lowered_search and lowered_search not in info["title"].lower():
                continue

            results.append(info)

    results.sort(key=lambda item: item["time"]["updated"], reverse=True)
    if limit is not None and limit > 0:
        return results[:limit]
    return results


def get_session_info(core: Any, session_id: str) -> Optional[dict[str, Any]]:
    """Return one session in OpenCode Session.Info shape."""
    session, manager = _find_session(core, session_id)
    if session is None or manager is None:
        return None
    return _build_session_info(core, session, manager)


def _default_assistant_info(
    core: Any, session_id: str, message_id: str
) -> dict[str, Any]:
    """Build a minimal valid assistant info envelope."""
    now = int(datetime.now().timestamp() * 1000)
    cwd = str(Path.cwd())
    return {
        "id": message_id,
        "sessionID": session_id,
        "role": "assistant",
        "time": {"created": now},
        "parentID": "root",
        "modelID": getattr(
            getattr(core, "model_config", None), "model", "penguin-default"
        ),
        "providerID": getattr(
            getattr(core, "model_config", None), "provider", "penguin"
        ),
        "mode": "chat",
        "agent": "default",
        "path": {"cwd": cwd, "root": cwd},
        "cost": 0,
        "tokens": {
            "input": 0,
            "output": 0,
            "reasoning": 0,
            "cache": {"read": 0, "write": 0},
        },
    }


def _legacy_message_to_with_parts(
    core: Any, session: Any, message: Any
) -> dict[str, Any]:
    """Project legacy Penguin message into OpenCode MessageV2.WithParts."""
    session_id = str(session.id)
    message_id = str(getattr(message, "id", ""))
    role = getattr(message, "role", "assistant")
    created = _iso_to_ms(getattr(message, "timestamp", None))
    created = created or int(datetime.now().timestamp() * 1000)
    content = getattr(message, "content", "")
    text = content if isinstance(content, str) else str(content)

    if role == "user":
        info = {
            "id": message_id,
            "sessionID": session_id,
            "role": "user",
            "time": {"created": created},
            "agent": getattr(message, "agent_id", None) or "default",
            "model": {
                "providerID": getattr(
                    getattr(core, "model_config", None), "provider", "penguin"
                ),
                "modelID": getattr(
                    getattr(core, "model_config", None), "model", "penguin-default"
                ),
            },
        }
    else:
        info = _default_assistant_info(core, session_id, message_id)
        info["time"] = {"created": created, "completed": created}

    part = {
        "id": f"part_{message_id}_0",
        "sessionID": session_id,
        "messageID": message_id,
        "type": "text",
        "text": text,
    }
    return {"info": info, "parts": [part]}


def get_session_messages(
    core: Any, session_id: str, *, limit: Optional[int] = None
) -> Optional[list[dict[str, Any]]]:
    """Return OpenCode MessageV2.WithParts[] for a session."""
    session, _manager = _find_session(core, session_id)
    if session is None:
        return None

    metadata = getattr(session, "metadata", {})
    transcript = metadata.get(TRANSCRIPT_KEY) if isinstance(metadata, dict) else None
    rows: list[dict[str, Any]] = []

    if isinstance(transcript, dict):
        messages = transcript.get("messages")
        order = transcript.get("order")
        if isinstance(messages, dict) and isinstance(order, list):
            for message_id in order:
                entry = messages.get(message_id)
                if not isinstance(entry, dict):
                    continue
                info = entry.get("info")
                if not isinstance(info, dict):
                    info = _default_assistant_info(core, session_id, str(message_id))

                parts_map = entry.get("parts")
                part_order = entry.get("part_order")
                parts: list[dict[str, Any]] = []
                if isinstance(parts_map, dict) and isinstance(part_order, list):
                    for part_id in part_order:
                        part = parts_map.get(part_id)
                        if isinstance(part, dict):
                            parts.append(part)
                if parts:
                    rows.append({"info": info, "parts": parts})

    if not rows:
        for message in getattr(session, "messages", []):
            role = getattr(message, "role", "")
            if role not in {"user", "assistant", "tool"}:
                continue
            rows.append(_legacy_message_to_with_parts(core, session, message))

    if limit is not None and limit > 0:
        return rows[-limit:]
    return rows
