"""CLI version output regression tests."""

from click.testing import CliRunner
from typer.main import get_command

from penguin._version import __version__
from penguin.cli.cli import app


def test_cli_version_matches_package_version() -> None:
    """Report the package version instead of a stale placeholder."""
    result = CliRunner().invoke(get_command(app), ["--version"])

    assert result.exit_code == 0
    assert result.output.strip() == f"Penguin {__version__}"
