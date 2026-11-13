"""Discovered MCP tools must reach native providers without bypassing allowlists."""

from penguin.tools.tool_manager import ToolManager


class FakeMCPProvider:
    def get_tool_schemas(self):
        return [{"name": "mcp__pullfrog__select_mode", "description": "Select a mode",
                 "input_schema": {"type": "object", "properties": {}}}]

    def is_mcp_tool(self, name):
        return str(name or "").startswith("mcp__")


def test_discovered_mcp_tools_join_default_native_surface():
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    manager._mcp_provider = FakeMCPProvider()
    tools = manager.get_responses_tools(include_web_search=False)
    assert "mcp__pullfrog__select_mode" in {tool["name"] for tool in tools}


def test_explicit_allowlist_does_not_gain_mcp_tools():
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    manager._mcp_provider = FakeMCPProvider()
    tools = manager.get_responses_tools(allowed_names=["read_file"], include_web_search=False)
    assert {tool["name"] for tool in tools} == {"read_file"}
    assert manager.get_responses_tools(allowed_names=[], include_web_search=False) == []
    tools = manager.get_responses_tools(allowed_names=["mcp__pullfrog__select_mode"], include_web_search=False)
    assert {tool["name"] for tool in tools} == {"mcp__pullfrog__select_mode"}
