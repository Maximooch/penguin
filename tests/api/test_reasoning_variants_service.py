"""Unit tests for provider-aware reasoning variant resolution."""

from penguin.web.services.reasoning_variants import native_reasoning_efforts


def test_openai_gpt_54_uses_full_reasoning_effort_surface() -> None:
    assert native_reasoning_efforts("openai", "gpt-5.4") == (
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    )


def test_openai_gpt_51_limits_reasoning_efforts() -> None:
    assert native_reasoning_efforts("openai", "gpt-5.1") == (
        "none",
        "low",
        "medium",
        "high",
    )


def test_openai_gpt_5_pro_is_high_only() -> None:
    assert native_reasoning_efforts("openai", "gpt-5-pro") == ("high",)


def test_anthropic_opus_46_supports_max_effort() -> None:
    assert native_reasoning_efforts("anthropic", "claude-opus-4-6") == (
        "low",
        "medium",
        "high",
        "max",
    )


def test_anthropic_non_effort_model_returns_no_variants() -> None:
    assert native_reasoning_efforts("anthropic", "claude-3-7-sonnet") == ()
