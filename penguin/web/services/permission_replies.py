"""Session ownership for permission replies.

A pending permission request belongs to the session that raised it. Every
reply surface calls :func:`authorize_permission_reply` before it resolves a
request, so a reply that names another session cannot approve or deny it.

The session is a claim made by the client (body ``sessionID`` /
``session_id`` or the ``X-Penguin-Session-Id`` header), not an identity the
server authenticates: every client of one server shares its credential. The
check stops a client from answering a request it was never shown; it does not
defend against a client that holds the credential and lies.
"""

from __future__ import annotations

import os
from typing import Any

__all__ = [
    "REQUIRE_SESSION_ENV",
    "PermissionReplyRefused",
    "authorize_permission_reply",
    "reply_session_required",
]

# When true, a reply that names no session is refused. Off by default so
# clients that predate the check keep working; a named session is always
# checked.
REQUIRE_SESSION_ENV = "PENGUIN_PERMISSION_REPLY_REQUIRE_SESSION"


class PermissionReplyRefused(PermissionError):
    """A reply may not resolve this request; ``status_code`` is the HTTP answer."""

    def __init__(self, message: str, *, status_code: int) -> None:
        super().__init__(message)
        self.status_code = status_code


def reply_session_required() -> bool:
    """Return whether a reply must name its session."""
    return os.environ.get(REQUIRE_SESSION_ENV, "").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _claimed_session(*candidates: Any) -> str | None:
    """Return the first non-empty session id among the reply's sources."""
    for candidate in candidates:
        if isinstance(candidate, str) and candidate.strip():
            return candidate.strip()
    return None


def authorize_permission_reply(request: Any, *claimed_sessions: Any) -> None:
    """Refuse a reply that does not come from the request's own session.

    Args:
        request: The approval request about to be resolved, or ``None`` when
            the id is unknown (the caller reports that itself).
        claimed_sessions: The reply's session id from each place a client may
            put it; non-string and empty values are ignored.

    Raises:
        PermissionReplyRefused: 403 when the reply names a different session;
            400 when it names none and the server requires one.
    """
    if request is None:
        return
    owner = getattr(request, "session_id", None)
    claimed = _claimed_session(*claimed_sessions)
    if claimed is None:
        if owner and reply_session_required():
            raise PermissionReplyRefused(
                "This permission request belongs to a session; the reply must "
                "name it (sessionID).",
                status_code=400,
            )
        return
    if owner and claimed != owner:
        raise PermissionReplyRefused(
            "This permission request belongs to another session.",
            status_code=403,
        )
