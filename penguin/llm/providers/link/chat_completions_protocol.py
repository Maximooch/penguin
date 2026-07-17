"""Chat Completions wire translation for LinkProvider."""

from __future__ import annotations

from typing import Any

from ...contracts import FinishReason, LLMToolCall, LLMUsage
from ...provider_transform import normalize_finish_reason


def build_chat_completions_body(
    *,
    model: str,
    messages: list[dict[str, Any]],
    max_output_tokens: int,
    temperature: float | None,
    stream: bool,
    tools: list[dict[str, Any]] | None = None,
    tool_choice: Any = None,
    reasoning: Any = None,
) -> dict[str, Any]:
    """Build a text-only Chat Completions request."""

    for message in messages:
        if not isinstance(message.get("content"), str) and not (
            message.get("role") == "assistant" and message.get("content") is None
        ):
            raise ValueError(
                "Link-managed inference supports text messages only until "
                "multimodal metering is enabled."
            )
    body: dict[str, Any] = {
        "model": model,
        "messages": messages,
        "max_completion_tokens": max_output_tokens,
        "stream": stream,
    }
    if stream:
        body["stream_options"] = {"include_usage": True}
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if reasoning is not None:
        body["reasoning"] = reasoning
    return body


def parse_chat_completions_body(
    payload: dict[str, Any],
) -> tuple[str, str, list[LLMToolCall], LLMUsage, FinishReason, dict[str, Any]]:
    choices = payload.get("choices")
    choice = choices[0] if isinstance(choices, list) and choices else {}
    choice = choice if isinstance(choice, dict) else {}
    message = choice.get("message")
    message = message if isinstance(message, dict) else {}
    text = message.get("content") if isinstance(message.get("content"), str) else ""
    reasoning = message.get("reasoning")
    reasoning = reasoning if isinstance(reasoning, str) else ""
    tool_calls: list[LLMToolCall] = []
    raw_tool_calls = message.get("tool_calls")
    if isinstance(raw_tool_calls, list):
        for raw in raw_tool_calls:
            function = raw.get("function") if isinstance(raw, dict) else None
            if not isinstance(function, dict):
                continue
            tool_calls.append(
                LLMToolCall(
                    name=str(function.get("name") or ""),
                    arguments=str(function.get("arguments") or "{}"),
                    call_id=str(raw.get("id") or "") or None,
                )
            )
    usage = normalize_chat_usage(payload.get("usage"))
    finish = normalize_finish_reason(choice.get("finish_reason"))
    return (
        text,
        reasoning,
        tool_calls,
        usage,
        finish,
        {"response_id": payload.get("id")},
    )


def normalize_chat_usage(value: Any) -> LLMUsage:
    usage = value if isinstance(value, dict) else {}
    prompt_details = usage.get("prompt_tokens_details")
    completion_details = usage.get("completion_tokens_details")
    prompt_details = prompt_details if isinstance(prompt_details, dict) else {}
    completion_details = (
        completion_details if isinstance(completion_details, dict) else {}
    )
    return LLMUsage(
        input_tokens=_int(usage.get("prompt_tokens")),
        output_tokens=_int(usage.get("completion_tokens")),
        reasoning_tokens=_int(completion_details.get("reasoning_tokens")),
        cache_read_tokens=_int(prompt_details.get("cached_tokens")),
        total_tokens=_int(usage.get("total_tokens")),
        provider_data=dict(usage),
    )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = [
    "build_chat_completions_body",
    "normalize_chat_usage",
    "parse_chat_completions_body",
]
