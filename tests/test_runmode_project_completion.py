import asyncio
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


@pytest.mark.asyncio
async def test_runmode_does_not_complete_project_task():
    project_task = SimpleNamespace(
        id="task-123",
        title="Example Task",
        description="Do the thing",
    )

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=project_task)
    project_manager.list_tasks_async = AsyncMock(return_value=[project_task])
    project_manager.update_task_status = MagicMock()

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
        context={"task_id": "task-123"},
    )

    assert result["status"] == "completed"
    project_manager.update_task_status.assert_not_called()
