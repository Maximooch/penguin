"""A closed MCP provider stays closed.

Covers SM-97: an ACP session's MCP provider is inherited by background agents
started during a prompt. After the session closed it, the provider kept its
client manager, so the next tool call from such an agent reconnected and
spawned the server again, with nothing left to close it.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

from penguin.tools.providers.mcp import MCPToolProvider

if TYPE_CHECKING:
    import pytest


class _Manager:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def call_tool_sync(self, name: str, arguments: dict[str, Any]) -> Any:
        self.calls.append(name)
        return {"ok": True}

    def list_tools_sync(self) -> list[Any]:
        self.calls.append("list")
        return []

    def close_sync(self) -> dict[str, Any]:
        return {}

    def status(self) -> dict[str, Any]:
        return {}


def test_a_closed_provider_does_not_reconnect(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PENGUIN_MCP_SERVERS_JSON", raising=False)
    provider = MCPToolProvider(
        {"mcp": {"enabled": True, "servers": {"local-fs": {"command": "fake"}}}}
    )
    manager = _Manager()
    provider._manager = manager

    provider.close()
    payload = json.loads(
        provider.execute_tool("mcp__local_fs__read_file", {"path": "x"})
    )

    assert payload["error"] == "mcp_provider_closed"
    assert provider.get_tool_schemas() == []
    assert manager.calls == []
