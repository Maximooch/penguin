from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.project.models import TaskPhase, TaskStatus
from penguin.project.workflow_orchestrator import WorkflowOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_returns_waiting_input_without_validation():
    task = SimpleNamespace(
        id="task-1",
        title="Task 1",
        recipe=None,
    )
    project_manager = MagicMock()
    project_manager.get_next_task_async = AsyncMock(return_value=task)
    project_manager.update_task_status = MagicMock(return_value=True)
    project_manager.update_task_phase_async = AsyncMock()
    project_manager.get_task = MagicMock(return_value=SimpleNamespace(status=TaskStatus.RUNNING))

    task_executor = SimpleNamespace(
        execute_task=AsyncMock(
            return_value={
                "status": "waiting_input",
                "message": "Need clarification",
                "run_mode_completion_type": "clarification_needed",
                "run_mode_result": {
                    "status": "waiting_input",
                    "completion_type": "clarification_needed",
                },
                "changed_files": [],
            }
        )
    )
    validation_manager = SimpleNamespace(validate_task_completion=AsyncMock())
    git_manager = SimpleNamespace(create_pr_for_task=AsyncMock())
    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    result = await orchestrator.run_next_task(project_id="project-1")

    assert result["status"] == "waiting_input"
    assert result["final_status"] == TaskStatus.RUNNING.value
    assert result["run_mode_completion_type"] == "clarification_needed"
    validation_manager.validate_task_completion.assert_not_called()
    git_manager.create_pr_for_task.assert_not_called()


@pytest.mark.asyncio
async def test_orchestrator_returns_executor_error_without_revalidation():
    task = SimpleNamespace(
        id="task-1",
        title="Task 1",
        recipe=None,
    )
    project_manager = MagicMock()
    project_manager.get_next_task_async = AsyncMock(return_value=task)
    project_manager.update_task_status = MagicMock(return_value=True)
    project_manager.update_task_phase_async = AsyncMock()
    project_manager.get_task = MagicMock(return_value=SimpleNamespace(status=TaskStatus.RUNNING))

    task_executor = SimpleNamespace(
        execute_task=AsyncMock(
            return_value={
                "status": "error",
                "message": "Critical executor error: boom",
            }
        )
    )
    validation_manager = SimpleNamespace(validate_task_completion=AsyncMock())
    git_manager = SimpleNamespace(create_pr_for_task=AsyncMock())
    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    result = await orchestrator.run_next_task(project_id="project-1")

    assert result["final_status"] == "FAILED"
    validation_manager.validate_task_completion.assert_not_called()
    git_manager.create_pr_for_task.assert_not_called()
