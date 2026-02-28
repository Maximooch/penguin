"""Regression tests for Engine initialization order."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
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


def test_finalize_streaming_response_persists_non_chunk_output() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    conversation = SimpleNamespace(
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    core = SimpleNamespace(finalize_streaming_message=MagicMock(return_value=None))
    cm = SimpleNamespace(
        conversation=conversation,
        core=core,
        get_current_session=MagicMock(return_value=SimpleNamespace(id="session_1")),
    )

    result = engine._finalize_streaming_response(
        cast(Any, cm),
        "[Error: Model rejected image input]",
        streaming=True,
        agent_id="default",
    )

    assert result == "[Error: Model rejected image input]"
    conversation.add_assistant_message.assert_called_once_with(
        "[Error: Model rejected image input]"
    )


def test_finalize_streaming_response_uses_finalized_content_without_duplicate_save() -> (
    None
):
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    conversation = SimpleNamespace(
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    core = SimpleNamespace(
        finalize_streaming_message=MagicMock(
            return_value={"content": "streamed answer"}
        )
    )
    cm = SimpleNamespace(
        conversation=conversation,
        core=core,
        get_current_session=MagicMock(return_value=SimpleNamespace(id="session_1")),
    )

    result = engine._finalize_streaming_response(
        cast(Any, cm),
        "fallback answer",
        streaming=True,
        agent_id="default",
    )

    assert result == "streamed answer"
    conversation.add_assistant_message.assert_not_called()
