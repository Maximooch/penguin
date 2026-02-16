"""Tests for part event persistence callback wiring."""

from __future__ import annotations

import pytest

from penguin.tui_adapter.part_events import PartEventAdapter


class _EventBus:
    def __init__(self):
        self.events = []

    async def emit(self, event_name, payload):
        self.events.append((event_name, payload))


@pytest.mark.asyncio
async def test_part_adapter_invokes_persist_callback_before_emit():
    bus = _EventBus()
    persisted = []

    async def persist(event_type, properties):
        persisted.append((event_type, properties["id"]))

    adapter = PartEventAdapter(bus, persist_callback=persist)
    adapter.set_session("session_test")
    await adapter.on_user_message("hello")

    assert persisted
    assert persisted[0][0] == "message.updated"
    assert bus.events
    assert bus.events[0][0] == "opencode_event"
