"""Regression tests for Engine initialization order."""

from __future__ import annotations

from unittest.mock import MagicMock

from penguin.engine import Engine, EngineSettings


def test_engine_initializes_without_run_state_attribute_error() -> None:
    conversation_manager = MagicMock()
    api_client = MagicMock()
    tool_manager = MagicMock()
    action_executor = MagicMock()

    engine = Engine(
        EngineSettings(),
        conversation_manager,
        api_client,
        tool_manager,
        action_executor,
    )

    assert engine.current_agent_id is None
    assert engine.default_agent_id == "default"
    assert "default" in engine.agents
