"""Configuration parsing for Penguin MCP client integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping

ServerEntries = Mapping[str, Any] | list[Any]


@dataclass(frozen=True)
class MCPServerConfig:
    """Configuration for one MCP server."""

    name: str
    command: str
    args: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)
    cwd: str | None = None
    transport: str = "stdio"
    enabled: bool = True
    startup_timeout_sec: float = 10.0
    tool_timeout_sec: float = 60.0
    enabled_tools: set[str] | None = None
    disabled_tools: set[str] = field(default_factory=set)

    @classmethod
    def from_mapping(cls, name: str, data: Mapping[str, Any]) -> MCPServerConfig:
        """Build server config from dict-style config."""
        transport = str(data.get("transport") or data.get("type") or "stdio")
        if transport not in {"stdio", "streamable_http", "sse"}:
            raise ValueError(
                f"MCP server '{name}' has unsupported transport '{transport}'"
            )
        if transport != "stdio":
            raise ValueError(
                f"MCP server '{name}' uses transport '{transport}', "
                "but Phase 1.5 only supports stdio"
            )

        args = data.get("args") or []
        if isinstance(args, str):
            args = [args]

        env = _parse_env(data.get("env") or {})
        enabled_tools = _parse_optional_tool_set(
            data.get("enabled_tools") or data.get("enabledTools")
        )
        disabled_tools = _parse_tool_set(
            data.get("disabled_tools") or data.get("disabledTools") or []
        )

        command = data.get("command")
        if not command:
            raise ValueError(f"MCP server '{name}' is missing required command")

        cwd = data.get("cwd")
        cwd_value = (
            str(Path(cwd).expanduser())
            if isinstance(cwd, str) and cwd
            else None
        )

        return cls(
            name=str(data.get("name") or name),
            command=str(command),
            args=[str(arg) for arg in args],
            env=env,
            cwd=cwd_value,
            transport=transport,
            enabled=bool(data.get("enabled", True)),
            startup_timeout_sec=float(
                data.get("startup_timeout_sec", data.get("startupTimeoutSec", 10.0))
            ),
            tool_timeout_sec=float(
                data.get("tool_timeout_sec", data.get("toolTimeoutSec", 60.0))
            ),
            enabled_tools=enabled_tools,
            disabled_tools=disabled_tools,
        )

    def allows_tool(self, tool_name: str) -> bool:
        """Return whether this config allows a raw MCP tool name."""
        if self.enabled_tools is not None and tool_name not in self.enabled_tools:
            return False
        return tool_name not in self.disabled_tools


def _parse_env(raw_env: Any) -> dict[str, str]:
    env: dict[str, str] = {}
    if not isinstance(raw_env, Mapping):
        return env
    for key, value in raw_env.items():
        if isinstance(value, str) and value.startswith("$"):
            env[str(key)] = os.environ.get(value[1:], "")
        else:
            env[str(key)] = str(value)
    return env


def _parse_tool_set(value: Any) -> set[str]:
    return {str(item) for item in value} if isinstance(value, list) else set()


def _parse_optional_tool_set(value: Any) -> set[str] | None:
    return _parse_tool_set(value) if isinstance(value, list) else None


def _server_entries_from_root(root: Mapping[str, Any]) -> tuple[ServerEntries, bool]:
    """Return MCP server entries and whether MCP is explicitly enabled."""
    mcp_config = root.get("mcp", {}) if isinstance(root, Mapping) else {}
    if isinstance(mcp_config, Mapping):
        servers = mcp_config.get("servers") or mcp_config.get("mcpServers") or {}
        enabled = bool(mcp_config.get("enabled", bool(servers)))
        if servers:
            return servers, enabled

    # Compatibility with Claude/Codex-style top-level maps.
    for key in ("mcpServers", "mcp_servers"):
        servers = root.get(key)
        if servers:
            return servers, True
    return {}, False


def load_mcp_server_configs(config: Mapping[str, Any] | None) -> list[MCPServerConfig]:
    """Load enabled MCP server configs from Penguin config data."""
    root = config or {}
    if not isinstance(root, Mapping):
        return []

    servers, enabled = _server_entries_from_root(root)
    if not enabled:
        return []

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
