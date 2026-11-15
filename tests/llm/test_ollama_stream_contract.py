"""Ollama streams through APIClient's callback and reports why it stopped.

Covers SM-82: the adapter called the stream callback with one argument, but
APIClient passes one that takes ``(chunk, message_type)``, so streaming failed
on the first token; ``done_reason`` was ignored, so a reply cut short by
``num_predict`` read as complete; an empty stream raised ``UnboundLocalError``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, patch

import pytest

from penguin.llm.adapters.ollama import OllamaAdapter
from penguin.llm.contracts import FinishReason
from penguin.llm.model_config import ModelConfig
from penguin.utils.callbacks import adapt_stream_callback


def _stream(*chunks: dict[str, Any]) -> Any:
    async def generate() -> Any:
        for chunk in chunks:
            yield chunk

    return generate()


@pytest.mark.asyncio
async def test_stream_through_the_api_client_callback() -> None:
    adapter = OllamaAdapter(ModelConfig(model="mistral", provider="ollama"))
    received: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        received.append((chunk, message_type))

    chunks = _stream(
        {"message": {"content": "hel"}, "done": False},
        {"message": {"content": "lo"}, "done": True, "done_reason": "length"},
    )
    with patch.object(adapter.client, "chat", AsyncMock(return_value=chunks)):
        text = await adapter.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
            stream_callback=adapt_stream_callback(on_chunk),
        )

    assert text == "hello"
    assert received == [("hel", "assistant"), ("lo", "assistant")]
    assert adapter.get_last_finish_reason() is FinishReason.LENGTH


@pytest.mark.asyncio
async def test_a_stream_that_never_finishes_is_not_a_stop() -> None:
    adapter = OllamaAdapter(ModelConfig(model="mistral", provider="ollama"))

    with patch.object(adapter.client, "chat", AsyncMock(return_value=_stream())):
        text = await adapter.get_response(
            [{"role": "user", "content": "hi"}], stream=True
        )

    assert text == ""
    assert adapter.get_last_finish_reason() is FinishReason.UNKNOWN


@pytest.mark.asyncio
async def test_a_non_streamed_reply_reports_its_finish_reason() -> None:
    adapter = OllamaAdapter(ModelConfig(model="mistral", provider="ollama"))
    reply = {"message": {"content": "done"}, "done": True, "done_reason": "stop"}

    with patch.object(adapter.client, "chat", AsyncMock(return_value=reply)):
        await adapter.get_response([{"role": "user", "content": "hi"}])

    assert adapter.get_last_finish_reason() is FinishReason.STOP
