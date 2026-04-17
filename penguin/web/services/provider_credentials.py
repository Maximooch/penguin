"""General-purpose provider credential persistence and runtime application."""

from __future__ import annotations

import json
import logging
import os
import time
import warnings
from pathlib import Path
from threading import RLock
from typing import Any

logger = logging.getLogger(__name__)

_CREDENTIALS_STORE_VERSION = 1
_STORE_ENV = "PENGUIN_PROVIDER_CREDENTIALS_STORE"
_LEGACY_STORE_ENV = "PENGUIN_PROVIDER_AUTH_STORE"
_DEFAULT_OAUTH_REFRESH_WINDOW_MS = 5 * 60 * 1000

_CREDENTIALS_LOCK = RLock()
_PLACEHOLDER_API_KEYS = {
    "sk-test",
    "sk-or-test",
    "sk-or-catalog",
    "your_api_key",
    "changeme",
    "dummy",
    "placeholder",
    "test",
}


_LEGACY_STORE_WARNING = (
    "Provider credentials loaded from legacy plaintext JSON store. Prefer environment "
    "variables for headless/server deployments; plaintext persistence is deprecated."
)
_WARNED_LEGACY_PATHS: set[Path] = set()


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


def _warn_legacy_store_usage(path: Path) -> None:
    resolved = path.expanduser().resolve()
    if resolved in _WARNED_LEGACY_PATHS:
        return
    _WARNED_LEGACY_PATHS.add(resolved)
    logger.warning("%s path=%s", _LEGACY_STORE_WARNING, resolved)
    warnings.warn(_LEGACY_STORE_WARNING, UserWarning, stacklevel=2)


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
        if os.getenv(_LEGACY_STORE_ENV) or path == _legacy_default_store_path():
            _warn_legacy_store_usage(path)
        return primary

    if path == _default_store_path():
        legacy_path = _legacy_store_path()
        if legacy_path != path and legacy_path.exists():
            legacy_payload = _read_store(legacy_path)
            legacy_providers = legacy_payload.get("providers")
            if isinstance(legacy_providers, dict) and legacy_providers:
                _warn_legacy_store_usage(legacy_path)
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
    """Return provider credential records with env values taking precedence."""
    with _CREDENTIALS_LOCK:
        providers = _load_store().get("providers")
        records = {
            str(key): value
            for key, value in providers.items()
            if isinstance(key, str) and isinstance(value, dict)
        } if isinstance(providers, dict) else {}

        merged = dict(records)
        provider_ids = set(records.keys())
        provider_ids.update({
            "openai",
            "openrouter",
            "anthropic",
            "google",
        })

        for provider_id in provider_ids:
            env_record = _credential_record_from_environment(provider_id)
            if env_record is not None:
                merged[provider_id] = env_record
        return merged


def get_provider_credential(provider_id: str) -> dict[str, Any] | None:
    """Return credential record for a provider if present."""
    pid = provider_id.strip().lower()
    if not pid:
        return None
    return get_provider_credentials().get(pid)


def oauth_record_expired(
    credential_record: dict[str, Any],
    *,
    now_ms: int | None = None,
) -> bool:
    """Return whether an OAuth credential record is already expired."""
    if credential_record.get("type") != "oauth":
        return False
    expires = credential_record.get("expires")
    if not isinstance(expires, int):
        return False
    current_ms = now_ms if isinstance(now_ms, int) else int(time.time() * 1000)
    return expires <= current_ms


def oauth_record_needs_refresh(
    credential_record: dict[str, Any],
    *,
    now_ms: int | None = None,
    refresh_window_ms: int = _DEFAULT_OAUTH_REFRESH_WINDOW_MS,
) -> bool:
    """Return whether an OAuth credential should be proactively refreshed."""
    if credential_record.get("type") != "oauth":
        return False
    expires = credential_record.get("expires")
    if not isinstance(expires, int):
        return False

    current_ms = now_ms if isinstance(now_ms, int) else int(time.time() * 1000)
    window_ms = refresh_window_ms if isinstance(refresh_window_ms, int) else 0
    if window_ms < 0:
        window_ms = 0
    return expires <= current_ms + window_ms


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
    }
    if pid in mapping:
        return mapping[pid]
    if pid:
        return [f"{pid.upper()}_API_KEY"]
    return []


def _credential_record_from_environment(provider_id: str) -> dict[str, Any] | None:
    pid = provider_id.strip().lower()
    if not pid:
        return None

    if pid == "ollama":
        return None

    if pid == "openai":
        access = os.getenv("OPENAI_OAUTH_ACCESS_TOKEN", "").strip()
        refresh = os.getenv("OPENAI_OAUTH_REFRESH_TOKEN", "").strip()
        expires_raw = os.getenv("OPENAI_OAUTH_EXPIRES_AT_MS", "").strip()
        if access and refresh and expires_raw:
            try:
                expires = int(expires_raw)
            except ValueError:
                logger.warning(
                    "Ignoring OPENAI OAuth environment credentials due to invalid expiry"
                )
            else:
                record: dict[str, Any] = {
                    "type": "oauth",
                    "access": access,
                    "refresh": refresh,
                    "expires": expires,
                }
                account_id = os.getenv("OPENAI_ACCOUNT_ID", "").strip()
                if account_id:
                    record["accountId"] = account_id
                return record

    for env_name in _provider_env_candidates(pid):
        value = os.getenv(env_name, "").strip()
        if value and not _is_placeholder_api_key(value):
            return {"type": "api", "key": value}
    return None


def _is_placeholder_api_key(value: Any) -> bool:
    if not isinstance(value, str):
        return False
    normalized = value.strip().lower()
    if not normalized:
        return False
    return normalized in _PLACEHOLDER_API_KEYS


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
            return bool(record["key"].strip()) and not _is_placeholder_api_key(
                record["key"]
            )
        if auth_type == "oauth" and isinstance(record.get("refresh"), str):
            return bool(record["refresh"].strip())
        if auth_type == "wellknown" and isinstance(record.get("token"), str):
            return bool(record["token"].strip())

    return any(
        value and not _is_placeholder_api_key(value)
        for env_name in _provider_env_candidates(pid)
        for value in [os.getenv(env_name)]
    )


def apply_credentials_to_environment(
    provider_id: str,
    credential_record: dict[str, Any],
) -> None:
    """Apply provider credentials to process environment variables only."""
    pid = provider_id.strip().lower()
    auth_type = (
        credential_record.get("type") if isinstance(credential_record, dict) else None
    )

    if auth_type == "api":
        if pid == "ollama":
            return
        key = credential_record.get("key")
        if not isinstance(key, str) or not key:
            return
        if _is_placeholder_api_key(key):
            logger.warning("Ignoring placeholder API credential for provider '%s'", pid)
            return

        if pid == "openrouter":
            os.environ["OPENROUTER_API_KEY"] = key
            return
        if pid == "openai":
            os.environ["OPENAI_API_KEY"] = key
            return

        os.environ[f"{pid.upper()}_API_KEY"] = key
        return

    if auth_type == "oauth" and pid == "openai":
        access = credential_record.get("access")
        account_id = credential_record.get("accountId")
        if isinstance(access, str) and access:
            os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] = access
        if isinstance(account_id, str) and account_id:
            os.environ["OPENAI_ACCOUNT_ID"] = account_id


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

    apply_credentials_to_environment(pid, credential_record)

    if auth_type == "api":
        key = credential_record.get("key")
        if not isinstance(key, str) or not key:
            return
        if _is_placeholder_api_key(key):
            logger.warning(
                "Ignoring placeholder runtime API credential for provider '%s'", pid
            )
            return

        model_config = getattr(core, "model_config", None)
        if getattr(model_config, "provider", None) == pid:
            setattr(model_config, "api_key", key)
        return

    if auth_type == "oauth" and pid == "openai":
        access = credential_record.get("access")

        model_config = getattr(core, "model_config", None)
        if (
            isinstance(access, str)
            and access
            and getattr(model_config, "provider", None) == pid
        ):
            setattr(model_config, "api_key", access)
