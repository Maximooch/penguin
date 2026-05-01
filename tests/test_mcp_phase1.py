from __future__ import annotations

import json

from penguin.integrations.mcp.config import load_mcp_server_configs
from penguin.integrations.mcp.manager import MCPToolDefinition
from penguin.integrations.mcp.names import is_mcp_tool_name, make_tool_name, sanitize_part
from penguin.tools.providers.mcp import MCPToolProvider
from penguin.tools.tool_manager import ToolManager


class FakeManager:
    def __init__(self) -> None:
        self.called_with = None

    def list_tools_sync(self) -> list[MCPToolDefinition]:
        return [
            MCPToolDefinition(
                public_name="mcp__local_fs__read_file",
                server_name="local-fs",
                raw_name="read-file",
                description="Read a file through MCP",
                input_schema={
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                    "required": ["path"],
                },
            )
        ]

    def call_tool_sync(self, public_name: str, arguments: dict) -> dict:
        self.called_with = (public_name, arguments)
        return {"public_name": public_name, "arguments": arguments}

    def status(self) -> dict:
        return {"available": True, "discovered": True, "servers": {}}


def test_mcp_config_parses_mapping_servers_and_env(monkeypatch) -> None:
    monkeypatch.setenv("MCP_TOKEN", "secret-value")
    configs = load_mcp_server_configs(
        {
            "mcp": {
                "enabled": True,
                "servers": {
                    "filesystem": {
                        "command": "uvx",
                        "args": ["mcp-server-filesystem"],
                        "env": {"TOKEN": "$MCP_TOKEN"},
                        "disabled_tools": ["write_file"],
                    }
                },
            }
        }
    )

    assert len(configs) == 1
    server = configs[0]
    assert server.name == "filesystem"
    assert server.command == "uvx"
    assert server.args == ["mcp-server-filesystem"]
    assert server.env == {"TOKEN": "secret-value"}
    assert server.allows_tool("read_file") is True
    assert server.allows_tool("write_file") is False


def test_mcp_config_is_disabled_by_default() -> None:
    assert load_mcp_server_configs({}) == []
    assert load_mcp_server_configs({"mcp": {"enabled": False}}) == []


def test_mcp_tool_name_sanitization_and_collision() -> None:
    first = make_tool_name("Local FS", "read-file")
    second = make_tool_name("Local FS", "read-file", existing=[first])

    assert first == "mcp__local_fs__read_file"
    assert second == "mcp__local_fs__read_file_2"
    assert sanitize_part("../Bad Name!!") == "bad_name"
    assert is_mcp_tool_name(first) is True
    assert is_mcp_tool_name("read_file") is False


def test_mcp_provider_exposes_schemas_and_dispatches() -> None:
    provider = MCPToolProvider(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        }
    )
    fake_manager = FakeManager()
    provider._manager = fake_manager

    schemas = provider.get_tool_schemas()
    assert schemas == [
        {
            "name": "mcp__local_fs__read_file",
            "description": "Read a file through MCP",
            "input_schema": {
                "type": "object",
                "properties": {"path": {"type": "string"}},
                "required": ["path"],
            },
            "metadata": {
                "provider": "mcp",
                "mcp_server": "local-fs",
                "mcp_tool": "read-file",
            },
        }
    ]

    payload = json.loads(
        provider.execute_tool("mcp__local_fs__read_file", {"path": "README.md"})
    )
    assert payload["status"] == "ok"
    assert payload["result"] == {
        "public_name": "mcp__local_fs__read_file",
        "arguments": {"path": "README.md"},
    }
    assert fake_manager.called_with == (
        "mcp__local_fs__read_file",
        {"path": "README.md"},
    )


def test_tool_manager_exposes_and_dispatches_mcp_tools() -> None:
    manager = ToolManager(
        {
            "mcp": {
                "enabled": True,
                "servers": {"local-fs": {"command": "fake"}},
            }
        },
        lambda *_args, **_kwargs: None,
        fast_startup=True,
    )
    fake_manager = FakeManager()
    manager._mcp_provider._manager = fake_manager

    tool_names = {tool["name"] for tool in manager.get_tools()}
    assert "mcp__local_fs__read_file" in tool_names

    payload = json.loads(
        manager.execute_tool("mcp__local_fs__read_file", {"path": "README.md"})
    )
    assert payload["status"] == "ok"
    assert fake_manager.called_with == (
        "mcp__local_fs__read_file",
        {"path": "README.md"},
    )


def test_mcp_provider_gracefully_noops_when_disabled() -> None:
    provider = MCPToolProvider({})

    assert provider.get_tool_schemas() == []
    payload = json.loads(provider.execute_tool("mcp__missing__tool", {}))
    assert payload["error"] == "mcp_disabled"
