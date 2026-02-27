"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

import asyncio
import json
from pathlib import Path
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

if TYPE_CHECKING:
    from penguin.core import PenguinCore

router = APIRouter()

# Global reference to core instance (set by app.py)
_core_instance: Optional["PenguinCore"] = None


def _normalize_directory(directory: Optional[str]) -> Optional[str]:
    if not isinstance(directory, str) or not directory.strip():
        return None
    try:
        resolved = Path(directory).expanduser().resolve()
    except Exception:
        return None
    return str(resolved)


def _directory_matches(left: Optional[str], right: Optional[str]) -> bool:
    left_norm = _normalize_directory(left)
    right_norm = _normalize_directory(right)
    if not left_norm or not right_norm:
        return False
    if left_norm == right_norm:
        return True
    try:
        return Path(left_norm).samefile(right_norm)
    except Exception:
        return False


def _extract_event_session(properties: dict[str, Any]) -> Optional[str]:
    event_session = (
        properties.get("sessionID")
        or properties.get("conversation_id")
        or properties.get("session_id")
    )
    if isinstance(event_session, str) and event_session:
        return event_session

    part = properties.get("part")
    if isinstance(part, dict):
        part_session = (
            part.get("sessionID")
            or part.get("conversation_id")
            or part.get("session_id")
        )
        if isinstance(part_session, str) and part_session:
            return part_session

    info = properties.get("info")
    if isinstance(info, dict):
        info_session = (
            info.get("sessionID")
            or info.get("conversation_id")
            or info.get("session_id")
        )
        if isinstance(info_session, str) and info_session:
            return info_session
    return None


def _extract_event_directory(properties: dict[str, Any]) -> Optional[str]:
    direct = properties.get("directory")
    if isinstance(direct, str) and direct:
        return direct

    info = properties.get("info")
    if isinstance(info, dict):
        info_directory = info.get("directory")
        if isinstance(info_directory, str) and info_directory:
            return info_directory
        info_path = info.get("path")
        if isinstance(info_path, dict):
            info_cwd = info_path.get("cwd")
            if isinstance(info_cwd, str) and info_cwd:
                return info_cwd

    path_info = properties.get("path")
    if isinstance(path_info, dict):
        path_cwd = path_info.get("cwd")
        if isinstance(path_cwd, str) and path_cwd:
            return path_cwd

    part = properties.get("part")
    if isinstance(part, dict):
        part_directory = part.get("directory")
        if isinstance(part_directory, str) and part_directory:
            return part_directory
    return None


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
    effective_directory = _normalize_directory(directory)

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

        def event_handler(event_type: str, data: Any):
            """Handler for EventBus events."""
            # Only handle opencode_event type
            if event_type != "opencode_event":
                return

            # Data should already be in OpenCode format
            if not isinstance(data, dict):
                return

            props = data.get("properties", {})
            if not isinstance(props, dict):
                props = {}

            event_name = data.get("type")
            event_session = _extract_event_session(props)
            event_directory = _normalize_directory(_extract_event_directory(props))

            # Filter by session_id if provided
            if effective_session_id:
                global_events = {
                    "vcs.branch.updated",
                    "lsp.updated",
                    "lsp.client.diagnostics",
                }
                if event_session == effective_session_id:
                    pass
                elif event_name in global_events and not event_session:
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

                    if session_directory and not _directory_matches(
                        session_directory, effective_directory
                    ):
                        return
                    if (
                        not session_directory
                        and event_directory
                        and not _directory_matches(event_directory, effective_directory)
                    ):
                        return
                    if (
                        not session_directory
                        and not event_directory
                        and event_name
                        in {
                            "lsp.updated",
                            "lsp.client.diagnostics",
                            "vcs.branch.updated",
                        }
                    ):
                        return
                else:
                    if event_directory and not _directory_matches(
                        event_directory, effective_directory
                    ):
                        return
                    if not event_directory and event_name in {
                        "lsp.updated",
                        "lsp.client.diagnostics",
                        "vcs.branch.updated",
                    }:
                        return

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
                queue.put_nowait(data)
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
            yield f"data: {json.dumps(connected_event)}\n\n"

            # Stream events
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                    yield f"data: {json.dumps(event)}\n\n"
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
