"""Runtime helpers for agent persona model configuration."""

from __future__ import annotations

import copy
from typing import TYPE_CHECKING, Any, Mapping

from penguin.core_runtime.model_runtime import canonicalize_runtime_model_id
from penguin.llm.model_config import ModelConfig, normalize_openai_service_tier

if TYPE_CHECKING:
    from penguin.config import AgentModelSettings

__all__ = ["model_config_for_agent_settings", "model_config_metadata"]


def _model_configs_dict(model_configs: Any) -> dict[str, dict[str, Any]]:
    if not isinstance(model_configs, Mapping):
        return {}
    return {
        key: dict(value)
        for key, value in model_configs.items()
        if isinstance(key, str) and isinstance(value, dict)
    }


def _infer_provider(model_id: str, configured: Mapping[str, Any]) -> str:
    provider = configured.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip()
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower()
    return "openrouter"


def _infer_client_preference(provider: str, configured: Mapping[str, Any]) -> str:
    client_preference = configured.get("client_preference")
    if isinstance(client_preference, str) and client_preference.strip():
        return client_preference.strip()
    return "openrouter" if provider == "openrouter" else "native"


def model_config_for_agent_settings(
    settings: AgentModelSettings | None,
    *,
    model_configs: Any,
    current_model_config: ModelConfig | None,
) -> ModelConfig:
    """Resolve persona model settings without provider discovery or network I/O."""

    if settings is None:
        if current_model_config is None:
            raise ValueError("current_model_config is required without agent settings")
        return copy.deepcopy(current_model_config)

    configs = _model_configs_dict(model_configs)
    config_key = settings.id or settings.model
    configured = configs.get(config_key or "", {})
    configured_model = str(
        settings.model or configured.get("model") or config_key or ""
    )

    if not configured_model and current_model_config is not None:
        model_config = copy.deepcopy(current_model_config)
    else:
        provider = settings.provider or _infer_provider(configured_model, configured)
        client_preference = settings.client_preference or _infer_client_preference(
            provider, configured
        )
        lookup_key = config_key if config_key in configs else configured_model
        model_config = ModelConfig.for_model(
            model_name=lookup_key,
            provider=provider,
            client_preference=client_preference,
            model_configs=configs,
        )
        model_config.model = canonicalize_runtime_model_id(
            configured_model,
            provider,
            client_preference,
        )

    for field_name in (
        "api_base",
        "temperature",
        "max_output_tokens",
        "streaming_enabled",
        "vision_enabled",
        "use_assistants_api",
    ):
        value = getattr(settings, field_name, None)
        if value is not None:
            setattr(model_config, field_name, value)

    if settings.service_tier is not None:
        model_config.service_tier = normalize_openai_service_tier(settings.service_tier)

    if settings.reasoning:
        reasoning = dict(settings.reasoning)
        if "enabled" in reasoning:
            model_config.reasoning_enabled = bool(reasoning["enabled"])
        if "effort" in reasoning:
            model_config.reasoning_effort = reasoning["effort"]
        if "max_tokens" in reasoning:
            model_config.reasoning_max_tokens = reasoning["max_tokens"]
        if "exclude" in reasoning:
            model_config.reasoning_exclude = bool(reasoning["exclude"])

    return model_config


def model_config_metadata(model_config: ModelConfig) -> dict[str, Any]:
    """Return stable model fields suitable for agent metadata payloads."""

    return {
        "model": model_config.model,
        "provider": model_config.provider,
        "client_preference": model_config.client_preference,
        "max_output_tokens": model_config.max_output_tokens,
        "temperature": model_config.temperature,
    }
