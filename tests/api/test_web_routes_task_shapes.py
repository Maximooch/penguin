from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

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




@pytest.mark.asyncio
async def test_execute_task_from_project_preserves_time_limit_truth():
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
                "status": "stopped",
                "message": "RunMode stopped because the explicit time limit was reached.",
                "completion_type": "time_limit_reached",
                "task_id": "task-1",
                "project_id": "project-1",
            }
        )
    )

    from unittest.mock import patch
    from penguin.web.routes import execute_task_from_project

    with patch("penguin.web.routes.RunMode", return_value=run_mode_instance):
        response = await execute_task_from_project("task-1", core=core)

    assert response["task_id"] == "task-1"
    assert response["result"]["status"] == "stopped"
    assert response["result"]["completion_type"] == "time_limit_reached"
    assert "time limit" in response["result"]["message"].lower()
    assert response["task"]["status"] == updated_task.status.value


@pytest.mark.asyncio
async def test_execute_task_from_project_preserves_idle_no_ready_work_truth():
    task = make_task()
    task.status = TaskStatus.ACTIVE
    task.phase = TaskPhase.IMPLEMENT
    updated_task = make_task()
    updated_task.status = TaskStatus.ACTIVE
    updated_task.phase = TaskPhase.PENDING

    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(side_effect=[task, updated_task]),
        ),
        engine=SimpleNamespace(),
    )

    run_mode_instance = SimpleNamespace(
        start=AsyncMock(
            return_value={
                "status": "idle",
                "message": "RunMode stopped because no ready work remained.",
                "completion_type": "idle_no_ready_tasks",
                "task_id": "task-1",
                "project_id": "project-1",
            }
        )
    )

    from unittest.mock import patch
    from penguin.web.routes import execute_task_from_project

    with patch("penguin.web.routes.RunMode", return_value=run_mode_instance):
        response = await execute_task_from_project("task-1", core=core)

    assert response["task_id"] == "task-1"
    assert response["result"]["status"] == "idle"
    assert response["result"]["completion_type"] == "idle_no_ready_tasks"
    assert "no ready work remained" in response["result"]["message"].lower()
    assert response["task"]["phase"] == updated_task.phase.value



@pytest.mark.asyncio
async def test_init_project_from_blueprint_reports_counts(tmp_path):
    from unittest.mock import Mock, patch
    from penguin.web.routes import ProjectInitRequest, init_project

    blueprint_path = tmp_path / "example.md"
    blueprint_path.write_text("# Example")
    project = make_project()
    task = make_task()
    blueprint = SimpleNamespace(title="Example", overview="desc", items=[SimpleNamespace(id="A")])
    diagnostics = SimpleNamespace(has_errors=False, has_warnings=False, diagnostics=[])
    parser = SimpleNamespace(
        parse_file=Mock(return_value=blueprint),
        lint_blueprint=Mock(return_value=diagnostics),
    )
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            create_project_async=AsyncMock(return_value=project),
            sync_blueprint=Mock(return_value={"created": ["A"], "updated": ["B"], "skipped": []}),
            get_ready_tasks_async=AsyncMock(return_value=[task]),
            list_tasks=Mock(return_value=[]),
            storage=SimpleNamespace(delete_task=Mock(), delete_project=Mock()),
        )
    )

    with patch("penguin.web.services.projects.BlueprintParser", return_value=parser):
        response = await init_project(
            ProjectInitRequest(
                name="Example",
                description="Example project",
                workspace_path=str(tmp_path / "workspace"),
                blueprint_path=str(blueprint_path),
            ),
            core=core,
        )

    assert response["project"]["id"] == project.id
    assert response["blueprint"]["tasks_created"] == 1
    assert response["blueprint"]["tasks_updated"] == 1
    assert response["blueprint"]["ready_tasks"] == 1


@pytest.mark.asyncio
async def test_init_project_from_blueprint_rolls_back_empty_import(tmp_path):
    from unittest.mock import Mock, patch
    from penguin.web.routes import ProjectInitRequest, init_project

    blueprint_path = tmp_path / "empty.md"
    blueprint_path.write_text("# Empty")
    project = make_project()
    empty_blueprint = SimpleNamespace(title="Empty", overview="desc", items=[])
    diagnostics = SimpleNamespace(has_errors=False, has_warnings=False, diagnostics=[])
    parser = SimpleNamespace(
        parse_file=Mock(return_value=empty_blueprint),
        lint_blueprint=Mock(return_value=diagnostics),
    )
    storage = SimpleNamespace(delete_task=Mock(), delete_project=Mock())
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            create_project_async=AsyncMock(return_value=project),
            sync_blueprint=Mock(),
            get_ready_tasks_async=AsyncMock(return_value=[]),
            list_tasks=Mock(return_value=[]),
            storage=storage,
        )
    )

    with patch("penguin.web.services.projects.BlueprintParser", return_value=parser):
        with pytest.raises(HTTPException) as exc_info:
            await init_project(
                ProjectInitRequest(
                    name="Empty",
                    description="Empty project",
                    workspace_path=str(tmp_path / "workspace"),
                    blueprint_path=str(blueprint_path),
                ),
                core=core,
            )

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert detail["message"] == "Blueprint import produced no tasks. Project initialization rolled back."
    assert detail["diagnostics"][0]["code"] == "BP-LINT-004"
    core.project_manager.sync_blueprint.assert_not_called()
    storage.delete_project.assert_called_once_with(project.id)


@pytest.mark.asyncio
async def test_init_project_from_blueprint_wraps_parse_failures_as_structured_detail(tmp_path):
    from unittest.mock import patch
    from penguin.project.blueprint_parser import BlueprintParseError
    from penguin.web.routes import ProjectInitRequest, init_project

    blueprint_path = tmp_path / "broken.md"
    blueprint_path.write_text("---\nnot: valid")
    project = make_project()
    storage = SimpleNamespace(delete_task=Mock(), delete_project=Mock())
    parser = SimpleNamespace(
        parse_file=Mock(side_effect=BlueprintParseError("bad frontmatter", source=str(blueprint_path))),
        lint_blueprint=Mock(),
    )
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            create_project_async=AsyncMock(return_value=project),
            sync_blueprint=Mock(),
            get_ready_tasks_async=AsyncMock(return_value=[]),
            list_tasks=Mock(return_value=[]),
            storage=storage,
        )
    )

    with patch("penguin.web.services.projects.BlueprintParser", return_value=parser):
        with pytest.raises(HTTPException) as exc_info:
            await init_project(
                ProjectInitRequest(
                    name="Broken",
                    description="Broken project",
                    workspace_path=str(tmp_path / "workspace"),
                    blueprint_path=str(blueprint_path),
                ),
                core=core,
            )

    assert exc_info.value.status_code == 400
    detail = exc_info.value.detail
    assert detail["message"].startswith("Blueprint parse failed:")
    assert "bad frontmatter" in detail["message"]
    storage.delete_project.assert_called_once_with(project.id)
    core.project_manager.sync_blueprint.assert_not_called()


@pytest.mark.asyncio
async def test_start_project_returns_exact_execution_summary_from_runmode_result():
    from penguin.web.routes import ProjectStartRequest, start_project

    project = make_project()
    project.name = "Bootstrap Project"
    project.description = "Bootstrap Description"
    first_ready = make_task("task-ready-1")
    first_ready.title = "First Ready Task"
    second_ready = make_task("task-ready-2")
    second_ready.title = "Second Ready Task"
    runmode_result = {
        "status": "waiting_input",
        "message": "Need deployment target",
        "completion_type": "clarification_needed",
        "project_id": project.id,
        "task_id": first_ready.id,
    }
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project=Mock(return_value=project),
            get_project_by_name=Mock(return_value=None),
            list_projects=Mock(return_value=[project]),
            list_tasks_async=AsyncMock(return_value=[first_ready, second_ready]),
            get_ready_tasks_async=AsyncMock(return_value=[first_ready, second_ready]),
        ),
        start_run_mode=AsyncMock(return_value=runmode_result),
    )

    response = await start_project(
        ProjectStartRequest(
            project_identifier=project.id,
            continuous=True,
            time_limit=30,
        ),
        core=core,
    )

    core.start_run_mode.assert_awaited_once_with(
        name=project.name,
        description=project.description,
        context={"project_id": project.id, "session_id": None, "conversation_id": None, "directory": None},
        continuous=True,
        time_limit=30,
        mode_type="project",
    )
    assert response["project"]["id"] == project.id
    assert response["execution"] == {
        "mode": "continuous",
        "time_limit": 30,
        "ready_tasks": 2,
        "first_ready_task": "First Ready Task",
        "result": runmode_result,
        "session_id": None,
        "directory": None,
    }


@pytest.mark.asyncio
async def test_start_project_threads_session_and_directory_into_runmode(tmp_path):
    from penguin.web.routes import ProjectStartRequest, start_project

    project = make_project()
    project.workspace_path = str(tmp_path / "fallback")
    ready_task = make_task("task-ready")
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project=Mock(return_value=project),
            get_project_by_name=Mock(return_value=None),
            list_projects=Mock(return_value=[project]),
            list_tasks_async=AsyncMock(return_value=[ready_task]),
            get_ready_tasks_async=AsyncMock(return_value=[ready_task]),
        ),
        start_run_mode=AsyncMock(return_value={"status": "started"}),
    )

    response = await start_project(
        ProjectStartRequest(
            project_identifier=project.id,
            continuous=True,
            session_id="session-test",
            directory=str(tmp_path),
        ),
        core=core,
    )

    core.start_run_mode.assert_awaited_once()
    call = core.start_run_mode.await_args.kwargs
    assert call["context"]["project_id"] == project.id
    assert call["context"]["session_id"] == "session-test"
    assert call["context"]["directory"] == str(tmp_path.resolve())
    assert response["execution"]["session_id"] == "session-test"
    assert response["execution"]["directory"] == str(tmp_path.resolve())


@pytest.mark.asyncio
async def test_start_project_by_exact_name_uses_same_project_runmode_path():
    from penguin.web.routes import ProjectStartRequest, start_project

    project = make_project()
    project.name = "Exact Name Match"
    ready_task = make_task("task-ready-name")
    ready_task.title = "Named Ready Task"
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project=Mock(return_value=None),
            get_project_by_name=Mock(return_value=project),
            list_projects=Mock(return_value=[project]),
            list_tasks_async=AsyncMock(return_value=[ready_task]),
            get_ready_tasks_async=AsyncMock(return_value=[ready_task]),
        ),
        start_run_mode=AsyncMock(
            return_value={
                "status": "idle",
                "completion_type": "idle_no_ready_tasks",
                "message": "RunMode stopped because no ready work remained.",
            }
        ),
    )

    response = await start_project(
        ProjectStartRequest(
            project_identifier=project.name,
            continuous=True,
            time_limit=None,
        ),
        core=core,
    )

    core.project_manager.get_project.assert_called_once_with(project.name)
    core.project_manager.get_project_by_name.assert_called_once_with(project.name)
    assert response["project"]["name"] == project.name
    assert response["execution"]["first_ready_task"] == "Named Ready Task"
    assert response["execution"]["result"]["completion_type"] == "idle_no_ready_tasks"

@pytest.mark.asyncio
async def test_start_project_routes_through_runmode_project_context():
    from penguin.web.routes import ProjectStartRequest, start_project

    project = make_project()
    ready_task = make_task()
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project=Mock(return_value=project),
            get_project_by_name=Mock(return_value=None),
            list_projects=Mock(return_value=[project]),
            list_tasks_async=AsyncMock(return_value=[ready_task]),
            get_ready_tasks_async=AsyncMock(return_value=[ready_task]),
        ),
        start_run_mode=AsyncMock(return_value={"status": "completed", "completion_type": "success"}),
    )

    response = await start_project(
        ProjectStartRequest(project_identifier=project.id, continuous=True, time_limit=20),
        core=core,
    )

    core.start_run_mode.assert_awaited_once()
    _, kwargs = core.start_run_mode.await_args
    assert kwargs["context"] == {"project_id": project.id, "session_id": None, "conversation_id": None, "directory": None}
    assert kwargs["mode_type"] == "project"
    assert response["execution"]["ready_tasks"] == 1
    assert response["execution"]["result"]["status"] == "completed"


@pytest.mark.asyncio
async def test_delete_project_returns_deleted_task_count():
    from penguin.web.routes import delete_project

    project = make_project()
    tasks = [make_task('task-1'), make_task('task-2')]
    storage = SimpleNamespace(delete_task=Mock(), delete_project=Mock())
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project_async=AsyncMock(return_value=project),
            list_tasks_async=AsyncMock(return_value=tasks),
            list_tasks=Mock(return_value=tasks),
            storage=storage,
        )
    )

    response = await delete_project('project-1', core=core)

    assert response['project']['id'] == project.id
    assert response['deleted_tasks'] == 2
    assert 'deleted successfully' in response['message'].lower()
    assert storage.delete_task.call_count == 2
    storage.delete_project.assert_called_once_with(project.id)


@pytest.mark.asyncio
async def test_delete_task_returns_deleted_task_payload():
    from penguin.web.routes import delete_task

    task = make_task()
    storage = SimpleNamespace(delete_task=Mock())
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(return_value=task),
            storage=storage,
        )
    )

    response = await delete_task('task-1', core=core)

    assert response['task']['id'] == task.id
    assert response['task']['phase'] == task.phase.value
    assert 'deleted successfully' in response['message'].lower()
    storage.delete_task.assert_called_once_with(task.id)


@pytest.mark.asyncio
async def test_run_project_requires_source_input():
    from penguin.web.routes import ProjectRunRequest, run_project

    core = SimpleNamespace(project_manager=SimpleNamespace())

    with pytest.raises(HTTPException) as exc_info:
        await run_project(ProjectRunRequest(), core=core)

    assert exc_info.value.status_code == 400
    assert 'spec_path or markdown_content' in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_run_project_from_inline_markdown_parses_then_starts_project():
    from unittest.mock import patch
    from penguin.web.routes import ProjectRunRequest, run_project

    parse_result = {
        'status': 'success',
        'message': 'ok',
        'creation_result': {
            'project': {'id': 'project-1', 'name': 'Example'},
            'tasks_created': 2,
        },
    }
    execution_result = {
        'project': {'id': 'project-1', 'name': 'Example'},
        'execution': {'mode': 'continuous', 'ready_tasks': 1, 'result': {'status': 'completed'}},
    }
    core = SimpleNamespace(project_manager=SimpleNamespace())

    with patch('penguin.web.services.projects.parse_project_specification_from_markdown', AsyncMock(return_value=parse_result)) as parse_mock, patch('penguin.web.services.projects.start_project_execution', AsyncMock(return_value=execution_result)) as start_mock:
        response = await run_project(
            ProjectRunRequest(markdown_content='# Demo\n\n## Tasks\n- One', continuous=True, time_limit=15),
            core=core,
        )

    parse_mock.assert_awaited_once()
    start_mock.assert_awaited_once_with(
        core=core,
        project_identifier='project-1',
        continuous=True,
        time_limit=15,
        session_id=None,
        directory=None,
    )
    assert response['source'] == 'inline_markdown'
    assert response['parse']['creation_result']['project']['id'] == 'project-1'
    assert response['execution']['execution']['result']['status'] == 'completed'


@pytest.mark.asyncio
async def test_run_project_reports_parse_failures_as_400():
    from unittest.mock import patch
    from penguin.web.routes import ProjectRunRequest, run_project

    parse_result = {'status': 'error', 'message': 'No tasks found'}
    core = SimpleNamespace(project_manager=SimpleNamespace())

    with patch('penguin.web.services.projects.parse_project_specification_from_markdown', AsyncMock(return_value=parse_result)):
        with pytest.raises(HTTPException) as exc_info:
            await run_project(ProjectRunRequest(markdown_content='# Empty'), core=core)

    assert exc_info.value.status_code == 400
    assert exc_info.value.detail['message'] == 'No tasks found'
    assert exc_info.value.detail['source'] == 'inline_markdown'
