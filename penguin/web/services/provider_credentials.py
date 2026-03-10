"""General-purpose provider credential persistence and runtime application."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

_CREDENTIALS_STORE_VERSION = 1
_STORE_ENV = "PENGUIN_PROVIDER_CREDENTIALS_STORE"
_LEGACY_STORE_ENV = "PENGUIN_PROVIDER_AUTH_STORE"

_CREDENTIALS_LOCK = RLock()


def _default_store_path() -> Path:
    return Path.home() / ".config" / "penguin" / "providers" / "credentials.json"


def _legacy_default_store_path() -> Path:
    return Path.home() / ".config" / "penguin" / "provider_auth.json"


def _store_path() -> Path:
    """Resolve active credentials store path."""
    explicit = os.getenv(_STORE_ENV)
    if explicit:
        return Path(explicit).expanduser().resolve()

    legacy = os.getenv(_LEGACY_STORE_ENV)
    if legacy:
        return Path(legacy).expanduser().resolve()

    return _default_store_path()


def _legacy_store_path() -> Path:
    legacy = os.getenv(_LEGACY_STORE_ENV)
    if legacy:
        return Path(legacy).expanduser().resolve()
    return _legacy_default_store_path()


def _ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def _normalize_store(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        return {"version": _CREDENTIALS_STORE_VERSION, "providers": {}}

    providers = payload.get("providers")
    if not isinstance(providers, dict):
        providers = {}

    return {
        "version": int(payload.get("version") or _CREDENTIALS_STORE_VERSION),
        "providers": providers,
    }


def _read_store(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"version": _CREDENTIALS_STORE_VERSION, "providers": {}}

    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("Provider credentials store is invalid JSON: %s", path)
        return {"version": _CREDENTIALS_STORE_VERSION, "providers": {}}

    return _normalize_store(payload)


def _load_store() -> dict[str, Any]:
    path = _store_path()
    primary = _read_store(path)

    providers = primary.get("providers")
    if isinstance(providers, dict) and providers:
        return primary

    if path == _default_store_path():
        legacy_path = _legacy_store_path()
        if legacy_path != path and legacy_path.exists():
            legacy_payload = _read_store(legacy_path)
            legacy_providers = legacy_payload.get("providers")
            if isinstance(legacy_providers, dict) and legacy_providers:
                return legacy_payload

    return primary


def _write_store(payload: dict[str, Any]) -> None:
    path = _store_path()
    _ensure_parent(path)
    temp_path = path.with_suffix(path.suffix + ".tmp")
    temp_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    try:
        os.chmod(temp_path, 0o600)
    except Exception:
        logger.debug("Unable to chmod temp credentials file", exc_info=True)
    temp_path.replace(path)
    try:
        os.chmod(path, 0o600)
    except Exception:
        logger.debug("Unable to chmod credentials file", exc_info=True)


def _sanitize_record(payload: dict[str, Any]) -> dict[str, Any]:
    auth_type = str(payload.get("type") or "").strip().lower()
    if auth_type == "api":
        key = payload.get("key")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("API auth requires non-empty 'key'")
        return {"type": "api", "key": key.strip()}

    if auth_type == "oauth":
        access = payload.get("access")
        refresh = payload.get("refresh")
        expires = payload.get("expires")
        if not isinstance(access, str) or not access.strip():
            raise ValueError("OAuth auth requires non-empty 'access'")
        if not isinstance(refresh, str) or not refresh.strip():
            raise ValueError("OAuth auth requires non-empty 'refresh'")
        if not isinstance(expires, int):
            raise ValueError("OAuth auth requires integer 'expires'")

        record: dict[str, Any] = {
            "type": "oauth",
            "access": access.strip(),
            "refresh": refresh.strip(),
            "expires": expires,
        }

        account_id = payload.get("accountId")
        if isinstance(account_id, str) and account_id.strip():
            record["accountId"] = account_id.strip()

        enterprise_url = payload.get("enterpriseUrl")
        if isinstance(enterprise_url, str) and enterprise_url.strip():
            record["enterpriseUrl"] = enterprise_url.strip()

        return record

    if auth_type == "wellknown":
        key = payload.get("key")
        token = payload.get("token")
        if not isinstance(key, str) or not key.strip():
            raise ValueError("WellKnown auth requires non-empty 'key'")
        if not isinstance(token, str) or not token.strip():
            raise ValueError("WellKnown auth requires non-empty 'token'")
        return {"type": "wellknown", "key": key.strip(), "token": token.strip()}

    raise ValueError("Unsupported auth type; expected 'api', 'oauth', or 'wellknown'")


def get_provider_credentials() -> dict[str, dict[str, Any]]:
    """Return provider credential records."""
    with _CREDENTIALS_LOCK:
        providers = _load_store().get("providers")
        if not isinstance(providers, dict):
            return {}
        return {
            str(key): value
            for key, value in providers.items()
            if isinstance(key, str) and isinstance(value, dict)
        }


def get_provider_credential(provider_id: str) -> dict[str, Any] | None:
    """Return credential record for a provider if present."""
    pid = provider_id.strip().lower()
    if not pid:
        return None
    return get_provider_credentials().get(pid)


def set_provider_credential(provider_id: str, payload: dict[str, Any]) -> None:
    """Create/update provider credentials record."""
    normalized = _sanitize_record(payload)
    pid = provider_id.strip().lower()
    if not pid:
        raise ValueError("provider_id is required")

    with _CREDENTIALS_LOCK:
        store = _load_store()
        providers = store.setdefault("providers", {})
        providers[pid] = normalized
        store["version"] = _CREDENTIALS_STORE_VERSION
        _write_store(store)


def remove_provider_credential(provider_id: str) -> bool:
    """Remove provider credentials record."""
    pid = provider_id.strip().lower()
    if not pid:
        return False

    with _CREDENTIALS_LOCK:
        store = _load_store()
        providers = store.setdefault("providers", {})
        if pid not in providers:
            return False
        providers.pop(pid, None)
        store["version"] = _CREDENTIALS_STORE_VERSION
        _write_store(store)
    return True


def _provider_env_candidates(provider_id: str) -> list[str]:
    pid = provider_id.strip().lower()
    mapping = {
        "openrouter": ["OPENROUTER_API_KEY"],
        "openai": ["OPENAI_API_KEY"],
        "anthropic": ["ANTHROPIC_API_KEY"],
        "google": ["GOOGLE_API_KEY", "GEMINI_API_KEY"],
        "ollama": ["OLLAMA_HOST"],
    }
    if pid in mapping:
        return mapping[pid]
    if pid:
        return [f"{pid.upper()}_API_KEY"]
    return []


def provider_connected(
    provider_id: str,
    records: dict[str, dict[str, Any]] | None = None,
) -> bool:
    """Return whether a provider appears connected."""
    pid = provider_id.strip().lower()
    if not pid:
        return False

    all_records = records if records is not None else get_provider_credentials()
    record = all_records.get(pid)
    if isinstance(record, dict):
        auth_type = record.get("type")
        if auth_type == "api" and isinstance(record.get("key"), str):
            return bool(record["key"].strip())
        if auth_type == "oauth" and isinstance(record.get("refresh"), str):
            return bool(record["refresh"].strip())
        if auth_type == "wellknown" and isinstance(record.get("token"), str):
            return bool(record["token"].strip())

    return any(os.getenv(env_name) for env_name in _provider_env_candidates(pid))


def apply_credentials_to_runtime(
    core: Any,
    provider_id: str,
    credential_record: dict[str, Any],
) -> None:
    """Apply provider credentials to process/runtime state for immediate use."""
    pid = provider_id.strip().lower()
    auth_type = (
        credential_record.get("type") if isinstance(credential_record, dict) else None
    )

    if auth_type == "api":
        key = credential_record.get("key")
        if not isinstance(key, str) or not key:
            return

        if pid == "openrouter":
            os.environ["OPENROUTER_API_KEY"] = key
        elif pid == "openai":
            os.environ["OPENAI_API_KEY"] = key
        else:
            os.environ[f"{pid.upper()}_API_KEY"] = key

        model_config = getattr(core, "model_config", None)
        if getattr(model_config, "provider", None) == pid:
            setattr(model_config, "api_key", key)
        return

    if auth_type == "oauth" and pid == "openai":
        access = credential_record.get("access")
        account_id = credential_record.get("accountId")
        if isinstance(access, str) and access:
            os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] = access
        if isinstance(account_id, str) and account_id:
            os.environ["OPENAI_ACCOUNT_ID"] = account_id

        model_config = getattr(core, "model_config", None)
        if (
            isinstance(access, str)
            and access
            and getattr(model_config, "provider", None) == pid
        ):
            setattr(model_config, "api_key", access)
