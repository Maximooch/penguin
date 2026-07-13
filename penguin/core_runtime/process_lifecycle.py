"""OpenCode process request lifecycle helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

logger = logging.getLogger(__name__)

_SUCCESSFUL_STREAM_TERMINAL_STATUSES = frozenset(
    {
        "completed",
        "implicit_completion",
        "ok",
        "pending_review",
        "succeeded",
        "success",
    }
)

__all__ = [
    "discard_opencode_abort_session",
    "emit_process_user_message",
    "finalize_opencode_process_request",
    "finalize_process_response",
    "get_session_request_gate",
    "handle_process_cancelled",
    "handle_process_error",
    "register_opencode_process_request",
]

logger = logging.getLogger(__name__)
_SESSION_STATUS_EMIT_TIMEOUT_SECONDS = 5.0
_FALLBACK_REQUEST_GATE_KEY = object()


def _session_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _ensure_request_state(owner: Any) -> None:
    if not isinstance(getattr(owner, "_opencode_abort_sessions", None), set):
        owner._opencode_abort_sessions = set()
    if not isinstance(getattr(owner, "_opencode_process_tasks", None), dict):
        owner._opencode_process_tasks = {}
    if not isinstance(getattr(owner, "_opencode_active_requests", None), dict):
        owner._opencode_active_requests = {}
    if not isinstance(getattr(owner, "_opencode_process_task_refs", None), dict):
        owner._opencode_process_task_refs = {}


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


def _ensure_opencode_status_heartbeat(owner: Any, session_id: str) -> None:
    """Best-effort heartbeat setup that cannot invalidate request ownership."""

    ensure = getattr(owner, "_ensure_opencode_session_status_heartbeat", None)
    if not callable(ensure):
        return
    try:
        ensure(session_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Failed to start OpenCode status heartbeat for session %s; "
            "request ownership remains active",
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


def discard_opencode_abort_session(owner: Any, session_id: Any) -> None:
    """Discard a stale abort marker for a session if request state exists."""

    sid = _session_id(session_id)
    if not sid:
        return
    _ensure_request_state(owner)
    owner._opencode_abort_sessions.discard(sid)


def handle_process_cancelled(owner: Any, session_id: Any) -> dict[str, Any]:
    """Return truthful cancellation state while finalization retains ownership."""

    sid = _session_id(session_id)
    abort_sessions = getattr(owner, "_opencode_abort_sessions", None)
    aborted = bool(sid and isinstance(abort_sessions, set) and sid in abort_sessions)
    return {
        "assistant_response": "",
        "action_results": [],
        "status": "aborted" if aborted else "cancelled",
        "aborted": aborted,
        "cancelled": not aborted,
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
    status = response.get("status")
    if isinstance(status, str) and status.strip():
        if status.strip().lower() not in _SUCCESSFUL_STREAM_TERMINAL_STATUSES:
            return True
    if response.get("error"):
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
    _ensure_request_state(owner)
    if not sid:
        return False

    if request_task is None:
        return False

    current_active = owner._opencode_active_requests.get(sid, 0)
    if current_active == 0:
        owner._opencode_abort_sessions.discard(sid)

    tasks = owner._opencode_process_tasks.get(sid)
    if not isinstance(tasks, set):
        tasks = set()
        owner._opencode_process_tasks[sid] = tasks
    tasks.add(request_task)
    refs = owner._opencode_process_task_refs.get(sid)
    if not isinstance(refs, dict):
        refs = {}
        owner._opencode_process_task_refs[sid] = refs
    refs[request_task] = int(refs.get(request_task, 0)) + 1

    next_count = current_active + 1
    owner._opencode_active_requests[sid] = next_count
    try:
        if next_count == 1:
            await _emit_session_status_best_effort(owner, sid, "busy")
            _ensure_opencode_status_heartbeat(owner, sid)
        return True
    except BaseException:
        if _release_opencode_process_request(owner, sid, request_task):
            _cancel_opencode_status_heartbeat(owner, sid)
        else:
            # A concurrent request may have registered while the first busy
            # status emission was pending. Keep that surviving request's
            # liveness heartbeat active even though the first registration
            # was cancelled.
            _ensure_opencode_status_heartbeat(owner, sid)
        raise


def _release_opencode_process_request(
    owner: Any,
    session_id: str,
    request_task: asyncio.Task[Any] | None,
) -> bool:
    """Release in-memory request ownership and report whether the session idled."""

    tasks = owner._opencode_process_tasks.get(session_id)
    refs = owner._opencode_process_task_refs.get(session_id)
    if isinstance(refs, dict) and request_task is not None:
        remaining_refs = max(0, int(refs.get(request_task, 1)) - 1)
        if remaining_refs:
            refs[request_task] = remaining_refs
        else:
            refs.pop(request_task, None)
            if isinstance(tasks, set):
                tasks.discard(request_task)
        if not refs:
            owner._opencode_process_task_refs.pop(session_id, None)
    elif isinstance(tasks, set) and request_task is not None:
        tasks.discard(request_task)
    if isinstance(tasks, set) and not tasks:
        owner._opencode_process_tasks.pop(session_id, None)

    current_count = owner._opencode_active_requests.get(session_id, 0)
    if current_count > 1:
        owner._opencode_active_requests[session_id] = current_count - 1
        return False

    owner._opencode_active_requests.pop(session_id, None)
    owner._opencode_abort_sessions.discard(session_id)
    return True


def _cancel_opencode_status_heartbeat(owner: Any, session_id: str) -> None:
    """Best-effort status-heartbeat cancellation after ownership is released."""

    try:
        owner._cancel_opencode_session_status_heartbeat(session_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.warning(
            "Failed to stop OpenCode status heartbeat for session %s; "
            "request ownership was still released",
            session_id,
            exc_info=True,
        )


async def finalize_opencode_process_request(
    owner: Any,
    session_id: Any,
    request_task: asyncio.Task[Any] | None,
    *,
    request_tracked: bool,
) -> None:
    """Release process request tracking and emit idle after the last request."""

    sid = _session_id(session_id)
    if not request_tracked or not sid:
        return
    _ensure_request_state(owner)

    if not _release_opencode_process_request(owner, sid, request_task):
        return

    _cancel_opencode_status_heartbeat(owner, sid)
    await _emit_session_status_best_effort(owner, sid, "idle")
