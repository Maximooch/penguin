"""Regression tests for CLI model runtime projection and target resolution."""

from types import SimpleNamespace

from penguin.cli.cli import (
    _project_reasoning_config,
    _resolve_cli_reasoning_config,
)
from penguin.cli.model_runtime import build_cli_model_config
from penguin.llm.model_config import ModelConfig


def _rebuild_reasoning_config(source: ModelConfig) -> ModelConfig:
    """Rebuild a model config through the primary CLI projection path."""

    projected = _resolve_cli_reasoning_config(_project_reasoning_config(source))
    return ModelConfig(
        model=source.model,
        provider=source.provider,
        client_preference=source.client_preference,
        reasoning_enabled=projected["reasoning_enabled"],
        reasoning_effort=projected["reasoning_effort"],
        reasoning_max_tokens=projected["reasoning_max_tokens"],
        reasoning_exclude=projected["reasoning_exclude"],
        supports_reasoning=projected["supports_reasoning"],
        supported_reasoning_levels=projected["supported_reasoning_levels"],
    )


def test_cli_reasoning_projection_preserves_implicit_defaults() -> None:
    """CLI reconstruction keeps implicit GPT reasoning enabled and non-explicit."""

    source = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
    )

    rebuilt = _rebuild_reasoning_config(source)

    assert rebuilt.reasoning_enabled is True
    assert rebuilt.reasoning_effort == "medium"
    assert rebuilt._reasoning_enabled_explicit is False
    assert rebuilt._reasoning_effort_explicit is False


def test_cli_reasoning_projection_preserves_explicit_effort() -> None:
    """CLI reconstruction keeps explicitly configured reasoning effort."""

    source = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
        reasoning_enabled=True,
        reasoning_effort="high",
    )

    rebuilt = _rebuild_reasoning_config(source)

    assert rebuilt.reasoning_enabled is True
    assert rebuilt.reasoning_effort == "high"
    assert rebuilt._reasoning_enabled_explicit is True
    assert rebuilt._reasoning_effort_explicit is True


def test_cli_reasoning_projection_preserves_explicit_opt_out() -> None:
    """CLI reconstruction keeps an explicit reasoning opt-out disabled."""

    source = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
        reasoning_enabled=False,
    )

    rebuilt = _rebuild_reasoning_config(source)

    assert rebuilt.reasoning_enabled is False
    assert rebuilt.reasoning_effort is None
    assert rebuilt._reasoning_enabled_explicit is True


def test_cli_reasoning_projection_preserves_explicit_token_budget() -> None:
    """A token budget remains explicit when enablement was omitted."""

    source = ModelConfig(
        model="anthropic/claude-sonnet-4",
        provider="anthropic",
        client_preference="native",
        reasoning_max_tokens=8000,
    )

    rebuilt = _rebuild_reasoning_config(source)

    assert rebuilt.reasoning_max_tokens == 8000
    assert rebuilt.reasoning_max_tokens_was_explicit is True


def test_model_override_recomputes_target_reasoning_capability() -> None:
    """A reasoning target does not inherit a non-reasoning source capability."""

    source = ModelConfig(
        model="gpt-4o",
        provider="openai",
        client_preference="native",
        supports_reasoning=False,
    )
    loaded = SimpleNamespace(model_config=source, model_configs={}, api=None)

    target = build_cli_model_config(loaded, model_override="gpt-5.6-sol")

    assert target.model == "gpt-5.6-sol"
    assert target.supports_reasoning is True
    assert target.reasoning_enabled is True


def test_model_override_drops_source_reasoning_capability() -> None:
    """A non-reasoning target does not inherit source reasoning metadata."""

    source = ModelConfig(
        model="gpt-5.6-sol",
        provider="openai",
        client_preference="native",
    )
    loaded = SimpleNamespace(model_config=source, model_configs={}, api=None)

    target = build_cli_model_config(loaded, model_override="gpt-4o")

    assert target.model == "gpt-4o"
    assert target.supports_reasoning is False
    assert target.reasoning_enabled is False
