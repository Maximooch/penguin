from datetime import datetime
import importlib
import os
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

import click
from click.testing import CliRunner
import pytest

from penguin.cli.event_manager import EventManager
from penguin.cli.interface import PenguinInterface
from penguin.project.models import Project, Task, TaskPhase, TaskStatus


def make_task(task_id: str, status: TaskStatus) -> Task:
    now = datetime.utcnow().isoformat()
    return Task(
        id=task_id,
        title=f"Task {task_id}",
        description="Task description",
        status=status,
        phase=TaskPhase.IMPLEMENT if status != TaskStatus.PENDING_REVIEW else TaskPhase.DONE,
        created_at=now,
        updated_at=now,
        project_id="project-1",
        metadata={},
    )


def make_project() -> Project:
    now = datetime.utcnow().isoformat()
    return Project(
        id="project-1",
        name="Project 1",
        description="Project description",
        created_at=now,
        updated_at=now,
        status="active",
    )


@pytest.mark.asyncio
async def test_project_status_summary_counts_lowercase_task_status_values():
    project = make_project()
    tasks = [
        make_task("task-1", TaskStatus.ACTIVE),
        make_task("task-2", TaskStatus.COMPLETED),
        make_task("task-3", TaskStatus.FAILED),
    ]
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_project_async=AsyncMock(return_value=project),
            list_tasks_async=AsyncMock(return_value=tasks),
        )
    )
    interface = PenguinInterface(core)

    result = await interface._handle_project_command(["status", "project-1"])

    summary = result["project"]["task_summary"]
    assert summary["total"] == 3
    assert summary["active"] == 1
    assert summary["completed"] == 1
    assert summary["failed"] == 1


def test_event_manager_surfaces_clarification_answered_status():
    display_manager = SimpleNamespace(display_message=Mock())
    streaming_display = SimpleNamespace(
        is_active=False,
        set_status=Mock(),
        clear_status=Mock(),
    )
    streaming_manager = SimpleNamespace(
        finalize_streaming=Mock(),
        _active_stream_id=None,
        is_streaming=False,
    )
    cli = SimpleNamespace(
        display_manager=display_manager,
        streaming_display=streaming_display,
        streaming_manager=streaming_manager,
        run_mode_active=False,
        run_mode_status="",
    )
    manager = EventManager(cli)

    manager.handle_status_event(
        "status",
        {
            "status_type": "clarification_answered",
            "data": {
                "task_id": "task-1",
                "answer": "Use rotating refresh tokens",
            },
        },
    )

    assert cli.run_mode_active is True
    assert "Clarification answered" in cli.run_mode_status
    display_manager.display_message.assert_called_once()
    message, level = display_manager.display_message.call_args.args
    assert "Use rotating refresh tokens" in message
    assert level == "system"


def test_task_list_accepts_uppercase_status_filter_and_shows_real_options():
    from penguin.cli import cli as cli_module

    task = make_task("task-1", TaskStatus.RUNNING)
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            list_tasks_async=AsyncMock(return_value=[task]),
        )
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.object(cli_module, "console") as console_mock:
        cli_module.task_list(project_id="project-1", status="RUNNING")

    core.project_manager.list_tasks_async.assert_awaited_once()
    _, kwargs = core.project_manager.list_tasks_async.await_args
    assert kwargs["project_id"] == "project-1"
    assert kwargs["status"] == TaskStatus.RUNNING
    assert not console_mock.print.call_args_list or all(
        "Invalid status" not in str(call.args[0])
        for call in console_mock.print.call_args_list
        if call.args
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.object(cli_module, "console") as console_mock:
        with pytest.raises(click.exceptions.Exit):
            cli_module.task_list(project_id=None, status="not-a-status")

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert TaskStatus.PENDING_REVIEW.value in printed
    assert TaskStatus.RUNNING.value in printed


def test_task_start_reports_active_state_honestly():
    from penguin.cli import cli as cli_module

    task = make_task("task-1", TaskStatus.RUNNING)
    updated_task = make_task("task-1", TaskStatus.ACTIVE)
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(side_effect=[task, updated_task]),
            update_task_status=Mock(return_value=True),
        )
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.object(cli_module, "console") as console_mock:
        cli_module.task_start("task-1")

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert "active state" in printed.lower()
    assert "running" not in printed.lower()


def test_task_complete_docstring_and_message_reflect_review_approval():
    from penguin.cli import cli as cli_module

    task = make_task("task-1", TaskStatus.PENDING_REVIEW)
    updated_task = make_task("task-1", TaskStatus.COMPLETED)
    task.approve = Mock()
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            get_task_async=AsyncMock(side_effect=[task, updated_task]),
            storage=SimpleNamespace(update_task=Mock()),
        )
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.object(cli_module, "console") as console_mock:
        cli_module.task_complete("task-1")

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert "approved" in printed.lower()
    assert "bypass" not in (cli_module.task_complete.__doc__ or "").lower()
    assert "pending review" in (cli_module.task_complete.__doc__ or "").lower()


def test_preconfigure_cli_environment_clears_stale_root_hints(tmp_path, monkeypatch):
    config_module = importlib.import_module("penguin.config")
    from penguin.cli import cli as cli_module

    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    stale_project_root = tmp_path / "stale-project"
    stale_project_root.mkdir()

    monkeypatch.chdir(repo_root)
    monkeypatch.setenv("PENGUIN_CWD", str(stale_project_root))
    monkeypatch.setenv("PENGUIN_PROJECT_ROOT", str(stale_project_root))
    monkeypatch.setenv("PENGUIN_WRITE_ROOT", "project")

    original_cli_workspace = cli_module.WORKSPACE_PATH
    original_config_workspace = config_module.WORKSPACE_PATH
    try:
        resolved_project_path, resolved_workspace = cli_module._preconfigure_cli_environment(
            workspace=workspace,
            project=None,
            root=None,
        )

        assert resolved_project_path is None
        assert resolved_workspace == workspace.resolve()
        assert os.environ["PENGUIN_CWD"] == str(repo_root.resolve())
        assert os.environ["PENGUIN_WORKSPACE"] == str(workspace.resolve())
        assert os.environ["PENGUIN_WRITE_ROOT"] == "project"
        assert "PENGUIN_PROJECT_ROOT" not in os.environ
        assert cli_module.WORKSPACE_PATH == workspace.resolve()
        assert config_module.WORKSPACE_PATH == workspace.resolve()
    finally:
        cli_module.WORKSPACE_PATH = original_cli_workspace
        config_module.WORKSPACE_PATH = original_config_workspace


def test_project_create_honors_explicit_workspace_path(tmp_path):
    from penguin.cli import cli as cli_module

    explicit_workspace = (tmp_path / "explicit-workspace").resolve()
    project = Project(
        id="project-1",
        name="Project 1",
        description="Project description",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        status="active",
        workspace_path=explicit_workspace,
        context_path=explicit_workspace / "context",
    )
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            create_project_async=AsyncMock(return_value=project),
        )
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.dict(os.environ, {"PENGUIN_CWD": str(tmp_path / "repo-root")}, clear=False), patch.object(
        cli_module, "console"
    ) as console_mock:
        cli_module.project_create(
            name="Project 1",
            description="Project description",
            workspace_path=str(explicit_workspace),
        )

    core.project_manager.create_project_async.assert_awaited_once()
    _, kwargs = core.project_manager.create_project_async.await_args
    assert kwargs["workspace_path"] == explicit_workspace

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert "Workspace (explicit):" in printed
    assert str(explicit_workspace) in printed
    assert "Execution root:" in printed


def test_project_create_reports_default_workspace_honestly(tmp_path):
    from penguin.cli import cli as cli_module

    default_workspace = (tmp_path / "managed-root" / "projects" / "project-1").resolve()
    project = Project(
        id="project-1",
        name="Project 1",
        description="Project description",
        created_at=datetime.utcnow().isoformat(),
        updated_at=datetime.utcnow().isoformat(),
        status="active",
        workspace_path=default_workspace,
        context_path=default_workspace / "context",
    )
    core = SimpleNamespace(
        project_manager=SimpleNamespace(
            create_project_async=AsyncMock(return_value=project),
        )
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), patch.object(
        cli_module, "_core", core
    ), patch.dict(os.environ, {"PENGUIN_CWD": str(tmp_path / "repo-root")}, clear=False), patch.object(
        cli_module, "console"
    ) as console_mock:
        cli_module.project_create(
            name="Project 1",
            description="Project description",
            workspace_path=None,
        )

    _, kwargs = core.project_manager.create_project_async.await_args
    assert kwargs["workspace_path"] is None

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert "Workspace (default):" in printed
    assert str(default_workspace) in printed
    assert "Execution root:" in printed


