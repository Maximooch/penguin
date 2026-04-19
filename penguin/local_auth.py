"""Shared local auth helpers for Penguin browser and TUI bootstrap flows."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Mapping
from urllib.parse import urlparse

from penguin.constants import DEFAULT_WEB_PORT

LOCAL_AUTH_CACHE_DIR_ENV = "PENGUIN_LOCAL_AUTH_CACHE_DIR"
WEB_AUTH_ENABLED_ENV = "PENGUIN_AUTH_ENABLED"

__all__ = [
    "WEB_AUTH_ENABLED_ENV",
    "is_web_auth_enabled",
    "local_auth_token_path",
    "read_local_auth_token",
    "write_local_auth_token",
]


def is_web_auth_enabled(env: Mapping[str, str] | None = None) -> bool:
    """Return whether Penguin web auth should be enabled.

    Web auth is protected-by-default. Only explicit false-like values disable it.
    """
    source = os.environ if env is None else env
    raw = source.get(WEB_AUTH_ENABLED_ENV, "")
    normalized = raw.strip().lower()
    if not normalized:
        return True
    return normalized not in {"0", "false", "no", "off"}


def _normalize_local_auth_host(host: str) -> str:
    normalized = (host or "").strip().lower()
    if normalized in {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}:
        return "127.0.0.1"
    return normalized.replace(":", "_")


def _local_auth_cache_dir() -> Path:
    raw = os.getenv(LOCAL_AUTH_CACHE_DIR_ENV, "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".cache" / "penguin" / "auth"


def local_auth_token_path(
    base_url: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> Path:
    """Return the cache path for a loopback Penguin startup token."""
    if base_url:
        parsed = urlparse(base_url)
        host = parsed.hostname or host or "127.0.0.1"
        port = parsed.port or port or DEFAULT_WEB_PORT
    else:
        host = host or os.getenv("HOST", "127.0.0.1")
        port = port or int(os.getenv("PORT", str(DEFAULT_WEB_PORT)))

    cache_dir = _local_auth_cache_dir()
    return cache_dir / f"{_normalize_local_auth_host(host)}-{port}.token"


def read_local_auth_token(
    base_url: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> str | None:
    """Read a cached local startup token if one exists."""
    path = local_auth_token_path(base_url, host=host, port=port)
    try:
        token = path.read_text(encoding="utf-8").strip()
    except OSError:
        return None
    return token or None


def write_local_auth_token(
    token: str,
    base_url: str | None = None,
    *,
    host: str | None = None,
    port: int | None = None,
) -> Path:
    """Persist a loopback Penguin startup token for local launcher reuse."""
    path = local_auth_token_path(base_url, host=host, port=port)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(token.strip(), encoding="utf-8")
    try:
        path.chmod(0o600)
    except OSError:
        pass
    return path
