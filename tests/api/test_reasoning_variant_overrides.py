"""Tests for provider-aware reasoning variant overrides in chat routes."""

from __future__ import annotations

from types import SimpleNamespace

from penguin.web.routes import (
    _apply_reasoning_variant_override,
    _restore_reasoning_variant_override,
)


def _core_with_model_config(provider: str, model: str) -> SimpleNamespace:
    return SimpleNamespace(
        model_config=SimpleNamespace(
            provider=provider,
            model=model,
            reasoning_enabled=False,
            reasoning_effort=None,
            reasoning_max_tokens=None,
            reasoning_exclude=False,
        )
    )


def test_openai_native_variant_rejects_unsupported_effort() -> None:
    core = _core_with_model_config("openai", "gpt-5.1")

    snapshot = _apply_reasoning_variant_override(core, "xhigh")

    assert snapshot is None
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens is None


def test_anthropic_native_variant_allows_max_for_opus_46() -> None:
    core = _core_with_model_config("anthropic", "claude-opus-4-6")

    snapshot = _apply_reasoning_variant_override(core, "max")

    assert isinstance(snapshot, dict)
    assert core.model_config.reasoning_enabled is True
    assert core.model_config.reasoning_effort == "max"
    assert core.model_config.reasoning_max_tokens is None

    _restore_reasoning_variant_override(core, snapshot)
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
    assert core.model_config.reasoning_max_tokens is None


def test_anthropic_native_variant_rejects_max_for_sonnet_46() -> None:
    core = _core_with_model_config("anthropic", "claude-sonnet-4-6")

    snapshot = _apply_reasoning_variant_override(core, "max")

    assert snapshot is None
    assert core.model_config.reasoning_enabled is False
    assert core.model_config.reasoning_effort is None
