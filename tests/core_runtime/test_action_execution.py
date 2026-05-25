"""Tests for core action execution result shaping."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import action_execution


class _ActionExecutor:
    def __init__(self, result: Any = None, error: Exception | None = None) -> None:
        self.result = result
        self.error = error
        self.calls: list[Any] = []

    async def execute_action(self, action: Any) -> Any:
        self.calls.append(action)
        if self.error is not None:
            raise self.error
        return self.result


def _action(name: str = "execute") -> SimpleNamespace:
    return SimpleNamespace(action_type=SimpleNamespace(value=name))


@pytest.mark.asyncio
async def test_execute_action_returns_completed_payload() -> None:
    action = _action("code_execution")
    executor = _ActionExecutor(result=13)
    owner = SimpleNamespace(action_executor=executor)

    result = await action_execution.execute_action(owner, action)

    assert result == {
        "action": "code_execution",
        "result": "13",
        "status": "completed",
    }
    assert executor.calls == [action]


@pytest.mark.asyncio
async def test_execute_action_returns_empty_string_for_none_result() -> None:
    action = _action("noop")
    owner = SimpleNamespace(action_executor=_ActionExecutor(result=None))

    result = await action_execution.execute_action(owner, action)

    assert result == {
        "action": "noop",
        "result": "",
        "status": "completed",
    }


@pytest.mark.asyncio
async def test_execute_action_logs_and_returns_error_payload() -> None:
    action = _action("edit_file")
    logs: list[tuple[Exception, dict[str, Any]]] = []
    owner = SimpleNamespace(
        action_executor=_ActionExecutor(error=RuntimeError("boom")),
    )

    result = await action_execution.execute_action(
        owner,
        action,
        log_error=lambda exc, context: logs.append((exc, context)),
    )

    assert result == {
        "action": "edit_file",
        "result": "Error: boom",
        "status": "error",
    }
    assert len(logs) == 1
    exc, context = logs[0]
    assert isinstance(exc, RuntimeError)
    assert context == {
        "component": "core",
        "method": "execute_action",
        "action": "edit_file",
    }


@pytest.mark.asyncio
async def test_execute_action_handles_string_action_type() -> None:
    action = SimpleNamespace(action_type="custom")
    owner = SimpleNamespace(action_executor=_ActionExecutor(result="ok"))

    result = await action_execution.execute_action(owner, action)

    assert result["action"] == "custom"
    assert result["result"] == "ok"
