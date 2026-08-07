"""Project command domain helpers."""

from __future__ import annotations

from typing import Any, Protocol

__all__ = [
    "AmbiguousProjectError",
    "ProjectNotFoundError",
    "resolve_project_identifier",
]


class ProjectNotFoundError(LookupError):
    """Raised when no exact project ID or name matches."""


class AmbiguousProjectError(LookupError):
    """Raised when an exact project name is not unique."""


class ProjectReader(Protocol):
    def get_project(self, project_id: str) -> Any: ...

    def get_project_by_name(self, name: str) -> Any: ...

    def list_projects(self) -> list[Any]: ...


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
