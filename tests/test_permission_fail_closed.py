"""Permission checks deny when a policy cannot give an answer (SM-03)."""

from __future__ import annotations

import json
from typing import Any
from unittest.mock import Mock

import pytest

from penguin.security import agent_permissions, tool_permissions
from penguin.security.permission_engine import (
    Operation,
    PermissionEnforcer,
    PermissionMode,
    PermissionResult,
    PolicyEngine,
)
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor, ActionType, CodeActAction

ENV_NAME = "PENGUIN_TOOL_ALLOWLIST_JSON"


class _BrokenPolicy(PolicyEngine):
    """A policy whose evaluation always fails."""

    @property
    def name(self) -> str:
        return "broken"

    def check_operation(
        self, operation: Operation, resource: str, context: Any = None
    ) -> tuple[PermissionResult, str]:
        raise RuntimeError("policy backend unavailable")


def test_policy_that_raises_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PENGUIN_YOLO", raising=False)
    enforcer = PermissionEnforcer(mode=PermissionMode.WORKSPACE)
    enforcer.add_policy(_BrokenPolicy())

    assert enforcer.check(Operation.FILESYSTEM_WRITE, "notes.txt", {}) == (
        PermissionResult.DENY
    )


def test_agent_policy_that_raises_denies(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        agent_permissions, "get_agent_policy", lambda agent_id: _BrokenPolicy()
    )

    result, reason = tool_permissions._check_agent_permission(
        "agent", [Operation.FILESYSTEM_WRITE], "notes.txt", {}
    )

    assert result == PermissionResult.DENY
    assert "agent" in reason.lower()


def _restricted_executor(monkeypatch: pytest.MonkeyPatch) -> ActionExecutor:
    monkeypatch.setenv(ENV_NAME, '["read_file"]')
    manager = ToolManager({}, lambda *_args, **_kwargs: None, fast_startup=True)
    return ActionExecutor(manager, Mock())


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "action_type",
    # enhanced_read is an alias of the one allowlisted tool, read_file.
    [a for a in ActionType if a.value not in {"read_file", "enhanced_read"}],
    ids=lambda action: action.value,
)
async def test_restricted_startup_policy_covers_action_tags(
    monkeypatch: pytest.MonkeyPatch, action_type: ActionType
) -> None:
    executor = _restricted_executor(monkeypatch)

    result = await executor.execute_action(CodeActAction(action_type, ""))

    assert json.loads(result)["error"] == "tool_capability_denied"
