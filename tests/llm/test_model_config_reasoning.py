"""ModelConfig reasoning payload regression tests."""

from penguin.llm.model_config import ModelConfig


def test_reasoning_effort_takes_precedence_for_claude_models() -> None:
    config = ModelConfig(
        model="anthropic/claude-sonnet-4.5",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort="low",
        reasoning_max_tokens=None,
    )

    assert config.get_reasoning_config() == {"effort": "low"}


def test_reasoning_max_tokens_used_when_effort_missing() -> None:
    config = ModelConfig(
        model="anthropic/claude-sonnet-4.5",
        provider="openrouter",
        client_preference="openrouter",
        reasoning_enabled=True,
        reasoning_effort=None,
        reasoning_max_tokens=4096,
    )

    assert config.get_reasoning_config() == {"max_tokens": 4096}


def test_explicit_reasoning_effort_overrides_support_detection() -> None:
    config = ModelConfig(
        model="z-ai/glm-5",
        provider="openrouter",
        client_preference="openrouter",
        supports_reasoning=False,
        reasoning_enabled=True,
        reasoning_effort="xhigh",
        reasoning_max_tokens=None,
    )

    assert config.get_reasoning_config() == {"effort": "xhigh"}
