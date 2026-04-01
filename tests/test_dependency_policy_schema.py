from pathlib import Path

from penguin.project.blueprint_parser import BlueprintParser
from penguin.project.manager import ProjectManager
from penguin.project.models import (
    Blueprint,
    BlueprintItem,
    DependencyPolicy,
    Task,
    TaskDependency,
    TaskPhase,
    TaskStatus,
)


def test_task_normalizes_plain_dependencies_to_completion_required():
    task = Task(
        id="task-1",
        title="Example",
        description="Example",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
        dependencies=["dep-1", "dep-2"],
    )

    assert [spec.task_id for spec in task.dependency_specs] == ["dep-1", "dep-2"]
    assert all(
        spec.policy == DependencyPolicy.COMPLETION_REQUIRED
        for spec in task.dependency_specs
    )


def test_blueprint_item_normalizes_plain_depends_on_to_completion_required():
    item = BlueprintItem(
        id="AUTH-1",
        title="Task",
        description="Task",
        depends_on=["AUTH-0"],
    )

    assert len(item.dependency_specs) == 1
    assert item.dependency_specs[0].task_id == "AUTH-0"
    assert item.dependency_specs[0].policy == DependencyPolicy.COMPLETION_REQUIRED


def test_blueprint_parser_reads_typed_dependency_specs_from_yaml(tmp_path: Path):
    blueprint_path = tmp_path / "typed-blueprint.yaml"
    blueprint_path.write_text(
        """
title: Typed Blueprint
project_key: TYPED
tasks:
  - id: AUTH-1
    title: Build auth
    description: Build auth
    dependency_specs:
      - task_id: AUTH-0
        policy: review_ready_ok
      - task_id: SCHEMA-1
        policy: artifact_ready
        artifact_key: generated_client
""".strip()
    )

    parser = BlueprintParser(base_path=tmp_path)
    blueprint = parser.parse_file(blueprint_path)

    assert len(blueprint.items) == 1
    specs = blueprint.items[0].dependency_specs
    assert [(spec.task_id, spec.policy.value, spec.artifact_key) for spec in specs] == [
        ("AUTH-0", "review_ready_ok", None),
        ("SCHEMA-1", "artifact_ready", "generated_client"),
    ]


def test_storage_persists_typed_dependency_specs(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    task = Task(
        id="task-1",
        title="Task",
        description="Task",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
        dependencies=["dep-1", "dep-2"],
        dependency_specs=[
            TaskDependency(task_id="dep-1", policy=DependencyPolicy.REVIEW_READY_OK),
            TaskDependency(
                task_id="dep-2",
                policy=DependencyPolicy.ARTIFACT_READY,
                artifact_key="client_bundle",
            ),
        ],
    )
    manager.storage.create_task(task)

    loaded = manager.storage.get_task(task.id)

    assert loaded is not None
    assert loaded.dependencies == ["dep-1", "dep-2"]
    assert [
        (spec.task_id, spec.policy.value, spec.artifact_key)
        for spec in loaded.dependency_specs
    ] == [
        ("dep-1", "review_ready_ok", None),
        ("dep-2", "artifact_ready", "client_bundle"),
    ]


def test_sync_blueprint_copies_dependency_specs_to_tasks(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    blueprint = Blueprint(
        title="Typed Sync",
        project_key="TS",
        items=[
            BlueprintItem(
                id="BASE-1",
                title="Base task",
                description="base",
            ),
            BlueprintItem(
                id="APP-1",
                title="App task",
                description="app",
                dependency_specs=[
                    TaskDependency(
                        task_id="BASE-1",
                        policy=DependencyPolicy.REVIEW_READY_OK,
                    )
                ],
            ),
        ],
    )

    result = manager.sync_blueprint(blueprint)
    app_task = next(
        task for task in manager.list_tasks(result["project_id"])
        if task.blueprint_id == "APP-1"
    )

    assert app_task.dependencies
    assert len(app_task.dependency_specs) == 1
    assert app_task.dependency_specs[0].policy == DependencyPolicy.REVIEW_READY_OK
