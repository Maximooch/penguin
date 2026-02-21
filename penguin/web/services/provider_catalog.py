"""General-purpose provider catalog helpers.

These helpers are backend utilities and intentionally avoid OpenCode-specific
payload shapes. They derive provider/model data from Penguin runtime state.
"""

from __future__ import annotations

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


def model_provider(model_id: str, conf: dict[str, Any]) -> str:
    """Resolve model provider from config and model id."""
    provider = conf.get("provider")
    if isinstance(provider, str) and provider.strip():
        return provider.strip().lower()
    if "/" in model_id:
        return model_id.split("/", 1)[0].strip().lower()
    return "openrouter"


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
    api_url = (
        metadata.get("api_url") if isinstance(metadata.get("api_url"), str) else ""
    )
    api_npm = (
        metadata.get("api_npm")
        if isinstance(metadata.get("api_npm"), str)
        else "@ai-sdk/openai-compatible"
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

    if "/" in model_id:
        return model_id
    if isinstance(provider_id, str) and provider_id:
        return f"{provider_id}/{model_id}"
    return model_id


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
            providers.setdefault(provider_id, {})[model_id] = conf

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    if isinstance(current_model, dict):
        model_id = current_model.get("model")
        provider_id = current_model.get("provider")
        if isinstance(model_id, str) and model_id:
            pid = (
                provider_id
                if isinstance(provider_id, str) and provider_id
                else model_provider(model_id, current_model)
            )
            providers.setdefault(pid, {}).setdefault(model_id, current_model)

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
    return ids
