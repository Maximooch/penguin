"""OpenCode process request lifecycle helpers for :mod:`penguin.core`."""

from __future__ import annotations

import asyncio
import logging
import traceback
from typing import Any

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


def _session_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _ensure_request_state(owner: Any) -> None:
    if not isinstance(getattr(owner, "_opencode_abort_sessions", None), set):
        owner._opencode_abort_sessions = set()
    if not isinstance(getattr(owner, "_opencode_process_tasks", None), dict):
        owner._opencode_process_tasks = {}
    if not isinstance(getattr(owner, "_opencode_active_requests", None), dict):
        owner._opencode_active_requests = {}


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

    sid = _session_id(session_id) or "__default__"
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
    _ensure_request_state(owner)
    if not sid:
        return False

    owner._opencode_abort_sessions.discard(sid)
    if request_task is None:
        return False

    tasks = owner._opencode_process_tasks.get(sid)
    if not isinstance(tasks, set):
        tasks = set()
        owner._opencode_process_tasks[sid] = tasks
    tasks.add(request_task)

    previous_count = owner._opencode_active_requests.get(sid, 0)
    next_count = previous_count + 1
    owner._opencode_active_requests[sid] = next_count
    try:
        if next_count == 1:
            await _emit_session_status_best_effort(owner, sid, "busy")
            owner._ensure_opencode_session_status_heartbeat(sid)
        return True
    except BaseException:
        tasks.discard(request_task)
        if not tasks:
            owner._opencode_process_tasks.pop(sid, None)
        current_count = owner._opencode_active_requests.get(sid, 0)
        remaining_count = max(current_count - 1, 0)
        if remaining_count > 0:
            owner._opencode_active_requests[sid] = remaining_count
            try:
                owner._ensure_opencode_session_status_heartbeat(sid)
            except Exception:
                logger.warning(
                    "Failed to preserve heartbeat during request rollback for %s",
                    sid,
                    exc_info=True,
                )
        else:
            owner._opencode_active_requests.pop(sid, None)
        if remaining_count == 0:
            try:
                owner._cancel_opencode_session_status_heartbeat(sid)
            except Exception:
                logger.debug(
                    "Failed to cancel heartbeat during request rollback for %s",
                    sid,
                    exc_info=True,
                )
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
    if not request_tracked or not sid:
        return
    _ensure_request_state(owner)

    tasks = owner._opencode_process_tasks.get(sid)
    if isinstance(tasks, set) and request_task is not None:
        tasks.discard(request_task)
        if not tasks:
            owner._opencode_process_tasks.pop(sid, None)

    current_count = owner._opencode_active_requests.get(sid, 0)
    if current_count > 1:
        owner._opencode_active_requests[sid] = current_count - 1
        return

    owner._opencode_active_requests.pop(sid, None)
    owner._opencode_abort_sessions.discard(sid)
    try:
        owner._cancel_opencode_session_status_heartbeat(sid)
    except Exception:
        logger.warning(
            "Failed to cancel OpenCode session heartbeat for %s",
            sid,
            exc_info=True,
        )
    await _emit_session_status_best_effort(owner, sid, "idle")
