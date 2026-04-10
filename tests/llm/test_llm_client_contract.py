from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.llm.client import LLMClient
from penguin.llm.model_config import ModelConfig


@pytest.mark.asyncio
async def test_llm_client_count_tokens_accepts_sync_gateway_counter() -> None:
    client = LLMClient(
        ModelConfig(
            model="openai/gpt-4o",
            provider="openrouter",
            client_preference="openrouter",
        )
    )
    client._get_gateway = lambda: SimpleNamespace(count_tokens=lambda _messages: 42)  # type: ignore[method-assign]

    result = await client.count_tokens([{"role": "user", "content": "hello"}])

    assert result == 42
