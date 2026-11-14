"""OpenCode process request lifecycle helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import logging
import traceback
from dataclasses import dataclass, field
from typing import Any

__all__ = [
    "SessionRun",
    "active_request_count",
    "active_request_session_ids",
    "busy_session_ids",
    "consume_session_abort",
    "discard_opencode_abort_session",
    "emit_process_user_message",
    "finalize_opencode_process_request",
    "finalize_process_response",
    "get_session_request_gate",
    "handle_process_cancelled",
    "handle_process_error",
    "mark_session_aborted",
    "register_opencode_process_request",
    "session_has_active_request",
    "session_tasks",
    "track_session_task",
    "untrack_session_task",
]

logger = logging.getLogger(__name__)
_SESSION_STATUS_EMIT_TIMEOUT_SECONDS = 5.0
_FALLBACK_REQUEST_GATE_KEY = object()


def _session_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


@dataclass
class SessionRun:
    """Live request state for one session.

    Only this module reads or writes it. A record exists while a session has
    work in flight or an abort waiting to be seen, and is dropped otherwise.

    Attributes:
        tasks: Tasks an abort of the session cancels.
        requests: Process requests registered and not yet finalized; busy and
            idle status events follow this count.
        abort_requested: The session was asked to stop; stream chunks for it
            raise ``CancelledError`` while this is set.
    """

    tasks: set[asyncio.Task[Any]] = field(default_factory=set)
    requests: int = 0
    abort_requested: bool = False

    @property
    def in_flight(self) -> bool:
        """Whether a request or tracked task for the session is running."""
        return self.requests > 0 or bool(self.tasks)


def _runs(owner: Any) -> dict[str, SessionRun]:
    runs = getattr(owner, "_opencode_session_runs", None)
    if not isinstance(runs, dict):
        runs = {}
        owner._opencode_session_runs = runs
    return runs


def _run(owner: Any, sid: str) -> SessionRun:
    return _runs(owner).setdefault(sid, SessionRun())


def _drop_if_idle(owner: Any, sid: str) -> None:
    run = _runs(owner).get(sid)
    if run is not None and not run.in_flight and not run.abort_requested:
        _runs(owner).pop(sid, None)


async def _emit_session_status_best_effort(
    owner: Any,
    session_id: str,
    status_type: str,
) -> None:
    """Emit bounded UI status without making request accounting depend on it."""

    try:
        await asyncio.wait_for(
            owner._emit_opencode_session_status(session_id, status_type),
            timeout=_SESSION_STATUS_EMIT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning(
            "Timed out emitting OpenCode session status %s for %s",
            status_type,
            session_id,
        )
    except Exception:
        logger.warning(
            "Failed to emit OpenCode session status %s for %s",
            status_type,
            session_id,
            exc_info=True,
        )


def get_session_request_gate(owner: Any, session_id: Any) -> asyncio.Lock:
    """Return the shared request-execution lock for one session."""

    sid = _session_id(session_id) or _FALLBACK_REQUEST_GATE_KEY
    gates = getattr(owner, "_opencode_request_gates", None)
    if not isinstance(gates, dict):
        gates = {}
        owner._opencode_request_gates = gates
    gate = gates.get(sid)
    if not isinstance(gate, asyncio.Lock):
        gate = asyncio.Lock()
        gates[sid] = gate
    return gate


def active_request_session_ids(owner: Any) -> set[str]:
    """Return the sessions that have a request in flight right now."""

    return {sid for sid, run in _runs(owner).items() if run.in_flight}


def session_has_active_request(owner: Any, session_id: Any) -> bool:
    """Return whether a request for the session is in flight."""

    run = _runs(owner).get(_session_id(session_id))
    return run is not None and run.in_flight


def active_request_count(owner: Any, session_id: Any) -> int:
    """Return how many process requests for the session are registered."""

    run = _runs(owner).get(_session_id(session_id))
    return run.requests if run is not None else 0


def session_tasks(owner: Any, session_id: Any) -> list[asyncio.Task[Any]]:
    """Return the tasks an abort of the session must cancel."""

    run = _runs(owner).get(_session_id(session_id))
    return list(run.tasks) if run is not None else []


def busy_session_ids(owner: Any) -> set[str]:
    """Return the sessions that are busy: any live source says so.

    A session is busy while a request is in flight, its stream is active, or
    its TUI adapter has an open stream or tool. Each source is live state that
    ends with the work, so none can leave a session busy after a crash.
    """

    busy = active_request_session_ids(owner)
    stream_states = getattr(owner, "_opencode_stream_states", None)
    if isinstance(stream_states, dict):
        busy |= {
            str(sid)
            for sid, state in stream_states.items()
            if isinstance(state, dict) and state.get("active")
        }
    adapters = getattr(owner, "_tui_adapters", None)
    if isinstance(adapters, dict):
        busy |= {
            str(sid)
            for sid, adapter in adapters.items()
            if getattr(adapter, "_session_status", None) == "busy"
        }
    return busy


def track_session_task(
    owner: Any,
    session_id: Any,
    request_task: asyncio.Task[Any] | None,
) -> bool:
    """Record a task that an abort of the session must cancel."""

    sid = _session_id(session_id)
    if not sid or request_task is None:
        return False
    _run(owner, sid).tasks.add(request_task)
    return True


def untrack_session_task(
    owner: Any,
    session_id: Any,
    request_task: asyncio.Task[Any] | None,
) -> None:
    """Forget a task recorded with :func:`track_session_task`."""

    sid = _session_id(session_id)
    run = _runs(owner).get(sid)
    if run is None or request_task is None:
        return
    run.tasks.discard(request_task)
    _drop_if_idle(owner, sid)


def mark_session_aborted(owner: Any, session_id: Any) -> None:
    """Ask in-flight work for the session to stop at its next stream chunk."""

    sid = _session_id(session_id)
    if sid:
        _run(owner, sid).abort_requested = True


def consume_session_abort(owner: Any, session_id: Any) -> bool:
    """Return whether the session was asked to abort.

    A request tracked by this module clears the marker when it ends, so the
    marker holds for every chunk of that request. With no tracked request
    nothing would ever clear it, so it is used up the first time it is read.
    """

    sid = _session_id(session_id)
    run = _runs(owner).get(sid)
    if run is None or not run.abort_requested:
        return False
    if not run.in_flight:
        run.abort_requested = False
        _drop_if_idle(owner, sid)
    return True


def discard_opencode_abort_session(owner: Any, session_id: Any) -> None:
    """Discard a stale abort marker for a session."""

    sid = _session_id(session_id)
    run = _runs(owner).get(sid)
    if run is None:
        return
    run.abort_requested = False
    _drop_if_idle(owner, sid)


def handle_process_cancelled(owner: Any, session_id: Any) -> dict[str, Any]:
    """Clear abort state and return the public aborted process payload."""

    discard_opencode_abort_session(owner, session_id)
    return {
        "assistant_response": "",
        "action_results": [],
        "aborted": True,
    }


async def handle_process_error(
    owner: Any,
    exc: Exception,
    input_data: Any,
    *,
    log: Any,
    log_error_fn: Any,
) -> dict[str, Any]:
    """Log a process failure, emit UI error state, and return API-safe payload."""

    error_msg = f"Error in process method: {exc!s}"
    log.error("%s\n%s", error_msg, traceback.format_exc())
    log_error_fn(exc, context={"method": "process", "input_data": input_data})

    await owner.emit_ui_event(
        "error",
        {
            "message": "Error processing your request",
            "source": "core.process",
            "details": str(exc),
        },
    )

    return {
        "assistant_response": (
            "I apologize, but an error occurred while processing your request."
        ),
        "action_results": [],
        "error": str(exc),
    }


async def emit_process_user_message(
    owner: Any,
    message: Any,
    *,
    message_category: Any,
    client_message_id: str | None,
    agent_id: str | None,
    log: Any,
) -> None:
    """Emit process user-message events without failing on OpenCode metadata."""

    user_message = {
        "role": "user",
        "content": message,
        "category": message_category,
    }
    if agent_id:
        user_message["agent_id"] = agent_id

    log.debug("Emitting user message event: %s...", message[:30])
    await owner.emit_ui_event("message", user_message)
    try:
        await owner._emit_opencode_user_message_with_metadata(
            message,
            message_id=client_message_id,
            agent_id=agent_id,
        )
    except Exception:
        log.debug("Failed to emit OpenCode user message", exc_info=True)


def _should_emit_assistant_event(response: Any, *, streaming: bool | None) -> bool:
    if not isinstance(response, dict) or "assistant_response" not in response:
        return False
    assistant_message = response["assistant_response"]
    if not assistant_message:
        return False
    if not streaming:
        return True
    stripped = assistant_message.lstrip()
    return stripped.startswith("[Error:") or stripped.startswith("[Note:")


async def finalize_process_response(
    owner: Any,
    conversation_manager: Any,
    response: Any,
    request_session_id: str | None,
    *,
    streaming: bool | None,
    agent_id: str | None,
    collect_token_usage: Any,
    message_category: Any,
    log: Any,
) -> Any:
    """Persist process response state and emit user-visible post-response events."""
    token_data = await collect_token_usage(
        owner,
        conversation_manager,
        response,
        request_session_id,
        log=log,
    )

    conversation_manager.save()

    if _should_emit_assistant_event(response, streaming=streaming):
        assistant_message = response["assistant_response"]
        log.debug("Emitting assistant message event: %s…", assistant_message[:30])
        await owner.emit_ui_event(
            "message",
            {
                "role": "assistant",
                "content": assistant_message,
                "category": message_category,
                "metadata": {},
                **({"agent_id": agent_id} if agent_id else {}),
            },
        )

    await owner.emit_ui_event("token_update", token_data)
    return token_data


async def register_opencode_process_request(
    owner: Any,
    session_id: Any,
    request_task: asyncio.Task[Any] | None,
) -> bool:
    """Track a session-scoped process request and emit busy on first request."""

    sid = _session_id(session_id)
    if not sid:
        return False

    discard_opencode_abort_session(owner, sid)
    if not track_session_task(owner, sid, request_task):
        return False
    run = _run(owner, sid)
    run.requests += 1
    try:
        if run.requests == 1:
            await _emit_session_status_best_effort(owner, sid, "busy")
            owner._ensure_opencode_session_status_heartbeat(sid)
        return True
    except BaseException:
        run.tasks.discard(request_task)
        run.requests = max(run.requests - 1, 0)
        if run.requests > 0:
            try:
                owner._ensure_opencode_session_status_heartbeat(sid)
            except Exception:
                logger.warning(
                    "Failed to preserve heartbeat during request rollback for %s",
                    sid,
                    exc_info=True,
                )
        else:
            try:
                owner._cancel_opencode_session_status_heartbeat(sid)
            except Exception:
                logger.debug(
                    "Failed to cancel heartbeat during request rollback for %s",
                    sid,
                    exc_info=True,
                )
        _drop_if_idle(owner, sid)
        raise


async def finalize_opencode_process_request(
    owner: Any,
    session_id: Any,
    request_task: asyncio.Task[Any] | None,
    *,
    request_tracked: bool,
) -> None:
    """Release process request tracking and emit idle after the last request."""

    sid = _session_id(session_id)
    run = _runs(owner).get(sid)
    if not request_tracked or run is None:
        return

    if request_task is not None:
        run.tasks.discard(request_task)
    run.requests = max(run.requests - 1, 0)
    if run.requests > 0:
        return

    run.abort_requested = False
    _drop_if_idle(owner, sid)
    try:
        owner._cancel_opencode_session_status_heartbeat(sid)
    except Exception:
        logger.warning(
            "Failed to cancel OpenCode session heartbeat for %s",
            sid,
            exc_info=True,
        )
    await _emit_session_status_best_effort(owner, sid, "idle")
