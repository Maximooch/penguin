"""OpenCode-shaped session event emission helpers."""

from __future__ import annotations

import logging
from typing import Any

from penguin.system.runtime_events import wrap_opencode_event

__all__ = [
    "emit_session_created_event",
    "emit_session_deleted_event",
    "emit_session_diff_event",
    "emit_session_event",
    "emit_session_updated_event",
]

logger = logging.getLogger(__name__)


async def emit_session_event(
    core: Any,
    event_type: str,
    info: dict[str, Any],
) -> None:
    """Emit an OpenCode-shaped session lifecycle event."""
    event_bus = getattr(core, "event_bus", None)
    emit = getattr(event_bus, "emit", None)
    if not callable(emit):
        return

    session_id = info.get("id") if isinstance(info, dict) else None
    properties: dict[str, Any] = {"info": info}
    if isinstance(session_id, str) and session_id:
        properties["sessionID"] = session_id

    try:
        await emit(
            "opencode_event",
            wrap_opencode_event(
                event_type,
                properties,
                default_session_id=session_id if isinstance(session_id, str) else None,
            ),
        )
    except Exception:
        logger.debug("Failed to emit %s event", event_type, exc_info=True)


async def emit_session_created_event(core: Any, info: dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.created event."""
    await emit_session_event(core, "session.created", info)


async def emit_session_updated_event(core: Any, info: dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.updated event."""
    await emit_session_event(core, "session.updated", info)


async def emit_session_deleted_event(core: Any, info: dict[str, Any]) -> None:
    """Emit OpenCode-shaped session.deleted event."""
    await emit_session_event(core, "session.deleted", info)


async def emit_session_diff_event(
    core: Any,
    session_id: str,
    diff: list[dict[str, Any]],
) -> None:
    """Emit OpenCode-shaped session.diff event."""
    emit = getattr(getattr(core, "event_bus", None), "emit", None)
    if not callable(emit):
        return
    try:
        await emit(
            "opencode_event",
            wrap_opencode_event(
                "session.diff",
                {
                    "sessionID": session_id,
                    "diff": diff,
                },
                default_session_id=session_id,
            ),
        )
    except Exception:
        logger.debug("Failed to emit session.diff event", exc_info=True)
