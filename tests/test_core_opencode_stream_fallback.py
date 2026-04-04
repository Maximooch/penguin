"""Regression tests for OpenCode stream fallback synthesis."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.core import PenguinCore
from penguin.tui_adapter.part_events import PartEventAdapter


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict]] = []

    async def emit(self, event_name: str, payload: dict) -> None:
        self.events.append((event_name, payload))


@pytest.mark.asyncio
async def test_on_tui_stream_chunk_synthesizes_final_content_when_no_delta() -> None:
    core = PenguinCore.__new__(PenguinCore)
    core._opencode_stream_states = {}
    core._opencode_message_adapters = {}
    core.model_config = SimpleNamespace(model="claude-3-7-sonnet", provider="anthropic")

    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_fallback")
    core._get_tui_adapter = lambda _session_id: adapter

    await PenguinCore._on_tui_stream_chunk(
        core,
        "stream_chunk",
        {
            "stream_id": "stream_1",
            "session_id": "session_fallback",
            "message_type": "assistant",
            "chunk": "",
            "is_final": True,
            "content": "fallback assistant text",
        },
    )

    emitted = [
        payload
        for event_name, payload in bus.events
        if event_name == "opencode_event"
        and payload.get("type") == "message.part.updated"
    ]
    deltas = [item.get("properties", {}).get("delta") for item in emitted]
    assert "fallback assistant text" in deltas

def test_finalize_streaming_message_loads_target_session_before_persisting() -> None:
    core = PenguinCore.__new__(PenguinCore)

    finalized_message = SimpleNamespace(
        role="assistant",
        content="scoped response",
        metadata={},
        was_empty=False,
        to_dict=lambda: {"content": "scoped response"},
    )
    core._stream_manager = SimpleNamespace(
        finalize=lambda agent_id: (finalized_message, []),
        get_active_agents=lambda: [],
    )

    load_calls: list[str] = []
    add_calls: list[dict[str, object]] = []
    save_calls: list[str] = []

    conversation = SimpleNamespace(
        session=SimpleNamespace(id="wrong-session"),
        load=lambda session_id: load_calls.append(session_id) or True,
        add_message=lambda **kwargs: add_calls.append(kwargs),
        save=lambda: save_calls.append("saved") or True,
    )
    core.conversation_manager = SimpleNamespace(
        current_agent_id="default",
        get_agent_conversation=lambda agent_id: conversation,
    )
    core._runmode_stream_callback = None
    core._filter_internal_markers_from_event = lambda data: data

    result = PenguinCore.finalize_streaming_message(
        core,
        agent_id="default",
        session_id="target-session",
        conversation_id="target-session",
    )

    assert result == {"content": "scoped response"}
    assert load_calls == ["target-session"]
    assert add_calls and add_calls[0]["content"] == "scoped response"
    assert save_calls == ["saved"]
