"""Tool provider adapters for dynamic external tool surfaces."""

from __future__ import annotations

from typing import Any, Type

__all__ = ["MCPToolProvider"]


def __getattr__(name: str) -> Type[Any]:
    if name == "MCPToolProvider":
        from penguin.tools.providers.mcp import MCPToolProvider

        return MCPToolProvider
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
