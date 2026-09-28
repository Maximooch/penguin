"""Local session access settings exposed by the TUI."""

from __future__ import annotations

from typing import Any

from fastapi import HTTPException

from penguin.security.approval import get_approval_manager
from penguin.security.session_access import (
    AccessMode,
    get_session_access,
    set_session_access,
)
from penguin.web.services.session_view import get_session_info


def get_access_settings(core: Any, session_id: str) -> dict[str, str]:
    """Return settings only for a session that exists."""
    if get_session_info(core, session_id) is None:
        raise HTTPException(status_code=404, detail="Session not found")
    return {"session_id": session_id, "mode": get_session_access(session_id)}


def update_access_settings(
    core: Any, session_id: str, mode: AccessMode
) -> dict[str, str]:
    """Update access and release local pending calls when full access is selected."""
    get_access_settings(core, session_id)
    set_session_access(session_id, mode)
    manager = get_approval_manager()
    if mode == "full_access":
        for request in manager.get_pending(session_id):
            if request.context.get("can_enable_full_access") is True:
                manager.approve(request.id)
    else:
        manager.clear_session_approvals(session_id)
    return get_access_settings(core, session_id)


__all__ = ["get_access_settings", "update_access_settings"]
