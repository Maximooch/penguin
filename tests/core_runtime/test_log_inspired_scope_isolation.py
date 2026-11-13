"""Replay scope-miss shapes without copying private conversation content."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.core_runtime.stream_events import finalize_streaming_message
from penguin.llm.stream_handler import AgentStreamingStateManager


@pytest.mark.parametrize("other_scope", ["other:default", "target:worker", "default"])
def test_scope_miss_never_consumes_another_conversation(other_scope: str) -> None:
    """A missing target must not borrow even the sole active stream."""
    manager = AgentStreamingStateManager()
    manager.handle_chunk("other conversation payload", agent_id=other_scope)
    persist = Mock(return_value=True)
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="default"),
        _stream_manager=manager,
        _runmode_stream_callback=None,
        _persist_finalized_message=persist,
    )
    result = finalize_streaming_message(
        owner,
        session_id="target",
        agent_id="default",
        logger=logging.getLogger(__name__),
    )
    assert result is None
    persist.assert_not_called()
    assert manager.get_agent_content(other_scope) == "other conversation payload"
    assert manager.is_agent_active(other_scope)


def test_interleaved_streams_keep_reasoning_content_and_finalize_separate() -> None:
    """Simulate overlapping agents and duplicate finalization after a retry."""
    manager = AgentStreamingStateManager()
    manager.handle_chunk("first ", agent_id="one:default")
    manager.handle_chunk("private reasoning", "two:worker", "reasoning")
    manager.handle_chunk("second", agent_id="two:worker")
    manager.handle_chunk("answer", agent_id="one:default")
    first, _ = manager.finalize("one:default")
    assert first.content == "first answer"
    assert first.reasoning == ""
    assert manager.is_agent_active("two:worker")
    duplicate, events = manager.finalize("one:default")
    assert duplicate is None
    assert events == []
    second, _ = manager.finalize("two:worker")
    assert second.content == "second"
    assert second.reasoning == "private reasoning"


@pytest.mark.parametrize("content", ["", " ", "\n\t"])
def test_reasoning_only_response_is_explicitly_empty(content: str) -> None:
    """Reasoning alone cannot masquerade as a usable assistant response."""
    manager = AgentStreamingStateManager()
    manager.handle_chunk("internal", "target:default", "reasoning")
    manager.handle_chunk(content, "target:default")
    message, _ = manager.finalize("target:default")
    assert message.was_empty
    assert message.metadata["was_empty"]
    assert message.reasoning == "internal"
