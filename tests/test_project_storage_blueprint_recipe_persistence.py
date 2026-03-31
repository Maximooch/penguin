from datetime import datetime
from pathlib import Path

from penguin.project.models import Task, TaskPhase, TaskStatus
from penguin.project.storage import ProjectStorage


def test_task_blueprint_and_recipe_fields_persist_round_trip(tmp_path: Path):
    storage = ProjectStorage(tmp_path / "projects.db")

    task = Task(
        id="task-blueprint-recipe-1",
        title="Blueprint Recipe Persistence",
        description="Ensure blueprint linkage and recipe survive storage round trip.",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        blueprint_id="AUTH-1",
        blueprint_source="blueprints/auth.md",
        recipe="smoke-auth-flow",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
    )

    storage.create_task(task)
    loaded = storage.get_task(task.id)

    assert loaded is not None
    assert loaded.blueprint_id == "AUTH-1"
    assert loaded.blueprint_source == "blueprints/auth.md"
    assert loaded.recipe == "smoke-auth-flow"

    loaded.recipe = "updated-smoke-auth-flow"
    storage.update_task(loaded)

    updated = storage.get_task(task.id)
    assert updated is not None
    assert updated.recipe == "updated-smoke-auth-flow"
