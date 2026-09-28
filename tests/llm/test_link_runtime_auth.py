"""Run-scoped inference uses bearer auth, never service authority."""

import os
from unittest.mock import patch

import httpx
import pytest

from penguin.llm.contracts import LLMProviderError
from penguin.llm.model_config import ModelConfig
from penguin.llm.providers.link import (
    LinkInferenceContext,
    LinkProvider,
    LinkProviderConfig,
)

TOKEN = "lk-run-" + "a" * 43


@pytest.mark.asyncio
@pytest.mark.parametrize("protocol", ["responses", "chat_completions"])
@pytest.mark.parametrize("status", [200, 403])
async def test_runtime_bearer_is_sent_but_not_in_prepared_request(
    protocol: str, status: int
) -> None:
    """Exercise the real provider request and its credential-free preview."""
    with patch.dict(
        os.environ,
        {"LINK_INFERENCE_RUNTIME_TOKEN": TOKEN, "LINK_INFERENCE_PROTOCOL": protocol},
        clear=True,
    ):
        config = LinkProviderConfig.from_env(base_url="https://link.test/api/v1")

    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.headers["authorization"] == f"Bearer {TOKEN}"
        assert "x-link-service-auth" not in request.headers
        assert "x-link-service-name" not in request.headers
        assert request.headers["x-link-run-id"] == "run-1"
        return httpx.Response(
            status,
            json={
                "id": "r1",
                "status": "completed",
                "output_text": "ok",
                "usage": {},
                "choices": [
                    {
                        "message": {"role": "assistant", "content": "ok"},
                        "finish_reason": "stop",
                    }
                ],
            },
        )

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        provider = LinkProvider(
            model_config=ModelConfig(
                model="test", provider="openrouter", max_output_tokens=32
            ),
            context=LinkInferenceContext(
                workspace_id="w1",
                user_id="u1",
                run_id="run-1",
                requested_model_id="test",
            ),
            config=config,
            http_client=client,
        )
        messages = [{"role": "user", "content": "hello"}]
        prepared = await provider.prepare_request(messages)
        assert "Authorization" not in prepared.headers
        assert TOKEN not in repr(prepared)
        assert TOKEN not in repr(config)
        if status == 200:
            assert await provider.get_response(messages) == "ok"
        else:
            with pytest.raises(LLMProviderError):
                await provider.get_response(messages)
        assert len(requests) == 1


@pytest.mark.parametrize("token", ["", "bad", "lk-run-short", TOKEN + "\r\nX-Foo: bad"])
@pytest.mark.parametrize("service_token", ["", "broad-secret"])
def test_invalid_explicit_runtime_token_never_falls_back(
    token: str, service_token: str
) -> None:
    """Reject bad scoped credentials even when a service secret is available."""
    with patch.dict(
        os.environ,
        {
            "LINK_INFERENCE_RUNTIME_TOKEN": token,
            "LINK_INFERENCE_SERVICE_TOKEN": service_token,
        },
        clear=True,
    ):
        with pytest.raises(ValueError):
            LinkProviderConfig.from_env()


def test_mixed_authorities_are_rejected() -> None:
    """Do not silently choose a broader authority."""
    with pytest.raises(ValueError):
        LinkProviderConfig(
            base_url="https://link.test", service_token="broad", runtime_token=TOKEN
        )
