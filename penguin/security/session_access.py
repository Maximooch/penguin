"""User-selected access modes for local sessions in this backend process."""

from __future__ import annotations

import logging
from threading import RLock
from typing import Any, Literal

logger = logging.getLogger(__name__)

AccessMode = Literal["workspace", "full_access"]
_full_access_sessions: set[str] = set()
_lock = RLock()


def get_session_access(session_id: str) -> AccessMode:
    """Read a session's access mode; new sessions start in workspace mode."""
    with _lock:
        return "full_access" if session_id in _full_access_sessions else "workspace"


def set_session_access(session_id: str, mode: AccessMode) -> None:
    """Change only the selected session's mode, until the backend exits."""
    if not session_id:
        raise ValueError("A session ID is required")
    if mode not in {"workspace", "full_access"}:
        raise ValueError("Access mode must be workspace or full_access")
    with _lock:
        if mode == "full_access":
            _full_access_sessions.add(session_id)
        else:
            _full_access_sessions.discard(session_id)
    logger.info("Session access changed: session=%s mode=%s", session_id, mode)


def apply_session_access(context: dict[str, Any]) -> dict[str, Any]:
    """Apply local access without replacing an external execution policy."""
    result = dict(context)
    # Remove our earlier overlay before re-reading a setting changed mid-turn.
    if result.pop("_session_access_override", False):
        if result.get("permission_mode") == "full_access":
            result.pop("permission_mode", None)
    if result.get("permission_mode") or result.get("approval_policy") is not None:
        return result
    session_id = result.get("session_id") or result.get("conversation_id")
    if session_id and get_session_access(session_id) == "full_access":
        result["permission_mode"] = "full_access"
        result["_session_access_override"] = True
    return result


__all__ = [
    "AccessMode",
    "apply_session_access",
    "get_session_access",
    "set_session_access",
]
