"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

import asyncio
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from fastapi import APIRouter, Query
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
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
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
                    return

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
                        return
                    if (
                        not session_directory
                        and event_directory
                        and not directory_matches(event_directory, effective_directory)
                    ):
                        return
                    if (
                        not session_directory
                        and not event_directory
                        and event_name in GLOBAL_STATUS_EVENTS
                    ):
                        return
                else:
                    if event_directory and not directory_matches(
                        event_directory, effective_directory
                    ):
                        return
                    if not event_directory and event_name in GLOBAL_STATUS_EVENTS:
                        # These are intentionally global status events. Dropping them when a directory
                        # filter is present makes SSE look dead even though the runtime emitted a valid event.
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
                    return

            try:
                queue.put_nowait(normalized)
            except asyncio.QueueFull:
                # Drop event if queue is full (client is slow)
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

            # Stream events
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
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


@router.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "penguin-sse"}
