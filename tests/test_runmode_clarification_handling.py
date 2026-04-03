from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.project.manager import ProjectManager
from penguin.project.models import Task, TaskPhase, TaskStatus
from penguin.run_mode import RunMode


def make_task(task_id: str, project_id: str) -> Task:
    now = datetime.utcnow().isoformat()
    return Task(
        id=task_id,
        title="Clarification Task",
        description="Needs clarification",
        status=TaskStatus.RUNNING,
        phase=TaskPhase.IMPLEMENT,
        created_at=now,
        updated_at=now,
        project_id=project_id,
        metadata={},
    )


class DummyCore:
    def __init__(self, project_manager, engine):
        self.project_manager = project_manager
        self.engine = engine
        self.emit_ui_event = AsyncMock()

    async def _handle_stream_chunk(self, *args, **kwargs):
        return None

    def finalize_streaming_message(self):
        return None


@pytest.mark.asyncio
async def test_execute_task_returns_waiting_input_and_persists_clarification(tmp_path):
    project_manager = ProjectManager(tmp_path)
    project = project_manager.create_project("Clarification", "Clarification project")
    task = make_task("task-1", project.id)
    project_manager.storage.create_task(task)

    engine = SimpleNamespace(
        settings=SimpleNamespace(streaming_default=False),
        run_task=AsyncMock(
            return_value={
                "status": "running",
                "assistant_response": "Need schema decision NEED_USER_CLARIFICATION",
                "iterations": 2,
                "execution_time": 1.5,
            }
        ),
    )
    core = DummyCore(project_manager=project_manager, engine=engine)
    run_mode = RunMode(core=core)

    result = await run_mode._execute_task(
        "Clarification Task",
        "Needs clarification",
        {"task_id": "task-1"},
    )

    assert result["status"] == "waiting_input"
    assert result["completion_type"] == "clarification_needed"

    reloaded = project_manager.get_task("task-1")
    assert reloaded is not None
    assert reloaded.status == TaskStatus.RUNNING
    assert reloaded.phase == TaskPhase.IMPLEMENT
    assert "clarification_requests" in reloaded.metadata
    assert len(reloaded.metadata["clarification_requests"]) == 1
    clarification = reloaded.metadata["clarification_requests"][0]
    assert clarification["task_id"] == "task-1"
    assert clarification["task_status"] == TaskStatus.RUNNING.value
    assert clarification["task_phase"] == TaskPhase.IMPLEMENT.value
    assert clarification["status"] == "open"
    assert "Need schema decision" in clarification["prompt"]

    status_calls = [
        call.args[1]
        for call in core.emit_ui_event.await_args_list
        if call.args and call.args[0] == "status"
    ]
    assert any(
        payload.get("status_type") == "clarification_needed"
        for payload in status_calls
    )


@pytest.mark.asyncio
async def test_start_does_not_emit_task_completed_when_clarification_needed(tmp_path):
    project_manager = ProjectManager(tmp_path)
    project = project_manager.create_project("Clarification", "Clarification project")
    task = make_task("task-2", project.id)
    project_manager.storage.create_task(task)

    engine = SimpleNamespace(
        settings=SimpleNamespace(streaming_default=False),
        run_task=AsyncMock(
            return_value={
                "status": "running",
                "assistant_response": "Need product decision NEED_USER_CLARIFICATION",
                "iterations": 1,
                "execution_time": 0.5,
            }
        ),
    )
    core = DummyCore(project_manager=project_manager, engine=engine)
    run_mode = RunMode(core=core)

    result = await run_mode.start(
        name="Clarification Task",
        context={"task_id": "task-2"},
    )

    assert result["status"] == "waiting_input"
    assert result["completion_type"] == "clarification_needed"

    status_calls = [
        call.args[1]
        for call in core.emit_ui_event.await_args_list
        if call.args and call.args[0] == "status"
    ]
    assert any(
        payload.get("status_type") == "clarification_needed"
        for payload in status_calls
    )
    assert not any(
        payload.get("status_type") == "task_completed"
        for payload in status_calls
    )
