"""OpenCode process request lifecycle helpers for :mod:`penguin.core`."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import asyncio

__all__ = [
    "discard_opencode_abort_session",
    "emit_process_user_message",
    "finalize_opencode_process_request",
    "register_opencode_process_request",
]


def _session_id(value: Any) -> str:
    return value.strip() if isinstance(value, str) and value.strip() else ""


def _ensure_request_state(owner: Any) -> None:
    if not isinstance(getattr(owner, "_opencode_abort_sessions", None), set):
        owner._opencode_abort_sessions = set()
    if not isinstance(getattr(owner, "_opencode_process_tasks", None), dict):
        owner._opencode_process_tasks = {}
    if not isinstance(getattr(owner, "_opencode_active_requests", None), dict):
        owner._opencode_active_requests = {}


def discard_opencode_abort_session(owner: Any, session_id: Any) -> None:
    """Discard a stale abort marker for a session if request state exists."""

    sid = _session_id(session_id)
    if not sid:
        return
    _ensure_request_state(owner)
    owner._opencode_abort_sessions.discard(sid)


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

    next_count = owner._opencode_active_requests.get(sid, 0) + 1
    owner._opencode_active_requests[sid] = next_count
    if next_count == 1:
        await owner._emit_opencode_session_status(sid, "busy")
    return True


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
    await owner._emit_opencode_session_status(sid, "idle")
