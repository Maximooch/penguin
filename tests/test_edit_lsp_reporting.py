from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction


class _ToolManager:
    def __init__(self, result: dict[str, Any]) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self._result = result
        self._file_root = "."

    def execute_tool(self, tool_name: str, tool_input: dict[str, Any]) -> str:
        self.calls.append((tool_name, tool_input))
        return json.dumps(self._result)


@pytest.mark.asyncio
async def test_multiedit_lsp_events_use_changed_files_from_tool_result() -> None:
    tool_manager = _ToolManager(
        {
            "success": True,
            "files_edited": ["src/a.py", "src/b.py"],
            "files_failed": [],
            "error_messages": {},
            "backup_paths": {},
            "rollback_performed": False,
            "applied": True,
            "diagnostics": {"src/a.py": [{"message": "TypeError at line 1, column 1"}]},
        }
    )
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _capture(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    executor = ActionExecutor(
        tool_manager=cast(Any, tool_manager),
        task_manager=cast(Any, SimpleNamespace()),
        ui_event_callback=_capture,
    )

    await executor.execute_action(
        CodeActAction(
            ActionType.MULTIEDIT,
            "apply=true\nsrc/a.py:\n@@ -1 +1 @@\n-a\n+b\n\nsrc/b.py:\n@@ -1 +1 @@\n-c\n+d\n",
        )
    )

    lsp_updated = [
        payload for event_type, payload in emitted if event_type == "lsp.updated"
    ]
    diagnostics = [
        payload
        for event_type, payload in emitted
        if event_type == "lsp.client.diagnostics"
    ]

    assert lsp_updated
    assert diagnostics
    assert lsp_updated[-1]["files"] == ["src/a.py", "src/b.py"]
    assert diagnostics[-1]["files"] == ["src/a.py", "src/b.py"]
    assert diagnostics[-1]["path"] == "src/a.py"


@pytest.mark.asyncio
async def test_lsp_reporting_normalizes_single_file_result_paths(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    abs_file = workspace / "src" / "example.py"
    abs_file.parent.mkdir(parents=True)

    tool_manager = _ToolManager(
        {
            "status": "success",
            "file": str(abs_file),
            "diagnostics": {
                str(abs_file): [{"message": "TypeError at line 4, column 2"}]
            },
        }
    )
    tool_manager._file_root = str(workspace)
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _capture(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    executor = ActionExecutor(
        tool_manager=cast(Any, tool_manager),
        task_manager=cast(Any, SimpleNamespace()),
        ui_event_callback=_capture,
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_1",
            conversation_id="session_1",
            agent_id="default",
            directory=str(workspace),
            project_root=str(workspace),
            workspace_root=str(workspace),
        )
    ):
        await executor.execute_action(
            CodeActAction(ActionType.ENHANCED_WRITE, "src/example.py:print('x')")
        )

    lsp_updated = [
        payload for event_type, payload in emitted if event_type == "lsp.updated"
    ]
    diagnostics = [
        payload
        for event_type, payload in emitted
        if event_type == "lsp.client.diagnostics"
    ]

    assert lsp_updated[-1]["files"] == ["src/example.py"]
    assert diagnostics[-1]["files"] == ["src/example.py"]
    assert diagnostics[-1]["path"] == "src/example.py"
    assert set(diagnostics[-1]["diagnostics"].keys()) == {"src/example.py"}


@pytest.mark.asyncio
async def test_lsp_reporting_prefers_normalized_multiedit_file_list(tmp_path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    file_a = workspace / "src" / "a.py"
    file_b = workspace / "src" / "b.py"
    file_a.parent.mkdir(parents=True)

    tool_manager = _ToolManager(
        {
            "success": True,
            "files": ["src/a.py", "src/b.py"],
            "files_edited": [str(file_a), str(file_b)],
            "files_failed": [],
            "error_messages": {},
            "backup_paths": {},
            "rollback_performed": False,
            "applied": True,
            "diagnostics": {
                str(file_a): [{"message": "TypeError at line 1, column 1"}],
                str(file_b): [{"message": "TypeError at line 2, column 1"}],
            },
        }
    )
    tool_manager._file_root = str(workspace)
    emitted: list[tuple[str, dict[str, Any]]] = []

    async def _capture(event_type: str, payload: dict[str, Any]) -> None:
        emitted.append((event_type, payload))

    executor = ActionExecutor(
        tool_manager=cast(Any, tool_manager),
        task_manager=cast(Any, SimpleNamespace()),
        ui_event_callback=_capture,
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session_1",
            conversation_id="session_1",
            agent_id="default",
            directory=str(workspace),
            project_root=str(workspace),
            workspace_root=str(workspace),
        )
    ):
        await executor.execute_action(
            CodeActAction(
                ActionType.MULTIEDIT,
                "apply=true\nsrc/a.py:\n@@ -1 +1 @@\n-a\n+b\n\nsrc/b.py:\n@@ -1 +1 @@\n-c\n+d\n",
            )
        )

    lsp_updated = [
        payload for event_type, payload in emitted if event_type == "lsp.updated"
    ]
    diagnostics = [
        payload
        for event_type, payload in emitted
        if event_type == "lsp.client.diagnostics"
    ]

    assert lsp_updated[-1]["files"] == ["src/a.py", "src/b.py"]
    assert diagnostics[-1]["files"] == ["src/a.py", "src/b.py"]
    assert set(diagnostics[-1]["diagnostics"].keys()) == {"src/a.py", "src/b.py"}
