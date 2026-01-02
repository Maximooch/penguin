"""Tests for sub-agent tools in ToolManager.

Tests the sub-agent tool schemas and basic functionality:
- spawn_sub_agent
- stop_sub_agent
- resume_sub_agent
- get_agent_status
- wait_for_agents
- delegate
- delegate_explore_task
- send_message
- get_context_info
- sync_context
"""

import pytest
from typing import Any, Dict, List
from unittest.mock import MagicMock


# =============================================================================
# FIXTURES
# =============================================================================

@pytest.fixture
def mock_config():
    """Create a minimal mock config."""
    return {
        "diagnostics": {"enabled": False},
    }


@pytest.fixture
def mock_log_error():
    """Create a mock error logger."""
    return MagicMock()


@pytest.fixture
def tool_manager(mock_config, mock_log_error):
    """Create a ToolManager instance for testing."""
    from penguin.tools.tool_manager import ToolManager
    tm = ToolManager(mock_config, mock_log_error)
    return tm


def find_tool_schema(tools: List[Dict], name: str) -> Dict:
    """Find a tool schema by name."""
    return next((t for t in tools if t.get("name") == name), None)


# =============================================================================
# TOOL SCHEMA TESTS
# =============================================================================

class TestToolSchemas:
    """Test that sub-agent tool schemas are defined correctly."""

    def test_spawn_sub_agent_schema_exists(self, tool_manager):
        """Test spawn_sub_agent schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "spawn_sub_agent")

        assert schema is not None
        assert "input_schema" in schema
        assert schema["input_schema"]["properties"]["id"] is not None

    def test_spawn_sub_agent_has_required_properties(self, tool_manager):
        """Test spawn_sub_agent has all expected properties."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "spawn_sub_agent")

        props = schema["input_schema"]["properties"]
        assert "id" in props
        assert "parent" in props
        assert "share_session" in props
        assert "share_context_window" in props
        assert "initial_prompt" in props
        assert "background" in props

    def test_delegate_schema_exists(self, tool_manager):
        """Test delegate schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "delegate")

        assert schema is not None
        assert "input_schema" in schema

    def test_delegate_has_required_properties(self, tool_manager):
        """Test delegate has all expected properties."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "delegate")

        props = schema["input_schema"]["properties"]
        assert "child_id" in props or "child" in props
        assert "content" in props
        assert "background" in props

    def test_get_agent_status_schema_exists(self, tool_manager):
        """Test get_agent_status schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "get_agent_status")

        assert schema is not None
        assert "input_schema" in schema

    def test_wait_for_agents_schema_exists(self, tool_manager):
        """Test wait_for_agents schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "wait_for_agents")

        assert schema is not None
        assert "input_schema" in schema

    def test_send_message_schema_exists(self, tool_manager):
        """Test send_message schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "send_message")

        assert schema is not None
        assert "input_schema" in schema

    def test_stop_sub_agent_schema_exists(self, tool_manager):
        """Test stop_sub_agent schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "stop_sub_agent")

        assert schema is not None
        assert "input_schema" in schema

    def test_resume_sub_agent_schema_exists(self, tool_manager):
        """Test resume_sub_agent schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "resume_sub_agent")

        assert schema is not None
        assert "input_schema" in schema

    def test_get_context_info_schema_exists(self, tool_manager):
        """Test get_context_info schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "get_context_info")

        assert schema is not None
        assert "input_schema" in schema

    def test_sync_context_schema_exists(self, tool_manager):
        """Test sync_context schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "sync_context")

        assert schema is not None
        assert "input_schema" in schema

    def test_delegate_explore_task_schema_exists(self, tool_manager):
        """Test delegate_explore_task schema is defined."""
        tools = tool_manager.get_tools()
        schema = find_tool_schema(tools, "delegate_explore_task")

        assert schema is not None
        assert "input_schema" in schema


# =============================================================================
# TOOL HANDLER METHOD TESTS
# =============================================================================

class TestToolHandlerMethods:
    """Test that tool handler methods exist and have correct signatures."""

    def test_spawn_sub_agent_method_exists(self, tool_manager):
        """Test _execute_spawn_sub_agent method exists."""
        assert hasattr(tool_manager, "_execute_spawn_sub_agent")
        assert callable(tool_manager._execute_spawn_sub_agent)

    def test_stop_sub_agent_method_exists(self, tool_manager):
        """Test _execute_stop_sub_agent method exists."""
        assert hasattr(tool_manager, "_execute_stop_sub_agent")
        assert callable(tool_manager._execute_stop_sub_agent)

    def test_resume_sub_agent_method_exists(self, tool_manager):
        """Test _execute_resume_sub_agent method exists."""
        assert hasattr(tool_manager, "_execute_resume_sub_agent")
        assert callable(tool_manager._execute_resume_sub_agent)

    def test_get_agent_status_method_exists(self, tool_manager):
        """Test _execute_get_agent_status method exists."""
        assert hasattr(tool_manager, "_execute_get_agent_status")
        assert callable(tool_manager._execute_get_agent_status)

    def test_wait_for_agents_method_exists(self, tool_manager):
        """Test _execute_wait_for_agents method exists."""
        assert hasattr(tool_manager, "_execute_wait_for_agents")
        assert callable(tool_manager._execute_wait_for_agents)

    def test_delegate_method_exists(self, tool_manager):
        """Test _execute_delegate method exists."""
        assert hasattr(tool_manager, "_execute_delegate")
        assert callable(tool_manager._execute_delegate)

    def test_delegate_explore_task_method_exists(self, tool_manager):
        """Test _execute_delegate_explore_task method exists."""
        assert hasattr(tool_manager, "_execute_delegate_explore_task")
        assert callable(tool_manager._execute_delegate_explore_task)

    def test_send_message_method_exists(self, tool_manager):
        """Test _execute_send_message method exists."""
        assert hasattr(tool_manager, "_execute_send_message")
        assert callable(tool_manager._execute_send_message)

    def test_get_context_info_method_exists(self, tool_manager):
        """Test _execute_get_context_info method exists."""
        assert hasattr(tool_manager, "_execute_get_context_info")
        assert callable(tool_manager._execute_get_context_info)

    def test_sync_context_method_exists(self, tool_manager):
        """Test _execute_sync_context method exists."""
        assert hasattr(tool_manager, "_execute_sync_context")
        assert callable(tool_manager._execute_sync_context)


# =============================================================================
# SCHEMA PROPERTY VALIDATION TESTS
# =============================================================================

class TestSchemaProperties:
    """Test tool schema property definitions."""

    def test_background_property_type(self, tool_manager):
        """Test that background property is boolean type."""
        tools = tool_manager.get_tools()

        spawn_schema = find_tool_schema(tools, "spawn_sub_agent")
        bg_prop = spawn_schema["input_schema"]["properties"].get("background")
        if bg_prop:
            assert bg_prop["type"] == "boolean"

        delegate_schema = find_tool_schema(tools, "delegate")
        bg_prop = delegate_schema["input_schema"]["properties"].get("background")
        if bg_prop:
            assert bg_prop["type"] == "boolean"

    def test_timeout_property_type(self, tool_manager):
        """Test that timeout properties are numeric type."""
        tools = tool_manager.get_tools()

        wait_schema = find_tool_schema(tools, "wait_for_agents")
        timeout_prop = wait_schema["input_schema"]["properties"].get("timeout")
        if timeout_prop:
            assert timeout_prop["type"] in ("number", "integer")

    def test_required_fields_defined(self, tool_manager):
        """Test that required fields are properly defined."""
        tools = tool_manager.get_tools()

        spawn_schema = find_tool_schema(tools, "spawn_sub_agent")
        required = spawn_schema["input_schema"].get("required", [])
        assert "id" in required

        delegate_schema = find_tool_schema(tools, "delegate")
        required = delegate_schema["input_schema"].get("required", [])
        # Either child or child_id should be required, plus content
        assert any(f in required for f in ["child", "child_id"])
        assert "content" in required


# =============================================================================
# TOOL LIST COMPLETENESS TESTS
# =============================================================================

class TestToolListCompleteness:
    """Test that all expected sub-agent tools are present."""

    def test_all_sub_agent_tools_present(self, tool_manager):
        """Test that all expected sub-agent tools are defined."""
        tools = tool_manager.get_tools()
        tool_names = [t["name"] for t in tools]

        expected_tools = [
            "spawn_sub_agent",
            "stop_sub_agent",
            "resume_sub_agent",
            "get_agent_status",
            "wait_for_agents",
            "delegate",
            "delegate_explore_task",
            "send_message",
            "get_context_info",
            "sync_context",
        ]

        for expected in expected_tools:
            assert expected in tool_names, f"Missing tool: {expected}"

    def test_tool_count_minimum(self, tool_manager):
        """Test that there are at least the expected number of tools."""
        tools = tool_manager.get_tools()
        # Should have at least 10 sub-agent tools plus other tools
        assert len(tools) >= 10


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
