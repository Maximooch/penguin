"""OpenRouter direct-stream usage recovery regressions."""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional, cast

import pytest

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


def test_extract_generation_id_from_chunk_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    assert (
        gateway._extract_generation_id_from_chunk({"generation_id": "gen-123"})
        == "gen-123"
    )
    assert gateway._extract_generation_id_from_chunk({"id": "gen-456"}) == "gen-456"
    assert gateway._extract_generation_id_from_chunk({"id": "chatcmpl-1"}) is None


@pytest.mark.asyncio
async def test_direct_stream_interrupt_recovers_usage_from_generation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="high",
            interrupt_on_action=True,
        )
    )

    stream_chunk = {
        "id": "chatcmpl-test",
        "choices": [
            {
                "delta": {"content": "I will check. <execute>pwd</execute>"},
                "finish_reason": None,
            }
        ],
    }
    stream_lines = [f"data: {json.dumps(stream_chunk)}", "data: [DONE]"]
    generation_payload = {
        "data": {
            "id": "gen-test-123",
            "tokens_prompt": 8164,
            "tokens_completion": 0,
            "native_tokens_reasoning": 0,
            "native_tokens_cached": 0,
            "usage": 0,
            "total_cost": 0,
        }
    }

    class _StreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers: Dict[str, str] = {
                "x-openrouter-generation-id": "gen-test-123"
            }

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            for line in stream_lines:
                yield line

    class _StreamContext:
        def __init__(self, response: _StreamResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _StreamResponse:
            return self._response

        async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc: Optional[BaseException],
            tb: Optional[Any],
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _GetResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.content = json.dumps(generation_payload).encode("utf-8")

        def json(self) -> Dict[str, Any]:
            return generation_payload

    class _Client:
        def __init__(self) -> None:
            self.get_calls = 0

        def stream(
            self, method: str, url: str, headers: Dict[str, str], json: Dict[str, Any]
        ):
            del method, url, headers, json
            return _StreamContext(_StreamResponse())

        async def get(
            self,
            url: str,
            headers: Dict[str, str],
            params: Dict[str, str],
            timeout: Any,
        ) -> _GetResponse:
            del url, headers, params, timeout
            self.get_calls += 1
            return _GetResponse()

    chunks: list[tuple[str, str]] = []

    async def _callback(chunk: str, message_type: str = "assistant") -> None:
        chunks.append((chunk, message_type))

    client = _Client()
    result = await gateway._handle_streaming_response(
        client=cast(Any, client),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=cast(Any, _callback),
    )

    assert "<execute>pwd</execute>" in result
    assert chunks
    assert client.get_calls == 1

    usage = gateway.get_last_usage()
    assert usage["input_tokens"] == 8164
    assert usage["output_tokens"] == 0
    assert usage["reasoning_tokens"] == 0
    assert usage["cache_read_tokens"] == 0
    assert usage["total_tokens"] == 8164


@pytest.mark.asyncio
async def test_sdk_stream_stall_returns_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "0.01")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="z-ai/glm-5-turbo",
            provider="openrouter",
            client_preference="openrouter",
            streaming_enabled=True,
        )
    )

    class _HangingStream:
        def __aiter__(self):
            return self

        async def __anext__(self):
            await asyncio.sleep(3600)
            raise StopAsyncIteration

    async def _create_completion(**kwargs: Any):
        del kwargs
        return _HangingStream()

    gateway.client.chat.completions.create = _create_completion  # type: ignore[attr-defined]

    result = await gateway.get_response(
        messages=[{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=lambda *_args: None,
    )

    assert "stream stalled" in result.lower()
    assert "glm-5-turbo" in result


@pytest.mark.asyncio
async def test_direct_stream_stall_returns_timeout_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "test-key")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "0.01")
    gateway = OpenRouterGateway(
        ModelConfig(
            model="anthropic/claude-sonnet-4.5",
            provider="openrouter",
            client_preference="openrouter",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )

    class _StreamResponse:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers: Dict[str, str] = {}

        async def aread(self) -> bytes:
            return b""

        async def aiter_lines(self):
            await asyncio.sleep(3600)
            if False:
                yield ""

    class _StreamContext:
        def __init__(self, response: _StreamResponse) -> None:
            self._response = response

        async def __aenter__(self) -> _StreamResponse:
            return self._response

        async def __aexit__(
            self,
            exc_type: Optional[type[BaseException]],
            exc: Optional[BaseException],
            tb: Optional[Any],
        ) -> bool:
            del exc_type, exc, tb
            return False

    class _Client:
        def stream(
            self, method: str, url: str, headers: Dict[str, str], json: Dict[str, Any]
        ):
            del method, url, headers, json
            return _StreamContext(_StreamResponse())

    result = await gateway._handle_streaming_response(
        client=cast(Any, _Client()),
        url="https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": "Bearer test-key"},
        params={"model": gateway.model_config.model, "messages": []},
        stream_callback=None,
    )

    assert "stream stalled" in result.lower()
    assert "claude-sonnet-4.5" in result
