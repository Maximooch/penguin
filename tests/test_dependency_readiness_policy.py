from datetime import datetime
from pathlib import Path

from penguin.project.manager import ProjectManager
from penguin.project.models import (
    DependencyPolicy,
    Task,
    TaskDependency,
    TaskPhase,
    TaskStatus,
)


def make_task(task_id: str, title: str, **overrides) -> Task:
    base = {
        "id": task_id,
        "title": title,
        "description": title,
        "status": TaskStatus.ACTIVE,
        "phase": TaskPhase.PENDING,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    base.update(overrides)
    return Task(**base)


def test_pending_review_dependency_keeps_task_blocked(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Deps", "Policy test")

    dep = make_task(
        "dep-1",
        "Dependency",
        project_id=project.id,
        status=TaskStatus.PENDING_REVIEW,
        phase=TaskPhase.DONE,
    )
    task = make_task(
        "task-1",
        "Dependent",
        project_id=project.id,
        dependencies=["dep-1"],
    )

    manager.storage.create_task(dep)
    manager.storage.create_task(task)

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert manager._is_task_blocked(loaded) is True


def test_get_ready_tasks_requires_completed_dependencies_not_pending_review(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Deps", "Ready policy")

    dep_review = make_task(
        "dep-review",
        "Dependency Review",
        project_id=project.id,
        status=TaskStatus.PENDING_REVIEW,
        phase=TaskPhase.DONE,
    )
    dep_done = make_task(
        "dep-complete",
        "Dependency Complete",
        project_id=project.id,
        status=TaskStatus.COMPLETED,
        phase=TaskPhase.DONE,
    )
    blocked = make_task(
        "task-blocked",
        "Blocked",
        project_id=project.id,
        dependencies=["dep-review"],
    )
    ready = make_task(
        "task-ready",
        "Ready",
        project_id=project.id,
        dependencies=["dep-complete"],
    )

    for task in [dep_review, dep_done, blocked, ready]:
        manager.storage.create_task(task)

    ready_tasks = manager.get_ready_tasks(project.id)
    ready_ids = {task.id for task in ready_tasks}

    assert "task-ready" in ready_ids
    assert "task-blocked" not in ready_ids

def test_review_ready_ok_dependency_unblocks_task(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Deps", "Review-ready policy")

    dep = make_task(
        "dep-review",
        "Dependency Review",
        project_id=project.id,
        status=TaskStatus.PENDING_REVIEW,
        phase=TaskPhase.DONE,
    )
    task = make_task(
        "task-review-ok",
        "Review OK",
        project_id=project.id,
        dependencies=["dep-review"],
        dependency_specs=[
            TaskDependency(
                task_id="dep-review",
                policy=DependencyPolicy.REVIEW_READY_OK,
            )
        ],
    )

    manager.storage.create_task(dep)
    manager.storage.create_task(task)

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert manager._is_task_blocked(loaded) is False

    ready_ids = {ready_task.id for ready_task in manager.get_ready_tasks(project.id)}
    assert "task-review-ok" in ready_ids


def test_artifact_ready_dependency_fails_closed_without_artifact_support(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Deps", "Artifact-ready policy")

    dep = make_task(
        "dep-artifact",
        "Dependency Artifact",
        project_id=project.id,
        status=TaskStatus.COMPLETED,
        phase=TaskPhase.DONE,
    )
    task = make_task(
        "task-artifact",
        "Artifact gated",
        project_id=project.id,
        dependencies=["dep-artifact"],
        dependency_specs=[
            TaskDependency(
                task_id="dep-artifact",
                policy=DependencyPolicy.ARTIFACT_READY,
                artifact_key="client_bundle",
            )
        ],
    )

    manager.storage.create_task(dep)
    manager.storage.create_task(task)

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert manager._is_task_blocked(loaded) is True

    ready_ids = {ready_task.id for ready_task in manager.get_ready_tasks(project.id)}
    assert "task-artifact" not in ready_ids
