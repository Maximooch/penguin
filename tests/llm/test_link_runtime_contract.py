from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.llm.client import LLMClient, LLMClientConfig, LinkConfig
from penguin.llm.model_config import ModelConfig


def test_llm_client_routes_link_headers_through_shared_provider_runtime() -> None:
    model_config = ModelConfig(
        model="openai/gpt-5.4-nano",
        provider="openrouter",
        client_preference="openrouter",
    )
    client = LLMClient(
        model_config,
        LLMClientConfig(
            base_url="http://localhost:3001/api/v1",
            link=LinkConfig(
                user_id="user-123",
                session_id="session-456",
                agent_id="agent-789",
                workspace_id="workspace-abc",
                api_key="link-secret",
            ),
        ),
    )

    captured: dict[str, Any] = {}

    def _create_handler(
        model_config: ModelConfig,
        *,
        base_url: str | None = None,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        captured["provider"] = model_config.provider
        captured["model"] = model_config.model
        captured["base_url"] = base_url
        captured["extra_headers"] = dict(extra_headers or {})
        return SimpleNamespace(extra_headers=dict(extra_headers or {}))

    client._provider_registry.create_handler = _create_handler  # type: ignore[method-assign]

    gateway = client._get_gateway()

    assert gateway.extra_headers["X-Link-User-Id"] == "user-123"
    assert captured == {
        "provider": "openrouter",
        "model": "openai/gpt-5.4-nano",
        "base_url": "http://localhost:3001/api/v1",
        "extra_headers": {
            "X-Link-User-Id": "user-123",
            "X-Link-Session-Id": "session-456",
            "X-Link-Agent-Id": "agent-789",
            "X-Link-Workspace-Id": "workspace-abc",
            "Authorization": "Bearer link-secret",
        },
    }
