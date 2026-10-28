"""Per-session MCP providers supplied by an ACP client."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from acp import RequestError

from penguin.integrations.mcp.config import MCPServerConfig, load_mcp_server_configs
from penguin.integrations.mcp.manager import MCPClientManager
from penguin.tools.providers.mcp import MCPToolProvider

if TYPE_CHECKING:
    from pathlib import Path

__all__ = ["session_provider"]


class _SessionProvider(MCPToolProvider):
    def __init__(self, configs: list[MCPServerConfig]) -> None:
        super().__init__()
        self.configs = configs

    @property
    def enabled(self) -> bool:
        return bool(self.configs)

    @property
    def manager(self) -> MCPClientManager:
        if self._manager is None:
            self._manager = MCPClientManager(self.configs)
        return self._manager


def session_provider(
    servers: list[Any], cwd: Path, config: dict[str, Any]
) -> MCPToolProvider:
    """Validate client descriptors without shell parsing or environment expansion."""
    configs = list(load_mcp_server_configs(config))
    names = {item.name for item in configs}
    try:
        for server in servers:
            name = server.name
            if not isinstance(name, str) or not name or name in names:
                raise ValueError("MCP server name is missing or duplicate")
            names.add(name)
            kind = getattr(server, "type", "stdio")
            if kind == "stdio":
                if not server.command:
                    raise ValueError("MCP command is empty")
                env = {entry.name: entry.value for entry in server.env}
                configs.append(
                    MCPServerConfig(
                        name=name,
                        command=server.command,
                        args=list(server.args),
                        env=env,
                        cwd=str(cwd),
                    )
                )
            elif kind in {"http", "sse"}:
                url = urlsplit(server.url)
                if url.scheme not in {"http", "https"} or not url.netloc:
                    raise ValueError("MCP URL must be HTTP(S)")
                headers = {header.name: header.value for header in server.headers}
                if any(
                    "\n" in str(value) or "\r" in str(value)
                    for pair in headers.items()
                    for value in pair
                ):
                    raise ValueError("Invalid MCP header")
                configs.append(
                    MCPServerConfig(
                        name=name,
                        url=server.url,
                        transport="streamable_http" if kind == "http" else "sse",
                        http_headers=headers,
                    )
                )
            else:
                raise ValueError("Unsupported MCP transport")
    except (AttributeError, TypeError, ValueError):
        raise RequestError.invalid_params(
            {"reason": "Invalid client MCP configuration"}
        ) from None
    return _SessionProvider(configs)
