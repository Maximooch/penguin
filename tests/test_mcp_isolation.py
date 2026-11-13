import json

import pytest

from penguin.security.mcp_isolation import isolated_mcp_config
from penguin.tools.providers.mcp import MCPToolProvider


def test_override_replaces_inherited_servers(monkeypatch):
    config = {"mcp": {"servers": {"evil": {"command": "sh"}}}}
    servers = {"pullfrog": {"transport": "streamable_http", "url": "http://127.0.0.1:9001/mcp"}}
    monkeypatch.setenv("PENGUIN_MCP_SERVERS_JSON", json.dumps(servers))
    provider = MCPToolProvider(config)
    assert provider.config == {"mcp": {"enabled": True, "servers": servers}}
    monkeypatch.setenv("PENGUIN_MCP_SERVERS_JSON", "{}")
    assert provider.config["mcp"]["servers"] == servers
    assert MCPToolProvider(config).config["mcp"]["servers"] == {}


@pytest.mark.parametrize("raw", ["null", "[]", "oops", '{"evil":{"command":"sh"}}'])
def test_bad_override_fails_closed(monkeypatch, raw):
    monkeypatch.setenv("PENGUIN_MCP_SERVERS_JSON", raw)
    with pytest.raises(ValueError):
        isolated_mcp_config({})


def test_no_override_preserves_configuration(monkeypatch):
    monkeypatch.delenv("PENGUIN_MCP_SERVERS_JSON", raising=False)
    config = {"mcp": {"enabled": False}}
    assert isolated_mcp_config(config) is config
