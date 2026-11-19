"""Harness-owned MCP configuration overrides for isolated workers."""

from __future__ import annotations

import json
import os
from typing import Any
from urllib.parse import urlsplit

__all__ = ["isolated_mcp_config"]


def _is_loopback_http_url(url: object) -> bool:
    """Return whether ``url`` is ``http://127.0.0.1:<port>/...`` once parsed.

    A prefix test is not enough: in ``http://127.0.0.1:1@other.host/`` the
    text before ``@`` is a username and the host is ``other.host``.
    """
    if not isinstance(url, str):
        return False
    try:
        parts = urlsplit(url)
        port = parts.port
    except ValueError:
        return False
    return (
        parts.scheme == "http"
        and parts.hostname == "127.0.0.1"
        and parts.username is None
        and parts.password is None
        and port is not None
    )


def isolated_mcp_config(config: dict[str, Any]) -> dict[str, Any]:
    """Replace inherited servers when the process owner supplies an override.

    Raises:
        ValueError: If the startup override is not a server mapping.
    """
    raw = os.environ.get("PENGUIN_MCP_SERVERS_JSON")
    if raw is None:
        return config
    try:
        servers = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise ValueError("Invalid isolated MCP server mapping") from exc
    if not isinstance(servers, dict) or any(
        not isinstance(name, str) or not isinstance(value, dict)
        or value.get("transport") != "streamable_http"
        or not _is_loopback_http_url(value.get("url"))
        for name, value in servers.items()
    ):
        raise ValueError("Isolated MCP servers must use loopback streamable HTTP")
    return {"mcp": {"enabled": True, "servers": servers}}
