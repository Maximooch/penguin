"""Tool provider adapters for dynamic external tool surfaces."""

from __future__ import annotations

__all__ = ["MCPToolProvider"]


def __getattr__(name: str):
    if name == "MCPToolProvider":
        from penguin.tools.providers.mcp import MCPToolProvider

        return MCPToolProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
