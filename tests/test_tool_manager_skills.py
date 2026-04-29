import json
from pathlib import Path

import pytest

from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction, parse_action


def _skill_names_from_responses_tools(manager: ToolManager) -> set[str]:
    names = set()
    for tool in manager.get_responses_tools(include_web_search=False):
        if tool.get("type") == "function":
            names.add(str(tool.get("name")))
    return names


def test_tool_manager_exposes_skill_tools() -> None:
    manager = ToolManager({"skills": {"enabled": False}}, lambda *args, **kwargs: None, fast_startup=True)
    names = {schema["name"] for schema in manager.tools}

    assert "list_skills" in names
    assert "activate_skill" in names
    assert "list_skills" in manager._tool_registry
    assert "activate_skill" in manager._tool_registry


def test_tool_manager_exposes_skill_tools_to_native_payload() -> None:
    manager = ToolManager({"skills": {"enabled": False}}, lambda *args, **kwargs: None, fast_startup=True)

    names = _skill_names_from_responses_tools(manager)

    assert "list_skills" in names
    assert "activate_skill" in names


def test_parser_detects_skill_actionxml_fallback_tags() -> None:
    actions = parse_action(
        '<list_skills>{"refresh": true}</list_skills>'
        '<activate_skill>{"name": "demo-skill"}</activate_skill>'
    )

    assert [action.action_type for action in actions] == [
        ActionType.LIST_SKILLS,
        ActionType.ACTIVATE_SKILL,
    ]


def _make_skill(path: Path, name: str) -> None:
    path.mkdir(parents=True, exist_ok=True)
    (path / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: Demo skill\n---\nUse this skill.\n",
        encoding="utf-8",
    )


@pytest.mark.asyncio
async def test_action_executor_runs_list_skills_fallback_tag(tmp_path: Path) -> None:
    _make_skill(tmp_path / "skills" / "demo", "demo-skill")
    manager = ToolManager(
        {"skills": {"scan_paths": {"user": [str(tmp_path / "skills")]}}},
        lambda *args, **kwargs: None,
        fast_startup=True,
    )
    executor = ActionExecutor(tool_manager=manager, task_manager=None)

    result = await executor.execute_action(
        CodeActAction(ActionType.LIST_SKILLS, '{"refresh": true}')
    )
    payload = json.loads(result)

    assert payload["skills"][0]["name"] == "demo-skill"
