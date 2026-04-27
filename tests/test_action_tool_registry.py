from __future__ import annotations

import pytest

from penguin.tools.action_registry import create_default_action_tool_registry
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction


class _RecordingToolManager:
    def __init__(self) -> None:
        self.calls: list[tuple[str, dict]] = []

    def execute_tool(self, tool_name: str, tool_input: dict) -> str:
        self.calls.append((tool_name, tool_input))
        return f"{tool_name}:ok"


def test_default_action_tool_registry_routes_canonical_read_file() -> None:
    registry = create_default_action_tool_registry()
    tool_manager = _RecordingToolManager()

    result = registry.execute(
        ActionType.READ_FILE,
        '{"path":"README.md","max_lines":5}',
        tool_manager,
    )

    assert result == "read_file:ok"
    assert tool_manager.calls == [
        (
            "read_file",
            {
                "path": "README.md",
                "show_line_numbers": False,
                "max_lines": 5,
            },
        )
    ]


def test_default_action_tool_registry_preserves_legacy_edit_aliases() -> None:
    registry = create_default_action_tool_registry()
    route = registry.get(ActionType.REPLACE_LINES)

    assert route is not None
    assert route.tool_name == "patch_file"
    assert route.canonical_action_type == ActionType.PATCH_FILE


@pytest.mark.asyncio
async def test_action_executor_uses_registry_for_tool_manager_backed_actions() -> None:
    tool_manager = _RecordingToolManager()
    executor = ActionExecutor(tool_manager=tool_manager, task_manager=None)

    result = await executor.execute_action(
        CodeActAction(
            ActionType.EXECUTE_COMMAND,
            "pwd",
        )
    )

    assert result == "execute_command:ok"
    assert tool_manager.calls == [("execute_command", {"command": "pwd"})]


@pytest.mark.asyncio
async def test_action_executor_registry_reports_payload_errors() -> None:
    tool_manager = _RecordingToolManager()
    executor = ActionExecutor(tool_manager=tool_manager, task_manager=None)

    result = await executor.execute_action(
        CodeActAction(
            ActionType.READ_FILE,
            '{"max_lines":5}',
        )
    )

    assert result == "Error: read_file requires 'path'"
    assert tool_manager.calls == []
