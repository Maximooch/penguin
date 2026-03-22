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
