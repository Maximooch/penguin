"""OpenCode/TUI stream event bridge helpers."""

from __future__ import annotations

import asyncio
import re
from datetime import datetime
from typing import Any

from penguin.system.execution_context import get_current_execution_context
from penguin.system.runtime_events import wrap_opencode_event
from penguin.system.state import Message, MessageCategory

from . import opencode_bridge as core_opencode_bridge

__all__ = [
    "abort_session",
    "abort_streaming_message",
    "active_part_text",
    "cancel_opencode_session_status_heartbeat",
    "emit_opencode_assistant_error",
    "emit_opencode_session_status",
    "emit_opencode_stream_chunk",
    "emit_opencode_stream_end",
    "emit_opencode_stream_start",
    "emit_opencode_user_message_with_metadata",
    "emit_ui_event",
    "ensure_opencode_session_status_heartbeat",
    "filter_internal_markers_from_event",
    "finalize_streaming_message",
    "handle_stream_chunk",
    "handle_tui_stream_chunk",
    "invoke_runmode_stream_callback",
    "opencode_session_status_heartbeat",
    "persist_finalized_message",
    "prepare_runmode_stream_callback",
    "resolve_stream_scope_id",
    "should_emit_final_content",
    "stream_state_for",
    "subscribe_to_stream_events",
]

_INTERNAL_MARKER_PATTERNS = (
    r"<execute>.*?</execute>",
    r"<system-reminder>.*?</system-reminder>",
    r"<internal>.*?</internal>",
    r"</?finish_response\b[^>]*>?",
)

_FILTERED_CONTENT_FIELDS = ("content", "chunk", "content_so_far", "message")


def _schedule_background_task(owner: Any, awaitable: Any) -> None:
    task = asyncio.create_task(awaitable)
    tasks = getattr(owner, "_opencode_background_tasks", None)
    if not isinstance(tasks, set):
        tasks = set()
        owner._opencode_background_tasks = tasks
    tasks.add(task)
    task.add_done_callback(tasks.discard)


def stream_state_for(owner: Any, session_id: Any) -> dict[str, Any]:
    """Return mutable stream state for a session-scoped stream."""

    stream_states = getattr(owner, "_opencode_stream_states", None)
    if not isinstance(stream_states, dict):
        stream_states = {}
        owner._opencode_stream_states = stream_states

    state = stream_states.get(session_id)
    if not isinstance(state, dict):
        state = {
            "active": False,
            "stream_id": None,
            "message_id": None,
            "part_id": None,
        }
        stream_states[session_id] = state
    return state


def subscribe_to_stream_events(owner: Any) -> None:
    """Subscribe a core-like owner to OpenCode/TUI bridge source events."""

    owner._opencode_stream_states = {}
    owner._opencode_message_adapters = {}
    owner._opencode_tool_parts = {}
    owner._opencode_tool_info = {}

    owner._tui_stream_handler = owner._on_tui_stream_chunk
    owner.event_bus.subscribe("stream_chunk", owner._tui_stream_handler)

    owner._tui_action_handler = owner._on_tui_action
    owner._tui_action_result_handler = owner._on_tui_action_result
    owner.event_bus.subscribe("action", owner._tui_action_handler)
    owner.event_bus.subscribe("action_result", owner._tui_action_result_handler)

    owner._tui_lsp_updated_handler = owner._on_tui_lsp_updated
    owner._tui_lsp_diagnostics_handler = owner._on_tui_lsp_diagnostics
    owner.event_bus.subscribe("lsp.updated", owner._tui_lsp_updated_handler)
    owner.event_bus.subscribe(
        "lsp.client.diagnostics",
        owner._tui_lsp_diagnostics_handler,
    )

    owner._tui_todo_updated_handler = owner._on_tui_todo_updated
    owner.event_bus.subscribe("todo.updated", owner._tui_todo_updated_handler)


def active_part_text(adapter: Any, part_id: str) -> str:
    """Return currently buffered text for an active adapter part."""

    active_parts = getattr(adapter, "_active_parts", {})
    active_part = active_parts.get(part_id) if isinstance(active_parts, dict) else None
    if isinstance(active_part, dict):
        existing_content = active_part.get("content", {})
    else:
        existing_content = getattr(active_part, "content", {}) if active_part else {}
    if not isinstance(existing_content, dict):
        return ""
    text = existing_content.get("text", "")
    return text if isinstance(text, str) else ""


def should_emit_final_content(adapter: Any, part_id: str, final_content: Any) -> bool:
    """Return whether a final no-delta stream event needs synthesized text."""

    if not isinstance(final_content, str) or not final_content.strip():
        return False
    try:
        return not bool(active_part_text(adapter, part_id))
    except Exception:
        return True


def prepare_runmode_stream_callback(
    callback: Any,
    *,
    adapter_factory: Any,
) -> Any:
    """Normalize a RunMode stream callback to Penguin's async callback shape."""
    return adapter_factory(callback, suppress_errors=True)


async def invoke_runmode_stream_callback(
    owner: Any,
    chunk: str,
    message_type: str,
    *,
    callback: Any = None,
    logger: Any,
) -> None:
    """Invoke the active RunMode stream callback and isolate callback failures."""
    cb = callback or getattr(owner, "_runmode_stream_callback", None)
    if not cb:
        return
    try:
        await cb(chunk, message_type)
    except Exception as exc:
        logger.debug("RunMode stream callback execution failed: %s", exc, exc_info=True)


def filter_internal_markers_from_event(data: dict[str, Any]) -> dict[str, Any]:
    """Return event data with internal implementation markers removed."""

    modified = False
    filtered_data = data

    for field in _FILTERED_CONTENT_FIELDS:
        value = data.get(field)
        if not isinstance(value, str):
            continue

        filtered_value = value
        for pattern in _INTERNAL_MARKER_PATTERNS:
            filtered_value = re.sub(pattern, "", filtered_value, flags=re.DOTALL)

        if filtered_value != value:
            if not modified:
                filtered_data = dict(data)
                modified = True
            filtered_data[field] = filtered_value.strip()

    return filtered_data


def resolve_stream_scope_id(
    *,
    conversation_manager: Any,
    execution_context: Any,
    agent_id: str | None,
) -> str:
    """Resolve the stream-state key for concurrent session isolation."""

    resolved_agent = agent_id
    if not resolved_agent and execution_context is not None:
        resolved_agent = getattr(execution_context, "agent_id", None)
    if not resolved_agent:
        resolved_agent = getattr(conversation_manager, "current_agent_id", None)
    resolved_agent = resolved_agent or "default"

    if execution_context is None:
        return resolved_agent

    session_scope = getattr(execution_context, "session_id", None) or getattr(
        execution_context, "conversation_id", None
    )
    if not session_scope:
        return resolved_agent
    return f"{session_scope}:{resolved_agent}"


async def emit_opencode_session_status(
    owner: Any,
    session_id: str,
    status_type: str,
    info: dict[str, Any] | None = None,
) -> None:
    """Emit an OpenCode session.status event for a session."""

    sid = session_id.strip() if isinstance(session_id, str) else ""
    if not sid:
        return

    properties: dict[str, Any] = {
        "sessionID": sid,
        "status": {"type": status_type},
    }
    if info:
        properties["info"] = info

    await owner.event_bus.emit(
        "opencode_event",
        wrap_opencode_event("session.status", properties, default_session_id=sid),
    )


async def opencode_session_status_heartbeat(
    owner: Any,
    session_id: str,
    *,
    interval: float = 5.0,
    logger: Any | None = None,
) -> None:
    """Refresh busy status while a session has active OpenCode requests."""

    current_task = asyncio.current_task()
    try:
        while True:
            await asyncio.sleep(interval)
            active_requests = getattr(owner, "_opencode_active_requests", None)
            active_count = (
                active_requests.get(session_id, 0)
                if isinstance(active_requests, dict)
                else 0
            )
            if active_count <= 0:
                return
            try:
                await owner._emit_opencode_session_status(session_id, "busy")
            except asyncio.CancelledError:
                raise
            except Exception:
                if logger is not None:
                    logger.debug(
                        "OpenCode session status heartbeat emit failed for %s",
                        session_id,
                        exc_info=True,
                    )
    except asyncio.CancelledError:
        raise
    except Exception:
        if logger is not None:
            logger.debug(
                "OpenCode session status heartbeat failed for %s",
                session_id,
                exc_info=True,
            )
    finally:
        heartbeats = getattr(owner, "_opencode_status_heartbeats", None)
        if isinstance(heartbeats, dict) and heartbeats.get(session_id) is current_task:
            heartbeats.pop(session_id, None)


def ensure_opencode_session_status_heartbeat(
    owner: Any,
    session_id: str,
    *,
    interval: float = 5.0,
) -> None:
    """Start one busy-status heartbeat for an active session request."""

    sid = session_id.strip() if isinstance(session_id, str) else ""
    if not sid:
        return

    heartbeats = getattr(owner, "_opencode_status_heartbeats", None)
    if not isinstance(heartbeats, dict):
        heartbeats = {}
        owner._opencode_status_heartbeats = heartbeats

    existing = heartbeats.get(sid)
    if existing is not None and not existing.done():
        return

    heartbeats[sid] = asyncio.create_task(
        owner._opencode_session_status_heartbeat(sid, interval=interval)
    )


def cancel_opencode_session_status_heartbeat(owner: Any, session_id: str) -> None:
    """Stop the busy-status heartbeat once a session request is fully idle."""

    heartbeats = getattr(owner, "_opencode_status_heartbeats", None)
    if not isinstance(heartbeats, dict):
        return
    task = heartbeats.pop(session_id, None)
    if task is not None and not task.done():
        task.cancel()


async def emit_ui_event(
    owner: Any,
    event_type: str,
    data: Any,
    *,
    logger: Any,
) -> None:
    """Emit a UI event with Penguin/OpenCode session scoping."""

    data_keys = list(data.keys()) if isinstance(data, dict) else []
    logger.debug(
        "emit_ui_event called: %s keys=%s bus=%s",
        event_type,
        data_keys,
        id(owner.event_bus),
    )

    if isinstance(data, dict):
        data = filter_internal_markers_from_event(data)

    execution_context = get_current_execution_context()

    try:
        if isinstance(data, dict) and not data.get("agent_id"):
            context_agent = execution_context.agent_id if execution_context else None
            if context_agent:
                data = dict(data)
                data["agent_id"] = context_agent
            else:
                conversation_manager = getattr(owner, "conversation_manager", None)
                if conversation_manager and hasattr(
                    conversation_manager, "current_agent_id"
                ):
                    data = dict(data)
                    data["agent_id"] = conversation_manager.current_agent_id
    except Exception:
        pass

    if isinstance(data, dict):
        scoped_conversation_id = None
        scoped_session_id = None
        if execution_context:
            scoped_conversation_id = (
                execution_context.conversation_id or execution_context.session_id
            )
            scoped_session_id = execution_context.session_id or scoped_conversation_id

        if scoped_conversation_id and not data.get("conversation_id"):
            data = dict(data)
            data["conversation_id"] = scoped_conversation_id
        if scoped_session_id and not data.get("session_id"):
            data = dict(data)
            data["session_id"] = scoped_session_id

        if not data.get("conversation_id") or not data.get("session_id"):
            fallback_conversation_id = getattr(owner, "_current_conversation_id", None)
            if fallback_conversation_id:
                data = dict(data)
                data.setdefault("conversation_id", fallback_conversation_id)
                data.setdefault("session_id", fallback_conversation_id)

    try:
        await owner.event_bus.emit(event_type, data)

        if event_type == "status" and isinstance(data, dict):
            status_type = data.get("status_type")
            session_id = data.get("session_id") or data.get("conversation_id")
            if isinstance(status_type, str) and isinstance(session_id, str):
                bridgeable_statuses = {
                    "clarification_needed",
                    "clarification_answered",
                    "time_limit_reached",
                    "idle_no_ready_tasks",
                }
                if status_type in bridgeable_statuses:
                    await emit_opencode_session_status(
                        owner,
                        session_id,
                        status_type,
                        info=(
                            data.get("data")
                            if isinstance(data.get("data"), dict)
                            else None
                        ),
                    )
    except Exception as e:
        logger.error("[TUI_ADAPTER] ERROR in event_bus.emit: %s", e, exc_info=True)


async def abort_session(
    owner: Any,
    session_id: str,
    *,
    logger: Any,
) -> bool:
    """Abort active OpenCode stream/tool state for a session."""

    sid = session_id.strip() if isinstance(session_id, str) else ""
    if not sid:
        return False

    abort_sessions = getattr(owner, "_opencode_abort_sessions", None)
    if not isinstance(abort_sessions, set):
        abort_sessions = set()
        owner._opencode_abort_sessions = abort_sessions
    abort_sessions.add(sid)
    aborted = False

    adapter = owner._get_tui_adapter(sid)
    adapter_abort = getattr(adapter, "abort", None)

    tasks_map = getattr(owner, "_opencode_process_tasks", None)
    if isinstance(tasks_map, dict):
        active_tasks = list(tasks_map.get(sid, set()))
        for task in active_tasks:
            if task.done():
                continue
            task.cancel()
            aborted = True

    states = getattr(owner, "_opencode_stream_states", None)
    state = states.get(sid) if isinstance(states, dict) else None
    if isinstance(state, dict):
        message_id = state.get("message_id")
        part_id = state.get("part_id")
        if (
            not callable(adapter_abort)
            and isinstance(message_id, str)
            and isinstance(part_id, str)
        ):
            try:
                await adapter.on_stream_end(message_id, part_id)
                aborted = True
            except Exception:
                logger.warning("Failed to force-finalize aborted stream", exc_info=True)
        state["active"] = False
        state["stream_id"] = None
        state["part_id"] = None

    tool_parts = getattr(owner, "_opencode_tool_parts", None)
    if isinstance(tool_parts, dict):
        for key in [
            key
            for key in tool_parts
            if isinstance(key, str) and key.startswith(f"{sid}:")
        ]:
            tool_parts.pop(key, None)

    tool_info = getattr(owner, "_opencode_tool_info", None)
    if isinstance(tool_info, dict):
        for key in [
            key
            for key in tool_info
            if isinstance(key, str) and key.startswith(f"{sid}:")
        ]:
            tool_info.pop(key, None)

    for scope in list(owner._stream_manager.get_active_agents()):
        if scope != sid and not scope.startswith(f"{sid}:"):
            continue
        for event in owner._stream_manager.abort(agent_id=scope):
            event_data = dict(event.data) if isinstance(event.data, dict) else {}
            event_data["session_id"] = sid
            event_data["conversation_id"] = sid
            await owner.emit_ui_event(event.event_type, event_data)
            aborted = True

    await emit_opencode_session_status(owner, sid, "idle")

    if callable(adapter_abort):

        async def _cleanup_adapter() -> None:
            try:
                await adapter_abort(reason="Tool execution was interrupted")
            except Exception:
                logger.warning("Failed to abort active TUI parts", exc_info=True)

        cleanup_tasks = getattr(owner, "_opencode_abort_cleanup_tasks", None)
        if not isinstance(cleanup_tasks, set):
            cleanup_tasks = set()
            owner._opencode_abort_cleanup_tasks = cleanup_tasks
        cleanup_task = asyncio.create_task(_cleanup_adapter())
        cleanup_tasks.add(cleanup_task)

        def _finish_cleanup(task: asyncio.Task[Any]) -> None:
            cleanup_tasks.discard(task)
            if not task.cancelled():
                task.exception()

        cleanup_task.add_done_callback(_finish_cleanup)

    return aborted


def persist_finalized_message(
    owner: Any,
    *,
    agent_id: str,
    session_id: str | None,
    message: Any,
    category: MessageCategory,
    trace_log: Any = None,
) -> bool:
    """Persist a finalized streaming message without reloading shared sessions."""

    target_session_id = session_id.strip() if isinstance(session_id, str) else ""
    if not target_session_id:
        return False

    session, manager = owner._find_session_store(target_session_id)
    if session is None or manager is None:
        if callable(trace_log):
            trace_log(
                "core.stream.persist session=%s agent=%s status=missing_store",
                target_session_id,
                agent_id,
            )
        return False

    persisted_message = Message(
        role=message.role,
        content=message.content,
        category=category,
        id=getattr(message, "id", None) or f"msg_{datetime.now().timestamp()}",
        timestamp=getattr(message, "timestamp", None) or datetime.now().isoformat(),
        metadata=dict(getattr(message, "metadata", {}) or {}),
        tokens=int(getattr(message, "tokens", 0) or 0),
        agent_id=getattr(message, "agent_id", None) or agent_id,
        recipient_id=getattr(message, "recipient_id", None),
        message_type=getattr(message, "message_type", "message") or "message",
    )
    session.add_message(persisted_message)
    saved = bool(manager.save_session(session))
    if callable(trace_log):
        trace_log(
            "core.stream.persist session=%s agent=%s manager=%s message_id=%s "
            "saved=%s message_len=%s category=%s",
            target_session_id,
            agent_id,
            hex(id(manager)),
            persisted_message.id,
            saved,
            len(persisted_message.content or ""),
            category,
        )
    return saved


def finalize_streaming_message(
    owner: Any,
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    stream_scope_id: str | None = None,
    logger: Any,
    trace_log: Any = None,
) -> dict[str, Any] | None:
    """Finalize a stream, persist the message, and emit scoped stream events."""

    execution_context = get_current_execution_context()
    conversation_manager = getattr(owner, "conversation_manager", None)

    if agent_id is None:
        if execution_context and execution_context.agent_id:
            agent_id = execution_context.agent_id
        else:
            agent_id = getattr(conversation_manager, "current_agent_id", "default")

    resolved_agent_id = agent_id
    if resolved_agent_id is None and execution_context and execution_context.agent_id:
        resolved_agent_id = execution_context.agent_id
    if resolved_agent_id is None:
        resolved_agent_id = getattr(
            conversation_manager,
            "current_agent_id",
            "default",
        )
    resolved_agent_id = resolved_agent_id or "default"

    resolved_conversation_id = conversation_id
    resolved_session_id = session_id or conversation_id
    if execution_context:
        resolved_conversation_id = (
            execution_context.conversation_id
            or execution_context.session_id
            or resolved_conversation_id
        )
        resolved_session_id = (
            execution_context.session_id
            or resolved_conversation_id
            or resolved_session_id
        )

    resolved_stream_scope_id = stream_scope_id
    if not resolved_stream_scope_id and resolved_session_id:
        resolved_stream_scope_id = f"{resolved_session_id}:{resolved_agent_id}"
    if not resolved_stream_scope_id:
        scope_resolver = getattr(owner, "_resolve_stream_scope_id", None)
        if callable(scope_resolver):
            resolved_stream_scope_id = scope_resolver(
                execution_context,
                resolved_agent_id,
            )
        else:
            resolved_stream_scope_id = resolve_stream_scope_id(
                conversation_manager=conversation_manager,
                execution_context=execution_context,
                agent_id=resolved_agent_id,
            )

    message, events = owner._stream_manager.finalize(agent_id=resolved_stream_scope_id)
    if message is None:
        active_scopes = owner._stream_manager.get_active_agents()
        allow_unscoped_fallback = not (
            isinstance(resolved_session_id, str) and resolved_session_id
        ) and not (
            isinstance(resolved_conversation_id, str) and resolved_conversation_id
        )
        logger.warning(
            "stream.finalize.scope_miss request=%s session=%s conversation=%s "
            "agent=%s scope=%s active_scopes=%s allow_unscoped_fallback=%s",
            execution_context.request_id if execution_context else "unknown",
            resolved_session_id or "",
            resolved_conversation_id or "",
            resolved_agent_id,
            resolved_stream_scope_id,
            active_scopes,
            allow_unscoped_fallback,
        )
        if allow_unscoped_fallback:
            logical_agent_id = resolved_agent_id
            if resolved_stream_scope_id != logical_agent_id:
                message, events = owner._stream_manager.finalize(
                    agent_id=logical_agent_id
                )
                if message is not None:
                    logger.warning(
                        "stream.finalize.fallback_used request=%s session=%s "
                        "conversation=%s requested_scope=%s fallback_scope=%s",
                        (
                            execution_context.request_id
                            if execution_context
                            else "unknown"
                        ),
                        resolved_session_id or "",
                        resolved_conversation_id or "",
                        resolved_stream_scope_id,
                        logical_agent_id,
                    )
            if message is None and len(active_scopes) == 1:
                message, events = owner._stream_manager.finalize(
                    agent_id=active_scopes[0]
                )
                if message is not None:
                    logger.warning(
                        "stream.finalize.single_active_fallback request=%s "
                        "session=%s conversation=%s requested_scope=%s "
                        "fallback_scope=%s",
                        (
                            execution_context.request_id
                            if execution_context
                            else "unknown"
                        ),
                        resolved_session_id or "",
                        resolved_conversation_id or "",
                        resolved_stream_scope_id,
                        active_scopes[0],
                    )

    if message is None:
        return None

    if message.was_empty:
        logger.warning(
            "[WALLET_GUARD] Empty response from LLM for agent '%s', "
            "forcing context advance.",
            resolved_agent_id,
        )

    if message.role == "assistant":
        category = MessageCategory.DIALOG
    elif message.role == "system":
        category = MessageCategory.SYSTEM
    else:
        category = MessageCategory.DIALOG

    if conversation_manager:
        target_session_id = (
            resolved_session_id
            if isinstance(resolved_session_id, str) and resolved_session_id
            else None
        )
        persisted = owner._persist_finalized_message(
            agent_id=resolved_agent_id,
            session_id=target_session_id,
            message=message,
            category=category,
        )
        trace_session_id = target_session_id if persisted else None
        try:
            if not persisted:
                conv = conversation_manager.get_agent_conversation(resolved_agent_id)
                current_session_id = getattr(getattr(conv, "session", None), "id", None)
                trace_session_id = current_session_id or trace_session_id
                if target_session_id and current_session_id != target_session_id:
                    logger.warning(
                        "Skipping shared-conversation finalize persistence for "
                        "agent '%s': target session '%s' != current session '%s'",
                        resolved_agent_id,
                        target_session_id,
                        current_session_id,
                    )
                else:
                    conv.add_message(
                        role=message.role,
                        content=message.content,
                        category=category,
                        metadata=message.metadata,
                    )
                    if hasattr(conv, "save"):
                        conv.save()
        except (KeyError, AttributeError):
            if not persisted:
                conv = conversation_manager.conversation
                current_session_id = getattr(getattr(conv, "session", None), "id", None)
                trace_session_id = current_session_id or trace_session_id
                if target_session_id and current_session_id != target_session_id:
                    logger.warning(
                        "Skipping fallback finalize persistence: target session "
                        "'%s' != current session '%s'",
                        target_session_id,
                        current_session_id,
                    )
                else:
                    conv.add_message(
                        role=message.role,
                        content=message.content,
                        category=category,
                        metadata=message.metadata,
                    )
                    if hasattr(conv, "save"):
                        conv.save()

        if callable(trace_log):
            trace_log(
                "core.stream.finalize request=%s session=%s conversation=%s "
                "agent=%s effective_conv_session=%s persisted=%s message_len=%s "
                "events=%s empty=%s",
                execution_context.request_id if execution_context else "unknown",
                target_session_id or "unknown",
                resolved_conversation_id or "",
                resolved_agent_id,
                trace_session_id or "unknown",
                persisted,
                len(message.content or ""),
                len(events),
                bool(message.was_empty),
            )

        temp_ws_callback = getattr(owner, "_temp_ws_callback", None)
        if temp_ws_callback:
            _schedule_background_task(
                owner,
                temp_ws_callback(
                    {
                        "type": "message",
                        "role": message.role,
                        "content": message.content,
                        "category": category,
                        "metadata": message.metadata,
                        "agent_id": resolved_agent_id,
                    }
                ),
            )

    callback_ref = getattr(owner, "_runmode_stream_callback", None)
    for event in events:
        event_data = (
            dict(event.data) if isinstance(event.data, dict) else {"data": event.data}
        )
        scoped_conversation_id = resolved_conversation_id
        scoped_session_id = resolved_session_id
        if execution_context:
            scoped_conversation_id = (
                execution_context.conversation_id
                or execution_context.session_id
                or scoped_conversation_id
            )
            scoped_session_id = (
                execution_context.session_id
                or scoped_conversation_id
                or scoped_session_id
            )

        if scoped_conversation_id:
            event_data["session_id"] = scoped_session_id or scoped_conversation_id
            event_data["conversation_id"] = scoped_conversation_id
        else:
            event_data["session_id"] = "unknown"
            event_data["conversation_id"] = "unknown"
            logger.warning(
                "stream.finalize.unknown_scope request=%s agent=%s scope=%s "
                "active_scopes=%s",
                execution_context.request_id if execution_context else "unknown",
                resolved_agent_id,
                resolved_stream_scope_id,
                owner._stream_manager.get_active_agents(),
            )

        event_data["agent_id"] = resolved_agent_id
        event_data = owner._filter_internal_markers_from_event(event_data)
        _schedule_background_task(
            owner,
            owner.emit_ui_event(event.event_type, event_data),
        )
        if callback_ref and event_data.get("is_final"):
            _schedule_background_task(
                owner,
                owner._invoke_runmode_stream_callback(
                    "",
                    "assistant",
                    callback_ref,
                ),
            )

    return message.to_dict()


def abort_streaming_message(
    owner: Any,
    *,
    agent_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    stream_scope_id: str | None = None,
    trace_log: Any = None,
) -> bool:
    """Abort an uncommitted streaming message without persisting dialog."""

    execution_context = get_current_execution_context()
    conversation_manager = getattr(owner, "conversation_manager", None)
    explicit_agent_id = agent_id is not None
    if agent_id is None:
        if execution_context and execution_context.agent_id:
            agent_id = execution_context.agent_id
        else:
            agent_id = getattr(conversation_manager, "current_agent_id", "default")

    resolved_agent_id = agent_id or "default"
    resolved_conversation_id = conversation_id
    resolved_session_id = session_id or conversation_id
    if execution_context:
        resolved_conversation_id = (
            resolved_conversation_id
            or execution_context.conversation_id
            or execution_context.session_id
        )
        resolved_session_id = (
            resolved_session_id
            or execution_context.session_id
            or resolved_conversation_id
        )

    resolved_stream_scope_id = stream_scope_id
    if not resolved_stream_scope_id and resolved_session_id:
        resolved_stream_scope_id = f"{resolved_session_id}:{resolved_agent_id}"
    if not resolved_stream_scope_id:
        scope_resolver = getattr(owner, "_resolve_stream_scope_id", None)
        if callable(scope_resolver):
            resolved_stream_scope_id = scope_resolver(
                execution_context,
                resolved_agent_id,
            )
        else:
            resolved_stream_scope_id = resolve_stream_scope_id(
                conversation_manager=conversation_manager,
                execution_context=execution_context,
                agent_id=resolved_agent_id,
            )

    if resolved_stream_scope_id and not explicit_agent_id:
        _scope_session, _, scope_agent_id = resolved_stream_scope_id.partition(":")
        if scope_agent_id.strip():
            resolved_agent_id = scope_agent_id.strip()
    if (
        resolved_stream_scope_id
        and ":" in resolved_stream_scope_id
        and (not resolved_session_id or not resolved_conversation_id)
    ):
        scope_session_id = resolved_stream_scope_id.split(":", 1)[0].strip()
        if scope_session_id:
            resolved_session_id = resolved_session_id or scope_session_id
            resolved_conversation_id = resolved_conversation_id or resolved_session_id

    events = owner._stream_manager.abort(agent_id=resolved_stream_scope_id)
    if not events:
        return False

    for event in events:
        event_data = (
            dict(event.data) if isinstance(event.data, dict) else {"data": event.data}
        )
        if resolved_conversation_id:
            event_data["session_id"] = resolved_session_id or resolved_conversation_id
            event_data["conversation_id"] = resolved_conversation_id
        elif resolved_session_id:
            event_data["session_id"] = resolved_session_id
            event_data["conversation_id"] = resolved_session_id
        else:
            event_data["session_id"] = "unknown"
            event_data["conversation_id"] = "unknown"
        event_data["agent_id"] = resolved_agent_id
        event_data = owner._filter_internal_markers_from_event(event_data)
        _schedule_background_task(
            owner,
            owner.emit_ui_event(event.event_type, event_data),
        )

    if callable(trace_log):
        trace_log(
            "core.stream.abort request=%s session=%s conversation=%s agent=%s "
            "scope=%s events=%s",
            execution_context.request_id if execution_context else "unknown",
            resolved_session_id or "unknown",
            resolved_conversation_id or "",
            resolved_agent_id,
            resolved_stream_scope_id,
            len(events),
        )
    return True


async def handle_stream_chunk(
    owner: Any,
    chunk: str,
    *,
    message_type: str | None = None,
    role: str = "assistant",
    agent_id: str | None = None,
    stream_scope_id: str | None = None,
    session_id: str | None = None,
    conversation_id: str | None = None,
    logger: Any,
) -> None:
    """Handle one provider stream chunk and emit scoped UI events."""

    execution_context = get_current_execution_context()
    conversation_manager = getattr(owner, "conversation_manager", None)
    if agent_id is None:
        if execution_context and execution_context.agent_id:
            agent_id = execution_context.agent_id
        else:
            agent_id = getattr(conversation_manager, "current_agent_id", "default")

    resolved_scope_id = stream_scope_id
    if not resolved_scope_id:
        scope_resolver = getattr(owner, "_resolve_stream_scope_id", None)
        if callable(scope_resolver):
            resolved_scope_id = scope_resolver(execution_context, agent_id)
        else:
            resolved_scope_id = resolve_stream_scope_id(
                conversation_manager=conversation_manager,
                execution_context=execution_context,
                agent_id=agent_id,
            )

    resolved_session_id = session_id or conversation_id
    if execution_context:
        resolved_session_id = (
            execution_context.session_id
            or execution_context.conversation_id
            or resolved_session_id
        )

    abort_sessions = getattr(owner, "_opencode_abort_sessions", None)
    if not isinstance(abort_sessions, set):
        abort_sessions = set()
        owner._opencode_abort_sessions = abort_sessions

    if isinstance(resolved_session_id, str) and resolved_session_id in abort_sessions:
        raise asyncio.CancelledError(f"Session {resolved_session_id} aborted")

    filter_event = getattr(owner, "_filter_internal_markers_from_event")
    filtered = filter_event({"chunk": chunk})
    if filtered.get("chunk") is not None:
        chunk = filtered.get("chunk", "")

    events = owner._stream_manager.handle_chunk(
        chunk,
        agent_id=resolved_scope_id,
        message_type=message_type,
        role=role,
    )

    for event in events:
        event_data = (
            dict(event.data) if isinstance(event.data, dict) else {"data": event.data}
        )
        scoped_conversation_id = conversation_id
        scoped_session_id = session_id or conversation_id
        if execution_context:
            scoped_conversation_id = (
                execution_context.conversation_id
                or execution_context.session_id
                or scoped_conversation_id
            )
            scoped_session_id = (
                execution_context.session_id
                or scoped_conversation_id
                or scoped_session_id
            )

        if scoped_conversation_id:
            event_data["conversation_id"] = scoped_conversation_id
            event_data["session_id"] = scoped_session_id or scoped_conversation_id
        else:
            event_data["session_id"] = "unknown"
            event_data["conversation_id"] = "unknown"
            logger.warning(
                "stream.event.unknown_scope request=%s event=%s agent=%s scope=%s "
                "chunk_preview=%r",
                execution_context.request_id if execution_context else "unknown",
                event.event_type,
                agent_id or "default",
                resolved_scope_id,
                (chunk or "")[:120],
            )

        event_data["agent_id"] = agent_id
        event_data = filter_event(event_data)
        await owner.emit_ui_event(event.event_type, event_data)

        if event_data.get("chunk") and not event_data.get("is_reasoning"):
            await owner._invoke_runmode_stream_callback(
                event_data["chunk"],
                event_data.get("message_type", "assistant"),
            )


async def emit_opencode_stream_start(
    owner: Any,
    *,
    agent_id: str = "default",
    model_id: str | None = None,
    provider_id: str | None = None,
    execution_context: Any = None,
) -> tuple[str, str]:
    """Initialize OpenCode streaming and remember the message adapter."""

    context = execution_context
    if context is None:
        context = get_current_execution_context()
    session_id = core_opencode_bridge.resolve_session_id(
        execution_context=context,
        conversation_manager=getattr(owner, "conversation_manager", None),
    )
    adapter = owner._get_tui_adapter(session_id)
    model_state = owner._resolve_opencode_model_state(
        session_id=session_id,
        model_id=model_id,
        provider_id=provider_id,
    )
    message_id, part_id = await adapter.on_stream_start(
        agent_id,
        model_state.get("modelID"),
        model_state.get("providerID"),
        model_state.get("variant"),
    )

    message_adapters = getattr(owner, "_opencode_message_adapters", None)
    if not isinstance(message_adapters, dict):
        message_adapters = {}
        owner._opencode_message_adapters = message_adapters
    message_adapters[message_id] = adapter
    return message_id, part_id


async def emit_opencode_assistant_error(
    owner: Any,
    message: str,
    *,
    error: dict[str, Any] | None = None,
    agent_id: str | None = None,
    model_id: str | None = None,
    provider_id: str | None = None,
    execution_context: Any = None,
) -> str:
    """Emit a persisted OpenCode assistant error without treating it as model text."""
    context = execution_context or get_current_execution_context()
    session_id = core_opencode_bridge.resolve_session_id(
        execution_context=context,
        conversation_manager=getattr(owner, "conversation_manager", None),
    )
    resolved_agent_id = (
        agent_id
        or (getattr(context, "agent_id", None) if context is not None else None)
        or getattr(
            getattr(owner, "conversation_manager", None), "current_agent_id", None
        )
        or "default"
    )
    error_payload = dict(error or {})
    model_state = owner._resolve_opencode_model_state(
        session_id=session_id,
        model_id=model_id
        or (
            error_payload.get("model")
            if isinstance(error_payload.get("model"), str)
            else None
        ),
        provider_id=provider_id
        or (
            error_payload.get("provider")
            if isinstance(error_payload.get("provider"), str)
            else None
        ),
    )
    adapter = owner._get_tui_adapter(session_id)
    return await adapter.on_assistant_error(
        message,
        error=error_payload,
        agent_id=resolved_agent_id,
        model_id=model_state.get("modelID"),
        provider_id=model_state.get("providerID"),
        variant=model_state.get("variant"),
    )


async def emit_opencode_stream_chunk(
    owner: Any,
    message_id: str,
    part_id: str,
    chunk: str,
    message_type: str = "assistant",
) -> None:
    """Emit an OpenCode-compatible stream chunk with delta."""

    message_adapters = getattr(owner, "_opencode_message_adapters", {})
    adapter = message_adapters.get(message_id, owner._tui_adapter)
    await adapter.on_stream_chunk(message_id, part_id, chunk, message_type)


async def emit_opencode_stream_end(
    owner: Any,
    message_id: str,
    part_id: str,
) -> None:
    """Finalize an OpenCode-compatible stream."""

    message_adapters = getattr(owner, "_opencode_message_adapters", {})
    adapter = message_adapters.pop(message_id, owner._tui_adapter)
    await adapter.on_stream_end(message_id, part_id)


async def emit_opencode_user_message_with_metadata(
    owner: Any,
    content: str,
    *,
    message_id: str | None = None,
    part_id: str | None = None,
    agent_id: str | None = None,
    persist: bool = True,
    execution_context: Any = None,
) -> str:
    """Emit a user message in OpenCode format with stable message metadata."""

    context = execution_context
    if context is None:
        context = get_current_execution_context()
    session_id = core_opencode_bridge.resolve_session_id(
        execution_context=context,
        conversation_manager=getattr(owner, "conversation_manager", None),
    )
    adapter = owner._get_tui_adapter(session_id)
    model_state = owner._resolve_opencode_model_state(session_id=session_id)
    user_message_kwargs: dict[str, Any] = {
        "message_id": message_id,
        "agent_id": agent_id or "default",
        "model_id": model_state.get("modelID"),
        "provider_id": model_state.get("providerID"),
        "variant": model_state.get("variant"),
    }
    if part_id is not None:
        user_message_kwargs["part_id"] = part_id
    if not persist:
        user_message_kwargs["persist"] = False
    emitted_message_id = await adapter.on_user_message_with_metadata(
        content,
        **user_message_kwargs,
    )
    state = stream_state_for(owner, session_id)
    state["active"] = False
    state["stream_id"] = None
    state["message_id"] = None
    state["part_id"] = None
    return emitted_message_id


async def handle_tui_stream_chunk(
    owner: Any,
    event_type: str,
    data: dict[str, Any],
    *,
    logger: Any,
) -> None:
    """Handle one Penguin stream event and emit OpenCode-compatible deltas."""

    if event_type != "stream_chunk":
        return

    chunk = data.get("chunk", "")
    message_type = data.get("message_type", "assistant")
    stream_id = data.get("stream_id", "unknown")
    session_id = (
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("sessionID")
        or "unknown"
    )
    agent_id = data.get("agent_id") or data.get("agentID") or "default"
    adapter = owner._get_tui_adapter(session_id)
    state = stream_state_for(owner, session_id)

    is_final = bool(data.get("is_final"))
    is_aborted = bool(data.get("aborted"))
    if is_aborted and is_final and not state.get("active") and not chunk:
        state["stream_id"] = None
        state["part_id"] = None
        return

    if (not state.get("active")) or state.get("stream_id") != stream_id:
        message_id = state.get("message_id")
        part_id = state.get("part_id")
        if state.get("active") and message_id and part_id:
            try:
                await adapter.on_stream_end(message_id, part_id)
            except Exception:
                pass

        state["active"] = True
        state["stream_id"] = stream_id
        model_state = owner._resolve_opencode_model_state(session_id=session_id)

        try:
            message_id, part_id = await adapter.on_stream_start(
                agent_id=agent_id,
                model_id=model_state.get("modelID"),
                provider_id=model_state.get("providerID"),
                variant=model_state.get("variant"),
            )
            state["message_id"] = message_id
            state["part_id"] = part_id
            owner._opencode_message_adapters[message_id] = adapter
        except Exception as exc:
            logger.error("Failed to start OpenCode stream: %s", exc)
            state["active"] = False
            return

    message_id = state.get("message_id")
    part_id = state.get("part_id")
    if message_id and part_id:
        try:
            await adapter.on_stream_chunk(message_id, part_id, chunk, message_type)
        except Exception as exc:
            logger.error("Failed to emit OpenCode chunk: %s", exc)

    if (
        is_final
        and message_id
        and part_id
        and not chunk
        and should_emit_final_content(adapter, part_id, data.get("content"))
    ):
        try:
            await adapter.on_stream_chunk(
                message_id,
                part_id,
                data["content"],
                "assistant",
            )
        except Exception as exc:
            logger.error("Failed to emit fallback OpenCode final chunk: %s", exc)

    if data.get("is_final"):
        if message_id and part_id:
            try:
                await adapter.on_stream_end(message_id, part_id)
            except Exception as exc:
                logger.error("Failed to finalize OpenCode stream: %s", exc)
        state["active"] = False
        state["stream_id"] = None
        state["message_id"] = message_id
        state["part_id"] = None
