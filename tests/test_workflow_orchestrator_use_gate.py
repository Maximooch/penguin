from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, call

import pytest

from penguin.project.exceptions import ValidationError
from penguin.project.models import TaskPhase, TaskStatus
from penguin.project.workflow_orchestrator import WorkflowOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_executes_use_gate_for_declared_recipe():
    task = SimpleNamespace(id="task-123", title="Example Task")
    updated_task = SimpleNamespace(
        id="task-123",
        title="Example Task",
        status=TaskStatus.RUNNING,
        recipe="smoke-auth-flow",
    )

    project_manager = MagicMock()
    project_manager.workspace_path = "/tmp"
    project_manager.get_next_task_async = AsyncMock(return_value=task)
    project_manager.update_task_status = MagicMock(return_value=True)
    project_manager.update_task_status_async = AsyncMock(return_value=True)
    project_manager.update_task_phase_async = AsyncMock(return_value=True)
    project_manager.resolve_task_recipe_async = AsyncMock(
        return_value={
            "name": "smoke-auth-flow",
            "steps": [{"shell": "echo auth-ok"}],
        }
    )
    project_manager.get_task = MagicMock(return_value=updated_task)

    task_executor = MagicMock()
    task_executor.execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "changed_files": ["src/example.py"],
        }
    )

    validation_manager = MagicMock()
    validation_manager.validate_task_completion = AsyncMock(
        return_value={"validated": True}
    )

    git_manager = MagicMock()
    git_manager.create_pr_for_task = AsyncMock(
        return_value={
            "status": "created",
            "pr_url": "https://example.test/pr/1",
        }
    )

    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )
    orchestrator._execute_use_recipe = AsyncMock(
        return_value={
            "success": True,
            "recipe": "smoke-auth-flow",
            "steps": [{"type": "shell", "command": "echo auth-ok", "returncode": 0}],
        }
    )

    result = await orchestrator.run_next_task()

    assert result["final_status"] == TaskStatus.PENDING_REVIEW.value
    assert result["use"]["success"] is True
    project_manager.resolve_task_recipe_async.assert_awaited_once_with(task.id)
    orchestrator._execute_use_recipe.assert_awaited_once()
    project_manager.update_task_phase_async.assert_has_awaits(
        [
            call(
                task.id,
                TaskPhase.IMPLEMENT,
                "Task claimed by orchestrator; starting implementation.",
            ),
            call(
                task.id,
                TaskPhase.TEST,
                "Implementation finished; running validation checks.",
            ),
            call(
                task.id,
                TaskPhase.USE,
                "Validation passed; running usage recipe.",
            ),
            call(
                task.id,
                TaskPhase.VERIFY,
                "Validation passed; verifying completion artifacts.",
            ),
            call(
                task.id,
                TaskPhase.DONE,
                "Validation succeeded; task is ready for review.",
            ),
        ]
    )


@pytest.mark.asyncio
async def test_orchestrator_fails_closed_when_recipe_resolution_fails():
    task = SimpleNamespace(id="task-123", title="Example Task")
    updated_task = SimpleNamespace(
        id="task-123",
        title="Example Task",
        status=TaskStatus.RUNNING,
        recipe="missing-recipe",
    )

    project_manager = MagicMock()
    project_manager.workspace_path = "/tmp"
    project_manager.get_next_task_async = AsyncMock(return_value=task)
    project_manager.update_task_status = MagicMock(return_value=True)
    project_manager.update_task_status_async = AsyncMock(return_value=True)
    project_manager.update_task_phase_async = AsyncMock(return_value=True)
    project_manager.resolve_task_recipe_async = AsyncMock(
        side_effect=ValidationError("Recipe 'missing-recipe' not found")
    )
    project_manager.get_task = MagicMock(return_value=updated_task)

    task_executor = MagicMock()
    task_executor.execute_task = AsyncMock(
        return_value={
            "status": "completed",
            "changed_files": ["src/example.py"],
        }
    )

    validation_manager = MagicMock()
    validation_manager.validate_task_completion = AsyncMock(
        return_value={"validated": True}
    )

    git_manager = MagicMock()
    git_manager.create_pr_for_task = AsyncMock()

    orchestrator = WorkflowOrchestrator(
        project_manager=project_manager,
        task_executor=task_executor,
        validation_manager=validation_manager,
        git_manager=git_manager,
    )

    result = await orchestrator.run_next_task()

    assert result["status"] == "use_failed"
    assert result["final_status"] == TaskStatus.FAILED.value
    assert "missing-recipe" in result["error"]
    git_manager.create_pr_for_task.assert_not_called()
    project_manager.update_task_status.assert_has_calls(
        [
            call(task.id, TaskStatus.RUNNING),
            call(
                task.id,
                TaskStatus.FAILED,
                "Usage recipe failed: Recipe 'missing-recipe' not found",
            ),
        ]
    )
