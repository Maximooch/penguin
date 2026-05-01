"""Configuration parsing for Penguin MCP client integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Optional


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for one MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: Optional[str] = None
    enabled: bool = True
    startup_timeout_sec: float = 10.0
    tool_timeout_sec: float = 60.0
    enabled_tools: Optional[set[str]] = None
    disabled_tools: set[str] = field(default_factory=set)

    @classmethod
    def from_mapping(cls, name: str, data: Mapping[str, Any]) -> "MCPServerConfig":
        """Build server config from dict-style config."""
        args = data.get("args") or []
        if isinstance(args, str):
            args = [args]

        raw_env = data.get("env") or {}
        env: dict[str, str] = {}
        if isinstance(raw_env, Mapping):
            for key, value in raw_env.items():
                if isinstance(value, str) and value.startswith("$"):
                    env[str(key)] = os.environ.get(value[1:], "")
                else:
                    env[str(key)] = str(value)

        enabled_tools = data.get("enabled_tools")
        if isinstance(enabled_tools, list):
            enabled_tools_set: Optional[set[str]] = {str(item) for item in enabled_tools}
        else:
            enabled_tools_set = None

        disabled_tools = data.get("disabled_tools") or []
        disabled_tools_set = (
            {str(item) for item in disabled_tools}
            if isinstance(disabled_tools, list)
            else set()
        )

        command = data.get("command")
        if not command:
            raise ValueError(f"MCP server '{name}' is missing required command")

        cwd = data.get("cwd")
        if isinstance(cwd, str) and cwd:
            cwd = str(Path(cwd).expanduser())
        else:
            cwd = None

        return cls(
            name=str(data.get("name") or name),
            command=str(command),
            args=[str(arg) for arg in args],
            env=env,
            cwd=cwd,
            enabled=bool(data.get("enabled", True)),
            startup_timeout_sec=float(data.get("startup_timeout_sec", 10.0)),
            tool_timeout_sec=float(data.get("tool_timeout_sec", 60.0)),
            enabled_tools=enabled_tools_set,
            disabled_tools=disabled_tools_set,
        )

    def allows_tool(self, tool_name: str) -> bool:
        """Return whether this config allows a raw MCP tool name."""
        if self.enabled_tools is not None and tool_name not in self.enabled_tools:
            return False
        return tool_name not in self.disabled_tools


def load_mcp_server_configs(config: Optional[Mapping[str, Any]]) -> list[MCPServerConfig]:
    """Load enabled MCP server configs from Penguin config data."""
    root = config or {}
    mcp_config = root.get("mcp", {}) if isinstance(root, Mapping) else {}
    if not isinstance(mcp_config, Mapping) or not bool(mcp_config.get("enabled", False)):
        return []

    servers = mcp_config.get("servers") or {}
    parsed: list[MCPServerConfig] = []
    if isinstance(servers, Mapping):
        for name, data in servers.items():
            if not isinstance(data, Mapping):
                continue
            server = MCPServerConfig.from_mapping(str(name), data)
            if server.enabled:
                parsed.append(server)
    elif isinstance(servers, list):
        for index, data in enumerate(servers):
            if not isinstance(data, Mapping):
                continue
            name = str(data.get("name") or f"server_{index + 1}")
            server = MCPServerConfig.from_mapping(name, data)
            if server.enabled:
                parsed.append(server)
    return parsed


__all__ = ["MCPServerConfig", "load_mcp_server_configs"]
