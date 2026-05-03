"""Shared MCP server-tool descriptors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable


@dataclass(frozen=True)
class MCPServerTool:
    """A Penguin runtime capability exposed as an MCP server tool."""

    name: str
    description: str
    input_schema: dict[str, Any]
    handler: Callable[[dict[str, Any]], Any]


__all__ = ["MCPServerTool"]
