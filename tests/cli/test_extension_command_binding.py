"""Compatibility contracts for extracted Skills and MCP commands."""

from typer.testing import CliRunner

from penguin.cli import cli


def test_extension_commands_remain_exported() -> None:
    for name in (
        "mcp_status",
        "mcp_refresh",
        "mcp_reconnect",
        "mcp_close",
        "skill_list",
        "skill_show",
        "skill_activate",
        "skill_doctor",
    ):
        assert callable(getattr(cli, name))


def test_extension_group_help_is_available_without_runtime_startup() -> None:
    runner = CliRunner()
    assert runner.invoke(cli.app, ["skill", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["mcp", "--help"]).exit_code == 0
