"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from penguin.system.runtime_events import opencode_payload_from_runtime_event
from penguin.web.services.opencode_events import (
    GLOBAL_STATUS_EVENTS,
    directory_matches,
    extract_event_directory,
    extract_event_session,
    normalize_directory,
    normalize_opencode_event,
    record_opencode_event,
    sse_event_frame,
)

if TYPE_CHECKING:
    from penguin.core import PenguinCore

logger = logging.getLogger(__name__)
router = APIRouter()
_LEDGER_RECORDER_ATTR = "_runtime_event_ledger_recorder_v1"
# Per-connection delivery limits for the compatibility SSE projection. The
# durable runtime event ledger owns replay truth; this queue only buffers live
# delivery for a connected client. Slow-client drops are recoverable by
# reconnecting with Last-Event-ID.
_SSE_QUEUE_MAX_EVENTS = 1000
_SSE_REPLAY_PAGE_SIZE = 1000
_SSE_KEEPALIVE_TIMEOUT_SECONDS = 300.0

# Global reference to core instance (set by app.py)
_core_instance: PenguinCore | None = None


def set_core_instance(core: PenguinCore):
    """Set the core instance for dependency injection."""
    global _core_instance
    _core_instance = core
    _install_runtime_event_ledger_recorder(core)


def get_core_instance() -> PenguinCore:
    """Get the core instance."""
    if _core_instance is None:
        raise RuntimeError("Core instance not set - call set_core_instance() first")
    return _core_instance


@router.get("/api/v1/events/sse")
async def events_sse(
    session_id: str | None = Query(None, description="Filter to specific session"),
    conversation_id: str | None = Query(
        None, description="Alias for session_id (API compatibility)"
    ),
    agent_id: str | None = Query(None, description="Filter to specific agent"),
    directory: str | None = Query(None, description="Workspace directory"),
    last_event_id: str | None = Query(
        None,
        description="Replay buffered events after this SSE id",
    ),
    last_event_id_header: str | None = Header(None, alias="Last-Event-ID"),
):
    """
    SSE stream of OpenCode-compatible events.

    Query params:
    - session_id: Filter events to specific session
    - agent_id: Filter events to specific agent
    - directory: Workspace directory (for context)
    """
    core = get_core_instance()

    # Use conversation_id if session_id not provided (API compatibility)
    effective_session_id = session_id or conversation_id
    effective_agent_id = agent_id
    effective_directory = normalize_directory(directory)
    effective_last_event_id = (
        last_event_id
        if isinstance(last_event_id, str) and last_event_id
        else last_event_id_header
        if isinstance(last_event_id_header, str) and last_event_id_header
        else None
    )

    if effective_session_id and directory:
        session_dirs = getattr(core, "_opencode_session_directories", None)
        if not isinstance(session_dirs, dict):
            session_dirs = {}
            setattr(core, "_opencode_session_directories", session_dirs)
        resolved = effective_directory or directory
        existing = session_dirs.get(effective_session_id)
        if not existing:
            session_dirs[effective_session_id] = resolved

    async def event_generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=_SSE_QUEUE_MAX_EVENTS)
        # Reconnect-only dedupe bridge: events can arrive after subscription but
        # before replay drains. The set is intentionally per connection; durable
        # replay identity comes from the runtime event ledger.
        queued_live_event_ids: set[str] = set()
        delivered_event_ids: set[str] = set()
        event_order = 0

        def next_event(data: dict[str, Any]) -> dict[str, Any] | None:
            nonlocal event_order
            event_order += 1
            return normalize_opencode_event(
                data,
                order=event_order,
                default_agent_id=effective_agent_id,
                default_directory=effective_directory or directory,
                default_session_id=effective_session_id,
            )

        def event_allowed(normalized: dict[str, Any]) -> bool:
            props = normalized.get("properties", {})
            if not isinstance(props, dict):
                props = {}

            event_name = normalized.get("type")
            event_session = extract_event_session(props)
            event_directory = normalize_directory(extract_event_directory(props))

            # Filter by session_id if provided
            if effective_session_id:
                if event_session == effective_session_id:
                    pass
                elif event_name in GLOBAL_STATUS_EVENTS and not event_session:
                    # Global status event without a session association
                    pass
                else:
                    return False

            if effective_directory:
                if event_session:
                    session_dirs = getattr(core, "_opencode_session_directories", None)
                    session_directory = (
                        session_dirs.get(event_session)
                        if isinstance(session_dirs, dict)
                        else None
                    )
                    if not isinstance(session_directory, str) or not session_directory:
                        try:
                            from penguin.web.services.session_view import (
                                get_session_info,
                            )

                            info = get_session_info(core, event_session)
                            maybe_directory = (
                                info.get("directory")
                                if isinstance(info, dict)
                                else None
                            )
                            if isinstance(session_dirs, dict) and isinstance(
                                maybe_directory, str
                            ):
                                session_dirs[event_session] = maybe_directory
                            session_directory = maybe_directory
                        except Exception:
                            session_directory = None

                    if session_directory and not directory_matches(
                        session_directory, effective_directory
                    ):
                        return False
                    if (
                        not session_directory
                        and event_directory
                        and not directory_matches(event_directory, effective_directory)
                    ):
                        return False
                    if (
                        not session_directory
                        and not event_directory
                        and event_name in GLOBAL_STATUS_EVENTS
                    ):
                        return False
                else:
                    if event_directory and not directory_matches(
                        event_directory, effective_directory
                    ):
                        return False
                    if not event_directory and event_name in GLOBAL_STATUS_EVENTS:
                        # These global status events are intentionally unscoped.
                        # Dropping them under a directory filter makes SSE look dead.
                        pass

            # Filter by agent_id if provided (check multiple possible fields)
            if effective_agent_id:
                event_agent = props.get("agentID") or props.get("agent_id")
                # Also check nested part if present
                if not event_agent and isinstance(props.get("part"), dict):
                    nested_part = props["part"]
                    event_agent = nested_part.get("agentID") or nested_part.get(
                        "agent_id"
                    )
                if event_agent and event_agent != effective_agent_id:
                    return False

            return True

        def event_handler(event_type: str, data: Any):
            """Handler for EventBus events."""
            # Only handle opencode_event type
            if event_type != "opencode_event":
                return

            # Data should already be in OpenCode format
            if not isinstance(data, dict):
                return

            normalized = next_event(data)
            if not normalized:
                return

            if not event_allowed(normalized):
                return

            normalized_id = normalized.get("id")
            if isinstance(normalized_id, str) and normalized_id in delivered_event_ids:
                return

            try:
                queue.put_nowait(normalized)
                event_id = normalized.get("id")
                if isinstance(event_id, str):
                    queued_live_event_ids.add(event_id)
            except asyncio.QueueFull:
                # Drop only this live delivery. The runtime event ledger already
                # recorded the event at emission time, so reconnect/replay remains
                # authoritative for slow clients.
                pass

        # Subscribe to events
        core.event_bus.subscribe("opencode_event", event_handler)

        try:
            # Send initial server.connected event
            connected_event = {
                "type": "server.connected",
                "properties": {
                    "sessionID": effective_session_id,
                    "agentID": effective_agent_id,
                    "directory": directory,
                },
            }
            normalized_connected = next_event(connected_event)
            if normalized_connected:
                yield sse_event_frame(normalized_connected)

            if effective_last_event_id:
                replay_cursor = effective_last_event_id
                while True:
                    replay = _replay_events_after(
                        core,
                        replay_cursor,
                        limit=_SSE_REPLAY_PAGE_SIZE,
                    )
                    if not replay.found:
                        gap_event = next_event(
                            _replay_gap_event(
                                effective_last_event_id,
                                oldest_event_id=replay.oldest_event_id,
                                newest_event_id=replay.newest_event_id,
                            )
                        )
                        if gap_event and event_allowed(gap_event):
                            yield sse_event_frame(gap_event)
                        break
                    if not replay.events:
                        break
                    for runtime_event in replay.events:
                        event = opencode_payload_from_runtime_event(runtime_event)
                        event_id = event.get("id")
                        if (
                            isinstance(event_id, str)
                            and event_id in queued_live_event_ids
                        ):
                            continue
                        if event_allowed(event):
                            if isinstance(event_id, str):
                                delivered_event_ids.add(event_id)
                            yield sse_event_frame(event)
                    next_cursor = replay.events[-1].get("id")
                    if (
                        len(replay.events) < _SSE_REPLAY_PAGE_SIZE
                        or not isinstance(next_cursor, str)
                    ):
                        break
                    replay_cursor = next_cursor

            # Stream events
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    event = await asyncio.wait_for(
                        queue.get(),
                        timeout=_SSE_KEEPALIVE_TIMEOUT_SECONDS,
                    )
                    event_id = event.get("id")
                    if isinstance(event_id, str):
                        queued_live_event_ids.discard(event_id)
                        delivered_event_ids.add(event_id)
                    yield sse_event_frame(event)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            # Always unsubscribe
            try:
                core.event_bus.unsubscribe("opencode_event", event_handler)
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        },
    )


def _install_runtime_event_ledger_recorder(core: Any) -> None:
    """Install one emission-time ledger recorder on the core EventBus."""
    if getattr(core, _LEDGER_RECORDER_ATTR, None) is not None:
        return
    event_bus = getattr(core, "event_bus", None)
    subscribe = getattr(event_bus, "subscribe", None)
    if not callable(subscribe):
        return

    def ledger_handler(event_type: str, data: Any) -> None:
        if event_type != "opencode_event" or not isinstance(data, dict):
            return
        try:
            record_opencode_event(core, data)
        except Exception:
            # Ledger failures must not interrupt live TUI streaming. The client can
            # still receive the live frame; replay will surface a gap if needed.
            logger.debug(
                "Failed to record OpenCode event in runtime ledger",
                exc_info=True,
            )

    subscribe("opencode_event", ledger_handler)
    setattr(core, _LEDGER_RECORDER_ATTR, ledger_handler)


def _replay_events_after(core: Any, last_event_id: str, *, limit: int):
    from penguin.system.runtime_event_ledger import get_runtime_event_ledger

    return get_runtime_event_ledger(core).replay_after(last_event_id, limit=limit)


def _replay_gap_event(
    last_event_id: str,
    *,
    oldest_event_id: str | None = None,
    newest_event_id: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "server.replay_gap",
        "properties": {
            "lastEventID": last_event_id,
            "oldestEventID": oldest_event_id,
            "newestEventID": newest_event_id,
            "reason": "last_event_id_not_available",
        },
    }


@router.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "penguin-sse"}
