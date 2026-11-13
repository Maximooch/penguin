"""Harness-owned MCP configuration overrides for isolated workers."""

from __future__ import annotations

import json
import os
from typing import Any

__all__ = ["isolated_mcp_config"]


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
        or not str(value.get("url", "")).startswith("http://127.0.0.1:")
        for name, value in servers.items()
    ):
        raise ValueError("Isolated MCP servers must use loopback streamable HTTP")
    return {"mcp": {"enabled": True, "servers": servers}}
