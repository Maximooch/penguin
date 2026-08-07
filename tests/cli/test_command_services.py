"""Unit tests for terminal-independent project and task command services."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from penguin.cli.command_services import (
    AmbiguousProjectError,
    InvalidTaskStateError,
    ProjectNotFoundError,
    TaskMutationError,
    complete_task,
    create_task,
    delete_task,
    list_tasks,
    parse_task_status,
    resolve_project_identifier,
    start_task,
)
from penguin.project.models import TaskStatus


def test_parse_task_status_is_case_insensitive() -> None:
    assert parse_task_status(" RUNNING ") is TaskStatus.RUNNING
    assert parse_task_status(None) is None


def test_resolve_project_prefers_exact_id() -> None:
    project = SimpleNamespace(id="id", name="Demo")
    manager = SimpleNamespace(
        get_project=Mock(return_value=project),
        get_project_by_name=Mock(),
        list_projects=Mock(),
    )
    assert resolve_project_identifier(manager, "id") is project
    manager.get_project_by_name.assert_not_called()


def test_resolve_project_reports_ambiguity_and_missing() -> None:
    projects = [SimpleNamespace(name="Demo"), SimpleNamespace(name="Demo")]
    manager = SimpleNamespace(
        get_project=Mock(return_value=None),
        get_project_by_name=Mock(return_value=None),
        list_projects=Mock(return_value=projects),
    )
    with pytest.raises(AmbiguousProjectError):
        resolve_project_identifier(manager, "Demo")
    manager.list_projects.return_value = []
    with pytest.raises(ProjectNotFoundError):
        resolve_project_identifier(manager, "Missing")


@pytest.mark.asyncio
async def test_task_service_crud_and_status_projection() -> None:
    created = SimpleNamespace(id="task", status=TaskStatus.ACTIVE)
    manager = SimpleNamespace(
        create_task_async=AsyncMock(return_value=created),
        list_tasks_async=AsyncMock(return_value=[created]),
    )

    assert (
        await create_task(
            manager,
            project_id="project",
            title="Title",
            description=None,
            parent_task_id=None,
            priority=2,
        )
        is created
    )
    assert await list_tasks(manager, project_id="project", status="ACTIVE") == [
        created
    ]
    assert manager.create_task_async.await_args.kwargs["description"] == "Title"
    assert manager.list_tasks_async.await_args.kwargs["status"] is TaskStatus.ACTIVE


@pytest.mark.asyncio
async def test_task_transition_services_enforce_state_and_mutation_truth() -> None:
    pending_review = SimpleNamespace(
        id="task",
        status=TaskStatus.PENDING_REVIEW,
        approve=Mock(),
    )
    completed = SimpleNamespace(id="task", status=TaskStatus.COMPLETED)
    storage = SimpleNamespace(update_task=Mock(), delete_task=Mock(return_value=True))
    manager = SimpleNamespace(
        storage=storage,
        get_task_async=AsyncMock(side_effect=[pending_review, completed]),
        update_task_status=Mock(return_value=True),
    )

    original, updated, already_completed = await complete_task(manager, "task")
    assert (original, updated, already_completed) == (
        pending_review,
        completed,
        False,
    )
    pending_review.approve.assert_called_once_with("cli", notes="Approved via CLI")
    storage.update_task.assert_called_once_with(pending_review)

    manager.get_task_async = AsyncMock(return_value=pending_review)
    assert await delete_task(manager, "task") is pending_review
    storage.delete_task.assert_called_once_with("task")


@pytest.mark.asyncio
async def test_start_task_reports_failed_persistence() -> None:
    task = SimpleNamespace(id="task", status=TaskStatus.ACTIVE)
    manager = SimpleNamespace(
        get_task_async=AsyncMock(return_value=task),
        update_task_status=Mock(return_value=False),
    )

    with pytest.raises(TaskMutationError):
        await start_task(manager, "task")

    failed = SimpleNamespace(id="task", status=TaskStatus.FAILED)
    manager.get_task_async = AsyncMock(return_value=failed)
    with pytest.raises(InvalidTaskStateError):
        await complete_task(manager, "task")
