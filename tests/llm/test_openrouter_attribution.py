"""OpenRouter attribution defaults and existing override contracts."""

from types import SimpleNamespace

import pytest

from penguin.llm.model_config import ModelConfig
from penguin.llm.openrouter_gateway import OpenRouterGateway


@pytest.fixture
def gateway_factory(monkeypatch):
    for name in (
        "OPENROUTER_SITE_URL",
        "OPENROUTER_SITE_TITLE",
        "OPENROUTER_BASE_URL",
        "PENGUIN_OPENROUTER_BASE_URL",
    ):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(
        "penguin.llm.adapters.openrouter.AsyncOpenAI",
        lambda **kwargs: SimpleNamespace(**kwargs),
    )
    config = ModelConfig(
        model="openai/gpt-4o",
        provider="openrouter",
        client_preference="openrouter",
        api_key="fixture-key",
    )
    return lambda **kwargs: OpenRouterGateway(config, **kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize("stream", [False, True])
async def test_penguin_attribution_in_prepared_requests(gateway_factory, stream):
    gateway = gateway_factory()
    expected = {"HTTP-Referer": "https://penguinagents.com", "X-Title": "Penguin"}
    assert gateway.extra_headers == expected
    request = await gateway.prepare_request(
        [{"role": "user", "content": "Hello"}],
        stream=stream,
    )
    assert request.headers == expected
    assert "extra_headers" not in request.body


def test_environment_and_constructor_overrides(gateway_factory, monkeypatch):
    monkeypatch.setenv("OPENROUTER_SITE_URL", "https://example.org")
    monkeypatch.setenv("OPENROUTER_SITE_TITLE", "Custom app")
    assert gateway_factory().extra_headers == {
        "HTTP-Referer": "https://example.org",
        "X-Title": "Custom app",
    }
    gateway = gateway_factory(site_url="https://explicit.org", site_title="Explicit")
    assert gateway.extra_headers == {
        "HTTP-Referer": "https://explicit.org",
        "X-Title": "Explicit",
    }


def test_extra_headers_override_and_preserve_proxy_billing(gateway_factory):
    gateway = gateway_factory(
        base_url="https://proxy.example.org/v1",
        extra_headers={"HTTP-Referer": "https://custom.org", "X-Link-Test": "billing"},
    )
    assert gateway.extra_headers == {
        "HTTP-Referer": "https://custom.org",
        "X-Title": "Penguin",
        "X-Link-Test": "billing",
    }


def test_empty_environment_can_disable_attribution(gateway_factory, monkeypatch):
    monkeypatch.setenv("OPENROUTER_SITE_URL", "")
    monkeypatch.setenv("OPENROUTER_SITE_TITLE", "")
    assert gateway_factory().extra_headers == {}
