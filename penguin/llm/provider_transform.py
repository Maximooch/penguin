from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .model_config import ModelConfig


OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai_compatible",
    "openai-compatible",
    "openai_compat",
}
VALID_CLIENT_PREFERENCES = {"native", "litellm", "openrouter"}


def normalize_provider_name(provider: str) -> str:
    """Return a canonical internal provider identifier."""

    normalized = str(provider or "").strip().lower().replace("-", "_")
    if normalized in OPENAI_COMPATIBLE_PROVIDER_ALIASES:
        return OPENAI_COMPATIBLE_PROVIDER
    return normalized


def is_openai_compatible_provider(provider: str) -> bool:
    """Return whether the provider should use the OpenAI-compatible path."""

    return normalize_provider_name(provider) == OPENAI_COMPATIBLE_PROVIDER


def normalize_client_preference(client_preference: str) -> str:
    """Return a canonical client preference with safe defaulting."""

    normalized = str(client_preference or "").strip().lower()
    if normalized in VALID_CLIENT_PREFERENCES:
        return normalized
    return "openrouter"


def canonicalize_native_model_name(
    model: str,
    provider: str,
    client_preference: str,
) -> str:
    """Strip redundant provider prefixes for native-compatible adapters."""

    model_value = str(model or "").strip()
    if not model_value:
        return model_value

    if normalize_client_preference(client_preference) != "native":
        return model_value

    provider_name = normalize_provider_name(provider)
    if provider_name not in {"openai", "anthropic", OPENAI_COMPATIBLE_PROVIDER}:
        return model_value

    if "/" not in model_value:
        return model_value

    prefix, remainder = model_value.split("/", 1)
    remainder = remainder.strip()
    if not remainder:
        return model_value

    prefix_name = normalize_provider_name(prefix)
    if provider_name == OPENAI_COMPATIBLE_PROVIDER:
        if prefix_name in {"openai", OPENAI_COMPATIBLE_PROVIDER}:
            return remainder
        return model_value

    if prefix_name == provider_name:
        return remainder
    return model_value


def apply_model_config_transforms(model_config: "ModelConfig") -> "ModelConfig":
    """Normalize provider/client/model fields in place for handler resolution."""

    model_config.provider = normalize_provider_name(
        str(getattr(model_config, "provider", "") or "")
    )
    model_config.client_preference = normalize_client_preference(
        str(getattr(model_config, "client_preference", "openrouter") or "openrouter")
    )
    model_config.model = canonicalize_native_model_name(
        str(getattr(model_config, "model", "") or ""),
        model_config.provider,
        model_config.client_preference,
    )
    return model_config


__all__ = [
    "OPENAI_COMPATIBLE_PROVIDER",
    "OPENAI_COMPATIBLE_PROVIDER_ALIASES",
    "VALID_CLIENT_PREFERENCES",
    "apply_model_config_transforms",
    "canonicalize_native_model_name",
    "is_openai_compatible_provider",
    "normalize_client_preference",
    "normalize_provider_name",
]
