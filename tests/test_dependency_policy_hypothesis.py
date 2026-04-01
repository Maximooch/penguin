from datetime import datetime
from tempfile import TemporaryDirectory

from hypothesis import given, strategies as st

from penguin.project.manager import ProjectManager
from penguin.project.models import (
    BlueprintItem,
    DependencyPolicy,
    Task,
    TaskDependency,
    TaskPhase,
    TaskStatus,
)


dependency_ids = st.lists(
    st.from_regex(r"[A-Z][A-Z0-9_-]{0,7}", fullmatch=True),
    min_size=0,
    max_size=5,
    unique=True,
)

task_statuses = st.sampled_from(list(TaskStatus))
task_phases = st.sampled_from(list(TaskPhase))


def make_task(task_id: str, status: TaskStatus, phase: TaskPhase) -> Task:
    now = datetime.utcnow().isoformat()
    return Task(
        id=task_id,
        title=task_id,
        description=task_id,
        status=status,
        phase=phase,
        created_at=now,
        updated_at=now,
    )


@given(dependency_ids)
def test_task_plain_dependencies_normalize_to_completion_required(dep_ids):
    task = Task(
        id="task-1",
        title="Example",
        description="Example",
        status=TaskStatus.ACTIVE,
        phase=TaskPhase.PENDING,
        created_at="2025-01-01T00:00:00",
        updated_at="2025-01-01T00:00:00",
        dependencies=dep_ids,
    )

    assert task.dependencies == dep_ids
    assert [spec.task_id for spec in task.dependency_specs] == dep_ids
    assert all(
        spec.policy == DependencyPolicy.COMPLETION_REQUIRED
        for spec in task.dependency_specs
    )


@given(dependency_ids)
def test_blueprint_item_plain_dependencies_normalize_to_completion_required(dep_ids):
    item = BlueprintItem(
        id="ITEM-1",
        title="Item",
        description="Item",
        depends_on=dep_ids,
    )

    assert item.depends_on == dep_ids
    assert [spec.task_id for spec in item.dependency_specs] == dep_ids
    assert all(
        spec.policy == DependencyPolicy.COMPLETION_REQUIRED
        for spec in item.dependency_specs
    )


@given(task_statuses, task_phases)
def test_completion_required_only_unlocks_completed(status, phase):
    with TemporaryDirectory() as tmpdir:
        manager = ProjectManager(tmpdir)
        dependency = TaskDependency(
            task_id="dep-1",
            policy=DependencyPolicy.COMPLETION_REQUIRED,
        )
        dependency_task = make_task("dep-1", status=status, phase=phase)

        satisfied = manager._is_dependency_satisfied(dependency, dependency_task)

        assert satisfied is (status == TaskStatus.COMPLETED)


@given(task_statuses, task_phases)
def test_review_ready_ok_requires_done_and_review_or_completed(status, phase):
    with TemporaryDirectory() as tmpdir:
        manager = ProjectManager(tmpdir)
        dependency = TaskDependency(
            task_id="dep-1",
            policy=DependencyPolicy.REVIEW_READY_OK,
        )
        dependency_task = make_task("dep-1", status=status, phase=phase)

        satisfied = manager._is_dependency_satisfied(dependency, dependency_task)

        expected = phase == TaskPhase.DONE and status in {
            TaskStatus.PENDING_REVIEW,
            TaskStatus.COMPLETED,
        }
        assert satisfied is expected


@given(task_statuses, task_phases)
def test_artifact_ready_fails_closed_until_evidence_support_exists(status, phase):
    with TemporaryDirectory() as tmpdir:
        manager = ProjectManager(tmpdir)
        dependency = TaskDependency(
            task_id="dep-1",
            policy=DependencyPolicy.ARTIFACT_READY,
            artifact_key="client_bundle",
        )
        dependency_task = make_task("dep-1", status=status, phase=phase)

        assert manager._is_dependency_satisfied(dependency, dependency_task) is False
