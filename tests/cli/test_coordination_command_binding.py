"""Compatibility contracts for extracted coordination commands."""

from typer.testing import CliRunner

from penguin.cli import cli


def test_coordination_commands_remain_exported() -> None:
    for name in (
        "msg_to_agent",
        "msg_to_human",
        "msg_human_reply",
        "coord_spawn",
        "coord_destroy",
        "coord_register",
        "coord_send_role",
        "coord_broadcast",
        "coord_rr_workflow",
        "coord_role_chain",
    ):
        assert callable(getattr(cli, name))


def test_coordination_help_is_available_without_runtime_startup() -> None:
    runner = CliRunner()

    message_help = runner.invoke(cli.app, ["msg", "--help"])
    coordinator_help = runner.invoke(cli.app, ["coord", "--help"])

    assert message_help.exit_code == 0
    assert coordinator_help.exit_code == 0
    for command in ("to-agent", "to-human", "human-reply"):
        assert command in message_help.stdout
    for command in (
        "spawn",
        "destroy",
        "register",
        "send-role",
        "broadcast",
        "rr-workflow",
        "role-chain",
    ):
        assert command in coordinator_help.stdout
