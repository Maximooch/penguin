"""OpenAI Responses wire translation for LinkProvider."""

from __future__ import annotations

from typing import Any

from ...contracts import FinishReason, LLMToolCall, LLMUsage


def build_responses_body(
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
    """Translate Penguin messages into a text-only Responses request."""

    instructions: list[str] = []
    items: list[dict[str, Any]] = []
    for message_index, message in enumerate(messages):
        role = str(message.get("role") or "user")
        content = message.get("content")
        if role == "system":
            _require_text_content(content)
            instructions.append(content)
            continue
        if role == "tool":
            _require_text_content(content)
            call_id = str(message.get("tool_call_id") or "").strip()
            if not call_id:
                raise ValueError("Tool results sent through Link require tool_call_id.")
            items.append(
                {
                    "type": "function_call_output",
                    "call_id": call_id,
                    "output": content,
                }
            )
            continue
        if role not in {"user", "assistant"}:
            raise ValueError(f"Unsupported Link Responses message role: {role}")
        if role == "user":
            _require_text_content(content)
            items.append(_message_item(role, content))
            continue

        assistant_has_output = False
        if isinstance(content, str):
            items.append(_assistant_message_item(content, message_index))
            assistant_has_output = True
        elif content is not None:
            _require_text_content(content)

        tool_calls = message.get("tool_calls")
        if isinstance(tool_calls, list):
            for tool_call in tool_calls:
                if not isinstance(tool_call, dict):
                    raise ValueError(
                        "Assistant tool calls sent through Link are invalid."
                    )
                function = tool_call.get("function")
                if not isinstance(function, dict):
                    raise ValueError(
                        "Assistant tool calls sent through Link are invalid."
                    )
                call_id = str(tool_call.get("id") or "").strip()
                name = str(function.get("name") or "").strip()
                if not call_id or not name:
                    raise ValueError(
                        "Assistant tool calls sent through Link require an id and name."
                    )
                arguments = function.get("arguments")
                if arguments is not None and not isinstance(arguments, str):
                    raise ValueError(
                        "Assistant tool-call arguments sent through Link must be text."
                    )
                items.append(
                    {
                        "type": "function_call",
                        "call_id": call_id,
                        "name": name,
                        "arguments": arguments or "{}",
                    }
                )
                assistant_has_output = True
        if not assistant_has_output:
            raise ValueError(
                "Assistant history sent through Link requires text or tool calls."
            )

    body: dict[str, Any] = {
        "model": model,
        "input": items,
        "max_output_tokens": max_output_tokens,
        "stream": stream,
    }
    if instructions:
        body["instructions"] = "\n\n".join(instructions)
    if temperature is not None:
        body["temperature"] = temperature
    if tools:
        body["tools"] = tools
    if tool_choice is not None:
        body["tool_choice"] = tool_choice
    if reasoning is not None:
        body["reasoning"] = reasoning
    return body


def _require_text_content(content: Any) -> None:
    if not isinstance(content, str):
        raise ValueError(
            "Link-managed inference supports text messages only until "
            "multimodal metering is enabled."
        )


def _message_item(role: str, content: str) -> dict[str, Any]:
    return {
        "role": role,
        "content": [
            {
                "type": "input_text" if role == "user" else "output_text",
                "text": content,
            }
        ],
    }


def _assistant_message_item(content: str, message_index: int) -> dict[str, Any]:
    return {
        "type": "message",
        "id": f"msg_link_history_{message_index}",
        "status": "completed",
        "role": "assistant",
        "content": [{"type": "output_text", "text": content}],
    }


def parse_responses_body(
    payload: dict[str, Any],
) -> tuple[str, str, list[LLMToolCall], LLMUsage, FinishReason, dict[str, Any]]:
    """Normalize one buffered Responses result."""

    text_parts: list[str] = []
    reasoning_parts: list[str] = []
    tool_calls: list[LLMToolCall] = []
    output = payload.get("output")
    if isinstance(payload.get("output_text"), str):
        text_parts.append(payload["output_text"])
    if isinstance(output, list):
        for item in output:
            if not isinstance(item, dict):
                continue
            item_type = item.get("type")
            if item_type == "function_call":
                tool_calls.append(
                    LLMToolCall(
                        name=str(item.get("name") or ""),
                        arguments=str(item.get("arguments") or "{}"),
                        call_id=str(item.get("call_id") or "") or None,
                        item_id=str(item.get("id") or "") or None,
                    )
                )
                continue
            content = item.get("content")
            if not isinstance(content, list):
                continue
            for part in content:
                if not isinstance(part, dict):
                    continue
                value = part.get("text")
                if not isinstance(value, str):
                    continue
                if part.get("type") in {"reasoning_text", "summary_text"}:
                    reasoning_parts.append(value)
                else:
                    text_parts.append(value)

    usage = normalize_responses_usage(payload.get("usage"))
    status = str(payload.get("status") or "completed")
    incomplete_details = payload.get("incomplete_details")
    raw_incomplete_reason = (
        incomplete_details.get("reason")
        if isinstance(incomplete_details, dict)
        else None
    )
    incomplete_reason = (
        raw_incomplete_reason.strip().lower()
        if isinstance(raw_incomplete_reason, str) and raw_incomplete_reason.strip()
        else None
    )
    finish = (
        FinishReason.TOOL_CALLS
        if tool_calls
        else (
            FinishReason.STOP
            if status == "completed"
            else FinishReason.LENGTH
            if status == "incomplete" and incomplete_reason == "max_output_tokens"
            else FinishReason.UNKNOWN
        )
    )
    return (
        "".join(text_parts),
        "".join(reasoning_parts),
        tool_calls,
        usage,
        finish,
        {
            "response_id": payload.get("id"),
            "status": status,
            "incomplete_reason": incomplete_reason,
        },
    )


def normalize_responses_usage(value: Any) -> LLMUsage:
    usage = value if isinstance(value, dict) else {}
    input_details = usage.get("input_tokens_details")
    output_details = usage.get("output_tokens_details")
    input_details = input_details if isinstance(input_details, dict) else {}
    output_details = output_details if isinstance(output_details, dict) else {}
    return LLMUsage(
        input_tokens=_int(usage.get("input_tokens")),
        output_tokens=_int(usage.get("output_tokens")),
        reasoning_tokens=_int(output_details.get("reasoning_tokens")),
        cache_read_tokens=_int(input_details.get("cached_tokens")),
        total_tokens=_int(usage.get("total_tokens")),
        provider_data=dict(usage),
    )


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


__all__ = ["build_responses_body", "normalize_responses_usage", "parse_responses_body"]
