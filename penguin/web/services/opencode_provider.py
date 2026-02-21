"""OpenCode compatibility adapter for provider/config/auth payloads.

Business logic is delegated to general-purpose provider services.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

import httpx

from penguin.web.services.provider_auth import (
    _OPENAI_OAUTH_DEVICE_URL,
    _PENDING_OAUTH,
    authorize_provider_oauth,
    callback_provider_oauth,
    provider_auth_methods as auth_methods_for_providers,
)
from penguin.web.services.provider_catalog import (
    collect_provider_models,
    current_model_string,
    model_limit,
    provider_api,
    provider_env,
    provider_ids,
    provider_name,
)
from penguin.web.services.provider_credentials import (
    apply_credentials_to_runtime,
    get_provider_credential,
    get_provider_credentials,
    provider_connected,
    remove_provider_credential,
    set_provider_credential,
)


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
    now = datetime.now(timezone.utc).isoformat()

    return {
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
        "cost": {
            "input": 0,
            "output": 0,
            "cache": {"read": 0, "write": 0},
        },
        "limit": {
            "context": context_limit,
            "output": output_limit,
        },
        "status": "active",
        "options": {},
        "headers": {},
        "release_date": now,
    }


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
    now = datetime.now(timezone.utc).isoformat()

    return {
        "id": model_id,
        "name": conf.get("name") or conf.get("model") or model_id,
        "release_date": now,
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


def build_config_payload(core: Any) -> dict[str, Any]:
    """Build OpenCode-compatible ``config.get`` payload."""
    payload: dict[str, Any] = {
        "share": "disabled",
        "experimental": {"disable_paste_summary": False},
    }

    model = current_model_string(core)
    if model:
        payload["model"] = model

    current_agent = getattr(
        getattr(core, "conversation_manager", None), "current_agent_id", None
    )
    if isinstance(current_agent, str) and current_agent:
        payload["default_agent"] = current_agent

    model_config = getattr(core, "model_config", None)
    if model_config is not None:
        reasoning: dict[str, Any] = {
            "enabled": bool(getattr(model_config, "reasoning_enabled", False)),
        }
        effort = getattr(model_config, "reasoning_effort", None)
        if isinstance(effort, str) and effort:
            reasoning["effort"] = effort
        payload["reasoning"] = reasoning

    runtime_config = getattr(core, "runtime_config", None)
    if runtime_config is not None:
        payload["penguin"] = {
            "execution_mode": getattr(runtime_config, "execution_mode", None),
            "active_root": getattr(runtime_config, "active_root", None),
            "project_root": getattr(runtime_config, "project_root", None),
            "workspace_root": getattr(runtime_config, "workspace_root", None),
        }

    return payload


def build_config_providers_payload(core: Any) -> dict[str, Any]:
    """Build OpenCode-compatible ``config.providers`` payload."""
    provider_models = collect_provider_models(core)
    providers: list[dict[str, Any]] = []
    default: dict[str, str] = {}

    current_model = (
        core.get_current_model() if hasattr(core, "get_current_model") else None
    )
    current_provider = ""
    current_model_id = ""
    if isinstance(current_model, dict):
        current_provider = str(current_model.get("provider") or "")
        current_model_id = str(current_model.get("model") or "")

    for provider_id, models in sorted(
        provider_models.items(), key=lambda item: item[0]
    ):
        mapped_models = {
            model_id: _config_model_payload(model_id, provider_id, conf)
            for model_id, conf in sorted(models.items(), key=lambda item: item[0])
        }
        providers.append(
            {
                "id": provider_id,
                "name": provider_name(provider_id),
                "source": "config",
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
    provider_models = collect_provider_models(core)
    auth_records = get_provider_credentials()

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
        current_model_id = str(current_model.get("model") or "")

    for provider_id, models in sorted(
        provider_models.items(), key=lambda item: item[0]
    ):
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
    core: Optional[Any] = None,
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
    code: Optional[str] = None,
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
    "provider_auth_methods",
    "provider_oauth_authorize",
    "provider_oauth_callback",
    "remove_provider_auth_record",
    "set_provider_auth_record",
    "get_provider_credential",
]
