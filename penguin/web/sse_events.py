"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections import deque
from typing import TYPE_CHECKING, Any, AsyncIterator, Optional

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
from penguin.web.services.system_status import (
    unwatch_vcs_directory,
    watch_vcs_directory,
)

if TYPE_CHECKING:
    from penguin.core import PenguinCore

logger = logging.getLogger(__name__)
router = APIRouter()
_LEDGER_RECORDER_ATTR = "_runtime_event_ledger_recorder_v1"
# Ledger writes are batched off the streaming hot path: event identity and
# ordering are assigned per event, but SQLite persistence is drained on a
# short cadence so the SSE frame is queued before any disk commit.
_LEDGER_BATCH_ATTR = "_runtime_event_ledger_batch_v1"
_LEDGER_FLUSH_INTERVAL_SECONDS = 0.25
_LEDGER_BATCH_MAX_EVENTS = 256
# One flush at a time per core, so rows commit in emission order (replay reads
# by rowid). After a failed write, routine flushes wait before retrying, and
# the unsaved backlog is capped; dropped events surface as a replay gap.
_LEDGER_FLUSH_LOCK_ATTR = "_runtime_event_ledger_flush_lock_v1"
_LEDGER_RETRY_AT_ATTR = "_runtime_event_ledger_retry_at_v1"
_LEDGER_RETRY_SECONDS = 5.0
_LEDGER_PENDING_MAX_EVENTS = 10_000
# Per-connection delivery limits for the compatibility SSE projection. The
# durable runtime event ledger owns replay truth; this queue only buffers live
# delivery for a connected client. Slow-client drops are recoverable by
# reconnecting with Last-Event-ID.
_SSE_QUEUE_MAX_EVENTS = 1000
_SSE_REPLAY_PAGE_SIZE = 1000
_SSE_KEEPALIVE_TIMEOUT_SECONDS = 300.0
_SSE_DEDUPE_MAX_EVENTS = 1000

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

# Pydantic 1.x evaluates FastAPI endpoint annotations eagerly, so these parameters
# intentionally use typing.Optional rather than PEP 604 unions.
@router.get("/api/v1/events/sse")
async def events_sse(
    session_id: Optional[str] = Query(  # noqa
        None, description="Filter to specific session"
    ),
    conversation_id: Optional[str] = Query(  # noqa
        None, description="Alias for session_id (API compatibility)"
    ),
    agent_id: Optional[str] = Query(  # noqa
        None, description="Filter to specific agent"
    ),
    directory: Optional[str] = Query(  # noqa
        None, description="Workspace directory"
    ),
    last_event_id: Optional[str] = Query(  # noqa
        None,
        description="Replay durable ledger events after this SSE id",
    ),
    last_event_id_header: Optional[str] = Header(  # noqa
        None, alias="Last-Event-ID"
    ),
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
        delivered_event_order: deque[str] = deque()
        event_order = 0
        # Set when the live queue overflows. Live events are then left to the
        # ledger, and once the queue drains the generator replays everything
        # after the last delivered event, so a slow client misses nothing.
        lagging = False
        last_delivered_id: str | None = None

        def mark_delivered(event_id: object) -> None:
            nonlocal last_delivered_id
            if not isinstance(event_id, str) or not event_id:
                return
            last_delivered_id = event_id
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

        async def event_handler(event_type: str, data: Any) -> None:
            """Handler for EventBus events.

            Async so the EventBus runs it on the event loop: a sync handler is
            run in a worker thread, where touching this connection's
            ``asyncio.Queue`` and state is not safe.
            """
            nonlocal lagging
            # Only handle opencode_event type
            if event_type != "opencode_event":
                return
            if lagging:
                return  # The ledger has it; the generator replays it.

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
                # The client is behind. The runtime event ledger recorded this
                # event at emission time; stop queueing and let the generator
                # replay from the ledger once the queue drains.
                lagging = True

        async def replay_after(cursor: str) -> AsyncIterator[str]:
            """Yield ledger events after ``cursor`` that this client may see."""
            # Ledger writes are batched off the delivery path; drain any
            # pending batch so replay reads the freshest events.
            await _flush_ledger_batch(core)
            while True:
                replay = await asyncio.to_thread(
                    _replay_events_after,
                    core,
                    cursor,
                    limit=_SSE_REPLAY_PAGE_SIZE,
                    session_id=effective_session_id,
                    agent_id=effective_agent_id,
                    directory=effective_directory,
                )
                if not replay.found:
                    gap_event = next_event(
                        _replay_gap_event(
                            cursor,
                            oldest_event_id=replay.oldest_event_id,
                            newest_event_id=replay.newest_event_id,
                        )
                    )
                    if gap_event and event_allowed(gap_event):
                        yield sse_event_frame(gap_event)
                    return
                if not replay.events:
                    return
                for runtime_event in replay.events:
                    event = opencode_payload_from_runtime_event(runtime_event)
                    event_id = event.get("id")
                    if isinstance(event_id, str) and (
                        event_id in queued_live_event_ids
                        or event_id in delivered_event_ids
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
                    return
                cursor = next_cursor

        async def catch_up() -> AsyncIterator[str]:
            """Replay what a lagging client missed, then resume live delivery."""
            nonlocal lagging
            cursor = last_delivered_id or effective_last_event_id
            if cursor is None:
                lagging = False
                gap_event = next_event(_replay_gap_event(""))
                if gap_event and event_allowed(gap_event):
                    yield sse_event_frame(gap_event)
                return
            async for frame in replay_after(cursor):
                yield frame
            # Resume live queueing, then replay once more for events emitted
            # while the first replay ran; ids already queued live are skipped.
            lagging = False
            async for frame in replay_after(last_delivered_id or cursor):
                yield frame

        # Subscribe to events
        core.event_bus.subscribe("opencode_event", event_handler)
        # This client's directory is polled for VCS changes while it is here.
        vcs_watch = watch_vcs_directory(core, directory, effective_session_id)

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
                async for frame in replay_after(effective_last_event_id):
                    yield frame

            # Stream events
            last_ledger_flush = time.monotonic()
            while True:
                if lagging and queue.empty():
                    async for frame in catch_up():
                        yield frame
                    continue
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
                    yield sse_event_frame(event)
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                # Ledger writes are batched off the delivery path; drain the
                # pending batch on a short cadence while this connection is
                # live so reconnect replay stays fresh.
                now = time.monotonic()
                if now - last_ledger_flush >= _LEDGER_FLUSH_INTERVAL_SECONDS:
                    await _flush_ledger_batch(core, wait=False)
                    last_ledger_flush = now

        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            # Always unsubscribe
            try:
                core.event_bus.unsubscribe("opencode_event", event_handler)
            except Exception:
                pass
            unwatch_vcs_directory(core, vcs_watch)
            # Final best-effort flush so replay sees the freshest events even
            # when the connection dropped mid-batch.
            try:
                await _flush_ledger_batch(core)
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


async def flush_runtime_event_ledger(core: Any) -> None:
    """Persist events still waiting in the ledger batch; call at shutdown."""
    await _flush_ledger_batch(core)


def _ledger_flush_lock(core: Any) -> asyncio.Lock:
    lock = getattr(core, _LEDGER_FLUSH_LOCK_ATTR, None)
    if not isinstance(lock, asyncio.Lock):
        lock = asyncio.Lock()
        setattr(core, _LEDGER_FLUSH_LOCK_ATTR, lock)
    return lock


def _cap_pending(batch: list[Any]) -> None:
    """Drop the oldest unsaved events beyond the backlog cap."""
    overflow = len(batch) - _LEDGER_PENDING_MAX_EVENTS
    if overflow > 0:
        del batch[:overflow]
        logger.warning(
            "Runtime event ledger backlog full; dropped %d unsaved events "
            "(replay reports a gap for them)",
            overflow,
        )


async def _flush_ledger_batch(core: Any, *, wait: bool = True) -> None:
    """Persist the pending opencode-event batch to the runtime ledger.

    Runs on the event loop and offloads the SQLite write to a worker thread;
    the whole batch lands in a single transaction (INSERT OR IGNORE keeps
    retries idempotent). Flushes run one at a time per core, so events commit
    in emission order.

    Args:
        core: The core whose batch to flush.
        wait: True (replay, disconnect, shutdown) waits for a flush in
            progress and retries even after a recent failure. False (the
            streaming cadence and a full batch) skips the flush instead.
    """
    if not getattr(core, _LEDGER_BATCH_ATTR, None):
        return
    lock = _ledger_flush_lock(core)
    if not wait and (
        lock.locked()
        or time.monotonic() < getattr(core, _LEDGER_RETRY_AT_ATTR, 0.0)
    ):
        return
    async with lock:
        batch = getattr(core, _LEDGER_BATCH_ATTR, None)
        if not batch:
            return
        events = list(batch)
        batch.clear()
        try:
            from penguin.system.runtime_event_ledger import get_runtime_event_ledger

            await asyncio.to_thread(get_runtime_event_ledger(core).extend, events)
            setattr(core, _LEDGER_RETRY_AT_ATTR, 0.0)
        except Exception:
            # Requeue at the front (identity/order were already assigned at
            # emission time) and wait before the next routine retry.
            batch[:0] = events
            _cap_pending(batch)
            setattr(
                core, _LEDGER_RETRY_AT_ATTR, time.monotonic() + _LEDGER_RETRY_SECONDS
            )
            logger.debug(
                "Failed to flush runtime event ledger batch",
                exc_info=True,
            )


def _install_runtime_event_ledger_recorder(core: Any) -> None:
    """Install one emission-time ledger recorder on the core EventBus.

    Live SSE delivery never waits on a disk commit: each event's identity and
    ordering are assigned synchronously, then the envelope is appended to a
    per-core batch that drains to SQLite in a single transaction.
    """
    if getattr(core, _LEDGER_RECORDER_ATTR, None) is not None:
        return
    event_bus = getattr(core, "event_bus", None)
    subscribe = getattr(event_bus, "subscribe", None)
    if not callable(subscribe):
        return

    if not isinstance(getattr(core, _LEDGER_BATCH_ATTR, None), list):
        setattr(core, _LEDGER_BATCH_ATTR, [])

    async def ledger_handler(event_type: str, data: Any) -> None:
        if event_type != "opencode_event" or not isinstance(data, dict):
            return
        try:
            runtime_event = record_opencode_event(core, data, persist=False)
            if runtime_event is None:
                return
            batch = getattr(core, _LEDGER_BATCH_ATTR, None)
            if not isinstance(batch, list):
                batch = []
                setattr(core, _LEDGER_BATCH_ATTR, batch)
            batch.append(runtime_event)
            _cap_pending(batch)
            if len(batch) >= _LEDGER_BATCH_MAX_EVENTS:
                await _flush_ledger_batch(core, wait=False)
        except Exception:
            # Ledger failures must not interrupt live TUI streaming. The client
            # can still receive the live frame; replay will surface a gap if
            # needed.
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
