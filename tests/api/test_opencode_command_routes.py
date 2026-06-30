"""Tests for OpenCode-compatible command registry routes."""

from __future__ import annotations

import pytest

from penguin.web.routes import api_command_list
from penguin.web.services.command_registry import list_opencode_commands


def test_list_opencode_commands_exposes_penguin_metadata() -> None:
    commands = list_opencode_commands()

    by_name = {command["name"]: command for command in commands}
    assert {"config", "thinking", "project", "project-start", "task-execute"} <= set(
        by_name
    )
    assert by_name["project"]["template"] == "/project $ARGUMENTS"
    assert by_name["project"]["execution"]["route"] == "/api/v1/projects"
    assert by_name["task-execute"]["requiresSession"] is True
    assert "session" in by_name["task-execute"]["requiredContext"]


@pytest.mark.asyncio
async def test_api_command_list_returns_registry_payload() -> None:
    commands = await api_command_list()

    assert isinstance(commands, list)
    assert commands[0]["name"] == "config"
    assert all(command["source"] == "command" for command in commands)
