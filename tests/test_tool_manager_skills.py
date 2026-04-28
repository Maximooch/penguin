from penguin.tools.tool_manager import ToolManager


def test_tool_manager_exposes_skill_tools() -> None:
    manager = ToolManager({"skills": {"enabled": False}}, lambda *args, **kwargs: None, fast_startup=True)
    names = {schema["name"] for schema in manager.tools}

    assert "list_skills" in names
    assert "activate_skill" in names
    assert "list_skills" in manager._tool_registry
    assert "activate_skill" in manager._tool_registry
