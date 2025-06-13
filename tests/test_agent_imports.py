"""Smoke-test public agent runtime symbols are importable."""

import inspect

import penguin.agent as agent_pkg  # noqa: WPS433


def test_runtime_symbols_present():
    expected = {"AgentConfig", "BaseAgent", "AgentLauncher"}
    for symbol in expected:
        assert hasattr(agent_pkg, symbol), f"{symbol} missing in penguin.agent"
        obj = getattr(agent_pkg, symbol)
        assert inspect.isclass(obj) or inspect.isfunction(obj), f"Bad type for {symbol}: {type(obj)}" 