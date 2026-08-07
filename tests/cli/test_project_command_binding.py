"""Compatibility contracts for extracted project and task commands."""

from typer.testing import CliRunner

from penguin.cli import cli


def test_project_and_task_commands_remain_exported() -> None:
    for name in (
        "project_init",
        "project_create",
        "project_list",
        "project_delete",
        "project_start",
        "project_run",
        "task_create",
        "task_list",
        "task_start",
        "task_complete",
        "task_delete",
    ):
        assert callable(getattr(cli, name))


def test_project_group_help_is_available_without_runtime_startup() -> None:
    runner = CliRunner()

    project_help = runner.invoke(cli.app, ["project", "--help"])
    task_help = runner.invoke(cli.app, ["project", "task", "--help"])

    assert project_help.exit_code == 0
    assert task_help.exit_code == 0
    for command in ("init", "create", "list", "delete", "start", "run", "task"):
        assert command in project_help.stdout
    for command in ("create", "list", "start", "complete", "delete"):
        assert command in task_help.stdout
