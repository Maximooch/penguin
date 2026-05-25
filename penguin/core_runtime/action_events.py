"""OpenCode/TUI action event bridge helpers.

These helpers keep action event routing out of :mod:`penguin.core` while
preserving PenguinCore's private compatibility methods.
"""

from __future__ import annotations

import json
import time
from typing import Any

__all__ = [
    "handle_tui_action",
    "handle_tui_action_result",
    "resolve_action_session_id",
    "tool_key_for",
]


def resolve_action_session_id(data: dict[str, Any]) -> str:
    """Resolve the session identifier used for OpenCode action events."""

    return str(
        data.get("session_id")
        or data.get("conversation_id")
        or data.get("sessionID")
        or "unknown"
    )


def tool_key_for(session_id: str, call_id: str) -> str:
    """Return the internal key for session-scoped tool-call bookkeeping."""

    return f"{session_id}:{call_id}"


async def handle_tui_action(
    owner: Any,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Translate a TUI action event into an OpenCode tool-start event."""

    if event_type != "action":
        return

    session_id = resolve_action_session_id(data)
    adapter = owner._get_tui_adapter(session_id)

    tool_name = data.get("type") or data.get("action") or "unknown"
    params = _decode_json_params(data.get("params"))
    mapped_tool, tool_input, metadata = owner._map_action_to_tool(tool_name, params)

    call_id = data.get("id") or data.get("call_id") or data.get("callID")
    if not call_id:
        call_id = f"call_{int(time.time() * 1000)}"
    call_id = str(call_id)
    tool_key = tool_key_for(session_id, call_id)

    model_state = owner._resolve_opencode_model_state(session_id=session_id)
    part_id = await adapter.on_tool_start(
        mapped_tool,
        tool_input,
        tool_call_id=call_id,
        metadata=metadata,
        message_id=_stream_message_id(owner, session_id),
        agent_id=_resolve_agent_id(data),
        model_id=model_state.get("modelID"),
        provider_id=model_state.get("providerID"),
        variant=model_state.get("variant"),
    )
    _tool_parts(owner)[tool_key] = part_id
    _tool_info(owner)[tool_key] = {
        "tool": mapped_tool,
        "input": tool_input,
        "metadata": metadata,
        "action": tool_name,
    }


async def handle_tui_action_result(
    owner: Any,
    event_type: str,
    data: dict[str, Any],
) -> None:
    """Translate a TUI action-result event into an OpenCode tool-end event."""

    if event_type != "action_result":
        return

    session_id = resolve_action_session_id(data)
    adapter = owner._get_tui_adapter(session_id)

    call_id = data.get("id") or data.get("call_id") or data.get("callID")
    if not call_id:
        return
    call_id = str(call_id)
    tool_key = tool_key_for(session_id, call_id)

    tool_info = _tool_info(owner)
    tool_parts = _tool_parts(owner)
    info = tool_info.get(tool_key, {})
    part_id = tool_parts.get(tool_key)
    action_name = (
        data.get("action")
        or data.get("type")
        or _info_value(info, "action")
        or "unknown"
    )
    if not part_id:
        mapped_tool, tool_input, metadata = owner._map_action_to_tool(action_name, {})
        model_state = owner._resolve_opencode_model_state(session_id=session_id)
        part_id = await adapter.on_tool_start(
            mapped_tool,
            tool_input,
            tool_call_id=call_id,
            metadata=metadata,
            message_id=_stream_message_id(owner, session_id),
            agent_id=_resolve_agent_id(data),
            model_id=model_state.get("modelID"),
            provider_id=model_state.get("providerID"),
            variant=model_state.get("variant"),
        )
        tool_parts[tool_key] = part_id
        info = {"tool": mapped_tool, "input": tool_input, "metadata": metadata}

    status = data.get("status")
    result = data.get("result")
    if (
        status != "error"
        and isinstance(result, str)
        and result.lstrip().lower().startswith("error")
    ):
        status = "error"
    error = result if status == "error" else None
    event_metadata = data.get("metadata")
    merged_meta = owner._map_action_result_metadata(
        str(action_name),
        result,
        _info_value(info, "metadata") if isinstance(info, dict) else None,
        _info_value(info, "input") if isinstance(info, dict) else None,
        status,
        event_metadata if isinstance(event_metadata, dict) else None,
    )
    await adapter.on_tool_end(part_id, result, error=error, metadata=merged_meta)
    tool_parts.pop(tool_key, None)
    tool_info.pop(tool_key, None)


def _decode_json_params(params: Any) -> Any:
    if isinstance(params, str) and params.strip().startswith(("{", "[")):
        try:
            return json.loads(params)
        except Exception:
            return params
    return params


def _resolve_agent_id(data: dict[str, Any]) -> str:
    agent_id = data.get("agent_id") or data.get("agentID") or "default"
    return str(agent_id)


def _stream_message_id(owner: Any, session_id: str) -> Any:
    states = getattr(owner, "_opencode_stream_states", None)
    if not isinstance(states, dict):
        return None
    maybe_state = states.get(session_id)
    if not isinstance(maybe_state, dict):
        return None
    return maybe_state.get("message_id")


def _tool_parts(owner: Any) -> dict[str, str]:
    tool_parts = getattr(owner, "_opencode_tool_parts", None)
    if not isinstance(tool_parts, dict):
        tool_parts = {}
        owner._opencode_tool_parts = tool_parts
    return tool_parts


def _tool_info(owner: Any) -> dict[str, dict[str, Any]]:
    tool_info = getattr(owner, "_opencode_tool_info", None)
    if not isinstance(tool_info, dict):
        tool_info = {}
        owner._opencode_tool_info = tool_info
    return tool_info


def _info_value(info: Any, key: str) -> Any:
    if not isinstance(info, dict):
        return None
    return info.get(key)
