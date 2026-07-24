from __future__ import annotations

import pytest

from penguin.llm.client import LinkConfig, LLMClient, LLMClientConfig
from penguin.llm.model_config import ModelConfig


def test_llm_client_rejects_the_legacy_openrouter_as_link_proxy_path() -> None:
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

    with pytest.raises(ValueError, match="first-class LinkProvider"):
        client._get_gateway()
