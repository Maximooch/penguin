"""Project command domain helpers."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Protocol

__all__ = [
    "AmbiguousProjectError",
    "NoProjectTasksError",
    "NoReadyProjectTasksError",
    "ProjectMutationError",
    "ProjectNotFoundError",
    "ProjectStartPlan",
    "ProjectSummary",
    "delete_project_and_tasks",
    "list_project_summaries",
    "prepare_project_start",
    "resolve_project_identifier",
]


class ProjectNotFoundError(LookupError):
    """Raised when no exact project ID or name matches."""


class AmbiguousProjectError(LookupError):
    """Raised when an exact project name is not unique."""


class NoProjectTasksError(RuntimeError):
    """Raised when project execution is requested without tasks."""


class NoReadyProjectTasksError(RuntimeError):
    """Raised when no project task is currently executable."""


class ProjectMutationError(RuntimeError):
    """Raised when project persistence reports a failed mutation."""


@dataclass(frozen=True)
class ProjectSummary:
    project: Any
    task_count: int


@dataclass(frozen=True)
class ProjectStartPlan:
    project: Any
    tasks: list[Any]
    ready_tasks: list[Any]


class ProjectReader(Protocol):
    storage: Any

    def get_project(self, project_id: str) -> Any: ...

    def get_project_by_name(self, name: str) -> Any: ...

    def list_projects(self) -> list[Any]: ...

    async def list_projects_async(self) -> list[Any]: ...

    async def list_tasks_async(self, **kwargs: Any) -> list[Any]: ...

    async def get_ready_tasks_async(self, project_id: str) -> list[Any]: ...


def resolve_project_identifier(manager: ProjectReader, identifier: str) -> Any:
    """Resolve exact ID or unique exact name without terminal side effects."""

    project = manager.get_project(identifier)
    if project:
        return project
    project = manager.get_project_by_name(identifier)
    if project:
        return project
    matches = [item for item in manager.list_projects() if item.name == identifier]
    if len(matches) > 1:
        raise AmbiguousProjectError(identifier)
    raise ProjectNotFoundError(identifier)


async def list_project_summaries(manager: ProjectReader) -> list[ProjectSummary]:
    """List projects and task counts without serial N+1 latency."""

    projects = await manager.list_projects_async()
    task_lists = await asyncio.gather(
        *(manager.list_tasks_async(project_id=project.id) for project in projects)
    )
    return [
        ProjectSummary(project=project, task_count=len(tasks))
        for project, tasks in zip(projects, task_lists)
    ]


async def prepare_project_start(
    manager: ProjectReader, identifier: str
) -> ProjectStartPlan:
    """Resolve and validate a project before invoking RunMode."""

    project = resolve_project_identifier(manager, identifier)
    tasks = await manager.list_tasks_async(project_id=project.id)
    if not tasks:
        raise NoProjectTasksError(project.name)
    ready_tasks = await manager.get_ready_tasks_async(project.id)
    if not ready_tasks:
        raise NoReadyProjectTasksError(project.name)
    return ProjectStartPlan(project=project, tasks=tasks, ready_tasks=ready_tasks)


async def delete_project_and_tasks(manager: ProjectReader, project_id: str) -> None:
    """Delete project tasks before their owning project."""

    tasks = await manager.list_tasks_async(project_id=project_id)
    for task in tasks:
        if not manager.storage.delete_task(task.id):
            raise ProjectMutationError(f"Failed to delete task {task.id}")
    if not manager.storage.delete_project(project_id):
        raise ProjectMutationError(f"Failed to delete project {project_id}")
