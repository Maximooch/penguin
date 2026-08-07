"""Compatibility contracts for extracted config and permission commands."""

from unittest.mock import AsyncMock, patch

from typer.testing import CliRunner

from penguin.cli import cli


def test_config_and_permission_commands_remain_exported() -> None:
    for name in (
        "config_setup",
        "config_edit",
        "config_check",
        "config_test_routing",
        "config_debug",
        "permissions_list",
        "permissions_audit",
        "permissions_summary",
    ):
        assert callable(getattr(cli, name))


def test_config_and_permissions_help_are_provider_free() -> None:
    with patch.object(
        cli, "_initialize_core_components_globally", AsyncMock()
    ) as initialize:
        config_result = CliRunner().invoke(cli.app, ["config", "--help"])
        permissions_result = CliRunner().invoke(cli.app, ["permissions", "--help"])

    assert config_result.exit_code == 0
    assert permissions_result.exit_code == 0
    initialize.assert_not_awaited()
