"""OpenCode/TUI stream event bridge helpers."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from penguin.system.state import Message, MessageCategory

__all__ = [
    "abort_session",
    "active_part_text",
    "emit_opencode_session_status",
    "filter_internal_markers_from_event",
    "handle_tui_stream_chunk",
    "persist_finalized_message",
    "resolve_stream_scope_id",
    "should_emit_final_content",
    "stream_state_for",
]

_INTERNAL_MARKER_PATTERNS = (
    r"<execute>.*?</execute>",
    r"<system-reminder>.*?</system-reminder>",
    r"<internal>.*?</internal>",
    r"</?finish_response\b[^>]*>?",
)

_FILTERED_CONTENT_FIELDS = ("content", "chunk", "content_so_far", "message")


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
        {
            "type": "session.status",
            "properties": properties,
        },
    )


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
    if callable(adapter_abort):
        try:
            adapter_aborted = await adapter_abort(
                reason="Tool execution was interrupted"
            )
            aborted = bool(adapter_aborted) or aborted
        except Exception:
            logger.warning("Failed to abort active TUI parts", exc_info=True)

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
