"""ToolManager provider for MCP-hosted tools."""

from __future__ import annotations

import json
import logging
from typing import Any

from penguin.integrations.mcp.config import load_mcp_server_configs
from penguin.integrations.mcp.manager import MCPClientManager
from penguin.integrations.mcp.names import is_mcp_tool_name

logger = logging.getLogger(__name__)


class MCPToolProvider:
    """Expose external MCP server tools through Penguin's ToolManager."""

    def __init__(self, config: dict[str, Any] | None = None) -> None:
        self.config = config or {}
        self._manager: MCPClientManager | None = None
        self._schemas: list[dict[str, Any]] | None = None

    @property
    def enabled(self) -> bool:
        """Return whether MCP has enabled server config."""
        return bool(load_mcp_server_configs(self.config))

    @property
    def manager(self) -> MCPClientManager:
        """Create the client manager lazily."""
        if self._manager is None:
            self._manager = MCPClientManager(load_mcp_server_configs(self.config))
        return self._manager

    def is_mcp_tool(self, tool_name: str) -> bool:
        """Return whether a public tool name belongs to this provider."""
        return is_mcp_tool_name(tool_name)

    def get_tool_schemas(self) -> list[dict[str, Any]]:
        """Return ToolManager-compatible schemas for discovered MCP tools."""
        if not self.enabled:
            return []
        if self._schemas is None:
            self._schemas = [
                definition.to_penguin_schema()
                for definition in self.manager.list_tools_sync()
            ]
        return list(self._schemas)

    def execute_tool(
        self, tool_name: str, tool_input: dict[str, Any] | None = None
    ) -> str:
        """Execute an MCP tool and return a JSON string payload."""
        if not self.enabled:
            return json.dumps(
                {
                    "error": "mcp_disabled",
                    "tool": tool_name,
                    "message": "MCP is not enabled in Penguin config.",
                }
            )
        try:
            result = self.manager.call_tool_sync(tool_name, tool_input or {})
            return json.dumps({"status": "ok", "result": result}, indent=2)
        except Exception as exc:
            logger.warning("MCP tool '%s' failed: %s", tool_name, exc)
            return json.dumps(
                {
                    "error": "mcp_tool_error",
                    "tool": tool_name,
                    "message": str(exc),
                },
                indent=2,
            )

    def refresh(self) -> list[dict[str, Any]]:
        """Force rediscovery and return fresh ToolManager-compatible schemas."""
        self._schemas = None
        if not self.enabled:
            return []
        definitions = self.manager.refresh_sync()
        self._schemas = [definition.to_penguin_schema() for definition in definitions]
        return list(self._schemas)

    def reconnect(self, server_name: str | None = None) -> dict[str, Any]:
        """Reconnect one or all MCP servers and invalidate cached schemas."""
        self._schemas = None
        if not self.enabled:
            return self.status()
        result = self.manager.reconnect_sync(server_name)
        self._schemas = [
            definition.to_penguin_schema()
            for definition in self.manager.list_tools_sync()
        ]
        return {"enabled": self.enabled, "initialized": True, **result}

    def close(self) -> dict[str, Any]:
        """Close MCP sessions and return diagnostics."""
        self._schemas = None
        if self._manager is None:
            return self.status()
        result = self._manager.close_sync()
        return {"enabled": self.enabled, "initialized": True, **result}

    def status(self) -> dict[str, Any]:
        """Return serializable provider diagnostics."""
        if self._manager is None:
            return {
                "enabled": self.enabled,
                "initialized": False,
                "available": None,
                "discovered": False,
                "server_count": len(load_mcp_server_configs(self.config)),
                "tool_count": 0,
                "servers": {},
            }
        return {
            "enabled": self.enabled,
            "initialized": True,
            **self._manager.status(),
        }


__all__ = ["MCPToolProvider"]
