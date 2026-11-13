"""The web startup Config -> dict boundary must retain external MCP tools."""

import importlib

import pytest
import yaml

from penguin.integrations.mcp.config import load_mcp_server_configs

Config = importlib.import_module("penguin.config").Config


@pytest.mark.parametrize("key", ["mcp", "mcpServers", "mcp_servers"])
def test_mcp_survives_typed_config_roundtrip(tmp_path, key):
    servers = {"pullfrog": {"transport": "streamable_http", "url": "http://127.0.0.1:12345/mcp"}}
    block = {"enabled": True, "servers": servers} if key == "mcp" else servers
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump({key: block, "model": None, "workspace": {"path": str(tmp_path)}}))

    config = Config.load_config(path)
    parsed = load_mcp_server_configs(config.to_dict())

    assert len(parsed) == 1
    assert parsed[0].name == "pullfrog"
    assert parsed[0].url == servers["pullfrog"]["url"]


def test_disabled_mcp_stays_disabled(tmp_path):
    path = tmp_path / "config.yml"
    path.write_text(yaml.safe_dump({"model": None, "workspace": {"path": str(tmp_path)}, "mcp": {
        "enabled": False, "servers": {"pullfrog": {"url": "http://127.0.0.1:12345/mcp"}}
    }}))
    assert load_mcp_server_configs(Config.load_config(path).to_dict()) == []
