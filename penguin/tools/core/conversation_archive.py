"""View-only lookup of persisted Penguin conversation JSON files.

The archive, not SessionManager's mutable session cache/index, is the source of
truth. In particular, load_session can change current_session and restore backups.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterator


_MAX_RESULTS = 30
_MAX_MESSAGES = 30
_MAX_TEXT = 4000
_MAX_SESSION_BYTES = 16 * 1024 * 1024


def _within(path: Path, root: Path) -> bool:
    return path.is_relative_to(root)  # resolved paths, Python >= 3.9


def _session_files(root: Path, agent_id: str | None = None) -> Iterator[tuple[str | None, Path]]:
    """Only root sessions and direct child agent sessions; never follow symlinks."""
    if agent_id is not None and (
        not isinstance(agent_id, str) or not agent_id or agent_id in (".", "..")
        or Path(agent_id).name != agent_id or "\\" in agent_id
    ):
        raise ValueError("Invalid agent_id")
    if not root.is_dir() or root.is_symlink():
        return
    directories = [(None, root)] if agent_id is None else []
    if agent_id is None:
        directories.extend(
            (child.name, child) for child in root.iterdir()
            if child.is_dir() and not child.is_symlink()
        )
    else:
        child = root / agent_id
        if child.is_dir() and not child.is_symlink():
            directories = [(agent_id, child)]
        else:
            directories = []
    for agent, directory in directories:
        for path in directory.glob("*.json"):
            if path.name != "session_index.json" and not path.is_symlink() and path.is_file():
                yield agent, path


def _read(root: Path, path: Path) -> tuple[dict[str, Any] | None, bool]:
    # Re-check containment immediately before opening; never read arbitrary paths.
    if root.is_symlink() or path.is_symlink() or not _within(path.resolve(), root.resolve()):
        return None, False
    try:
        with path.open("rb") as handle:
            raw = handle.read(_MAX_SESSION_BYTES + 1)
        if len(raw) > _MAX_SESSION_BYTES:
            return None, True
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("messages"), list) and data.get("id", path.stem) == path.stem:
            return data, False
    except (OSError, ValueError, UnicodeError):
        pass
    return None, False


def _text(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "\n".join(
            part.get("text", "") for part in content
            if isinstance(part, dict) and isinstance(part.get("text"), str)
        )
    if isinstance(content, dict):
        return content.get("text", "") if isinstance(content.get("text"), str) else ""
    return ""


def _bounded(value: Any, maximum: int, default: int) -> int:
    try:
        return min(max(int(value), 1), maximum)
    except (ValueError, TypeError):
        return default


def _matches(root: Path, session_id: str, agent_id: str | None) -> Iterator[tuple[str | None, Path]]:
    if not isinstance(session_id, str) or not session_id or Path(session_id).name != session_id or "\\" in session_id or session_id in (".", "..") or session_id == "session_index":
        raise ValueError("Invalid session_id")
    for agent, path in _session_files(root, agent_id):
        if path.stem == session_id:
            yield agent, path


def search(
    workspace: str | Path,
    query: str,
    limit: int = 10,
    agent_id: str | None = None,
    session_id: str | None = None,
    case_sensitive: bool = False,
) -> dict[str, Any]:
    """Find bounded message excerpts; search dialog by default, not system prompts."""
    if not isinstance(query, str) or not query.strip() or len(query) > 256:
        raise ValueError("query must be 1-256 characters")
    root = Path(workspace).expanduser().resolve() / "conversations"
    files = _matches(root, session_id, agent_id) if session_id else _session_files(root, agent_id)
    # Most recently modified sessions first. Results are deterministic for a fixed archive.
    # The archive can be modified concurrently; disappearing files are skipped.
    def modified(pair: tuple[str | None, Path]) -> int:
        try:
            return -pair[1].stat().st_mtime_ns
        except OSError:
            return 0

    paths = sorted(files, key=lambda pair: (modified(pair), str(pair[1])))
    needle = query if case_sensitive else query.casefold()
    results: list[dict[str, Any]] = []
    skipped_large = 0
    for agent, path in paths:
        data, too_large = _read(root, path)
        skipped_large += too_large
        if data is None:
            continue
        for index, message in enumerate(data["messages"]):
            if not isinstance(message, dict) or message.get("role") not in ("user", "assistant") or message.get("category", "DIALOG") != "DIALOG":
                continue
            text = _text(message.get("content"))
            haystack = text if case_sensitive else text.casefold()
            offset = haystack.find(needle)
            if offset < 0:
                continue
            excerpt = text[max(0, offset - 160):offset + len(query) + 160]
            meta = data.get("metadata") or {}
            results.append({
                "session_id": path.stem,
                "agent_id": agent,
                "path": str(path),
                "message_index": index,
                "role": message["role"],
                "timestamp": message.get("timestamp"),
                "title": meta.get("title") if isinstance(meta, dict) else None,
                "excerpt": excerpt,
            })
            if len(results) >= _bounded(limit, _MAX_RESULTS, 10):
                return {"results": results, "truncated": True, "skipped_large": skipped_large}
    return {"results": results, "truncated": False, "skipped_large": skipped_large}


def open_session(
    workspace: str | Path,
    session_id: str,
    agent_id: str | None = None,
    message_start: int = 0,
    limit: int = 10,
) -> dict[str, Any]:
    """Read a bounded slice of one session, without switching active sessions."""
    root = Path(workspace).expanduser().resolve() / "conversations"
    matches = list(_matches(root, session_id, agent_id))
    if not matches:
        return {"error": "session_not_found", "session_id": session_id}
    if len(matches) > 1:
        return {"error": "ambiguous_session_id", "session_id": session_id, "agent_ids": [agent for agent, _ in matches]}
    agent, path = matches[0]
    data, too_large = _read(root, path)
    if too_large:
        return {"error": "session_too_large", "session_id": session_id,
                "max_bytes": _MAX_SESSION_BYTES}
    if data is None:
        return {"error": "unreadable_session", "session_id": session_id}
    try:
        start = max(0, int(message_start))
    except (TypeError, ValueError):
        raise ValueError("Invalid message_start") from None
    count = _bounded(limit, _MAX_MESSAGES, 10)
    messages = []
    for index in range(start, min(start + count, len(data["messages"]))):
        message = data["messages"][index]
        if not isinstance(message, dict) or message.get("category", "DIALOG") != "DIALOG" or message.get("role") not in ("user", "assistant"):
            continue
        text = _text(message.get("content"))
        messages.append({
            "message_index": index,
            "id": message.get("id"),
            "role": message.get("role"),
            "timestamp": message.get("timestamp"),
            "content": text[:_MAX_TEXT],
            "content_truncated": len(text) > _MAX_TEXT,
        })
    meta = data.get("metadata") or {}
    return {
        "session_id": path.stem,
        "agent_id": agent,
        "path": str(path),
        "title": meta.get("title") if isinstance(meta, dict) else None,
        "created_at": data.get("created_at"),
        "last_active": data.get("last_active"),
        "total_messages": len(data["messages"]),
        "message_start": start,
        "messages": messages,
    }
