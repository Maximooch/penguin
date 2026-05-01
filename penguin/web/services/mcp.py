"""MCP diagnostics service helpers for the web/API layer."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from penguin.core import PenguinCore


def get_mcp_status(core: PenguinCore, refresh: bool = False) -> dict[str, Any]:
    """Return MCP provider status, optionally refreshing tool discovery first."""
    tool_manager = getattr(core, "tool_manager", None)
    if tool_manager is None:
        return {"enabled": False, "initialized": False, "servers": {}}
    if refresh and hasattr(tool_manager, "refresh_mcp_tools"):
        tool_manager.refresh_mcp_tools()
    if hasattr(tool_manager, "get_mcp_status"):
        return tool_manager.get_mcp_status()
    return {"enabled": False, "initialized": False, "servers": {}}


def reconnect_mcp(
    core: PenguinCore,
    server_name: str | None = None,
) -> dict[str, Any]:
    """Reconnect one or all configured MCP servers."""
    tool_manager = getattr(core, "tool_manager", None)
    if tool_manager is None or not hasattr(tool_manager, "reconnect_mcp"):
        return {"enabled": False, "initialized": False, "servers": {}}
    return tool_manager.reconnect_mcp(server_name)


def close_mcp(core: PenguinCore) -> dict[str, Any]:
    """Close all MCP sessions."""
    tool_manager = getattr(core, "tool_manager", None)
    if tool_manager is None or not hasattr(tool_manager, "close_mcp"):
        return {"enabled": False, "initialized": False, "servers": {}}
    return tool_manager.close_mcp()


__all__ = ["close_mcp", "get_mcp_status", "reconnect_mcp"]
