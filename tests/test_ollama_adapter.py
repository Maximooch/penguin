import sys
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def mock_tiktoken(monkeypatch):
    mock_encoding = MagicMock()
    mock_encoding.encode = lambda s: list(range(len(str(s))))
    monkeypatch.setattr("tiktoken.get_encoding", lambda _: mock_encoding)

    # Reload diagnostics to apply patch before adapter import
    import importlib

    import penguin.utils.diagnostics as diagnostics_module
    importlib.reload(diagnostics_module)

    yield

    importlib.reload(diagnostics_module)


@pytest.fixture(autouse=True)
def stub_penguin_modules(monkeypatch):
    import types
    # Provide minimal stubs to satisfy package imports
    monkeypatch.setitem(
        sys.modules,
        "penguin.penguin.core",
        types.ModuleType("penguin.penguin.core"),
    )
    monkeypatch.setitem(
        sys.modules, "penguin.config", types.ModuleType("penguin.config")
    )
    yield



@pytest.mark.asyncio
async def test_ollama_adapter_get_response_non_stream():
    import importlib.util
    from pathlib import Path

    adapter_spec = importlib.util.spec_from_file_location(
        "ollama_adapter",
        Path(__file__).resolve().parent.parent / "penguin/llm/adapters/ollama.py",
    )
    adapter_mod = importlib.util.module_from_spec(adapter_spec)
    assert adapter_spec and adapter_spec.loader
    adapter_spec.loader.exec_module(adapter_mod)
    OllamaAdapter = adapter_mod.OllamaAdapter

    model_config_spec = importlib.util.spec_from_file_location(
        "model_config",
        Path(__file__).resolve().parent.parent / "penguin/llm/model_config.py",
    )
    model_mod = importlib.util.module_from_spec(model_config_spec)
    assert model_config_spec and model_config_spec.loader
    model_config_spec.loader.exec_module(model_mod)
    ModelConfig = model_mod.ModelConfig

    model_config = ModelConfig(model="mistral", provider="ollama")
    adapter = OllamaAdapter(model_config)

    fake_response = {"message": {"content": "hello"}}

    with patch.object(
        adapter.client,
        "chat",
        AsyncMock(return_value=fake_response),
    ) as mock_chat:
        result = await adapter.get_response([
            {"role": "user", "content": "hi"}
        ])
        assert result == "hello"
        mock_chat.assert_awaited_once()


@pytest.mark.asyncio
async def test_ollama_adapter_get_response_stream():
    import importlib.util
    from pathlib import Path

    adapter_spec = importlib.util.spec_from_file_location(
        "ollama_adapter",
        Path(__file__).resolve().parent.parent / "penguin/llm/adapters/ollama.py",
    )
    adapter_mod = importlib.util.module_from_spec(adapter_spec)
    assert adapter_spec and adapter_spec.loader
    adapter_spec.loader.exec_module(adapter_mod)
    OllamaAdapter = adapter_mod.OllamaAdapter

    model_config_spec = importlib.util.spec_from_file_location(
        "model_config",
        Path(__file__).resolve().parent.parent / "penguin/llm/model_config.py",
    )
    model_mod = importlib.util.module_from_spec(model_config_spec)
    assert model_config_spec and model_config_spec.loader
    model_config_spec.loader.exec_module(model_mod)
    ModelConfig = model_mod.ModelConfig

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
