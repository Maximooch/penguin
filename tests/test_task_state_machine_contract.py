from datetime import datetime

import pytest

from penguin.project.exceptions import StateTransitionError
from penguin.project.manager import ProjectManager
from penguin.project.models import ExecutionResult, Task, TaskPhase, TaskStatus


def make_task(**overrides):
    base = {
        "id": "task-1",
        "title": "Example Task",
        "description": "Example",
        "status": TaskStatus.ACTIVE,
        "phase": TaskPhase.PENDING,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    base.update(overrides)
    return Task(**base)


def test_manager_rejects_completed_status_when_phase_is_not_done(tmp_path):
    manager = ProjectManager(tmp_path)
    task = make_task(status=TaskStatus.RUNNING, phase=TaskPhase.IMPLEMENT)
    manager.storage.create_task(task)

    with pytest.raises(StateTransitionError, match="status/phase"):
        manager.update_task_status(task.id, TaskStatus.COMPLETED)


def test_manager_rejects_done_phase_for_running_status(tmp_path):
    manager = ProjectManager(tmp_path)
    task = make_task(status=TaskStatus.RUNNING, phase=TaskPhase.IMPLEMENT)
    manager.storage.create_task(task)

    with pytest.raises(StateTransitionError, match="status/phase"):
        manager.update_task_phase(task.id, TaskPhase.DONE)


def test_complete_current_execution_moves_running_task_to_pending_review_not_completed():
    task = make_task(status=TaskStatus.RUNNING, phase=TaskPhase.VERIFY)
    task.start_execution()

    task.complete_current_execution(ExecutionResult.SUCCESS, response="ok")

    assert task.status == TaskStatus.PENDING_REVIEW
    assert task.phase == TaskPhase.DONE
