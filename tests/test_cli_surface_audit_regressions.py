from datetime import datetime

import click
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, patch

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
    streaming_display = SimpleNamespace(is_active=False, set_status=Mock(), clear_status=Mock())
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

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), \
         patch.object(cli_module, "_core", core), \
         patch.object(cli_module, "console") as console_mock:
        cli_module.task_list(project_id="project-1", status="RUNNING")

    core.project_manager.list_tasks_async.assert_awaited_once()
    _, kwargs = core.project_manager.list_tasks_async.await_args
    assert kwargs["project_id"] == "project-1"
    assert kwargs["status"] == TaskStatus.RUNNING
    assert not console_mock.print.call_args_list or all(
        "Invalid status" not in str(call.args[0]) for call in console_mock.print.call_args_list if call.args
    )

    with patch.object(cli_module, "_initialize_core_components_globally", AsyncMock()), \
         patch.object(cli_module, "_core", core), \
         patch.object(cli_module, "console") as console_mock:
        with pytest.raises(click.exceptions.Exit):
            cli_module.task_list(project_id=None, status="not-a-status")

    printed = " ".join(str(call.args[0]) for call in console_mock.print.call_args_list if call.args)
    assert TaskStatus.PENDING_REVIEW.value in printed
    assert TaskStatus.RUNNING.value in printed
