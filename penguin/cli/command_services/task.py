"""Task command domain helpers."""

from __future__ import annotations

from typing import Any, Protocol

from penguin.project.models import TaskStatus

__all__ = [
    "InvalidTaskStateError",
    "TaskMutationError",
    "TaskNotFoundError",
    "complete_task",
    "create_task",
    "delete_task",
    "list_tasks",
    "parse_task_status",
    "start_task",
]


class TaskNotFoundError(LookupError):
    """Raised when a requested task does not exist."""


class InvalidTaskStateError(ValueError):
    """Raised when a transition is invalid for the current task state."""


class TaskMutationError(RuntimeError):
    """Raised when task persistence reports a failed mutation."""


class TaskManager(Protocol):
    storage: Any

    async def create_task_async(self, **kwargs: Any) -> Any: ...

    async def list_tasks_async(self, **kwargs: Any) -> list[Any]: ...

    async def get_task_async(self, task_id: str) -> Any: ...

    def update_task_status(self, task_id: str, status: TaskStatus) -> bool: ...


def parse_task_status(value: str | None) -> TaskStatus | None:
    """Parse a case-insensitive task status or return ``None`` when unset."""

    if value is None:
        return None
    return TaskStatus(value.strip().lower())


async def create_task(
    manager: TaskManager,
    *,
    project_id: str,
    title: str,
    description: str | None,
    parent_task_id: str | None,
    priority: int,
) -> Any:
    """Create a task from typed command inputs."""

    return await manager.create_task_async(
        title=title,
        description=description or title,
        project_id=project_id,
        parent_task_id=parent_task_id,
        priority=priority,
    )


async def list_tasks(
    manager: TaskManager,
    *,
    project_id: str | None,
    status: str | None,
) -> list[Any]:
    """List tasks after normalizing the optional status selector."""

    return await manager.list_tasks_async(
        project_id=project_id,
        status=parse_task_status(status),
    )


async def start_task(manager: TaskManager, task_id: str) -> tuple[Any, Any]:
    """Move an existing task into the active state."""

    task = await manager.get_task_async(task_id)
    if not task:
        raise TaskNotFoundError(task_id)
    if not manager.update_task_status(task_id, TaskStatus.ACTIVE):
        raise TaskMutationError(f"Failed to start task {task_id}")
    return task, await manager.get_task_async(task_id)


async def complete_task(manager: TaskManager, task_id: str) -> tuple[Any, Any, bool]:
    """Approve a pending-review task, returning whether it was already complete."""

    task = await manager.get_task_async(task_id)
    if not task:
        raise TaskNotFoundError(task_id)
    if task.status == TaskStatus.COMPLETED:
        return task, task, True
    if task.status != TaskStatus.PENDING_REVIEW:
        raise InvalidTaskStateError(task.status.value)
    task.approve("cli", notes="Approved via CLI")
    manager.storage.update_task(task)
    return task, await manager.get_task_async(task_id), False


async def delete_task(manager: TaskManager, task_id: str) -> Any:
    """Delete an existing task and return its pre-delete representation."""

    task = await manager.get_task_async(task_id)
    if not task:
        raise TaskNotFoundError(task_id)
    if not manager.storage.delete_task(task_id):
        raise TaskMutationError(f"Failed to delete task {task_id}")
    return task
