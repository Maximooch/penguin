"""Unit tests for terminal-independent project and task command services."""

from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.cli.command_services import (
    AmbiguousProjectError,
    ProjectNotFoundError,
    parse_task_status,
    resolve_project_identifier,
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
