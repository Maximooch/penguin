from datetime import datetime
from pathlib import Path

from penguin.project.models import Task, TaskPhase, TaskStatus
from penguin.project.storage import ProjectStorage


def test_task_phase_persists_through_storage_round_trip(tmp_path: Path):
    storage = ProjectStorage(tmp_path / "projects.db")

    task = Task(
        id="task-phase-1",
        title="Phase Persistence",
        description="Ensure task phase survives storage round trip.",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.TEST,
        phase_started_at=datetime.utcnow().isoformat(),
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )

    storage.create_task(task)
    loaded = storage.get_task(task.id)

    assert loaded is not None
    assert loaded.phase == TaskPhase.TEST
    assert loaded.phase_started_at == task.phase_started_at

    loaded.set_phase(TaskPhase.VERIFY)
    storage.update_task(loaded)

    updated = storage.get_task(task.id)
    assert updated is not None
    assert updated.phase == TaskPhase.VERIFY
    assert updated.phase_started_at == loaded.phase_started_at
