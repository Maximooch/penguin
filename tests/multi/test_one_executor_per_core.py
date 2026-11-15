"""Native tools, ActionXML tags and CLI commands share one agent executor.

Covers SM-83: outside an isolated runtime the tool manager made its own
``AgentExecutor``, while ActionXML spawn, stop and delegate and the CLI used
the global one, so a background agent started one way could not be waited
on, stopped or shut down the other way.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.multi import executor as executor_module
from penguin.multi.executor import get_executor
from penguin.tools.tool_manager import ToolManager
from penguin.utils.parser import ActionExecutor


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> ToolManager:
    monkeypatch.setattr(executor_module, "_executor_instance", None)
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    manager.set_core(SimpleNamespace(tool_manager=manager))
    return manager


def test_the_global_accessor_sees_the_tool_manager_executor(
    manager: ToolManager,
) -> None:
    executor = manager._get_agent_executor(create=True)

    assert get_executor() is executor


def test_the_tool_manager_adopts_an_executor_made_for_its_core(
    manager: ToolManager,
) -> None:
    made_by_actionxml = get_executor(manager._core)

    assert manager._get_agent_executor(create=True) is made_by_actionxml


def test_actionxml_uses_the_tool_manager_executor(manager: ToolManager) -> None:
    actions = ActionExecutor(manager, None, None)

    executor = actions._agent_executor(manager._core, create=True)

    assert executor is manager._get_agent_executor(create=False)
