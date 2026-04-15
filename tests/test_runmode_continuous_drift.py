from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.run_mode import RunMode


class DummyCore:
    def __init__(self, project_manager):
        self.project_manager = project_manager
        self._event_handlers = {}
        self._interrupted = False

    def register_event_handler(self, event_type, handler):
        self._event_handlers.setdefault(event_type, []).append(handler)

    async def emit_event(self, event):
        return None

    async def emit_ui_event(self, event_type, data):
        return None


@pytest.mark.asyncio
async def test_continuous_mode_does_not_synthesize_next_step_in_project_scope():
    project_manager = MagicMock()
    project_manager.get_task_by_title = MagicMock(return_value=None)
    project_manager.get_next_task_dag_async = AsyncMock(return_value=None)
    project_manager.get_next_task_async = AsyncMock(return_value=None)

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)
    run_mode._execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "completion_type": "user_specified",
        }
    )
    run_mode._graceful_shutdown = AsyncMock()
    run_mode._health_check = AsyncMock()

    await run_mode.start_continuous(project_id="proj-123", use_dag=True)

    run_mode._execute_task.assert_not_called()
    project_manager.get_next_task_dag_async.assert_awaited_once_with("proj-123")


@pytest.mark.asyncio
async def test_continuous_mode_keeps_exploration_fallback_outside_project_scope():
    project_manager = MagicMock()
    project_manager.get_task_by_title = MagicMock(return_value=None)
    project_manager.get_next_task_async = AsyncMock(return_value=None)

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)
    run_mode._execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "completion_type": "user_specified",
        }
    )
    run_mode._graceful_shutdown = AsyncMock()
    run_mode._health_check = AsyncMock()

    await run_mode.start_continuous(project_id=None, use_dag=False)

    run_mode._execute_task.assert_awaited_once()
    name, description, context = run_mode._execute_task.await_args.args
    assert name == "determine_next_step"
    assert "next logical step" in description
    assert context == {}
