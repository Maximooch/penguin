"""The workflow orchestrator leaves a task in a resumable state when a run fails."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.project.exceptions import StateTransitionError
from penguin.project.models import TaskStatus
from penguin.project.workflow_orchestrator import WorkflowOrchestrator


def _orchestrator(project_manager: MagicMock, task_executor: MagicMock):
    return WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=MagicMock(),
        git_manager=MagicMock(),
    )


def _project_manager(current_status: TaskStatus) -> MagicMock:
    task = SimpleNamespace(id="task-1", title="Example")
    project_manager = MagicMock()
    project_manager.get_next_task_async = AsyncMock(return_value=task)
    project_manager.update_task_phase_async = AsyncMock(return_value=True)
    current = SimpleNamespace(id="task-1", title="Example", status=current_status)
    project_manager.get_task = MagicMock(return_value=current)
    return project_manager


@pytest.mark.asyncio
async def test_failure_before_running_is_reported_not_raised() -> None:
    project_manager = _project_manager(TaskStatus.ACTIVE)

    def reject(task_id: str, status: TaskStatus) -> bool:
        raise StateTransitionError(
            "illegal", from_state="active", to_state=status.value, task_id=task_id
        )

    project_manager.update_task_status = MagicMock(side_effect=reject)

    result = await _orchestrator(project_manager, MagicMock()).run_next_task()

    assert result["final_status"] == "FAILED"
    assert "illegal" in result["error"]


@pytest.mark.asyncio
async def test_cancelled_run_returns_the_task_to_active() -> None:
    project_manager = _project_manager(TaskStatus.RUNNING)
    project_manager.update_task_status = MagicMock(return_value=True)
    task_executor = MagicMock()
    task_executor.execute_task = AsyncMock(side_effect=asyncio.CancelledError())

    with pytest.raises(asyncio.CancelledError):
        await _orchestrator(project_manager, task_executor).run_next_task()

    project_manager.update_task_status.assert_called_with("task-1", TaskStatus.ACTIVE)
