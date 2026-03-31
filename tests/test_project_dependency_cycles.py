from datetime import datetime

import pytest

from penguin.project.exceptions import DependencyError
from penguin.project.manager import ProjectManager
from penguin.project.models import Blueprint, BlueprintItem, Task, TaskStatus


def test_validate_dependencies_rejects_cycle_against_existing_project_graph(tmp_path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Cycle Test", "Cycle detection")

    task_a = Task(
        id="task-a",
        title="Task A",
        description="A",
        status=TaskStatus.ACTIVE,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        project_id=project.id,
    )
    task_b = Task(
        id="task-b",
        title="Task B",
        description="B",
        status=TaskStatus.ACTIVE,
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        project_id=project.id,
        dependencies=["task-a"],
    )

    manager.storage.create_task(task_a)
    manager.storage.create_task(task_b)

    with pytest.raises(DependencyError, match="cycle"):
        manager._validate_dependencies(["task-b"], project.id, task_id="task-a")


def test_sync_blueprint_rejects_dependency_cycle(tmp_path):
    manager = ProjectManager(tmp_path)

    blueprint = Blueprint(
        title="Cycle Blueprint",
        project_key="CYCLE",
        items=[
            BlueprintItem(
                id="A-1",
                title="Task A",
                description="A",
                depends_on=["B-1"],
            ),
            BlueprintItem(
                id="B-1",
                title="Task B",
                description="B",
                depends_on=["A-1"],
            ),
        ],
    )

    with pytest.raises(DependencyError, match="cycle"):
        manager.sync_blueprint(blueprint)
