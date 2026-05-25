"""OpenCode/TUI stream event bridge helpers."""

from __future__ import annotations

from typing import Any

__all__ = [
    "active_part_text",
    "handle_tui_stream_chunk",
    "should_emit_final_content",
    "stream_state_for",
]


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
