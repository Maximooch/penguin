"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

from __future__ import annotations

import asyncio
import logging
import threading
from collections import deque
from typing import TYPE_CHECKING, Any, AsyncIterator

from fastapi import APIRouter, Header, Query
from fastapi.responses import StreamingResponse

from penguin.system.runtime_diagnostics import ConnectionHistory
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
_SSE_DEDUPE_MAX_EVENTS = 1000
_SSE_CONNECTION_HISTORY_MAX_ENTRIES = 64
_SSE_CONNECTION_HISTORY_ATTR = "_sse_connection_history_v1"
_SSE_CONNECTION_HISTORY_LOCK = threading.RLock()

# Global reference to core instance (set by app.py)
_core_instance: PenguinCore | None = None


def set_core_instance(core: PenguinCore):
    """Set the core instance for dependency injection."""
    global _core_instance
    _core_instance = core
    _get_or_create_connection_history(core)
    _install_runtime_event_ledger_recorder(core)


def get_core_instance() -> PenguinCore:
    """Get the core instance."""
    if _core_instance is None:
        raise RuntimeError("Core instance not set - call set_core_instance() first")
    return _core_instance


def get_sse_connection_history(
    core: Any | None = None,
) -> list[dict[str, str | float | None]]:
    """Return a bounded, content-free SSE lifecycle snapshot.

    The snapshot deliberately excludes cursor values, session identifiers,
    directories, URLs, payloads, and exception text so a later debug route can
    expose it without disclosing conversation content or credentials.
    """

    owner = core if core is not None else get_core_instance()
    return _get_or_create_connection_history(owner).snapshot()


def _get_or_create_connection_history(core: Any) -> ConnectionHistory:
    """Return the per-core connection history, creating it exactly once."""

    history = getattr(core, _SSE_CONNECTION_HISTORY_ATTR, None)
    if isinstance(history, ConnectionHistory):
        return history

    with _SSE_CONNECTION_HISTORY_LOCK:
        history = getattr(core, _SSE_CONNECTION_HISTORY_ATTR, None)
        if not isinstance(history, ConnectionHistory):
            history = ConnectionHistory(
                max_entries=_SSE_CONNECTION_HISTORY_MAX_ENTRIES,
            )
            setattr(core, _SSE_CONNECTION_HISTORY_ATTR, history)
        return history


def _record_connection_state(
    core: Any,
    state: str,
    *,
    reason_code: str | None = None,
) -> None:
    """Record one privacy-safe SSE connection state transition."""

    _get_or_create_connection_history(core).record(
        state,
        transport="sse",
        reason_code=reason_code,
    )


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
        description="Replay durable ledger events after this SSE id",
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
    _record_connection_state(core, "attempt")

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
        delivered_event_order: deque[str] = deque()
        live_status_seen = False
        event_order = 0

        def mark_delivered(event_id: object) -> None:
            if not isinstance(event_id, str) or not event_id:
                return
            if event_id in delivered_event_ids:
                return
            delivered_event_ids.add(event_id)
            delivered_event_order.append(event_id)
            while len(delivered_event_order) > _SSE_DEDUPE_MAX_EVENTS:
                delivered_event_ids.discard(delivered_event_order.popleft())

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
            nonlocal live_status_seen
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

            if normalized.get("type") == "session.status":
                live_status_seen = True

            delivery_properties = dict(normalized.get("properties") or {})
            delivery_properties["_penguin_delivery"] = {"durability": "pending"}
            normalized["properties"] = delivery_properties
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

        close_reason = "generator_closed"
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
            if connected_event:
                _record_connection_state(core, "connected")
                _record_connection_state(
                    core,
                    "replay_requested" if effective_last_event_id else "replay_skipped",
                    reason_code=(
                        "cursor_present" if effective_last_event_id else "no_cursor"
                    ),
                )
                # Control frames are never ledger rows and must not advance a
                # reconnect cursor or consume a runtime-event sequence.
                yield sse_event_frame(connected_event, include_id=False)

            if effective_last_event_id:
                replay_cursor = effective_last_event_id
                replayed_any = False
                while True:
                    try:
                        replay = await asyncio.to_thread(
                            _replay_events_after,
                            core,
                            replay_cursor,
                            limit=_SSE_REPLAY_PAGE_SIZE,
                            session_id=effective_session_id,
                            agent_id=effective_agent_id,
                            directory=effective_directory,
                        )
                    except Exception:
                        _record_connection_state(
                            core,
                            "replay_failed",
                            reason_code="ledger_read_error",
                        )
                        raise
                    if not replay.found:
                        _record_connection_state(
                            core,
                            "replay_gap",
                            reason_code="cursor_not_available",
                        )
                        gap_event = _replay_gap_event(
                            replay_cursor,
                            oldest_event_id=replay.oldest_event_id,
                            newest_event_id=replay.newest_event_id,
                            session_id=effective_session_id,
                            agent_id=effective_agent_id,
                            directory=effective_directory,
                        )
                        if event_allowed(gap_event):
                            yield sse_event_frame(gap_event, include_id=False)
                        break
                    if not replay.events:
                        _record_connection_state(
                            core,
                            "replay_complete",
                            reason_code=(
                                "events_replayed" if replayed_any else "no_new_events"
                            ),
                        )
                        break
                    if not replayed_any:
                        _record_connection_state(
                            core,
                            "replay_started",
                            reason_code="cursor_found",
                        )
                    replayed_any = True
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
                                mark_delivered(event_id)
                            yield sse_event_frame(event)
                    next_cursor = replay.events[-1].get("id")
                    if (
                        len(replay.events) < _SSE_REPLAY_PAGE_SIZE
                        or not isinstance(next_cursor, str)
                    ):
                        _record_connection_state(
                            core,
                            "replay_complete",
                            reason_code="events_replayed",
                        )
                        break
                    replay_cursor = next_cursor

            # Reconcile the canonical session status after replay. A status
            # event queued while replay was running wins over this snapshot,
            # preventing stale hydration from replacing newer live state.
            if effective_session_id and not live_status_seen:
                status_event = await _canonical_session_status_event(
                    core,
                    effective_session_id,
                    agent_id=effective_agent_id,
                    directory=effective_directory,
                )
                if status_event is not None:
                    _record_connection_state(
                        core,
                        "status_reconciled",
                        reason_code="canonical_session_status",
                    )
                    yield sse_event_frame(status_event, include_id=False)

            if effective_last_event_id:
                yield sse_event_frame(
                    {
                        "type": "server.replay_complete",
                        "properties": {
                            "sessionID": effective_session_id,
                            "agentID": effective_agent_id,
                            "directory": effective_directory,
                        },
                    },
                    include_id=False,
                )

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
                        mark_delivered(event_id)
                    # Live events are admitted asynchronously. The pending
                    # marker keeps clients from advancing a durable cursor until
                    # the same event is replayed from SQLite after commit.
                    yield sse_event_frame(event)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"

        except asyncio.CancelledError:
            # Client disconnected
            close_reason = "client_cancelled"
        except Exception:
            close_reason = "stream_error"
            raise
        finally:
            _record_connection_state(
                core,
                "disconnected",
                reason_code=close_reason,
            )
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


def _replay_events_after(
    core: Any,
    last_event_id: str,
    *,
    limit: int,
    session_id: str | None = None,
    agent_id: str | None = None,
    directory: str | None = None,
):
    from penguin.system.runtime_event_ledger import get_runtime_event_ledger

    return get_runtime_event_ledger(core).replay_after(
        last_event_id,
        limit=limit,
        session_id=session_id,
        agent_id=agent_id,
        directory=directory,
    )


def _replay_gap_event(
    last_event_id: str,
    *,
    oldest_event_id: str | None = None,
    newest_event_id: str | None = None,
    session_id: str | None = None,
    agent_id: str | None = None,
    directory: str | None = None,
) -> dict[str, Any]:
    return {
        "type": "server.replay_gap",
        "properties": {
            "lastEventID": last_event_id,
            "oldestEventID": oldest_event_id,
            "newestEventID": newest_event_id,
            "reason": "last_event_id_not_available",
            "sessionID": session_id,
            "agentID": agent_id,
            "directory": directory,
        },
    }


async def _canonical_session_status_event(
    core: Any,
    session_id: str,
    *,
    agent_id: str | None,
    directory: str | None,
) -> dict[str, Any] | None:
    """Build an id-less status snapshot for reconnect reconciliation."""

    try:
        from penguin.web.services.session_view import list_session_statuses

        statuses = await asyncio.to_thread(list_session_statuses, core)
    except Exception:
        logger.debug("Failed to hydrate canonical SSE session status", exc_info=True)
        return None
    status = statuses.get(session_id) if isinstance(statuses, dict) else None
    if not isinstance(status, dict):
        return None
    return {
        "type": "session.status",
        "properties": {
            "sessionID": session_id,
            "status": dict(status),
            "agentID": agent_id,
            "directory": directory,
        },
    }


@router.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "penguin-sse"}
