"""OpenCode compatibility adapter for provider/config/auth payloads.

Business logic is delegated to general-purpose provider services.
"""

from __future__ import annotations

import logging
import os
import time
from datetime import datetime, timezone
from threading import RLock
from typing import Any

from penguin.config import load_config
from penguin.web.services import provider_auth as provider_auth_service
from penguin.web.services.provider_auth import (
    _OPENAI_OAUTH_DEVICE_URL,
    _PENDING_OAUTH,
    authorize_provider_oauth,
    callback_provider_oauth,
    provider_auth_methods as auth_methods_for_providers,
)
from penguin.web.services.provider_catalog import (
    canonical_model_id,
    collect_provider_models,
    current_model_string,
    env_connected_provider_ids,
    model_limit,
    models_dev_provider_models,
    provider_api,
    provider_env,
    provider_ids,
    provider_name,
    qualified_model_ref,
)
from penguin.web.services.provider_credentials import (
    apply_credentials_to_runtime,
    get_provider_credential,
    get_provider_credentials,
    provider_connected,
    remove_provider_credential,
    set_provider_credential,
)

# Compatibility export used by existing tests/patch points.
httpx = provider_auth_service.httpx

logger = logging.getLogger(__name__)

_OPENROUTER_CATALOG_URL = "https://openrouter.ai/api/v1/models"
_OPENROUTER_CATALOG_TTL_SECONDS = 600.0
_OPENROUTER_CATALOG_LOCK = RLock()
_OPENROUTER_CATALOG_CACHE: dict[str, Any] = {
    "fetched_at": 0.0,
    "models": {},
}
_MODELS_DEV_PROVIDER_IDS = {"openai", "anthropic"}


def _normalize_provider_filter_values(raw_value: Any) -> set[str]:
    if isinstance(raw_value, str):
        values = [raw_value]
    elif isinstance(raw_value, list):
        values = [item for item in raw_value if isinstance(item, str)]
    else:
        values = []
    return {item.strip().lower() for item in values if item.strip()}


def _provider_filters(config_data: dict[str, Any]) -> tuple[set[str], set[str]]:
    enabled = _normalize_provider_filter_values(config_data.get("enabled_providers"))
    disabled = _normalize_provider_filter_values(config_data.get("disabled_providers"))
    return enabled, disabled


def _provider_visible(
    provider_id: str,
    enabled: set[str],
    disabled: set[str],
) -> bool:
    pid = provider_id.strip().lower()
    if not pid:
        return False
    if enabled and pid not in enabled:
        return False
    if pid in disabled:
        return False
    return True


def _supports_reasoning_model(model_id: str) -> bool:
    value = model_id.lower()
    return any(
        token in value
        for token in (
            "o1",
            "o3",
            "r1",
            "thinking",
            "reasoning",
            "gpt-5",
            "claude-3.7",
            "claude-4",
            "gemini-2.5",
            "deepseek-r1",
        )
    )


def _openrouter_release_date(raw_value: Any) -> str | None:
    if isinstance(raw_value, str) and raw_value.strip():
        return raw_value.strip()
    if isinstance(raw_value, (int, float)) and raw_value > 0:
        try:
            return datetime.fromtimestamp(float(raw_value), tz=timezone.utc).isoformat()
        except Exception:
            return None
    return None


def _coerce_positive_int(value: Any, default: int) -> int:
    try:
        parsed = int(value)
    except Exception:
        return default
    return parsed if parsed > 0 else default


def _coerce_non_negative_float(value: Any, default: float = 0.0) -> float:
    try:
        parsed = float(value)
    except Exception:
        return default
    if parsed < 0:
        return default
    return parsed


def _model_cost_payload(conf: dict[str, Any]) -> dict[str, Any]:
    raw_cost = conf.get("cost")
    if isinstance(raw_cost, dict):
        raw_cache = raw_cost.get("cache")
        cache: dict[str, Any] = raw_cache if isinstance(raw_cache, dict) else {}
        return {
            "input": _coerce_non_negative_float(raw_cost.get("input"), 0.0),
            "output": _coerce_non_negative_float(raw_cost.get("output"), 0.0),
            "cache": {
                "read": _coerce_non_negative_float(cache.get("read"), 0.0),
                "write": _coerce_non_negative_float(cache.get("write"), 0.0),
            },
        }

    raw_pricing = conf.get("pricing")
    pricing: dict[str, Any] = raw_pricing if isinstance(raw_pricing, dict) else {}
    return {
        "input": _coerce_non_negative_float(pricing.get("prompt"), 0.0),
        "output": _coerce_non_negative_float(pricing.get("completion"), 0.0),
        "cache": {
            "read": _coerce_non_negative_float(pricing.get("input_cache_read"), 0.0),
            "write": _coerce_non_negative_float(pricing.get("input_cache_write"), 0.0),
        },
    }


def _openrouter_reasoning_variants(
    model_id: str,
) -> dict[str, dict[str, Any]] | None:
    """Return OpenRouter reasoning variants aligned with OpenCode expectations."""
    value = model_id.strip().lower()
    if not value:
        return None

    if any(
        token in value for token in ("deepseek", "minimax", "glm", "mistral", "kimi")
    ):
        return None

    if "grok" in value:
        if "grok-3-mini" not in value:
            return None
        return {
            "low": {"reasoning": {"effort": "low"}},
            "high": {"reasoning": {"effort": "high"}},
        }

    if "gpt" in value or "gemini-3" in value:
        efforts = ("none", "minimal", "low", "medium", "high", "xhigh")
        return {effort: {"reasoning": {"effort": effort}} for effort in efforts}

    return None


def _model_variants_payload(
    provider_id: str,
    model_id: str,
    reasoning_enabled: bool,
) -> dict[str, dict[str, Any]] | None:
    if not reasoning_enabled:
        return None

    if provider_id.strip().lower() == "openrouter":
        return _openrouter_reasoning_variants(model_id)

    return {
        "low": {"reasoning": {"effort": "low"}},
        "medium": {"reasoning": {"effort": "medium"}},
        "high": {"reasoning": {"effort": "high"}},
    }


def _openrouter_catalog_models(api_key: str | None = None) -> dict[str, dict[str, Any]]:
    if not isinstance(api_key, str) or not api_key.strip():
        api_key = os.getenv("OPENROUTER_API_KEY", "").strip()
    if not api_key:
        return {}

    now = time.time()
    with _OPENROUTER_CATALOG_LOCK:
        fetched_at = float(_OPENROUTER_CATALOG_CACHE.get("fetched_at") or 0.0)
        cached_models = _OPENROUTER_CATALOG_CACHE.get("models")
        if (
            isinstance(cached_models, dict)
            and cached_models
            and now - fetched_at <= _OPENROUTER_CATALOG_TTL_SECONDS
        ):
            return {
                str(key): value
                for key, value in cached_models.items()
                if isinstance(key, str) and isinstance(value, dict)
            }

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    site_url = os.getenv("OPENROUTER_SITE_URL")
    site_title = os.getenv("OPENROUTER_SITE_TITLE") or "Penguin"
    if site_url:
        headers["HTTP-Referer"] = site_url
    if site_title:
        headers["X-Title"] = site_title

    discovered: dict[str, dict[str, Any]] = {}
    try:
        with httpx.Client(timeout=10.0) as client:
            response = client.get(_OPENROUTER_CATALOG_URL, headers=headers)
            response.raise_for_status()
            payload = response.json()

        data = payload.get("data") if isinstance(payload, dict) else None
        models = data if isinstance(data, list) else []

        for item in models:
            if not isinstance(item, dict):
                continue
            raw_model_id = item.get("id")
            if not isinstance(raw_model_id, str) or not raw_model_id.strip():
                continue

            model_id = raw_model_id.strip()
            key = canonical_model_id("openrouter", model_id)
            raw_context = item.get("context_length")
            context_window = _coerce_positive_int(raw_context, 131072)

            top_provider: dict[str, Any] = {}
            top_provider_payload = item.get("top_provider")
            if isinstance(top_provider_payload, dict):
                top_provider = top_provider_payload
            raw_output = top_provider.get("max_completion_tokens") or item.get(
                "max_output_tokens"
            )
            max_output = _coerce_positive_int(raw_output, max(context_window // 4, 1))

            architecture: dict[str, Any] = {}
            architecture_payload = item.get("architecture")
            if isinstance(architecture_payload, dict):
                architecture = architecture_payload
            modalities = architecture.get("input_modalities")
            modality = architecture.get("modality")
            vision_enabled = bool(
                isinstance(modalities, list)
                and any(str(value).lower() == "image" for value in modalities)
            )
            if not vision_enabled and isinstance(modality, str):
                modality_lower = modality.lower()
                vision_enabled = (
                    "image" in modality_lower or "multimodal" in modality_lower
                )

            conf: dict[str, Any] = {
                "provider": "openrouter",
                "model": model_id,
                "name": item.get("name") or model_id,
                "context_window": context_window,
                "max_output_tokens": max_output,
                "vision_enabled": vision_enabled,
                "reasoning_enabled": _supports_reasoning_model(model_id),
            }
            if isinstance(item.get("pricing"), dict):
                conf["pricing"] = item["pricing"]
            release_date = _openrouter_release_date(item.get("created"))
            if release_date:
                conf["release_date"] = release_date

            discovered[key] = conf
    except Exception as exc:
        logger.debug("OpenRouter model catalog fetch failed: %s", exc)
        return {}

    with _OPENROUTER_CATALOG_LOCK:
        _OPENROUTER_CATALOG_CACHE["fetched_at"] = time.time()
        _OPENROUTER_CATALOG_CACHE["models"] = discovered
    return discovered


def _merge_openrouter_catalog_models(
    provider_models: dict[str, dict[str, dict[str, Any]]],
    auth_records: dict[str, dict[str, Any]],
) -> dict[str, dict[str, dict[str, Any]]]:
    openrouter_record = auth_records.get("openrouter")
    record_key = ""
    if (
        isinstance(openrouter_record, dict)
        and openrouter_record.get("type") == "api"
        and isinstance(openrouter_record.get("key"), str)
    ):
        record_key = openrouter_record["key"].strip()

    discovered = _openrouter_catalog_models(api_key=record_key)
    if not discovered:
        return provider_models

    merged: dict[str, dict[str, dict[str, Any]]] = {
        provider_id: dict(models) for provider_id, models in provider_models.items()
    }
    openrouter_models = merged.setdefault("openrouter", {})
    for model_id, conf in discovered.items():
        openrouter_models.setdefault(model_id, conf)
    return merged


def _merge_models_dev_catalog_models(
    provider_models: dict[str, dict[str, dict[str, Any]]],
) -> dict[str, dict[str, dict[str, Any]]]:
    discovered = models_dev_provider_models(_MODELS_DEV_PROVIDER_IDS)
    if not discovered:
        return provider_models

    merged: dict[str, dict[str, dict[str, Any]]] = {
        provider_id: dict(models) for provider_id, models in provider_models.items()
    }
    for provider_id, models in discovered.items():
        mapped = merged.setdefault(provider_id, {})
        for model_id, conf in models.items():
            mapped.setdefault(model_id, conf)
    return merged


def _config_model_payload(
    model_id: str,
    provider_id: str,
    conf: dict[str, Any],
) -> dict[str, Any]:
    context_limit, output_limit = model_limit(conf)
    api_url, api_npm = provider_api(provider_id)
    reasoning_enabled = bool(
        conf.get("reasoning_enabled")
        or (
            isinstance(conf.get("reasoning"), dict) and conf["reasoning"].get("enabled")
        )
    )
    name = conf.get("name") or conf.get("model") or model_id
    release_date = conf.get("release_date")
    if not isinstance(release_date, str) or not release_date.strip():
        release_date = "1970-01-01T00:00:00+00:00"

    variants = _model_variants_payload(provider_id, model_id, reasoning_enabled)

    payload = {
        "id": model_id,
        "providerID": provider_id,
        "name": name,
        "api": {
            "id": model_id,
            "url": api_url,
            "npm": api_npm,
        },
        "capabilities": {
            "temperature": True,
            "reasoning": reasoning_enabled,
            "attachment": bool(conf.get("vision_enabled", False)),
            "toolcall": True,
            "input": {
                "text": True,
                "audio": False,
                "image": bool(conf.get("vision_enabled", False)),
                "video": False,
                "pdf": False,
            },
            "output": {
                "text": True,
                "audio": False,
                "image": False,
                "video": False,
                "pdf": False,
            },
            "interleaved": False,
        },
        "cost": _model_cost_payload(conf),
        "limit": {
            "context": context_limit,
            "output": output_limit,
        },
        "status": "active",
        "options": {},
        "headers": {},
        "release_date": release_date,
    }
    if variants:
        payload["variants"] = variants
    return payload


def _provider_list_model_payload(
    model_id: str,
    provider_id: str,
    conf: dict[str, Any],
) -> dict[str, Any]:
    context_limit, output_limit = model_limit(conf)
    reasoning_enabled = bool(
        conf.get("reasoning_enabled")
        or (
            isinstance(conf.get("reasoning"), dict) and conf["reasoning"].get("enabled")
        )
    )
    release_date = conf.get("release_date")
    if not isinstance(release_date, str) or not release_date.strip():
        release_date = "1970-01-01T00:00:00+00:00"

    variants = _model_variants_payload(provider_id, model_id, reasoning_enabled)

    payload = {
        "id": model_id,
        "name": conf.get("name") or conf.get("model") or model_id,
        "release_date": release_date,
        "attachment": bool(conf.get("vision_enabled", False)),
        "reasoning": reasoning_enabled,
        "temperature": True,
        "tool_call": True,
        "limit": {
            "context": context_limit,
            "output": output_limit,
        },
        "status": "active",
        "options": {},
    }
    if variants:
        payload["variants"] = variants
    return payload


def build_config_payload(core: Any) -> dict[str, Any]:
    """Build OpenCode-compatible ``config.get`` payload."""
    config_data = load_config()
    if not isinstance(config_data, dict):
        config_data = {}

    experimental_payload = {"disable_paste_summary": False}
    raw_experimental = config_data.get("experimental")
    if isinstance(raw_experimental, dict):
        experimental_payload.update(raw_experimental)

    payload: dict[str, Any] = {
        "share": str(config_data.get("share") or "disabled"),
        "experimental": experimental_payload,
    }

    passthrough_keys = (
        "theme",
        "keybinds",
        "tui",
        "lsp",
        "formatter",
        "plugin",
        "disabled_providers",
        "enabled_providers",
        "small_model",
    )
    for key in passthrough_keys:
        value = config_data.get(key)
        if value is not None:
            payload[key] = value

    provider_overrides = config_data.get("provider")
    if isinstance(provider_overrides, dict):
        payload["provider"] = provider_overrides

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    current_provider = ""
    current_model_id = ""
    if isinstance(current_model, dict):
        raw_provider = current_model.get("provider")
        if isinstance(raw_provider, str) and raw_provider.strip():
            current_provider = raw_provider.strip().lower()

        raw_model = current_model.get("model")
        if isinstance(raw_model, str) and raw_model.strip():
            current_model_id = canonical_model_id(current_provider, raw_model)

    model = current_model_string(core)
    if model:
        payload["model"] = model
    elif isinstance(config_data.get("model"), str) and config_data["model"].strip():
        payload["model"] = config_data["model"].strip()

    if current_provider:
        payload["provider"] = current_provider

    current_agent = getattr(
        getattr(core, "conversation_manager", None), "current_agent_id", None
    )
    if isinstance(current_agent, str) and current_agent:
        payload["default_agent"] = current_agent
    elif isinstance(config_data.get("default_agent"), str):
        default_agent = config_data.get("default_agent", "").strip()
        if default_agent:
            payload["default_agent"] = default_agent

    model_config = getattr(core, "model_config", None)
    if model_config is not None:
        reasoning: dict[str, Any] = {
            "enabled": bool(getattr(model_config, "reasoning_enabled", False)),
        }
        effort = getattr(model_config, "reasoning_effort", None)
        if isinstance(effort, str) and effort:
            reasoning["effort"] = effort
        max_tokens = getattr(model_config, "reasoning_max_tokens", None)
        if isinstance(max_tokens, int) and max_tokens > 0:
            reasoning["max_tokens"] = max_tokens
        if bool(getattr(model_config, "reasoning_exclude", False)):
            reasoning["exclude"] = True
        supports_reasoning = getattr(model_config, "supports_reasoning", None)
        if isinstance(supports_reasoning, bool):
            reasoning["supported"] = supports_reasoning
        payload["reasoning"] = reasoning

    runtime_config = getattr(core, "runtime_config", None)
    if runtime_config is not None:
        runtime_dict: dict[str, Any] = {}
        if hasattr(runtime_config, "to_dict"):
            maybe_runtime = runtime_config.to_dict()
            if isinstance(maybe_runtime, dict):
                runtime_dict = maybe_runtime

        capabilities = {
            "reasoning_enabled": bool(
                getattr(model_config, "reasoning_enabled", False)
            ),
            "reasoning_supported": bool(
                getattr(model_config, "supports_reasoning", False)
            ),
            "vision_enabled": bool(getattr(model_config, "vision_enabled", False)),
        }

        payload["penguin"] = {
            **runtime_dict,
            "execution_mode": getattr(runtime_config, "execution_mode", None),
            "active_root": getattr(runtime_config, "active_root", None),
            "project_root": getattr(runtime_config, "project_root", None),
            "workspace_root": getattr(runtime_config, "workspace_root", None),
            "current_model": {
                "provider": current_provider or None,
                "id": current_model_id or None,
                "qualified": (
                    qualified_model_ref(current_provider, current_model_id)
                    if current_provider and current_model_id
                    else None
                ),
            },
            "capabilities": capabilities,
        }

    return payload


def build_config_providers_payload(core: Any) -> dict[str, Any]:
    """Build OpenCode-compatible ``config.providers`` payload."""
    config_data = load_config()
    if not isinstance(config_data, dict):
        config_data = {}
    config_provider_models = collect_provider_models(core)
    providers: list[dict[str, Any]] = []
    default: dict[str, str] = {}
    auth_records = get_provider_credentials()
    provider_models = _merge_openrouter_catalog_models(
        config_provider_models,
        auth_records,
    )

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    current_provider = ""
    current_model_id = ""
    if isinstance(current_model, dict):
        current_provider = str(current_model.get("provider") or "")
        current_model_id = canonical_model_id(
            current_provider,
            str(current_model.get("model") or ""),
        )

    enabled_filters, disabled_filters = _provider_filters(config_data)

    provider_set = set(provider_models.keys())
    provider_set.update(auth_records.keys())
    provider_set.update(env_connected_provider_ids())
    if current_provider:
        provider_set.add(current_provider)

    provider_models = _merge_models_dev_catalog_models(provider_models)
    provider_set.update(provider_models.keys())

    for provider_id in sorted(provider_set):
        if not _provider_visible(provider_id, enabled_filters, disabled_filters):
            continue
        models = provider_models.get(provider_id, {})
        mapped_models = {
            model_id: _config_model_payload(model_id, provider_id, conf)
            for model_id, conf in sorted(models.items(), key=lambda item: item[0])
        }
        source = "config"
        config_models = config_provider_models.get(provider_id, {})
        if mapped_models and provider_id == "openrouter" and not config_models:
            source = (
                "api" if provider_connected(provider_id, auth_records) else "custom"
            )
        elif not mapped_models:
            source = (
                "env"
                if any(os.getenv(name) for name in provider_env(provider_id))
                else "api"
                if provider_connected(provider_id, auth_records)
                else "custom"
            )
        providers.append(
            {
                "id": provider_id,
                "name": provider_name(provider_id),
                "source": source,
                "env": provider_env(provider_id),
                "options": {},
                "models": mapped_models,
            }
        )

        if current_provider == provider_id and current_model_id in mapped_models:
            default[provider_id] = current_model_id
        elif mapped_models:
            default[provider_id] = next(iter(mapped_models.keys()))

    return {
        "providers": providers,
        "default": default,
    }


def build_provider_list_payload(core: Any) -> dict[str, Any]:
    """Build OpenCode-compatible ``provider.list`` payload."""
    config_provider_models = collect_provider_models(core)
    auth_records = get_provider_credentials()
    provider_models = _merge_openrouter_catalog_models(
        config_provider_models,
        auth_records,
    )

    all_providers: list[dict[str, Any]] = []
    default: dict[str, str] = {}
    connected: list[str] = []

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    current_provider = ""
    current_model_id = ""
    if isinstance(current_model, dict):
        current_provider = str(current_model.get("provider") or "")
        current_model_id = canonical_model_id(
            current_provider,
            str(current_model.get("model") or ""),
        )

    config_data = load_config()
    if not isinstance(config_data, dict):
        config_data = {}
    enabled_filters, disabled_filters = _provider_filters(config_data)

    provider_set = set(provider_models.keys())
    provider_set.update(auth_records.keys())
    provider_set.update(env_connected_provider_ids())
    if current_provider:
        provider_set.add(current_provider)

    provider_models = _merge_models_dev_catalog_models(provider_models)
    provider_set.update(provider_models.keys())

    for provider_id in sorted(provider_set):
        if not _provider_visible(provider_id, enabled_filters, disabled_filters):
            continue
        models = provider_models.get(provider_id, {})
        mapped_models = {
            model_id: _provider_list_model_payload(model_id, provider_id, conf)
            for model_id, conf in sorted(models.items(), key=lambda item: item[0])
        }
        api_url, api_npm = provider_api(provider_id)
        all_providers.append(
            {
                "id": provider_id,
                "name": provider_name(provider_id),
                "api": api_url,
                "npm": api_npm,
                "env": provider_env(provider_id),
                "models": mapped_models,
            }
        )

        if current_provider == provider_id and current_model_id in mapped_models:
            default[provider_id] = current_model_id
        elif mapped_models:
            default[provider_id] = next(iter(mapped_models.keys()))

        if provider_connected(provider_id, auth_records):
            connected.append(provider_id)

    return {
        "all": all_providers,
        "default": default,
        "connected": sorted(set(connected)),
    }


def provider_auth_methods(
    core: Any | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Build OpenCode-compatible provider auth methods map."""
    ids = provider_ids(core) if core is not None else set()
    return auth_methods_for_providers(ids)


def get_provider_auth_records() -> dict[str, dict[str, Any]]:
    """Compatibility wrapper for provider credentials records."""
    return get_provider_credentials()


def set_provider_auth_record(provider_id: str, payload: dict[str, Any]) -> None:
    """Compatibility wrapper to set provider credentials record."""
    set_provider_credential(provider_id, payload)


def remove_provider_auth_record(provider_id: str) -> bool:
    """Compatibility wrapper to remove provider credentials record."""
    return remove_provider_credential(provider_id)


async def provider_oauth_authorize(
    provider_id: str, method_index: int
) -> dict[str, Any]:
    """Compatibility wrapper to start provider OAuth flow."""
    return await authorize_provider_oauth(provider_id, method_index)


async def provider_oauth_callback(
    provider_id: str,
    method_index: int,
    code: str | None = None,
) -> bool:
    """Compatibility wrapper to complete provider OAuth flow."""
    return await callback_provider_oauth(provider_id, method_index, code=code)


def apply_auth_to_runtime(
    core: Any,
    provider_id: str,
    auth_record: dict[str, Any],
) -> None:
    """Compatibility wrapper for runtime credential application."""
    apply_credentials_to_runtime(core, provider_id, auth_record)


__all__ = [
    "_OPENAI_OAUTH_DEVICE_URL",
    "_PENDING_OAUTH",
    "apply_auth_to_runtime",
    "build_config_payload",
    "build_config_providers_payload",
    "build_provider_list_payload",
    "get_provider_auth_records",
    "get_provider_credential",
    "provider_auth_methods",
    "provider_oauth_authorize",
    "provider_oauth_callback",
    "remove_provider_auth_record",
    "set_provider_auth_record",
]
