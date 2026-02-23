"""General-purpose provider catalog helpers.

These helpers are backend utilities and intentionally avoid OpenCode-specific
payload shapes. They derive provider/model data from Penguin runtime state.
"""

from __future__ import annotations

import os
from typing import Any

_PROVIDER_METADATA: dict[str, dict[str, Any]] = {
    "openai": {
        "name": "OpenAI",
        "env": ["OPENAI_API_KEY"],
        "api_url": "https://api.openai.com/v1",
        "api_npm": "@ai-sdk/openai",
    },
    "openrouter": {
        "name": "OpenRouter",
        "env": ["OPENROUTER_API_KEY"],
        "api_url": "https://openrouter.ai/api/v1",
        "api_npm": "@openrouter/ai-sdk-provider",
    },
    "anthropic": {
        "name": "Anthropic",
        "env": ["ANTHROPIC_API_KEY"],
        "api_url": "https://api.anthropic.com/v1",
        "api_npm": "@ai-sdk/anthropic",
    },
    "google": {
        "name": "Google",
        "env": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "api_url": "",
        "api_npm": "@ai-sdk/google",
    },
    "ollama": {
        "name": "Ollama",
        "env": ["OLLAMA_HOST"],
        "api_url": "http://localhost:11434/v1",
        "api_npm": "@ai-sdk/openai-compatible",
    },
}


def canonical_model_id(provider_id: str, model_id: str) -> str:
    """Return provider-local model id.

    Provider-local IDs should not repeat the provider prefix for providers that
    already namespace model IDs at the provider layer (for example
    ``openai/gpt-5`` under provider ``openai`` becomes ``gpt-5``).
    """
    model_value = str(model_id or "").strip()
    provider_value = str(provider_id or "").strip().lower()
    if not model_value:
        return model_value
    if not provider_value:
        return model_value

    if "/" not in model_value:
        return model_value

    prefix, remainder = model_value.split("/", 1)
    if prefix.strip().lower() == provider_value and remainder.strip():
        return remainder.strip()
    return model_value


def qualified_model_ref(provider_id: str, model_id: str) -> str:
    """Return ``provider/model`` selector used by config payloads."""
    provider_value = str(provider_id or "").strip().lower()
    canonical = canonical_model_id(provider_value, model_id)
    if not canonical:
        return canonical
    if provider_value:
        return f"{provider_value}/{canonical}"
    return canonical


def model_provider(model_id: str, conf: dict[str, Any]) -> str:
    """Resolve model provider from config and model id."""
    provider = conf.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower()
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower()
    return "unknown"


def model_limit(conf: dict[str, Any]) -> tuple[int, int]:
    """Resolve context and output token limits with safe defaults."""
    context = (
        conf.get("context_window") or conf.get("max_context_window_tokens") or 131072
    )
    output = conf.get("max_output_tokens") or conf.get("max_tokens") or 8192
    try:
        context_int = int(context)
    except Exception:
        context_int = 131072
    try:
        output_int = int(output)
    except Exception:
        output_int = 8192
    return max(context_int, 1), max(output_int, 1)


def provider_name(provider_id: str) -> str:
    """Return display name for a provider id."""
    metadata = _PROVIDER_METADATA.get(provider_id.strip().lower())
    if metadata and isinstance(metadata.get("name"), str):
        return str(metadata["name"])
    return provider_id.title()


def provider_env(provider_id: str) -> list[str]:
    """Return env vars commonly used by the provider."""
    metadata = _PROVIDER_METADATA.get(provider_id.strip().lower())
    env = metadata.get("env") if isinstance(metadata, dict) else None
    if isinstance(env, list):
        return [str(item) for item in env if isinstance(item, str)]
    if provider_id.strip():
        return [f"{provider_id.strip().upper()}_API_KEY"]
    return []


def provider_api(provider_id: str) -> tuple[str, str]:
    """Return provider API URL and npm package hint."""
    metadata = _PROVIDER_METADATA.get(provider_id.strip().lower())
    if not isinstance(metadata, dict):
        return "", "@ai-sdk/openai-compatible"
    raw_api_url = metadata.get("api_url")
    api_url = raw_api_url if isinstance(raw_api_url, str) else ""
    raw_api_npm = metadata.get("api_npm")
    api_npm = (
        raw_api_npm if isinstance(raw_api_npm, str) else "@ai-sdk/openai-compatible"
    )
    return api_url, api_npm


def current_model_string(core: Any) -> str | None:
    """Return current model as provider-qualified string when possible."""
    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    if not isinstance(current_model, dict):
        return None

    model_id = current_model.get("model")
    provider_id = current_model.get("provider")
    if not isinstance(model_id, str) or not model_id:
        return None

    return qualified_model_ref(str(provider_id or ""), model_id)


def collect_provider_models(core: Any) -> dict[str, dict[str, dict[str, Any]]]:
    """Collect provider->model map from Penguin config and runtime model."""
    providers: dict[str, dict[str, dict[str, Any]]] = {}

    model_configs = getattr(getattr(core, "config", None), "model_configs", {}) or {}
    if isinstance(model_configs, dict):
        for model_id, raw_conf in model_configs.items():
            if not isinstance(model_id, str):
                continue
            conf = raw_conf if isinstance(raw_conf, dict) else {}
            provider_id = model_provider(model_id, conf)
            canonical = canonical_model_id(provider_id, model_id)
            providers.setdefault(provider_id, {})[canonical] = conf

    available_models = (
        core.list_available_models() if hasattr(core, "list_available_models") else []
    )
    if isinstance(available_models, list):
        for item in available_models:
            if not isinstance(item, dict):
                continue
            raw_model_id = item.get("id") or item.get("model")
            if not isinstance(raw_model_id, str) or not raw_model_id.strip():
                continue
            provider_id = model_provider(raw_model_id, item)
            canonical = canonical_model_id(provider_id, raw_model_id)
            providers.setdefault(provider_id, {}).setdefault(canonical, dict(item))

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    if isinstance(current_model, dict):
        model_id = current_model.get("model")
        provider_id = current_model.get("provider")
        if isinstance(model_id, str) and model_id:
            pid = (
                provider_id.strip().lower()
                if isinstance(provider_id, str) and provider_id.strip()
                else model_provider(model_id, current_model)
            )
            canonical = canonical_model_id(pid, model_id)
            providers.setdefault(pid, {}).setdefault(canonical, current_model)

    return providers


def provider_ids(core: Any) -> set[str]:
    """Return provider ids currently relevant for runtime."""
    ids = set(collect_provider_models(core).keys())
    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    if isinstance(current_model, dict):
        provider_id = current_model.get("provider")
        if isinstance(provider_id, str) and provider_id.strip():
            ids.add(provider_id.strip().lower())
    ids.update(env_connected_provider_ids())
    return ids


def env_connected_provider_ids() -> set[str]:
    """Return providers with connection hints present in environment."""
    ids: set[str] = set()
    for provider_id in _PROVIDER_METADATA:
        candidates = provider_env(provider_id)
        if any(os.getenv(name) for name in candidates):
            ids.add(provider_id)
    return ids
