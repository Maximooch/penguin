"""Compatibility contracts for extracted diagnostic commands."""

from typer.testing import CliRunner

from penguin.cli import cli


def test_diagnostic_commands_remain_exported() -> None:
    assert callable(cli.perf_test)
    assert callable(cli.profile)


def test_diagnostic_help_is_available_without_runtime_startup() -> None:
    runner = CliRunner()

    assert runner.invoke(cli.app, ["perf-test", "--help"]).exit_code == 0
    assert runner.invoke(cli.app, ["profile", "--help"]).exit_code == 0
