"""ToolManager provider for MCP-hosted tools."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from penguin.integrations.mcp.config import load_mcp_server_configs
from penguin.integrations.mcp.manager import MCPClientManager
from penguin.integrations.mcp.names import is_mcp_tool_name

logger = logging.getLogger(__name__)


class MCPToolProvider:
    """Expose external MCP server tools through Penguin's ToolManager."""

    def __init__(self, config: Optional[dict[str, Any]] = None) -> None:
        self.config = config or {}
        self._manager: Optional[MCPClientManager] = None
        self._schemas: Optional[list[dict[str, Any]]] = None

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
        self, tool_name: str, tool_input: Optional[dict[str, Any]] = None
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

    def status(self) -> dict[str, Any]:
        """Return serializable provider diagnostics."""
        if self._manager is None:
            return {
                "enabled": self.enabled,
                "initialized": False,
                "servers": {},
            }
        return {
            "enabled": self.enabled,
            "initialized": True,
            **self._manager.status(),
        }


__all__ = ["MCPToolProvider"]
