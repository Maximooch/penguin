"""Model Context Protocol integration package for Penguin."""

from __future__ import annotations

from penguin.integrations.mcp.config import MCPServerConfig, load_mcp_server_configs
from penguin.integrations.mcp.manager import (
    HAS_MCP_SDK,
    MCPClientManager,
    MCPServerStatus,
    MCPToolDefinition,
)
from penguin.integrations.mcp.names import (
    MCP_TOOL_PREFIX,
    is_mcp_tool_name,
    make_tool_name,
    sanitize_part,
)

__all__ = [
    "HAS_MCP_SDK",
    "MCPClientManager",
    "MCPServerConfig",
    "MCPServerStatus",
    "MCPToolDefinition",
    "MCP_TOOL_PREFIX",
    "is_mcp_tool_name",
    "load_mcp_server_configs",
    "make_tool_name",
    "sanitize_part",
]
