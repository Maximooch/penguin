from datetime import datetime
from pathlib import Path

from penguin.project.manager import ProjectManager
from penguin.project.models import (
    ArtifactEvidence,
    DependencyPolicy,
    Task,
    TaskDependency,
    TaskPhase,
    TaskStatus,
)


def make_task(task_id: str, **overrides) -> Task:
    base = {
        "id": task_id,
        "title": task_id,
        "description": task_id,
        "status": TaskStatus.ACTIVE,
        "phase": TaskPhase.PENDING,
        "created_at": datetime.utcnow().isoformat(),
        "updated_at": datetime.utcnow().isoformat(),
    }
    base.update(overrides)
    return Task(**base)


def test_task_normalizes_artifact_evidence_dicts():
    task = make_task(
        "task-1",
        artifact_evidence=[
            {
                "key": "generated_client",
                "kind": "file",
                "path": "artifacts/client.json",
                "producer_task_id": "task-1",
                "created_at": "2026-04-01T12:00:00Z",
                "valid": True,
            }
        ],
    )

    assert len(task.artifact_evidence) == 1
    artifact = task.artifact_evidence[0]
    assert artifact.key == "generated_client"
    assert artifact.kind == "file"
    assert artifact.path == "artifacts/client.json"
    assert artifact.valid is True


def test_storage_persists_artifact_evidence(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    task = make_task(
        "task-1",
        status=TaskStatus.COMPLETED,
        phase=TaskPhase.DONE,
        artifact_evidence=[
            ArtifactEvidence(
                key="generated_client",
                kind="file",
                path="artifacts/client.json",
                producer_task_id="task-1",
                created_at="2026-04-01T12:00:00Z",
                valid=True,
            )
        ],
    )
    manager.storage.create_task(task)

    loaded = manager.storage.get_task(task.id)

    assert loaded is not None
    assert len(loaded.artifact_evidence) == 1
    assert loaded.artifact_evidence[0].key == "generated_client"


def test_artifact_ready_dependency_unlocks_when_valid_artifact_exists(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Artifacts", "artifact-ready")

    dep = make_task(
        "dep-1",
        project_id=project.id,
        status=TaskStatus.COMPLETED,
        phase=TaskPhase.DONE,
        artifact_evidence=[
            ArtifactEvidence(
                key="generated_client",
                kind="file",
                path="artifacts/client.json",
                producer_task_id="dep-1",
                created_at="2026-04-01T12:00:00Z",
                valid=True,
            )
        ],
    )
    task = make_task(
        "task-1",
        project_id=project.id,
        dependencies=["dep-1"],
        dependency_specs=[
            TaskDependency(
                task_id="dep-1",
                policy=DependencyPolicy.ARTIFACT_READY,
                artifact_key="generated_client",
            )
        ],
    )

    manager.storage.create_task(dep)
    manager.storage.create_task(task)

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert manager._is_task_blocked(loaded) is False


def test_artifact_ready_dependency_stays_blocked_for_invalid_or_wrong_artifact(tmp_path: Path):
    manager = ProjectManager(tmp_path)
    project = manager.create_project("Artifacts", "artifact-invalid")

    dep = make_task(
        "dep-1",
        project_id=project.id,
        status=TaskStatus.COMPLETED,
        phase=TaskPhase.DONE,
        artifact_evidence=[
            ArtifactEvidence(
                key="other_key",
                kind="file",
                path="artifacts/client.json",
                producer_task_id="dep-1",
                created_at="2026-04-01T12:00:00Z",
                valid=True,
            ),
            ArtifactEvidence(
                key="generated_client",
                kind="file",
                path="artifacts/bad.json",
                producer_task_id="dep-1",
                created_at="2026-04-01T12:00:00Z",
                valid=False,
            ),
        ],
    )
    task = make_task(
        "task-1",
        project_id=project.id,
        dependencies=["dep-1"],
        dependency_specs=[
            TaskDependency(
                task_id="dep-1",
                policy=DependencyPolicy.ARTIFACT_READY,
                artifact_key="generated_client",
            )
        ],
    )

    manager.storage.create_task(dep)
    manager.storage.create_task(task)

    loaded = manager.get_task(task.id)
    assert loaded is not None
    assert manager._is_task_blocked(loaded) is True
