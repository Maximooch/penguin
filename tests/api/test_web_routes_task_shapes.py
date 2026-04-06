from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from fastapi import HTTPException

from penguin.project.models import ArtifactEvidence, Project, Task, TaskDependency, TaskPhase, TaskStatus
from penguin.web.routes import get_project, get_task, list_tasks


def make_task(task_id: str = "task-1") -> Task:
    now = datetime.utcnow().isoformat()
    return Task(
        id=task_id,
        title="Task Title",
        description="Task Description",
        status=TaskStatus.RUNNING,
        phase=TaskPhase.IMPLEMENT,
        created_at=now,
        updated_at=now,
        priority=2,
        project_id="project-1",
        parent_task_id=None,
        dependencies=["dep-1"],
        dependency_specs=[
            TaskDependency(
                task_id="dep-1",
                policy="artifact_ready",
                artifact_key="client_bundle",
            )
        ],
        artifact_evidence=[
            ArtifactEvidence(
                key="client_bundle",
                kind="file",
                producer_task_id=task_id,
                valid=True,
            )
        ],
        recipe="happy-path",
        metadata={
            "clarification_requests": [
                {
                    "task_id": task_id,
                    "prompt": "Choose auth mode",
                    "status": "open",
                }
            ]
        },
    )


def make_project() -> Project:
    now = datetime.utcnow().isoformat()
    return Project(
        id="project-1",
        name="Project 1",
        description="Project Description",
        created_at=now,
        updated_at=now,
        status="active",
    )


@pytest.mark.asyncio
async def test_list_tasks_accepts_uppercase_status_filter():
    task = make_task()
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            list_tasks_async=AsyncMock(return_value=[task]),
        )
    )

    response = await list_tasks(project_id="project-1", status="RUNNING", core=core)

    core.project_manager.list_tasks_async.assert_awaited_once()
    _, kwargs = core.project_manager.list_tasks_async.await_args
    assert kwargs["project_id"] == "project-1"
    assert kwargs["status"] == TaskStatus.RUNNING
    assert response["tasks"][0]["phase"] == TaskPhase.IMPLEMENT.value


@pytest.mark.asyncio
async def test_list_tasks_rejects_unknown_status_with_real_enum_values():
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            list_tasks_async=AsyncMock(return_value=[]),
        )
    )

    with pytest.raises(HTTPException) as exc_info:
        await list_tasks(status="not-a-status", core=core)

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert "Valid options:" in detail
    assert TaskStatus.PENDING_REVIEW.value in detail
    assert TaskStatus.RUNNING.value in detail


@pytest.mark.asyncio
async def test_get_task_returns_phase_dependencies_artifacts_and_clarification_state():
    task = make_task()
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(return_value=task),
        )
    )

    response = await get_task("task-1", core=core)

    assert response["status"] == TaskStatus.RUNNING.value
    assert response["phase"] == TaskPhase.IMPLEMENT.value
    assert response["dependencies"] == ["dep-1"]
    assert response["dependency_specs"][0]["policy"] == "artifact_ready"
    assert response["artifact_evidence"][0]["key"] == "client_bundle"
    assert response["recipe"] == "happy-path"
    assert response["clarification_requests"][0]["prompt"] == "Choose auth mode"
    assert response["metadata"]["clarification_requests"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_get_project_embeds_tasks_with_phase_and_clarification_visibility():
    task = make_task()
    project = make_project()
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project_async=AsyncMock(return_value=project),
            list_tasks_async=AsyncMock(return_value=[task]),
        )
    )

    response = await get_project("project-1", core=core)

    assert response["id"] == "project-1"
    assert len(response["tasks"]) == 1
    embedded_task = response["tasks"][0]
    assert embedded_task["status"] == TaskStatus.RUNNING.value
    assert embedded_task["phase"] == TaskPhase.IMPLEMENT.value
    assert embedded_task["clarification_requests"][0]["prompt"] == "Choose auth mode"


@pytest.mark.asyncio
async def test_resume_task_clarification_returns_resumed_result():
    task = make_task()
    task.title = "Resume Title"
    task.description = "Resume Description"

    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(return_value=task),
        )
    )

    run_mode_instance = SimpleNamespace(
        resume_with_clarification=AsyncMock(
            return_value={
                "status": "waiting_input",
                "message": "Need one more answer",
                "completion_type": "clarification_needed",
            }
        )
    )

    from unittest.mock import patch
    from penguin.web.routes import ClarificationAnswerRequest, resume_task_clarification

    with patch("penguin.web.routes.RunMode", return_value=run_mode_instance):
        response = await resume_task_clarification(
            "task-1",
            ClarificationAnswerRequest(answer="Use rotating refresh tokens", answered_by="human"),
            core=core,
        )

    run_mode_instance.resume_with_clarification.assert_awaited_once_with(
        task_id="task-1",
        answer="Use rotating refresh tokens",
        answered_by="human",
    )
    assert response["task_id"] == "task-1"
    assert response["result"]["status"] == "waiting_input"
    assert response["task"]["clarification_requests"][0]["status"] == "open"


@pytest.mark.asyncio
async def test_resume_task_clarification_returns_404_when_task_missing():
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(return_value=None),
        )
    )

    from penguin.web.routes import ClarificationAnswerRequest, resume_task_clarification

    with pytest.raises(HTTPException) as exc_info:
        await resume_task_clarification(
            "missing-task",
            ClarificationAnswerRequest(answer="Anything", answered_by="human"),
            core=core,
        )

    assert exc_info.value.status_code == 404


@pytest.mark.asyncio
async def test_start_task_reports_active_state_honestly():
    task = make_task()
    task.status = TaskStatus.RUNNING
    task.phase = TaskPhase.IMPLEMENT
    updated_task = make_task()
    updated_task.status = TaskStatus.ACTIVE
    updated_task.phase = TaskPhase.PENDING

    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(side_effect=[task, updated_task]),
            update_task_status=lambda task_id, status, reason: True,
        )
    )

    from penguin.web.routes import start_task

    response = await start_task("task-1", core=core)

    assert response["status"] == TaskStatus.ACTIVE.value
    assert "active" in response["message"].lower()


@pytest.mark.asyncio
async def test_execute_task_from_project_preserves_waiting_input_truth():
    task = make_task()
    task.status = TaskStatus.ACTIVE
    task.phase = TaskPhase.IMPLEMENT
    updated_task = make_task()
    updated_task.status = TaskStatus.RUNNING
    updated_task.phase = TaskPhase.IMPLEMENT

    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(side_effect=[task, updated_task]),
        ),
        engine=SimpleNamespace(),
    )

    run_mode_instance = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "status": "waiting_input",
                "message": "Need schema decision",
                "completion_type": "clarification_needed",
                "task_id": "task-1",
                "project_id": "project-1",
            }
        )
    )

    from unittest.mock import patch
    from penguin.web.routes import execute_task_from_project

    with patch("penguin.web.routes.RunMode", return_value=run_mode_instance):
        response = await execute_task_from_project("task-1", core=core)

    run_mode_instance.start.assert_awaited_once()
    assert response["task_id"] == "task-1"
    assert response["result"]["status"] == "waiting_input"
    assert response["result"]["completion_type"] == "clarification_needed"
    assert response["task"]["status"] == updated_task.status.value
    assert response["task"]["phase"] == updated_task.phase.value

