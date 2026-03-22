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
