"""Model configuration projection and resolution for the Python CLI.

This module owns the boundary between the merged Penguin configuration and the
runtime ``ModelConfig`` used to construct the CLI's API client.  It deliberately
has no dependency on Typer, terminal state, or CLI module globals.
"""

from __future__ import annotations

import copy
from collections.abc import Mapping
from typing import Any

from penguin.llm.model_config import ModelConfig

__all__ = [
    "build_cli_model_config",
    "project_reasoning_config",
    "resolve_reasoning_config",
]


def project_reasoning_config(model_config: ModelConfig) -> dict[str, Any]:
    """Project only explicitly configured reasoning inputs and capabilities."""

    return {
        "reasoning_enabled": (
            model_config.reasoning_enabled
            if model_config.reasoning_enabled_was_explicit
            else None
        ),
        "reasoning_effort": (
            model_config.reasoning_effort
            if model_config.reasoning_effort_was_explicit
            else None
        ),
        "reasoning_max_tokens": (
            model_config.reasoning_max_tokens
            if model_config.reasoning_max_tokens_was_explicit
            else None
        ),
        "reasoning_exclude": model_config.reasoning_exclude,
        "supports_reasoning": model_config.supports_reasoning,
        "supported_reasoning_levels": model_config.supported_reasoning_levels,
    }


def resolve_reasoning_config(model_settings: Mapping[str, Any]) -> dict[str, Any]:
    """Resolve flat or nested reasoning settings without inventing values."""

    nested = model_settings.get("reasoning")
    reasoning = nested if isinstance(nested, Mapping) else {}
    if "enabled" in reasoning:
        reasoning_enabled: bool | None = bool(reasoning.get("enabled"))
    elif "reasoning_enabled" in model_settings:
        configured_enabled = model_settings.get("reasoning_enabled")
        reasoning_enabled = (
            None if configured_enabled is None else bool(configured_enabled)
        )
    else:
        reasoning_enabled = None

    return {
        "reasoning_enabled": reasoning_enabled,
        "reasoning_effort": reasoning.get(
            "effort", model_settings.get("reasoning_effort")
        ),
        "reasoning_max_tokens": reasoning.get(
            "max_tokens", model_settings.get("reasoning_max_tokens")
        ),
        "reasoning_exclude": bool(
            reasoning.get("exclude", model_settings.get("reasoning_exclude", False))
        ),
        "supports_reasoning": model_settings.get("supports_reasoning"),
        "supported_reasoning_levels": model_settings.get("supported_reasoning_levels"),
    }


def _model_configs(loaded_config: Any) -> dict[str, dict[str, Any]]:
    raw_configs = getattr(loaded_config, "model_configs", None)
    if not isinstance(raw_configs, Mapping) and isinstance(loaded_config, Mapping):
        raw_configs = loaded_config.get("model_configs")
    if not isinstance(raw_configs, Mapping):
        return {}
    return {
        str(model_id): dict(settings)
        for model_id, settings in raw_configs.items()
        if isinstance(settings, Mapping)
    }


def build_cli_model_config(
    loaded_config: Any,
    *,
    model_override: str | None = None,
    streaming_enabled: bool | None = None,
) -> ModelConfig:
    """Return the complete runtime model configuration for CLI startup.

    The already-resolved typed model configuration is retained when there is no
    model override.  An override is resolved as a new target model so inferred
    capabilities can never leak from the configured source model.
    """

    source = getattr(loaded_config, "model_config", None)
    if not isinstance(source, ModelConfig):
        raise TypeError("Loaded CLI configuration has no typed model_config")

    if model_override:
        qualified_provider = (
            model_override.split("/", 1)[0].strip().lower()
            if "/" in model_override
            else None
        )
        provider = qualified_provider or source.provider
        client_preference = (
            "native"
            if qualified_provider and qualified_provider != "openrouter"
            else source.client_preference
        )
        result = ModelConfig.for_model(
            model_name=model_override,
            provider=provider,
            client_preference=client_preference,
            model_configs=_model_configs(loaded_config),
        )
        if result.api_base is None:
            result.api_base = source.api_base
    else:
        result = copy.copy(source)

    api_settings = getattr(loaded_config, "api", None)
    configured_api_base = getattr(api_settings, "base_url", None)
    if configured_api_base:
        result.api_base = configured_api_base
    if streaming_enabled is not None:
        result.streaming_enabled = streaming_enabled
    return result
