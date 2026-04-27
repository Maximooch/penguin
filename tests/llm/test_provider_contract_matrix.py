from __future__ import annotations

from typing import Any

import pytest

from penguin.llm.contracts import FinishReason

from .provider_contract_fixtures import (
    ANTHROPIC_USAGE,
    OPENAI_USAGE,
    OPENROUTER_USAGE,
    AnthropicStreamChunk,
    AnthropicStreamDelta,
    OpenAIStreamEvent,
    build_anthropic_handler,
    build_openai_handler,
    build_openrouter_handler,
    make_openrouter_chunk,
)


REQUIRED_USAGE_KEYS = {
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost",
}


def _build_handler(
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
    *,
    scenario: str,
) -> Any:
    if provider_id in {"openai", "openai_compatible"}:
        monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
        monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
        if scenario == "nonstream":
            events = [
                OpenAIStreamEvent(type="response.output_text.delta", delta="answer")
            ]
            return build_openai_handler(
                provider=provider_id,
                stream_events=events,
                final_text="answer",
                usage=OPENAI_USAGE,
            )
        if scenario == "stream_text":
            events = [
                OpenAIStreamEvent(type="response.output_text.delta", delta="answer")
            ]
            return build_openai_handler(
                provider=provider_id,
                stream_events=events,
                final_text="answer",
                usage=OPENAI_USAGE,
            )
        if scenario == "reasoning":
            events = [
                OpenAIStreamEvent(
                    type="response.reasoning_summary_text.delta",
                    delta="thinking...",
                ),
                OpenAIStreamEvent(type="response.output_text.delta", delta="answer"),
            ]
            return build_openai_handler(
                provider=provider_id,
                stream_events=events,
                final_text="answer",
                usage=OPENAI_USAGE,
                reasoning_enabled=True,
            )
        if scenario == "tool_call":
            events = [
                OpenAIStreamEvent(
                    type="response.output_item.added",
                    item={
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": "",
                    },
                ),
                OpenAIStreamEvent(
                    type="response.function_call_arguments.delta",
                    item_id="item_1",
                    delta='{"path":"README.md"}',
                ),
                OpenAIStreamEvent(
                    type="response.output_item.done",
                    item={
                        "type": "function_call",
                        "id": "item_1",
                        "call_id": "call_1",
                        "name": "read_file",
                        "arguments": '{"path":"README.md"}',
                        "status": "completed",
                    },
                ),
            ]
            return build_openai_handler(
                provider=provider_id,
                stream_events=events,
                final_text="",
                usage=OPENAI_USAGE,
                interrupt_on_tool_call=True,
            )

    if provider_id == "anthropic":
        if scenario == "nonstream":
            return build_anthropic_handler(
                stream_chunks=[AnthropicStreamChunk("message_stop")],
                final_text="answer",
                usage=ANTHROPIC_USAGE,
            )
        if scenario == "stream_text":
            return build_anthropic_handler(
                stream_chunks=[
                    AnthropicStreamChunk(
                        "content_block_delta",
                        AnthropicStreamDelta("text_delta", text="answer"),
                    ),
                    AnthropicStreamChunk("message_stop"),
                ],
                final_text="answer",
                usage=ANTHROPIC_USAGE,
            )
        if scenario == "reasoning":
            return build_anthropic_handler(
                stream_chunks=[
                    AnthropicStreamChunk(
                        "content_block_delta",
                        AnthropicStreamDelta(
                            "thinking_delta",
                            thinking="thinking...",
                        ),
                    ),
                    AnthropicStreamChunk(
                        "content_block_delta",
                        AnthropicStreamDelta("text_delta", text="answer"),
                    ),
                    AnthropicStreamChunk("message_stop"),
                ],
                final_text="answer",
                usage=ANTHROPIC_USAGE,
                reasoning_enabled=True,
            )
        if scenario == "tool_call":
            return build_anthropic_handler(
                stream_chunks=[
                    AnthropicStreamChunk(
                        "content_block_start",
                        content_block=type(
                            "ToolUseBlock",
                            (),
                            {
                                "type": "tool_use",
                                "id": "toolu_1",
                                "name": "read_file",
                                "input": {"path": "README.md"},
                            },
                        )(),
                    ),
                    AnthropicStreamChunk("message_stop"),
                ],
                final_text="",
                usage=ANTHROPIC_USAGE,
            )

    if provider_id == "openrouter":
        if scenario == "nonstream":
            return build_openrouter_handler(
                monkeypatch,
                stream_chunks=[],
                final_text="answer",
                usage=OPENROUTER_USAGE,
            )
        if scenario == "stream_text":
            return build_openrouter_handler(
                monkeypatch,
                stream_chunks=[
                    make_openrouter_chunk(
                        model="openai/gpt-4.1-mini",
                        content="answer",
                        finish_reason="stop",
                        usage=OPENROUTER_USAGE,
                    )
                ],
                final_text="answer",
                usage=OPENROUTER_USAGE,
            )
        if scenario == "reasoning":
            return build_openrouter_handler(
                monkeypatch,
                stream_chunks=[
                    make_openrouter_chunk(
                        model="arcee-ai/trinity-large-thinking",
                        reasoning="thinking...",
                        usage=OPENROUTER_USAGE,
                    ),
                    make_openrouter_chunk(
                        model="arcee-ai/trinity-large-thinking",
                        content="answer",
                        finish_reason="stop",
                        usage=OPENROUTER_USAGE,
                    ),
                ],
                final_text="answer",
                usage=OPENROUTER_USAGE,
                model_id="arcee-ai/trinity-large-thinking",
                reasoning_enabled=True,
            )
        if scenario == "tool_call":
            return build_openrouter_handler(
                monkeypatch,
                stream_chunks=[
                    make_openrouter_chunk(
                        model="openai/gpt-4.1-mini",
                        tool_calls=[
                            {
                                "id": "call_1",
                                "type": "function",
                                "function": {
                                    "name": "read_file",
                                    "arguments": '{"path":"README.md"}',
                                },
                            }
                        ],
                        usage=OPENROUTER_USAGE,
                    )
                ],
                final_text="",
                usage=OPENROUTER_USAGE,
                interrupt_on_tool_call=True,
            )

    raise AssertionError(f"Unsupported scenario {scenario!r} for {provider_id!r}")


@pytest.mark.parametrize(
    "provider_id",
    ["openai", "openai_compatible", "anthropic", "openrouter"],
)
@pytest.mark.asyncio
async def test_provider_contract_nonstream_usage_matrix(
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _build_handler(provider_id, monkeypatch, scenario="nonstream")

    result = await handler.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result == "answer"
    usage = handler.get_last_usage()
    assert REQUIRED_USAGE_KEYS.issubset(set(usage.keys()))
    assert usage["input_tokens"] > 0
    assert usage["output_tokens"] > 0
    assert usage["total_tokens"] >= usage["input_tokens"] + usage["output_tokens"]
    assert handler.get_last_finish_reason() == FinishReason.STOP
    assert handler.has_pending_tool_call() is False
    assert handler.get_and_clear_last_tool_call() is None
    assert handler.count_tokens("hello") > 0


@pytest.mark.parametrize(
    "provider_id",
    ["openai", "openai_compatible", "anthropic", "openrouter"],
)
@pytest.mark.asyncio
async def test_provider_contract_streaming_callback_matrix(
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _build_handler(provider_id, monkeypatch, scenario="stream_text")
    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await handler.get_response(
        [{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == "answer"
    assert chunks == [("answer", "assistant")]


@pytest.mark.parametrize(
    "provider_id",
    ["openai", "openai_compatible", "anthropic", "openrouter"],
)
@pytest.mark.asyncio
async def test_provider_contract_reasoning_stream_matrix(
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _build_handler(provider_id, monkeypatch, scenario="reasoning")
    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await handler.get_response(
        [{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == "answer"
    assert chunks[0] == ("thinking...", "reasoning")
    assert chunks[1] == ("answer", "assistant")
    assert handler.get_last_reasoning() == "thinking..."


@pytest.mark.parametrize(
    "provider_id",
    ["openai", "openai_compatible", "anthropic", "openrouter"],
)
@pytest.mark.asyncio
async def test_provider_contract_tool_call_interrupt_matrix(
    provider_id: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = _build_handler(provider_id, monkeypatch, scenario="tool_call")
    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await handler.get_response(
        [{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=on_chunk,
    )

    assert result == ""
    assert chunks == []
    assert handler.get_last_finish_reason() == FinishReason.TOOL_CALLS
    assert handler.has_pending_tool_call() is True
    tool_call = handler.get_and_clear_last_tool_call()
    assert tool_call is not None
    assert tool_call["name"] == "read_file"
    assert tool_call["arguments"] == '{"path":"README.md"}'
    assert handler.get_and_clear_last_tool_call() is None


@pytest.mark.asyncio
async def test_openrouter_preserves_multiple_pending_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = build_openrouter_handler(
        monkeypatch,
        stream_chunks=[
            make_openrouter_chunk(
                model="openai/gpt-4.1-mini",
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    },
                    {
                        "index": 1,
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "list_files",
                            "arguments": '{"path":"."}',
                        },
                    },
                ],
                finish_reason="tool_calls",
                usage=OPENROUTER_USAGE,
            )
        ],
        final_text="",
        usage=OPENROUTER_USAGE,
        interrupt_on_tool_call=True,
    )

    result = await handler.get_response(
        [{"role": "user", "content": "inspect files"}],
        stream=True,
        stream_callback=lambda *_args: None,
    )

    assert result == ""
    assert handler.has_pending_tool_call() is True
    pending = handler.get_and_clear_pending_tool_calls()
    assert [tool_call["name"] for tool_call in pending] == [
        "read_file",
        "list_files",
    ]


@pytest.mark.asyncio
async def test_openrouter_deduplicates_fragmented_stream_tool_calls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    handler = build_openrouter_handler(
        monkeypatch,
        stream_chunks=[
            make_openrouter_chunk(
                model="openai/gpt-4.1-mini",
                tool_calls=[
                    {
                        "index": 0,
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":',
                        },
                    }
                ],
            ),
            make_openrouter_chunk(
                model="openai/gpt-4.1-mini",
                tool_calls=[
                    {
                        "index": 0,
                        "type": "function",
                        "function": {
                            "arguments": '"README.md"}',
                        },
                    }
                ],
                finish_reason="tool_calls",
                usage=OPENROUTER_USAGE,
            ),
        ],
        final_text="",
        usage=OPENROUTER_USAGE,
        interrupt_on_tool_call=True,
    )

    result = await handler.get_response(
        [{"role": "user", "content": "inspect README"}],
        stream=True,
        stream_callback=lambda *_args: None,
    )

    assert result == ""
    assert handler.has_pending_tool_call() is True
    pending = handler.get_and_clear_pending_tool_calls()
    assert pending == [
        {
            "item_id": None,
            "call_id": "call_1",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    ]


def test_anthropic_formats_tool_transcript() -> None:
    handler = build_anthropic_handler(
        stream_chunks=[AnthropicStreamChunk("message_stop")],
        final_text="answer",
        usage=ANTHROPIC_USAGE,
    )

    formatted = handler.format_messages(
        [
            {"role": "user", "content": "read README"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "toolu_1",
                "content": "# README",
            },
        ]
    )

    assert formatted[1] == {
        "role": "assistant",
        "content": [
            {
                "type": "tool_use",
                "id": "toolu_1",
                "name": "read_file",
                "input": {"path": "README.md"},
            }
        ],
    }
    assert formatted[2] == {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": "toolu_1",
                "content": "# README",
            }
        ],
    }


def test_anthropic_repairs_orphaned_tool_result_adjacency() -> None:
    handler = build_anthropic_handler(
        stream_chunks=[AnthropicStreamChunk("message_stop")],
        final_text="answer",
        usage=ANTHROPIC_USAGE,
    )

    formatted = handler.format_messages(
        [
            {"role": "user", "content": "howdy"},
            {
                "role": "assistant",
                "content": "Howdy!",
                "tool_calls": [
                    {
                        "id": "toolu_1",
                        "type": "function",
                        "function": {
                            "name": "shell",
                            "arguments": '{"command":"pwd"}',
                        },
                    }
                ],
            },
            {"role": "user", "content": "what dir are you in?"},
            {
                "role": "tool",
                "tool_call_id": "toolu_1",
                "name": "shell",
                "tool_arguments": '{"command":"pwd"}',
                "content": "/tmp/project",
            },
        ]
    )

    assert formatted == [
        {"role": "user", "content": [{"type": "text", "text": "howdy"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Howdy!"}]},
        {
            "role": "user",
            "content": [{"type": "text", "text": "what dir are you in?"}],
        },
        {
            "role": "assistant",
            "content": [
                {
                    "type": "tool_use",
                    "id": "toolu_1",
                    "name": "shell",
                    "input": {"command": "pwd"},
                }
            ],
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "tool_result",
                    "tool_use_id": "toolu_1",
                    "content": "/tmp/project",
                }
            ],
        },
    ]
