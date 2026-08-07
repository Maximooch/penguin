"""Compatibility contracts for extracted agent command registration."""

from typer.testing import CliRunner

from penguin.cli import cli


def test_agent_commands_remain_exported_from_cli_facade() -> None:
    for name in (
        "agent_personas",
        "agent_list",
        "agent_spawn",
        "agent_set_persona",
        "agent_pause",
        "agent_resume",
        "agent_activate",
        "agent_status",
        "agent_tree",
        "agent_tasks",
        "agent_info",
    ):
        assert callable(getattr(cli, name))


def test_agent_group_help_preserves_public_commands() -> None:
    result = CliRunner().invoke(cli.app, ["agent", "--help"])

    assert result.exit_code == 0
    for command in ("personas", "list", "spawn", "status", "tree", "tasks", "info"):
        assert command in result.stdout
