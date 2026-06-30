"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

import asyncio
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from penguin.web.services.opencode_events import (
    GLOBAL_STATUS_EVENTS,
    directory_matches,
    extract_event_directory,
    extract_event_session,
    normalize_directory,
    normalize_opencode_event,
    sse_event_frame,
)

if TYPE_CHECKING:
    from penguin.core import PenguinCore

router = APIRouter()
_REPLAY_BUFFER_ATTR = "_opencode_sse_replay_v1"
# Bounded compatibility buffer until Phase 11.5 lands the durable runtime event
# ledger. It covers short reconnects only; gaps are surfaced to clients instead
# of being silently ignored. Do not treat this route-local memory as durable
# event truth; the ledger should own replay, retention, drop logging, and policy.
_MAX_REPLAY_EVENTS = 1000
# Temporary per-connection delivery limits for the compatibility SSE projection.
# Phase 11.5 should promote these to named policy/config values with metrics for
# slow-client drops once the ledger can remain the source of replay truth.
_SSE_QUEUE_MAX_EVENTS = 1000
_SSE_KEEPALIVE_TIMEOUT_SECONDS = 300.0

# Global reference to core instance (set by app.py)
_core_instance: Optional["PenguinCore"] = None


def set_core_instance(core: "PenguinCore"):
    """Set the core instance for dependency injection."""
    global _core_instance
    _core_instance = core


def get_core_instance() -> "PenguinCore":
    """Get the core instance."""
    if _core_instance is None:
        raise RuntimeError("Core instance not set - call set_core_instance() first")
    return _core_instance


@router.get("/api/v1/events/sse")
async def events_sse(
    session_id: Optional[str] = Query(None, description="Filter to specific session"),
    conversation_id: Optional[str] = Query(
        None, description="Alias for session_id (API compatibility)"
    ),
    agent_id: Optional[str] = Query(None, description="Filter to specific agent"),
    directory: Optional[str] = Query(None, description="Workspace directory"),
    last_event_id: Optional[str] = Query(
        None,
        description="Replay buffered events after this SSE id",
    ),
    last_event_id_header: Optional[str] = Header(None, alias="Last-Event-ID"),
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
        # before replay drains. The set is intentionally per connection and
        # should disappear when Phase 11.5 moves replay/dedupe to the ledger.
        queued_live_event_ids: set[str] = set()
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

            try:
                _remember_replay_event(core, normalized)
                queue.put_nowait(normalized)
                event_id = normalized.get("id")
                if isinstance(event_id, str):
                    queued_live_event_ids.add(event_id)
            except asyncio.QueueFull:
                # Drop event if queue is full (client is slow). Phase 11.5 should
                # add ledger-backed recovery plus logging/metrics for this path.
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
                replay_found, replay_events = _replay_events_after(
                    core,
                    effective_last_event_id,
                )
                if not replay_found:
                    gap_event = next_event(
                        _replay_gap_event(core, effective_last_event_id)
                    )
                    if gap_event and event_allowed(gap_event):
                        yield sse_event_frame(gap_event)
                for event in replay_events:
                    event_id = event.get("id")
                    if isinstance(event_id, str) and event_id in queued_live_event_ids:
                        continue
                    if event_allowed(event):
                        yield sse_event_frame(event)

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


def _replay_buffer(core: Any) -> list[dict[str, Any]]:
    # Phase 11 bridge only: keep the compatibility buffer attached to the shared
    # core so reconnects can replay across SSE connections. Move this behind a
    # ledger/service boundary when durable runtime events land in Phase 11.5.
    existing = getattr(core, _REPLAY_BUFFER_ATTR, None)
    if isinstance(existing, list):
        return existing
    buffer: list[dict[str, Any]] = []
    setattr(core, _REPLAY_BUFFER_ATTR, buffer)
    return buffer


def _remember_replay_event(core: Any, event: dict[str, Any]) -> None:
    event_id = event.get("id")
    if not isinstance(event_id, str) or not event_id:
        return
    buffer = _replay_buffer(core)
    if any(item.get("id") == event_id for item in buffer):
        return
    buffer.append(event)
    if len(buffer) > _MAX_REPLAY_EVENTS:
        del buffer[: len(buffer) - _MAX_REPLAY_EVENTS]


def _replay_events_after(
    core: Any,
    last_event_id: str,
) -> tuple[bool, list[dict[str, Any]]]:
    buffer = _replay_buffer(core)
    for index, event in enumerate(buffer):
        if event.get("id") == last_event_id:
            return True, buffer[index + 1 :]
    return False, []


def _replay_gap_event(core: Any, last_event_id: str) -> dict[str, Any]:
    # Temporary transport signal, not durable runtime truth. Current EventSource
    # clients may resume from this synthetic frame's SSE id and receive another
    # gap; the eventual TUI/Link consumer should treat it as a full-resync signal
    # unless Phase 11.5 changes the frame to carry a real ledger resume cursor.
    buffer = _replay_buffer(core)
    oldest_id = buffer[0].get("id") if buffer else None
    newest_id = buffer[-1].get("id") if buffer else None
    return {
        "type": "server.replay_gap",
        "properties": {
            "lastEventID": last_event_id,
            "oldestEventID": oldest_id if isinstance(oldest_id, str) else None,
            "newestEventID": newest_id if isinstance(newest_id, str) else None,
            "reason": "last_event_id_not_available",
        },
    }


@router.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "penguin-sse"}
