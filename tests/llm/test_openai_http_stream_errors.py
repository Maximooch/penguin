"""A provider error event on the OpenAI HTTP stream is reported as that error."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.llm.adapters import openai as openai_adapter
from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.contracts import LLMProviderError
from penguin.llm.model_config import ModelConfig
from tests.llm.codex_oauth_fixtures import (
    FakeResponse,
    FakeStreamContext,
    codex_sse,
    codex_text_delta,
)


class _Http:
    def __init__(self, lines: list[str]) -> None:
        self._lines = lines

    def stream(self, *_args: Any, **_kwargs: Any) -> FakeStreamContext:
        return FakeStreamContext(FakeResponse(200, lines=self._lines))


class _Pool:
    def __init__(self, lines: list[str]) -> None:
        self._http = _Http(lines)

    async def get_client(self, _base_url: str) -> _Http:
        return self._http


def _adapter(monkeypatch: pytest.MonkeyPatch, lines: list[str]) -> OpenAIAdapter:
    monkeypatch.setattr(
        openai_adapter.ConnectionPoolManager,
        "get_instance",
        classmethod(lambda cls: _Pool(lines)),
    )
    return OpenAIAdapter(
        ModelConfig(
            model="gpt-5.6-sol",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
        )
    )


@pytest.mark.asyncio
async def test_error_event_is_raised_as_the_provider_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    adapter = _adapter(
        monkeypatch,
        [
            codex_text_delta("partial"),
            codex_sse(
                {
                    "type": "error",
                    "error": {"message": "insufficient_quota: out of credits"},
                }
            ),
        ],
    )

    with pytest.raises(LLMProviderError) as raised:
        await adapter._stream_with_http({"model": "gpt-5.6-sol", "input": []}, None)

    assert "insufficient_quota" in raised.value.error.message
    assert "ended before response.completed" not in raised.value.error.message


@pytest.mark.asyncio
async def test_malformed_line_is_still_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    adapter = _adapter(
        monkeypatch,
        [
            "data: {not json",
            codex_text_delta("hello"),
            codex_sse({"type": "response.completed", "response": {}}),
        ],
    )

    text = await adapter._stream_with_http({"model": "gpt-5.6-sol", "input": []}, None)

    assert text == "hello"
