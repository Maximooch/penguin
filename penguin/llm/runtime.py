from __future__ import annotations

import asyncio
from typing import Any, Awaitable, Callable, Dict, List, Optional

from penguin.tools.runtime import (
    ToolExecutionPolicy,
    execute_tool_calls_serially,
    legacy_action_result_from_tool_result,
    tool_call_from_responses_info,
)
from penguin.utils.errors import LLMEmptyResponseError

from .provider_transform import (
    native_tool_format,
    normalize_anthropic_tools,
    normalize_openai_chat_tool_choice,
    normalize_openai_chat_tools,
    normalize_openai_responses_tool_choice,
    normalize_openai_responses_tools,
)
from .reasoning_variants import native_reasoning_efforts

_REASONING_EFFORT_VARIANTS = {"none", "minimal", "low", "medium", "high", "xhigh"}
_REASONING_MAX_VARIANTS = {"max"}
_REASONING_DISABLE_VARIANTS = {"off"}


def _get_tool_payload(
    tool_manager: Any,
    *,
    include_web_search: bool,
) -> List[Dict[str, Any]]:
    tools_getter = getattr(tool_manager, "get_responses_tools", None)
    if not callable(tools_getter):
        return []
    try:
        tools_payload = tools_getter(include_web_search=include_web_search)
    except TypeError:
        tools_payload = tools_getter()
    return list(tools_payload or [])


def prepare_native_tool_kwargs(
    model_config: Any, tool_manager: Any
) -> Dict[str, Any]:
    """Build native tool kwargs for providers that support structured tool calls."""

    extra_kwargs: Dict[str, Any] = {}
    if model_config is None:
        return extra_kwargs

    tool_format = native_tool_format(model_config)
    if not tool_format:
        return extra_kwargs

    tools_payload = _get_tool_payload(
        tool_manager,
        include_web_search=tool_format == "openai_responses",
    )
    if not tools_payload:
        return extra_kwargs

    setattr(model_config, "interrupt_on_tool_call", True)

    if tool_format == "openai_responses":
        extra_kwargs["tools"] = normalize_openai_responses_tools(tools_payload)
        extra_kwargs["tool_choice"] = normalize_openai_responses_tool_choice("auto")
        return extra_kwargs

    if tool_format == "openai_chat":
        extra_kwargs["tools"] = normalize_openai_chat_tools(tools_payload)
        extra_kwargs["tool_choice"] = normalize_openai_chat_tool_choice("auto")
        extra_kwargs["parallel_tool_calls"] = False
        return extra_kwargs

    if tool_format == "anthropic":
        extra_kwargs["tools"] = normalize_anthropic_tools(tools_payload)
        extra_kwargs["tool_choice"] = {"type": "auto"}
        return extra_kwargs

    return extra_kwargs


def prepare_responses_tool_kwargs(
    model_config: Any, tool_manager: Any
) -> Dict[str, Any]:
    """Backward-compatible wrapper for native tool kwargs preparation."""

    return prepare_native_tool_kwargs(model_config, tool_manager)


def handler_has_pending_tool_call(api_client: Any) -> bool:
    """Return whether the active handler captured a tool call to execute."""

    try:
        handler = getattr(api_client, "client_handler", None)
        checker = getattr(handler, "has_pending_tool_call", None)
        if callable(checker):
            return bool(checker())
    except Exception:
        return False
    return False


def build_empty_response_diagnostics(
    *,
    messages: List[Dict[str, Any]],
    raw_response: Optional[str],
    model_config: Any = None,
    provider_error: Any = None,
    handler: Any = None,
) -> Dict[str, Any]:
    """Build detailed diagnostics for empty provider responses."""

    diagnostics: Dict[str, Any] = {
        "raw_response": repr(raw_response) if raw_response else "(None)",
        "response_length": len(raw_response) if raw_response else 0,
    }

    try:
        diagnostics["message_count"] = len(messages)
        diagnostics["total_chars"] = sum(
            len(str(m.get("content", ""))) for m in messages
        )
        diagnostics["approx_tokens"] = diagnostics["total_chars"] // 4
    except Exception:
        diagnostics["message_stats_error"] = "Failed to compute message stats"

    try:
        if model_config:
            diagnostics["model"] = getattr(model_config, "model", "unknown")
            diagnostics["provider"] = getattr(model_config, "provider", "unknown")
            diagnostics["max_context_window_tokens"] = getattr(
                model_config,
                "max_context_window_tokens",
                None,
            )
            diagnostics["max_output_tokens"] = getattr(
                model_config,
                "max_output_tokens",
                None,
            )
    except Exception:
        diagnostics["model_config_error"] = "Failed to get model config"

    api_error_detected = False
    error_type = "unknown"
    error_detail = None

    if provider_error is not None:
        api_error_detected = True
        error_type = getattr(
            getattr(provider_error, "category", None), "value", "unknown"
        )
        error_detail = getattr(provider_error, "message", None)
        diagnostics["handler_error"] = error_detail
        retry_after = getattr(provider_error, "retry_after_seconds", None)
        if retry_after is not None:
            diagnostics["retry_after_seconds"] = retry_after
    elif raw_response:
        stripped = raw_response.strip()
        if stripped.startswith("[Error:"):
            api_error_detected = True
            error_detail = stripped
            if "context" in stripped.lower() or "token" in stripped.lower():
                error_type = "context_window_exceeded"
            elif "quota" in stripped.lower() or "credit" in stripped.lower():
                error_type = "quota_exceeded"
            elif "rate" in stripped.lower() or "429" in stripped:
                error_type = "rate_limited"
            elif "auth" in stripped.lower() or "key" in stripped.lower():
                error_type = "authentication_error"
            elif "model" in stripped.lower() and "not found" in stripped.lower():
                error_type = "model_not_found"
            else:
                error_type = "api_error"

    diagnostics["api_error_detected"] = api_error_detected
    diagnostics["error_type"] = error_type
    if error_detail:
        diagnostics["error_detail"] = error_detail

    try:
        if handler is not None:
            last_error = getattr(handler, "last_error", None) or getattr(
                handler, "_last_error", None
            )
            if last_error:
                diagnostics["handler_error"] = str(last_error)
    except Exception:
        pass

        # TODO: review these user messages for clarity and helpfulness, and consider adding more specific guidance based on error type and diagnostics
    user_messages = {
        "context_window_exceeded": (
            f"Context window exceeded. Your conversation has ~{diagnostics.get('approx_tokens', '?')} tokens "
            "but the model limit may be lower."
        ),
        "quota_exceeded": "API quota/credits exceeded. Check your account balance and billing status.",
        "rate_limit": "Rate limit exceeded. Wait a moment and try again, or reduce request frequency.",
        "rate_limited": "Rate limit exceeded. Wait a moment and try again, or reduce request frequency.",
        "bad_request": (
            f"LLM upstream rejected the request. {error_detail or 'Check request parameters and token limits.'}"
        ),
        "provider_unavailable": "LLM upstream is unavailable. Wait a moment and try again.",
        "network": "LLM network request failed. Check connectivity and retry.",
        "timeout": "LLM request timed out. Wait a moment and try again.",
        "auth": "LLM authentication failed. Reconnect or check credentials.",
        "authentication_error": "API authentication failed. Check your API key is valid and properly configured.",
        "model_not_found": (
            f"Model '{diagnostics.get('model', 'unknown')}' not found. Check the model name is correct and you have access to it."
        ),
        "api_error": (
            f"API returned an error: {error_detail or 'Unknown error'}. Check the API status and your request parameters."
        ),
        "unknown": (
            f"Model returned empty response after retry. Conversation has {diagnostics.get('message_count', '?')} messages, "
            f"~{diagnostics.get('approx_tokens', '?')} tokens. Possible causes: (1) Context too large, (2) API issue, (3) Model refusing to respond."
        ),
    }
    diagnostics["user_message"] = user_messages.get(
        error_type, user_messages["unknown"]
    )
    diagnostics["summary"] = (
        f"Empty response from {diagnostics.get('model', 'unknown')} "
        f"(type={error_type}, msgs={diagnostics.get('message_count', '?')}, "
        f"tokens≈{diagnostics.get('approx_tokens', '?')})"
    )
    return diagnostics


async def call_with_retry(
    *,
    api_client: Any,
    messages: List[Dict[str, Any]],
    streaming: Optional[bool],
    stream_callback: Optional[Callable[..., Any]],
    extra_kwargs: Dict[str, Any],
    model_config: Any = None,
) -> str:
    """Call provider once, retrying one time for empty non-tool responses."""

    streamed_assistant_chunk = False
    replayed_retry_response = False

    async def _tracked_stream_callback(
        chunk: str, message_type: str = "assistant"
    ) -> None:
        nonlocal streamed_assistant_chunk
        if chunk and message_type == "assistant":
            streamed_assistant_chunk = True
        if stream_callback is None:
            return
        if asyncio.iscoroutinefunction(stream_callback):
            await stream_callback(chunk, message_type)
            return
        try:
            stream_callback(chunk, message_type)
        except TypeError:
            stream_callback(chunk)

    assistant_response = await api_client.get_response(
        messages,
        stream=streaming,
        stream_callback=(
            _tracked_stream_callback
            if streaming and stream_callback
            else stream_callback
        ),
        **extra_kwargs,
    )

    if not assistant_response or not assistant_response.strip():
        if streamed_assistant_chunk:
            return assistant_response or ""
        if handler_has_pending_tool_call(api_client):
            return assistant_response or ""
        assistant_response = await api_client.get_response(messages, stream=False)
        if (
            streaming
            and stream_callback
            and assistant_response
            and assistant_response.strip()
        ):
            await _tracked_stream_callback(assistant_response, "assistant")
            replayed_retry_response = True

    if not assistant_response or not assistant_response.strip():
        if handler_has_pending_tool_call(api_client):
            return assistant_response or ""
        provider_error = None
        try:
            getter = getattr(api_client, "get_last_error", None)
            provider_error = getter() if callable(getter) else None
        except Exception:
            provider_error = None
        diagnostics = build_empty_response_diagnostics(
            messages=messages,
            raw_response=assistant_response,
            model_config=model_config,
            provider_error=provider_error,
            handler=getattr(api_client, "client_handler", None),
        )
        raise LLMEmptyResponseError(diagnostics["user_message"])

    if (
        streaming
        and stream_callback
        and assistant_response
        and assistant_response.strip()
        and not streamed_assistant_chunk
        and not replayed_retry_response
    ):
        await _tracked_stream_callback(assistant_response, "assistant")

    return assistant_response


async def execute_pending_tool_call(
    *,
    api_client: Any,
    tool_manager: Any,
    persist_action_result: Callable[[Dict[str, Any], Dict[str, Any]], None],
    emit_action_start: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_action_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_tool_timeline: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> Optional[Dict[str, Any]]:
    """Execute a pending provider-captured tool call using generic hooks."""

    results = await execute_pending_tool_calls(
        api_client=api_client,
        tool_manager=tool_manager,
        persist_action_result=persist_action_result,
        emit_action_start=emit_action_start,
        emit_action_result=emit_action_result,
        emit_tool_timeline=emit_tool_timeline,
    )
    return results[0] if results else None


async def _call_pending_tool_getter(getter: Any) -> Any:
    """Call a sync or async pending-tool getter."""

    if not callable(getter):
        return None
    result = getter()
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _get_and_clear_pending_tool_infos(api_client: Any) -> List[Dict[str, Any]]:
    """Return all provider-captured tool calls from the active handler."""

    try:
        handler = getattr(api_client, "client_handler", None)
        plural_getter = getattr(handler, "get_and_clear_pending_tool_calls", None)
        tool_infos = await _call_pending_tool_getter(plural_getter)
        if isinstance(tool_infos, list):
            return [item for item in tool_infos if isinstance(item, dict)]
        if isinstance(tool_infos, dict):
            return [tool_infos]

        singular_getter = getattr(handler, "get_and_clear_last_tool_call", None)
        tool_info = await _call_pending_tool_getter(singular_getter)
    except Exception:
        return []

    return [tool_info] if isinstance(tool_info, dict) else []


async def execute_pending_tool_calls(
    *,
    api_client: Any,
    tool_manager: Any,
    persist_action_result: Callable[[Dict[str, Any], Dict[str, Any]], None],
    emit_action_start: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_action_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_tool_timeline: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
) -> List[Dict[str, Any]]:
    """Execute all pending provider-captured tool calls using generic hooks."""

    tool_infos = await _get_and_clear_pending_tool_infos(api_client)
    tool_calls = [
        tool_call
        for tool_call in (
            tool_call_from_responses_info(tool_info) for tool_info in tool_infos
        )
        if tool_call is not None
    ]
    if not tool_calls:
        return []

    parsed_args_by_id: Dict[str, Dict[str, Any]] = {}
    raw_args_by_id: Dict[str, str] = {}
    for tool_call in tool_calls:
        raw_args = tool_call.arguments
        raw_args_text = raw_args if isinstance(raw_args, str) else str(raw_args)
        raw_args_by_id[tool_call.id] = raw_args_text
        try:
            import json as _json

            parsed_args = (
                _json.loads(raw_args_text)
                if isinstance(raw_args_text, str) and raw_args_text.strip()
                else {}
            )
        except Exception:
            parsed_args = {}
        if not isinstance(parsed_args, dict):
            parsed_args = {}
        parsed_args_by_id[tool_call.id] = parsed_args

    visible_tool_calls = [
        tool_call for tool_call in tool_calls if tool_call.name != "finish_response"
    ]

    event_metadata = {
        "provider": getattr(
            getattr(api_client, "model_config", None), "provider", None
        ),
        "model": getattr(getattr(api_client, "model_config", None), "model", None),
        "source": "responses_tool_call",
    }

    if emit_action_start is not None:
        for tool_call in visible_tool_calls:
            await emit_action_start(
                {
                    "id": tool_call.id,
                    "type": tool_call.name,
                    "action": tool_call.name,
                    "params": raw_args_by_id.get(tool_call.id, ""),
                    "metadata": event_metadata,
                }
            )

    try:
        scheduler_results = await execute_tool_calls_serially(
            tool_calls,
            lambda current_tool_call: tool_manager.execute_tool(
                current_tool_call.name,
                parsed_args_by_id.get(current_tool_call.id, {}),
            ),
            policy=ToolExecutionPolicy(max_calls=len(tool_calls)),
        )
        if not scheduler_results:
            return []
        action_results: List[Dict[str, Any]] = []
        for tool_result in scheduler_results:
            source_tool_call = next(
                (
                    current_tool_call
                    for current_tool_call in tool_calls
                    if current_tool_call.id == tool_result.call_id
                ),
                None,
            )
            if source_tool_call is None:
                continue
            suppress_ui_artifacts = source_tool_call.name == "finish_response"
            raw_args_text = raw_args_by_id.get(source_tool_call.id, "")
            tool_call_id = source_tool_call.id
            legacy_action_result = legacy_action_result_from_tool_result(tool_result)
            runtime_action_result = {
                **legacy_action_result,
                "tool_call_id": source_tool_call.id,
                "tool_arguments": raw_args_text,
                "output_hash": tool_result.output_hash,
            }
            if not suppress_ui_artifacts:
                persist_action_result(
                    legacy_action_result,
                    {
                        "tool_call_id": tool_call_id,
                        "tool_arguments": runtime_action_result["tool_arguments"],
                    },
                )

            if emit_action_result is not None and not suppress_ui_artifacts:
                await emit_action_result(
                    {
                        "id": tool_call_id,
                        "status": legacy_action_result["status"],
                        "result": legacy_action_result["result"],
                        "action": legacy_action_result["action"],
                        "metadata": event_metadata,
                    }
                )
            if emit_tool_timeline is not None and not suppress_ui_artifacts:
                await emit_tool_timeline(legacy_action_result)
            action_results.append(
                legacy_action_result if suppress_ui_artifacts else runtime_action_result
            )
        return action_results
    except Exception as exc:
        if emit_action_result is not None:
            for tool_call in visible_tool_calls:
                await emit_action_result(
                    {
                        "id": tool_call.id,
                        "status": "error",
                        "result": f"Error executing action {tool_call.name}: {exc}",
                        "action": tool_call.name,
                        "metadata": event_metadata,
                    }
                )
        return []


def resolve_reasoning_payload(model_config: Any) -> Optional[Dict[str, Any]]:
    """Return normalized reasoning payload from a model config when available."""

    getter = getattr(model_config, "get_reasoning_config", None)
    if not callable(getter):
        return None
    try:
        resolved = getter()
    except Exception:
        return None
    return dict(resolved) if isinstance(resolved, dict) else None


def build_reasoning_visibility_note(
    *,
    include_reasoning: bool,
    reasoning_text: str,
    reasoning_payload: Optional[Dict[str, Any]],
    usage: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Return no UI note when visible reasoning is absent."""

    del include_reasoning, reasoning_text, reasoning_payload, usage
    return None


def build_reasoning_debug_snapshot(
    *,
    api_client: Optional[Any],
    session_id: Optional[str],
    request_id: Optional[str],
    model_config: Optional[Any],
    reasoning_payload: Optional[Dict[str, Any]],
    include_reasoning: bool,
    reasoning_text: str,
    reasoning_note: Optional[str],
    usage: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Collect a persisted reasoning debug snapshot for the last request."""

    handler_snapshot: Dict[str, Any] = {}
    finish_reason = None
    if api_client is not None:
        getter = getattr(api_client, "get_reasoning_debug_snapshot", None)
        if callable(getter):
            try:
                resolved = getter()
                if isinstance(resolved, dict):
                    handler_snapshot = dict(resolved)
            except Exception:
                handler_snapshot = {}
        handler = getattr(api_client, "client_handler", None)
        finish_getter = getattr(handler, "get_last_finish_reason", None)
        if callable(finish_getter):
            try:
                finish_value = finish_getter()
                finish_reason = (
                    finish_value.value
                    if hasattr(finish_value, "value")
                    else str(finish_value)
                )
            except Exception:
                finish_reason = None

    return {
        "session_id": session_id,
        "request_id": request_id,
        "provider": getattr(model_config, "provider", None),
        "model": getattr(model_config, "model", None),
        "include_reasoning": include_reasoning,
        "reasoning_requested": bool(
            isinstance(reasoning_payload, dict) and reasoning_payload
        ),
        "reasoning_payload": dict(reasoning_payload or {}),
        "reasoning_text": reasoning_text,
        "reasoning_len": len(reasoning_text or ""),
        "reasoning_note": reasoning_note,
        "usage": dict(usage or {}),
        "finish_reason": finish_reason,
        "handler_debug": handler_snapshot,
    }


def persist_reasoning_debug_snapshot(
    core: Any,
    session_id: Optional[str],
    snapshot: Optional[Dict[str, Any]],
) -> None:
    """Persist latest reasoning debug snapshot for inspection."""

    if not isinstance(session_id, str) or not session_id.strip():
        return
    if not isinstance(snapshot, dict) or not snapshot:
        return
    snapshot_store = getattr(core, "_reasoning_debug_snapshots", None)
    if not isinstance(snapshot_store, dict):
        snapshot_store = {}
        setattr(core, "_reasoning_debug_snapshots", snapshot_store)
    snapshot_store[session_id] = dict(snapshot)


def build_reasoning_fallback_note(
    api_client: Any, usage: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Return no fallback note when visible reasoning is absent."""

    del api_client, usage
    return None


def apply_reasoning_variant_override(
    model_config: Any, variant: Optional[str]
) -> Optional[Dict[str, Any]]:
    """Apply a temporary reasoning variant override to a model config."""

    if model_config is None:
        return None

    value = variant.strip().lower() if isinstance(variant, str) else ""
    if not value:
        return None

    snapshot = {
        "reasoning_enabled": getattr(model_config, "reasoning_enabled", False),
        "reasoning_effort": getattr(model_config, "reasoning_effort", None),
        "reasoning_max_tokens": getattr(model_config, "reasoning_max_tokens", None),
        "reasoning_exclude": getattr(model_config, "reasoning_exclude", False),
        "supports_reasoning": getattr(model_config, "supports_reasoning", None),
        "_has_supports_reasoning": hasattr(model_config, "supports_reasoning"),
    }

    if value in _REASONING_DISABLE_VARIANTS:
        model_config.reasoning_enabled = False
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        return snapshot

    provider_id = str(getattr(model_config, "provider", "") or "").strip().lower()
    model_id = str(getattr(model_config, "model", "") or "").strip()

    if provider_id in {"openai", "anthropic"}:
        supported_native_variants = set(native_reasoning_efforts(provider_id, model_id))
        if value not in supported_native_variants:
            return None

        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_EFFORT_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_MAX_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = 32000
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    return None


def restore_reasoning_variant_override(
    model_config: Any, snapshot: Optional[Dict[str, Any]]
) -> None:
    """Restore model config reasoning settings from a snapshot."""

    if model_config is None or not isinstance(snapshot, dict):
        return

    model_config.reasoning_enabled = bool(snapshot.get("reasoning_enabled", False))
    model_config.reasoning_effort = snapshot.get("reasoning_effort")
    model_config.reasoning_max_tokens = snapshot.get("reasoning_max_tokens")
    model_config.reasoning_exclude = bool(snapshot.get("reasoning_exclude", False))
    if snapshot.get("_has_supports_reasoning"):
        model_config.supports_reasoning = snapshot.get("supports_reasoning")
    elif hasattr(model_config, "supports_reasoning"):
        try:
            delattr(model_config, "supports_reasoning")
        except Exception:
            pass


__all__ = [
    "apply_reasoning_variant_override",
    "build_empty_response_diagnostics",
    "build_reasoning_debug_snapshot",
    "build_reasoning_fallback_note",
    "build_reasoning_visibility_note",
    "call_with_retry",
    "execute_pending_tool_call",
    "execute_pending_tool_calls",
    "handler_has_pending_tool_call",
    "persist_reasoning_debug_snapshot",
    "prepare_native_tool_kwargs",
    "prepare_responses_tool_kwargs",
    "resolve_reasoning_payload",
    "restore_reasoning_variant_override",
]
