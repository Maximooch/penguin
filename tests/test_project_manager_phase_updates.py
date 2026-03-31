from datetime import datetime
from pathlib import Path

from penguin.project.manager import ProjectManager
from penguin.project.models import Task, TaskPhase, TaskStatus


def test_project_manager_updates_task_phase(tmp_path: Path):
    manager = ProjectManager(tmp_path)

    task = Task(
        id="task-phase-manager-1",
        title="Manager Phase Update",
        description="Ensure manager persists phase changes.",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )
    manager.storage.create_task(task)

    assert manager.update_task_phase(
        task.id,
        TaskPhase.IMPLEMENT,
        "Starting implementation phase.",
    )

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert loaded.phase == TaskPhase.IMPLEMENT
    assert loaded.phase_started_at is not None
