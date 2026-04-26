from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.project.manager import ProjectManager
from penguin.project.models import DependencyPolicy, Task, TaskDependency, TaskPhase, TaskStatus
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
async def test_runmode_one_shot_does_not_update_project_task_status():
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


def test_project_manager_marks_task_execution_ready_for_review(tmp_path):
    project_manager = ProjectManager(workspace_path=tmp_path)
    project = project_manager.create_project(
        name="Example Project",
        description="Project for task finalization",
    )
    task = project_manager.create_task(
        title="Example Task",
        description="Do the thing",
        project_id=project.id,
    )
    finalized_task = project_manager.mark_task_execution_ready_for_review(
        task.id,
        executor_id="runmode",
        response="accepted",
        task_prompt="RunMode execution: Example Task",
        context={"source": "runmode_continuous"},
    )

    assert finalized_task.status == TaskStatus.PENDING_REVIEW
    assert finalized_task.phase == TaskPhase.DONE
    assert finalized_task.execution_history[-1].result.value == "success"
    assert finalized_task.execution_history[-1].executor_id == "runmode"
    assert finalized_task.execution_history[-1].response == "accepted"

    stored_task = project_manager.get_task(task.id)
    assert stored_task.status == TaskStatus.PENDING_REVIEW
    assert stored_task.phase == TaskPhase.DONE


@pytest.mark.asyncio
async def test_project_continuous_does_not_reselect_finished_blueprint_task():
    task = Task(
        id="task-123",
        title="Blueprint Task",
        description="Created from blueprint",
        status=TaskStatus.ACTIVE,
        created_at="2026-04-25T00:00:00",
        updated_at="2026-04-25T00:00:00",
        project_id="project-1",
        blueprint_id="blueprint-1",
    )

    async def get_next_task_dag(project_id):
        if task.status == TaskStatus.ACTIVE:
            return task
        return None

    async def finalize_task(**kwargs):
        task.status = TaskStatus.PENDING_REVIEW
        task.phase = TaskPhase.DONE
        return task

    project_manager = MagicMock()
    project_manager.get_next_task_async = AsyncMock(return_value=None)
    project_manager.get_next_task_dag_async = AsyncMock(side_effect=get_next_task_dag)
    project_manager.mark_task_execution_ready_for_review_async = AsyncMock(
        side_effect=finalize_task
    )

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)
    run_mode._execute_task = AsyncMock(
        return_value={
            "status": "pending_review",
            "message": "done",
            "completion_type": "pending_review",
        }
    )

    await run_mode.start_continuous(project_id="project-1", use_dag=True)

    run_mode._execute_task.assert_awaited_once_with(
        "Blueprint Task",
        "Created from blueprint",
        task_data_context := {
            "id": "task-123",
            "project_id": "project-1",
            "priority": 0,
            "metadata": {},
            "status": "active",
            "progress": 0,
            "due_date": None,
            "phase": TaskPhase.PENDING,
            "phase_value": "pending",
            "blueprint_id": "blueprint-1",
            "acceptance_criteria": [],
            "recipe": None,
            "agent_role": None,
            "required_tools": [],
            "skills": [],
            "effort": None,
            "value": None,
            "risk": None,
        },
    )
    project_manager.mark_task_execution_ready_for_review_async.assert_awaited_once_with(
        task_id="task-123",
        executor_id="runmode",
        response="done",
        task_prompt="RunMode execution: Blueprint Task",
        context={"source": "runmode_continuous"},
    )
    assert task_data_context["blueprint_id"] == "blueprint-1"
    assert task.status == TaskStatus.PENDING_REVIEW
    assert task.phase == TaskPhase.DONE


@pytest.mark.asyncio
async def test_runmode_task_prompt_uses_finish_task_not_task_completed():
    captured = {}
    project_manager = MagicMock()

    async def run_task(**kwargs):
        captured.update(kwargs)
        return {"status": "pending_review", "assistant_response": "done"}

    core = DummyCore(project_manager=project_manager)
    core.engine = SimpleNamespace(run_task=run_task, settings=SimpleNamespace())
    core.finalize_streaming_message = MagicMock(return_value=None)
    core._handle_stream_chunk = AsyncMock()

    run_mode = RunMode(core=core)
    await run_mode._execute_task("Example Task", "Do the thing", {"id": "task-123"})

    assert "finish_task" in captured["task_prompt"]
    assert "Respond with TASK_COMPLETED" not in captured["task_prompt"]


def test_project_manager_reports_strict_dependency_blocked_by_pending_review(tmp_path):
    project_manager = ProjectManager(workspace_path=tmp_path)
    project = project_manager.create_project(
        name="Blueprint Project",
        description="Project with dependent tasks",
    )
    upstream = project_manager.create_task(
        title="Foundation",
        description="Create the base app",
        project_id=project.id,
    )
    downstream = project_manager.create_task(
        title="CRUD",
        description="Build on the base app",
        project_id=project.id,
        dependencies=[upstream.id],
    )

    project_manager.mark_task_execution_ready_for_review(
        upstream.id,
        executor_id="runmode",
        response="base app ready",
    )

    assert project_manager.get_ready_tasks(project.id) == []
    blocked = project_manager.get_blocked_ready_candidates(project.id)
    assert blocked == [
        {
            "task_id": downstream.id,
            "title": "CRUD",
            "blueprint_id": None,
            "blockers": [
                {
                    "task_id": upstream.id,
                    "policy": "completion_required",
                    "artifact_key": None,
                    "status": "pending_review",
                    "phase": "done",
                    "title": "Foundation",
                }
            ],
        }
    ]


def test_project_manager_review_ready_dependency_unblocks_pending_review(tmp_path):
    project_manager = ProjectManager(workspace_path=tmp_path)
    project = project_manager.create_project(
        name="Blueprint Project",
        description="Project with relaxed dependency",
    )
    upstream = project_manager.create_task(
        title="Foundation",
        description="Create the base app",
        project_id=project.id,
    )
    downstream = project_manager.create_task(
        title="CRUD",
        description="Build on the base app",
        project_id=project.id,
        dependencies=[upstream.id],
    )
    downstream.dependency_specs = [
        TaskDependency(
            task_id=upstream.id,
            policy=DependencyPolicy.REVIEW_READY_OK,
        )
    ]
    project_manager.storage.update_task(downstream)

    project_manager.mark_task_execution_ready_for_review(
        upstream.id,
        executor_id="runmode",
        response="base app ready",
    )

    ready = project_manager.get_ready_tasks(project.id)
    assert [task.id for task in ready] == [downstream.id]
    assert project_manager.get_blocked_ready_candidates(project.id) == []


@pytest.mark.asyncio
async def test_project_continuous_idle_reports_blocked_dependency_frontier():
    task = Task(
        id="task-123",
        title="Blueprint Task",
        description="Created from blueprint",
        status=TaskStatus.ACTIVE,
        created_at="2026-04-25T00:00:00",
        updated_at="2026-04-25T00:00:00",
        project_id="project-1",
        blueprint_id="blueprint-1",
    )
    blocked_candidates = [
        {
            "task_id": "task-456",
            "title": "Dependent Task",
            "blueprint_id": "blueprint-2",
            "blockers": [
                {
                    "task_id": "task-123",
                    "policy": "completion_required",
                    "status": "pending_review",
                    "phase": "done",
                    "title": "Blueprint Task",
                    "artifact_key": None,
                }
            ],
        }
    ]
    events = []

    async def get_next_task_dag(project_id):
        if task.status == TaskStatus.ACTIVE:
            return task
        return None

    async def finalize_task(**kwargs):
        task.status = TaskStatus.PENDING_REVIEW
        task.phase = TaskPhase.DONE
        return task

    project_manager = MagicMock()
    project_manager.get_next_task_async = AsyncMock(return_value=None)
    project_manager.get_next_task_dag_async = AsyncMock(side_effect=get_next_task_dag)
    project_manager.mark_task_execution_ready_for_review_async = AsyncMock(
        side_effect=finalize_task
    )
    project_manager.get_blocked_ready_candidates_async = AsyncMock(
        return_value=blocked_candidates
    )

    core = DummyCore(project_manager=project_manager)
    run_mode = RunMode(core=core)
    run_mode._execute_task = AsyncMock(
        return_value={
            "status": "pending_review",
            "message": "done",
            "completion_type": "pending_review",
        }
    )
    run_mode._emit_event = AsyncMock(side_effect=lambda event: events.append(event))

    await run_mode.start_continuous(project_id="project-1", use_dag=True)

    idle_events = [
        event
        for event in events
        if event.get("type") == "status"
        and event.get("status_type") == "continuous_mode_idle"
    ]
    assert idle_events[-1]["data"] == {
        "reason": "project_tasks_blocked",
        "project_id": "project-1",
        "blocked_tasks": blocked_candidates,
    }
    assert any(
        "Project execution paused" in event.get("content", "")
        for event in events
        if event.get("type") == "message"
    )

