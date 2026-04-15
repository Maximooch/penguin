from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException

from penguin.project.models import TaskStatus
from penguin.web.routes import complete_task, execute_task_from_project


@pytest.mark.asyncio
async def test_api_complete_task_approves_pending_review_task():
    task = MagicMock()
    task.id = "task-1"
    task.title = "Review Me"
    task.status = TaskStatus.PENDING_REVIEW

    approved_task = SimpleNamespace(id="task-1", title="Review Me", status=TaskStatus.COMPLETED)

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(side_effect=[task, approved_task])
    project_manager.storage.update_task = MagicMock()

    core = SimpleNamespace(project_manager=project_manager)

    result = await complete_task("task-1", core)

    task.approve.assert_called_once_with("api", notes="Approved via API")
    project_manager.storage.update_task.assert_called_once_with(task)
    assert result["status"] == TaskStatus.COMPLETED.value
    assert result["message"] == "Task approved successfully"


@pytest.mark.asyncio
async def test_api_complete_task_rejects_non_review_ready_task():
    task = SimpleNamespace(id="task-1", title="Not Ready", status=TaskStatus.RUNNING)

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=task)

    core = SimpleNamespace(project_manager=project_manager)

    with pytest.raises(HTTPException, match="pending_review"):
        await complete_task("task-1", core)


@pytest.mark.asyncio
async def test_execute_task_from_project_moves_success_to_pending_review():
    task = MagicMock()
    task.id = "task-1"
    task.title = "Execute Me"
    task.description = "Run through engine"
    task.project_id = "proj-1"
    task.priority = 1

    project_manager = MagicMock()
    project_manager.get_task_async = AsyncMock(return_value=task)
    project_manager.update_task_status = MagicMock(return_value=True)
    project_manager.storage.update_task = MagicMock()

    engine = MagicMock()
    engine.run_task = AsyncMock(return_value={"status": "completed", "assistant_response": "ok"})

    core = SimpleNamespace(project_manager=project_manager, engine=engine)

    result = await execute_task_from_project("task-1", core)

    task.mark_pending_review.assert_called_once_with(
        "Engine execution completed", reviewer="engine"
    )
    project_manager.storage.update_task.assert_called_once_with(task)
    assert result["task_id"] == "task-1"
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_native_verify_moves_success_to_pending_review():
    from penguin.orchestration.native import NativeBackend, WorkflowPhase

    backend = NativeBackend.__new__(NativeBackend)
    task = MagicMock()
    task.id = "task-1"

    backend._project_manager = MagicMock()
    backend._project_manager.get_task = MagicMock(return_value=task)
    backend._project_manager.storage.update_task = MagicMock()

    state = SimpleNamespace(
        task_id="task-1",
        phase_results=[
            SimpleNamespace(phase=WorkflowPhase.IMPLEMENT, success=True),
            SimpleNamespace(phase=WorkflowPhase.TEST, success=True),
            SimpleNamespace(phase=WorkflowPhase.USE, success=True),
        ],
    )

    passed, artifacts = await backend._execute_verify(state, timeout=30)

    assert passed is True
    assert artifacts["verification"] == "All gates passed"
    task.mark_pending_review.assert_called_once_with(
        "ITUV workflow completed successfully",
        reviewer="native",
    )
    backend._project_manager.storage.update_task.assert_called_once_with(task)
