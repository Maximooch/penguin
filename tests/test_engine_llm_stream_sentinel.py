"""Engine._llm_stream always ends: with every chunk, or with the error (SM-18)."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.engine import Engine


class _Conversation:
    def __init__(self) -> None:
        self.saved: list[str] = []

    def prepare_conversation(self, prompt: str) -> None:
        self.prompt = prompt

    def get_formatted_messages(self) -> list[dict[str, str]]:
        return [{"role": "user", "content": self.prompt}]

    def add_assistant_message(self, text: str) -> None:
        self.saved.append(text)


def _engine(api_client: Any) -> tuple[Engine, _Conversation]:
    conversation = _Conversation()
    manager = SimpleNamespace(conversation=conversation, save=lambda: None)
    engine = Engine.__new__(Engine)
    engine._resolve_components = lambda _agent: (manager, api_client, None, None)
    engine._apply_agent_mode_notice = lambda messages: messages
    return engine, conversation


async def _collect(engine: Engine) -> list[str]:
    return [chunk async for chunk in engine._llm_stream("hi", agent_id="default")]


@pytest.mark.asyncio
async def test_provider_failure_ends_the_stream_with_the_error() -> None:
    class _Failing:
        async def get_response(self, *_args: Any, **_kwargs: Any) -> str:
            raise RuntimeError("provider down")

    engine, _ = _engine(_Failing())

    with pytest.raises(RuntimeError, match="provider down"):
        await asyncio.wait_for(_collect(engine), timeout=2)


@pytest.mark.asyncio
async def test_every_chunk_arrives_before_the_stream_ends() -> None:
    class _Streaming:
        async def get_response(
            self, _messages: Any, *, stream: bool, stream_callback: Any
        ) -> str:
            for chunk in ("a", "b", "c"):
                stream_callback(chunk)
            return "abc"

    engine, conversation = _engine(_Streaming())

    chunks = await asyncio.wait_for(_collect(engine), timeout=2)

    assert chunks == ["a", "b", "c"]
    assert conversation.saved == ["abc"]
