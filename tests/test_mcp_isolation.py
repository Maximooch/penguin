import json

import pytest

from penguin.security.mcp_isolation import isolated_mcp_config
from penguin.tools.providers.mcp import MCPToolProvider


def test_override_replaces_inherited_servers(monkeypatch):
    config = {"mcp": {"servers": {"evil": {"command": "sh"}}}}
    servers = {
        "pullfrog": {"transport": "streamable_http", "url": "http://127.0.0.1:9001/mcp"}
    }
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


@pytest.mark.parametrize(
    "url",
    [
        "http://127.0.0.1:1@other.host/mcp",  # 127.0.0.1:1 is a username here
        "http://127.0.0.1:8080@other.host:9000/mcp",
        "http://127.0.0.1:/mcp",  # no port
        "http://127.0.0.1:99999/mcp",  # not a port
    ],
)
def test_isolated_mcp_rejects_urls_that_only_look_local(
    monkeypatch: pytest.MonkeyPatch, url: str
) -> None:
    servers = {"s": {"transport": "streamable_http", "url": url}}
    monkeypatch.setenv("PENGUIN_MCP_SERVERS_JSON", json.dumps(servers))

    with pytest.raises(ValueError, match="loopback"):
        isolated_mcp_config({})


def test_isolated_mcp_accepts_a_loopback_url(monkeypatch: pytest.MonkeyPatch) -> None:
    servers = {
        "s": {"transport": "streamable_http", "url": "http://127.0.0.1:8123/mcp"}
    }
    monkeypatch.setenv("PENGUIN_MCP_SERVERS_JSON", json.dumps(servers))

    assert isolated_mcp_config({}) == {"mcp": {"enabled": True, "servers": servers}}
