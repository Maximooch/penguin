from __future__ import annotations

from pathlib import Path

import pytest

from penguin.config import Config
from penguin.llm.api_client import APIClient
from penguin.llm.client import LLMClient
from penguin.llm.model_config import ModelConfig


def test_model_config_from_env_defaults_to_openrouter(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGUIN_PROVIDER", raising=False)
    monkeypatch.delenv("PENGUIN_CLIENT_PREFERENCE", raising=False)
    monkeypatch.delenv("PENGUIN_MODEL", raising=False)

    config = ModelConfig.from_env()

    assert config.client_preference == "openrouter"
    assert config.provider == "openrouter"
    assert config.model == "openai/gpt-4o"


def test_config_load_config_defaults_client_preference_to_openrouter(
    tmp_path: Path,
) -> None:
    config_path = tmp_path / "config.yml"
    config_path.write_text(
        """
model:
  default: anthropic/claude-3-5-sonnet-20240620
  provider: openrouter
""".strip()
        + "\n",
        encoding="utf-8",
    )

    config = Config.load_config(config_path=config_path)

    assert config.model_config.client_preference == "openrouter"


def test_api_client_litellm_preference_without_extra_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = (
        "client_preference='litellm' is unavailable. "
        "LiteLLM support is not installed. Install with "
        '`pip install "penguin-ai[llm_litellm]"` or switch '
        'client_preference to "openrouter" or "native".'
    )
    monkeypatch.setattr(
        "penguin.llm.api_client.load_litellm_gateway_class",
        lambda feature: (_ for _ in ()).throw(RuntimeError(error_message)),
    )

    with pytest.raises(RuntimeError, match=r"penguin-ai\[llm_litellm\]"):
        APIClient(
            ModelConfig(
                model="anthropic/claude-3-5-sonnet-20240620",
                provider="anthropic",
                client_preference="litellm",
            )
        )


def test_llm_client_litellm_preference_without_extra_fails_clearly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    error_message = (
        "client_preference='litellm' is unavailable. "
        "LiteLLM support is not installed. Install with "
        '`pip install "penguin-ai[llm_litellm]"` or switch '
        'client_preference to "openrouter" or "native".'
    )
    monkeypatch.setattr(
        "penguin.llm.client.load_litellm_gateway_class",
        lambda feature: (_ for _ in ()).throw(RuntimeError(error_message)),
    )

    client = LLMClient(
        ModelConfig(
            model="anthropic/claude-3-5-sonnet-20240620",
            provider="anthropic",
            client_preference="litellm",
        )
    )

    with pytest.raises(RuntimeError, match=r"penguin-ai\[llm_litellm\]"):
        client._get_gateway()
