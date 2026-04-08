"""Tests for APIClient native model-ID canonicalization."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.llm import api_client as api_client_module
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig


@pytest.mark.parametrize(
    ("provider", "model_name", "expected_model"),
    [
        ("openai", "openai/gpt-5", "gpt-5"),
        ("anthropic", "anthropic/claude-3-7-sonnet-latest", "claude-3-7-sonnet-latest"),
    ],
)
def test_api_client_canonicalizes_native_provider_prefixed_model_ids(
    provider: str,
    model_name: str,
    expected_model: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _DummyAdapter:
        async def get_response(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            return ""

    def _get_adapter(provider_id: str, model_config: ModelConfig) -> _DummyAdapter:
        seen["provider"] = provider_id
        seen["model"] = model_config.model
        return _DummyAdapter()

    monkeypatch.setattr(api_client_module, "get_adapter", _get_adapter)

    cfg = ModelConfig(
        model=model_name,
        provider=provider,
        client_preference="native",
        api_key="test-key",
    )

    APIClient(cfg)

    assert seen["provider"] == provider
    assert seen["model"] == expected_model


@pytest.mark.asyncio
async def test_api_client_surfaces_concise_error_with_upstream_diagnostic_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingAdapter:
        async def get_response(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            raise RuntimeError(
                "OpenAI OAuth Codex request failed "
                "(diag_id=oaoc_deadbeef, status=503) detail=upstream unavailable"
            )

    def _get_adapter(provider_id: str, model_config: ModelConfig) -> _FailingAdapter:
        del provider_id, model_config
        return _FailingAdapter()

    monkeypatch.setattr(api_client_module, "get_adapter", _get_adapter)

    cfg = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="test-key",
    )
    client = APIClient(cfg)

    result = await client.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result == (
        "Error: LLM upstream is unavailable. Diagnostic ID: oaoc_deadbeef."
    )


@pytest.mark.asyncio
async def test_api_client_generates_diagnostic_id_when_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingAdapter:
        async def get_response(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            raise RuntimeError("unexpected failure")

    def _get_adapter(provider_id: str, model_config: ModelConfig) -> _FailingAdapter:
        del provider_id, model_config
        return _FailingAdapter()

    monkeypatch.setattr(api_client_module, "get_adapter", _get_adapter)

    cfg = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="test-key",
    )
    client = APIClient(cfg)

    result = await client.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result.startswith("Error: LLM request failed. Diagnostic ID: llm_")


@pytest.mark.asyncio
async def test_api_client_clamps_output_tokens_to_remaining_context(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    class _CapturingAdapter:
        async def get_response(self, *args: Any, **kwargs: Any) -> str:
            del args
            seen["max_output_tokens"] = kwargs.get("max_output_tokens")
            return "ok"

    def _get_adapter(provider_id: str, model_config: ModelConfig) -> _CapturingAdapter:
        del provider_id, model_config
        return _CapturingAdapter()

    monkeypatch.setattr(api_client_module, "get_adapter", _get_adapter)

    cfg = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="test-key",
        max_output_tokens=202752,
        max_context_window_tokens=204800,
    )
    client = APIClient(cfg)
    monkeypatch.setattr(client, "count_tokens", lambda messages: 10205)

    result = await client.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result == "ok"
    assert seen["max_output_tokens"] == 194083


@pytest.mark.asyncio
async def test_api_client_classifies_context_limit_400_as_upstream_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _FailingAdapter:
        async def get_response(self, *args: Any, **kwargs: Any) -> str:
            del args, kwargs
            raise RuntimeError(
                "Error code: 400 - {'error': {'message': \"This endpoint's maximum context length is 204800 tokens. "
                'However, you requested about 212957 tokens (10205 of text input, 202752 in the output)."}}'
            )

    def _get_adapter(provider_id: str, model_config: ModelConfig) -> _FailingAdapter:
        del provider_id, model_config
        return _FailingAdapter()

    monkeypatch.setattr(api_client_module, "get_adapter", _get_adapter)

    cfg = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="test-key",
    )
    client = APIClient(cfg)

    result = await client.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result.startswith(
        "Error: LLM upstream rejected the request, likely due to context or output token limits. Diagnostic ID:"
    )
