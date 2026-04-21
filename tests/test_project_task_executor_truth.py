from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.project.task_executor import ProjectTaskExecutor


@pytest.mark.asyncio
async def test_execute_task_preserves_runmode_status_and_completion_type():
    task = SimpleNamespace(
        id="task-1",
        title="Task title",
        description="Task description",
        project_id="project-1",
        acceptance_criteria=["one"],
    )
    git = SimpleNamespace(
        get_changed_files=MagicMock(side_effect=[[], ["a.py", "b.py"]])
    )
    run_mode = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "status": "waiting_input",
                "completion_type": "clarification_needed",
                "message": "Need clarification",
            }
        )
    )
    executor = ProjectTaskExecutor(
        run_mode=run_mode,
        project_manager=SimpleNamespace(),
        git_integration=git,
    )

    result = await executor.execute_task(task)

    assert result["status"] == "waiting_input"
    assert result["run_mode_status"] == "waiting_input"
    assert result["run_mode_completion_type"] == "clarification_needed"
    assert result["run_mode_result"]["message"] == "Need clarification"
    assert sorted(result["changed_files"]) == ["a.py", "b.py"]


@pytest.mark.asyncio
async def test_execute_task_returns_error_on_executor_failure():
    task = SimpleNamespace(
        id="task-1",
        title="Task title",
        description="Task description",
        project_id="project-1",
        acceptance_criteria=[],
    )
    git = SimpleNamespace(get_changed_files=MagicMock(return_value=[]))
    run_mode = SimpleNamespace(start=AsyncMock(side_effect=RuntimeError("boom")))
    executor = ProjectTaskExecutor(
        run_mode=run_mode,
        project_manager=SimpleNamespace(),
        git_integration=git,
    )

    result = await executor.execute_task(task)

    assert result["status"] == "error"
    assert "boom" in result["message"]
