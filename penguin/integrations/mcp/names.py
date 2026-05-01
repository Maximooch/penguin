"""Name mapping helpers for MCP tools exposed through Penguin."""

from __future__ import annotations

import re
from typing import Iterable

MCP_TOOL_PREFIX = "mcp__"
_SAFE_NAME_RE = re.compile(r"[^a-zA-Z0-9_]+")


def sanitize_part(value: str) -> str:
    """Return a conservative function-name component."""
    text = _SAFE_NAME_RE.sub("_", str(value or "").strip())
    text = re.sub(r"_+", "_", text).strip("_").lower()
    return text or "unnamed"


def make_tool_name(server_name: str, tool_name: str, existing: Iterable[str] = ()) -> str:
    """Build a collision-safe Penguin tool name for an MCP tool."""
    base = f"{MCP_TOOL_PREFIX}{sanitize_part(server_name)}__{sanitize_part(tool_name)}"
    seen = set(existing)
    if base not in seen:
        return base

    index = 2
    candidate = f"{base}_{index}"
    while candidate in seen:
        index += 1
        candidate = f"{base}_{index}"
    return candidate


def is_mcp_tool_name(tool_name: str) -> bool:
    """Return True when a public Penguin tool name belongs to MCP."""
    return str(tool_name or "").startswith(MCP_TOOL_PREFIX)


__all__ = ["MCP_TOOL_PREFIX", "is_mcp_tool_name", "make_tool_name", "sanitize_part"]
