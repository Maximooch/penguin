from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin.llm.adapters.ollama import OllamaAdapter
from penguin.llm.model_config import ModelConfig


@pytest.fixture(autouse=True)
def mock_tiktoken(monkeypatch):
    mock_encoding = MagicMock()
    mock_encoding.encode = lambda s: list(range(len(str(s))))
    monkeypatch.setattr("tiktoken.get_encoding", lambda _: mock_encoding)

    # Reload diagnostics to apply patch before adapter import
    import importlib

    diagnostics_module = importlib.import_module("penguin.utils.diagnostics")
    importlib.reload(diagnostics_module)

    yield

    importlib.reload(diagnostics_module)

@pytest.mark.asyncio
async def test_ollama_adapter_get_response_non_stream():
    model_config = ModelConfig(model="mistral", provider="ollama")
    adapter = OllamaAdapter(model_config)

    fake_response = {"message": {"content": "hello"}}

    with patch.object(
        adapter.client,
        "chat",
        AsyncMock(return_value=fake_response),
    ) as mock_chat:
        result = await adapter.get_response([{"role": "user", "content": "hi"}])
        assert result == "hello"
        mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_adapter_get_response_stream():
    model_config = ModelConfig(model="mistral", provider="ollama")
    adapter = OllamaAdapter(model_config)

    async def stream_gen(*args, **kwargs):
        for part in [
            {"message": {"content": "hel"}},
            {"message": {"content": "lo"}},
        ]:
            yield part

    with patch.object(
        adapter.client,
        "chat",
        AsyncMock(return_value=stream_gen()),
    ) as mock_chat:
        collected = []

        async def cb(chunk: str):
            collected.append(chunk)

        result = await adapter.get_response(
            [{"role": "user", "content": "hi"}],
            stream=True,
            stream_callback=cb,
        )
        assert result == "hello"
        assert collected == ["hel", "lo"]
        mock_chat.assert_awaited_once()
