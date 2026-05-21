"""Model runtime resolution helpers for PenguinCore.

The functions in this module are intentionally free of ``PenguinCore`` state.
They accept the small pieces of configuration they need and return derived
runtime values for the caller to apply.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable, Mapping

from penguin.llm.model_config import (
    ModelConfig,
    fetch_model_specs,
    normalize_openai_service_tier,
    safe_context_window,
)

logger = logging.getLogger(__name__)

FetchModelSpecs = Callable[[str], Awaitable[dict[str, Any]]]
ResolveModelProvider = Callable[[str], tuple[str | None, str]]


def _coerce_optional_int(value: Any) -> int | None:
    """Return a positive int or ``None`` for unset/invalid values."""

    try:
        parsed = int(value)
    except Exception:
        return None
    return parsed if parsed > 0 else None


def _model_configs_dict(model_configs: Any) -> dict[str, dict[str, Any]]:
    """Return only dict-valued model config entries."""

    if not isinstance(model_configs, Mapping):
        return {}
    result: dict[str, dict[str, Any]] = {}
    for key, value in model_configs.items():
        if isinstance(key, str) and isinstance(value, dict):
            result[key] = dict(value)
    return result


def canonicalize_runtime_model_id(
    model_id: str,
    provider: str,
    client_preference: str,
) -> str:
    """Canonicalize model IDs into provider-local form for runtime adapters."""

    value = str(model_id or "").strip()
    if not value:
        return value

    provider_value = str(provider or "").strip().lower()
    client_value = str(client_preference or "").strip().lower()

    # Native SDK adapters expect provider-local IDs.
    if client_value == "native" and provider_value in {"openai", "anthropic"}:
        if "/" in value:
            prefix, remainder = value.split("/", 1)
            if prefix.strip().lower() == provider_value and remainder.strip():
                return remainder.strip()
        return value

    # OpenRouter runtime model IDs should not include an extra openrouter/ prefix.
    if provider_value == "openrouter" and "/" in value:
        prefix, remainder = value.split("/", 1)
        if prefix.strip().lower() == "openrouter" and remainder.strip():
            return remainder.strip()

    return value


def resolve_model_provider(
    model_id: str,
    model_configs: Any,
    *,
    current_client_preference: str | None = None,
) -> tuple[str | None, str]:
    """Resolve provider and client preference for a model ID."""

    configs = _model_configs_dict(model_configs)
    model_conf = configs.get(model_id)
    if model_conf:
        provider = model_conf.get("provider")
        client_pref = str(model_conf.get("client_preference", "openrouter"))
        return str(provider) if provider else None, client_pref

    if "/" not in model_id:
        logger.error(
            "Model '%s' not in model_configs and not fully-qualified", model_id
        )
        return None, ""

    provider_part = model_id.split("/", 1)[0].strip().lower()

    if provider_part == "openrouter":
        return "openrouter", "openrouter"

    native_providers = {"openai", "anthropic", "google", "ollama"}
    if provider_part in native_providers:
        return provider_part, "native"

    client_pref = str(current_client_preference or "openrouter").strip().lower()
    provider = "openrouter" if client_pref == "openrouter" else provider_part
    return provider, client_pref


async def build_model_config_for_model(
    model_id: str,
    *,
    model_configs: Any,
    current_model_config: ModelConfig | None = None,
    fetch_specs: FetchModelSpecs | None = None,
    resolve_provider: ResolveModelProvider | None = None,
) -> tuple[ModelConfig, int | None]:
    """Resolve a runtime model id into a concrete ``ModelConfig``.

    Returns:
        A tuple of ``(model_config, safe_context_window_tokens)``. The caller is
        responsible for applying the config to runtime state.
    """

    configs = _model_configs_dict(model_configs)
    fetch_specs = fetch_specs or fetch_model_specs
    current_client_preference = (
        getattr(current_model_config, "client_preference", None)
        if current_model_config is not None
        else None
    )
    if resolve_provider is None:
        provider, client_pref = resolve_model_provider(
            model_id,
            configs,
            current_client_preference=current_client_preference,
        )
    else:
        provider, client_pref = resolve_provider(model_id)
    if not provider:
        raise ValueError(f"Could not resolve provider for model '{model_id}'")

    provider_value = provider.strip().lower()
    client_value = client_pref.strip().lower()
    runtime_model_id = canonicalize_runtime_model_id(
        model_id,
        provider_value,
        client_value,
    )

    model_lookup_id = (
        runtime_model_id
        if runtime_model_id in configs and model_id not in configs
        else model_id
    )

    requires_openrouter_specs = bool(
        provider_value == "openrouter" or client_value == "openrouter"
    )
    model_specs: dict[str, Any] = {}
    spec_model_id = runtime_model_id if provider_value == "openrouter" else model_id

    if requires_openrouter_specs:
        model_specs = await fetch_specs(spec_model_id)
        if not model_specs:
            raise ValueError(
                f"Could not fetch specifications for model '{spec_model_id}'"
            )
        logger.info("Fetched specs for %s: %s", spec_model_id, model_specs)

    model_specific = configs.get(model_lookup_id, {})

    context_length = _coerce_optional_int(model_specs.get("context_length"))
    if context_length is None:
        context_length = _coerce_optional_int(
            model_specific.get("context_window")
            or model_specific.get("max_context_window_tokens")
        )

    safe_window = safe_context_window(context_length)
    max_output = _coerce_optional_int(model_specs.get("max_output_tokens"))
    if max_output is None:
        max_output = _coerce_optional_int(
            model_specific.get("max_output_tokens") or model_specific.get("max_tokens")
        )
    if max_output is None:
        max_output = safe_window
    elif safe_window is not None and max_output > safe_window:
        logger.warning(
            "Clamping model '%s' max_output_tokens from %s to safe window %s",
            runtime_model_id,
            max_output,
            safe_window,
        )
        max_output = safe_window

    new_model_config = ModelConfig.for_model(
        model_name=model_lookup_id,
        provider=provider,
        client_preference=client_pref,
        model_configs=configs,
    )

    new_model_config.model = runtime_model_id
    if "service_tier" not in model_specific:
        inherited_service_tier = (
            getattr(current_model_config, "service_tier", None)
            if current_model_config is not None
            else None
        )
        new_model_config.service_tier = normalize_openai_service_tier(
            inherited_service_tier
        )
    if context_length is not None:
        new_model_config.max_context_window_tokens = context_length
        new_model_config.max_history_tokens = safe_window
    if max_output is not None:
        new_model_config.max_output_tokens = max_output

    user_explicit_vision = model_specific.get("vision_enabled")
    if user_explicit_vision is not None:
        new_model_config.vision_enabled = bool(user_explicit_vision)
        logger.info(
            "Model '%s' vision set to %s (user config)",
            runtime_model_id,
            new_model_config.vision_enabled,
        )
    elif model_specs.get("supports_vision"):
        new_model_config.vision_enabled = True
        logger.info("Model '%s' supports vision (auto-detected)", runtime_model_id)

    return new_model_config, safe_window


def list_available_models(
    model_configs: Any,
    *,
    current_model_name: str | None = None,
) -> list[dict[str, Any]]:
    """Return model metadata derived from configured model entries."""

    models: list[dict[str, Any]] = []
    for model_id, conf in _model_configs_dict(model_configs).items():
        entry = {
            "id": model_id,
            "name": conf.get("model", model_id),
            "provider": conf.get("provider", "unknown"),
            "client_preference": conf.get("client_preference", "openrouter"),
            "vision_enabled": conf.get("vision_enabled", False),
            "max_output_tokens": conf.get("max_output_tokens", conf.get("max_tokens")),
            "temperature": conf.get("temperature"),
            "current": model_id == current_model_name
            or conf.get("model") == current_model_name,
        }
        models.append(entry)

    models.sort(key=lambda item: (not item["current"], item["id"]))
    return models


def current_model_payload(
    model_config: ModelConfig | None,
) -> dict[str, Any] | None:
    """Return the public current-model payload for a loaded config."""

    if model_config is None:
        return None

    return {
        "model": model_config.model,
        "provider": model_config.provider,
        "client_preference": model_config.client_preference,
        "max_output_tokens": getattr(model_config, "max_output_tokens", None),
        "temperature": getattr(model_config, "temperature", None),
        "streaming_enabled": model_config.streaming_enabled,
        "vision_enabled": bool(getattr(model_config, "vision_enabled", False)),
        "api_base": getattr(model_config, "api_base", None),
    }


__all__ = [
    "build_model_config_for_model",
    "canonicalize_runtime_model_id",
    "current_model_payload",
    "list_available_models",
    "resolve_model_provider",
]
