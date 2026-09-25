"""View-only lookup of persisted Penguin conversation JSON files.

The archive, not SessionManager's mutable session cache/index, is the source of
truth. In particular, load_session can change current_session and restore backups.
"""

from __future__ import annotations

import json
import os
import stat
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Iterator


_MAX_RESULTS = 30
_MAX_MESSAGES = 30
_MAX_TEXT = 4000
_MAX_SESSION_BYTES = 16 * 1024 * 1024


def _session_files(root: Path, agent_id: str | None = None) -> Iterator[tuple[str | None, Path]]:
    """Yield root/child session candidates without following listed symlinks.

    Args:
        root: Archive conversations directory.
        agent_id: Optional child-agent directory name.

    Yields:
        Agent name (or None) and candidate JSON file path.

    Raises:
        ValueError: If the agent identifier is invalid.
    """
    if agent_id == "":
        agent_id = None  # Optional native-tool string fields can arrive empty.
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
    """Read bounded JSON through no-follow directory and file descriptors.

    Args:
        root: Configured archive directory.
        path: Candidate root or direct-child session path.

    Returns:
        Valid session data (if any) and whether the file exceeded the size cap.
    """
    nofollow = getattr(os, "O_NOFOLLOW", None)
    directory_flag = getattr(os, "O_DIRECTORY", None)
    if nofollow is None or directory_flag is None:
        return None, False  # Fail closed without descriptor-based containment.
    try:
        parts = path.relative_to(root).parts
    except ValueError:
        return None, False
    if (
        len(parts) not in (1, 2)
        or any(part in (".", "..") for part in parts)
        or not parts[-1].endswith(".json")
        or parts[-1] == "session_index.json"
    ):
        return None, False
    try:
        with ExitStack() as stack:
            # Open every ancestor by descriptor too: a replaced workspace parent
            # must not make an otherwise safe root pathname point elsewhere.
            directory = os.open(root.anchor, os.O_RDONLY | directory_flag | nofollow)
            stack.callback(os.close, directory)
            for component in root.parts[1:]:
                directory = os.open(
                    component, os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=directory,
                )
                stack.callback(os.close, directory)
            if len(parts) == 2:
                directory = os.open(
                    parts[0], os.O_RDONLY | directory_flag | nofollow,
                    dir_fd=directory,
                )
                stack.callback(os.close, directory)
            # A replaced FIFO must not block before fstat can reject it.
            fd = os.open(
                parts[-1], os.O_RDONLY | nofollow | os.O_NONBLOCK,
                dir_fd=directory,
            )
            stack.callback(os.close, fd)
            if not stat.S_ISREG(os.fstat(fd).st_mode):
                return None, False
            raw = bytearray()
            while len(raw) <= _MAX_SESSION_BYTES:
                chunk = os.read(fd, _MAX_SESSION_BYTES + 1 - len(raw))
                if not chunk:
                    break
                raw.extend(chunk)
        if len(raw) > _MAX_SESSION_BYTES:
            return None, True
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("messages"), list) and data.get("id", path.stem) == path.stem:
            return data, False
    except (OSError, ValueError, UnicodeError):
        pass
    return None, False


def _text(content: Any) -> str:
    """Extract text from a persisted message's content."""
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
    """Clamp an optional numeric argument to a positive upper bound."""
    try:
        return min(max(int(value), 1), maximum)
    except (ValueError, TypeError):
        return default


def _matches(root: Path, session_id: str, agent_id: str | None) -> Iterator[tuple[str | None, Path]]:
    """Yield candidates for a validated session identifier.

    Raises:
        ValueError: If the session or agent identifier is invalid.
    """
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
    """Find bounded dialog excerpts without switching active sessions.

    Args:
        workspace: Configured workspace path.
        query: Literal text to find in dialog messages.
        limit: Maximum number of excerpts to return (clamped to 30).
        agent_id: Optional direct child-agent directory name.
        session_id: Optional session identifier to narrow the search.
        case_sensitive: Whether to match exact case.

    Returns:
        Excerpts, result truncation status and number of oversized files.

    Raises:
        ValueError: If query or either identifier is invalid.
    """
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
    """Read a bounded slice of one session without switching active sessions.

    Args:
        workspace: Configured workspace path.
        session_id: Session identifier returned by search.
        agent_id: Optional direct child-agent directory name.
        message_start: Zero-based first message index.
        limit: Maximum number of messages to return (clamped to 30).

    Returns:
        Session metadata and bounded dialog messages, or a structured error.

    Raises:
        ValueError: If either identifier or the starting index is invalid.
    """
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
