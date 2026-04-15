from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.run_mode import RunMode


class DummyCore:
    def __init__(self, project_manager):
        self.project_manager = project_manager
        self._event_handlers = {}

    def register_event_handler(self, event_type, handler):
        self._event_handlers.setdefault(event_type, []).append(handler)

    async def emit_event(self, event):
        return None

    async def emit_ui_event(self, event_type, data):
        return None


@pytest.mark.asyncio
async def test_runmode_does_not_fallback_to_global_title_search_when_task_id_missing():
    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=None)
    project_manager.list_tasks_async = AsyncMock()

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)

    result = await run_mode.start(
        name="Example Task",
        context={"task_id": "missing-task-id"},
    )

    assert result["status"] == "error"
    assert "missing-task-id" in result["message"]
    project_manager.list_tasks_async.assert_not_called()


@pytest.mark.asyncio
async def test_runmode_fails_on_ambiguous_title_resolution_within_scope():
    matching_task_1 = SimpleNamespace(id="task-1", title="Example Task", description="one")
    matching_task_2 = SimpleNamespace(id="task-2", title="Example Task", description="two")

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=None)
    project_manager.list_tasks_async = AsyncMock(return_value=[matching_task_1, matching_task_2])

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)

    result = await run_mode.start(
        name="Example Task",
        context={"project_id": "proj-123"},
    )

    assert result["status"] == "error"
    assert "ambiguous" in result["message"].lower()
    project_manager.list_tasks_async.assert_awaited_once_with(project_id="proj-123")


@pytest.mark.asyncio
async def test_runmode_scopes_title_resolution_to_project_id():
    matching_task = SimpleNamespace(id="task-1", title="Example Task", description="scoped")
    other_project_task = SimpleNamespace(id="task-2", title="Example Task", description="other")

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=None)
    project_manager.list_tasks_async = AsyncMock(return_value=[matching_task])

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)
    run_mode._execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "message": "done",
            "completion_type": "success",
        }
    )

    result = await run_mode.start(
        name="Example Task",
        context={"project_id": "proj-123"},
    )

    assert result["status"] == "completed"
    assert result["task_name"] == "Example Task"
    project_manager.list_tasks_async.assert_awaited_once_with(project_id="proj-123")
    run_mode._execute_task.assert_awaited_once()
