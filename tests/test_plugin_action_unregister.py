"""Unloading a plugin removes its actions as well as its tools (SM-43)."""

from __future__ import annotations

from types import SimpleNamespace

from penguin.plugins.plugin_manager import PluginManager


def _plugin(name: str) -> SimpleNamespace:
    return SimpleNamespace(metadata=SimpleNamespace(name=name))


def test_unregistering_a_plugin_removes_only_its_actions() -> None:
    manager = PluginManager.__new__(PluginManager)
    mine, other = _plugin("mine"), _plugin("other")
    manager.tool_registry = {"mine_tool": mine, "other_tool": other}
    manager.action_registry = {"mine_action": mine, "other_action": other}

    manager._unregister_plugin_tools_and_actions(mine)

    assert manager.tool_registry == {"other_tool": other}
    assert manager.action_registry == {"other_action": other}
