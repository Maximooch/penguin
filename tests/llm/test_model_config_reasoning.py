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


def test_codex_model_metadata_sets_supported_reasoning_default() -> None:
    config = ModelConfig.for_model(
        model_name="openai/gpt-5.6-sol",
        provider="openai",
        model_configs={
            "openai/gpt-5.6-sol": {
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "reasoning_enabled": True,
                "default_reasoning_level": "low",
                "supported_reasoning_levels": [
                    {"effort": "low"},
                    {"effort": "medium"},
                    {"effort": "high"},
                    {"effort": "xhigh"},
                    {"effort": "max"},
                    {"effort": "ultra"},
                ],
            }
        },
    )

    assert config.supported_reasoning_levels == [
        "low",
        "medium",
        "high",
        "xhigh",
        "max",
        "ultra",
    ]
    assert config.get_reasoning_config() == {"effort": "low"}


def test_codex_model_metadata_falls_back_to_middle_supported_effort() -> None:
    config = ModelConfig.for_model(
        model_name="openai/gpt-5.6-luna",
        provider="openai",
        model_configs={
            "openai/gpt-5.6-luna": {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "supported_reasoning_levels": [
                    {"effort": "low"},
                    {"effort": "medium"},
                    {"effort": "high"},
                    {"effort": "max"},
                ],
            }
        },
    )

    assert config.get_reasoning_config() == {"effort": "medium"}


def test_codex_model_metadata_rejects_unsupported_efforts() -> None:
    """Unsupported configured and default efforts fall back to metadata."""

    config = ModelConfig.for_model(
        model_name="openai/gpt-5.6-luna",
        provider="openai",
        model_configs={
            "openai/gpt-5.6-luna": {
                "provider": "openai",
                "model": "gpt-5.6-luna",
                "reasoning": {"effort": "ultra"},
                "default_reasoning_level": "xhigh",
                "supported_reasoning_levels": [
                    {"effort": "low"},
                    {"effort": "medium"},
                    {"effort": "high"},
                    {"effort": "max"},
                ],
            }
        },
    )

    assert config.get_reasoning_config() == {"effort": "medium"}


def test_explicit_reasoning_opt_out_wins_over_supported_metadata() -> None:
    """An explicit reasoning opt-out wins over inferred catalog support."""

    config = ModelConfig.for_model(
        model_name="openai/gpt-5.6-sol",
        provider="openai",
        model_configs={
            "openai/gpt-5.6-sol": {
                "provider": "openai",
                "model": "gpt-5.6-sol",
                "reasoning_enabled": False,
                "default_reasoning_level": "low",
                "supported_reasoning_levels": [
                    {"effort": "low"},
                    {"effort": "medium"},
                    {"effort": "high"},
                ],
            }
        },
    )

    assert config.reasoning_enabled is False
    assert config.supports_reasoning is True
    assert config.supported_reasoning_levels == ["low", "medium", "high"]
    assert config.get_reasoning_config() is None


def test_direct_explicit_reasoning_opt_out_is_not_auto_enabled() -> None:
    """Direct construction preserves an explicit False reasoning setting."""

    config = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
        reasoning_enabled=False,
    )

    assert config.reasoning_enabled is False
    assert config.get_reasoning_config() is None
