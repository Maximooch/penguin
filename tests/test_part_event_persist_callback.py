"""Tests for part event persistence callback wiring."""

from __future__ import annotations

import pytest

from penguin.tui_adapter.part_events import PartEventAdapter


class _EventBus:
    def __init__(self):
        self.events = []

    async def emit(self, event_name, payload):
        self.events.append((event_name, payload))


def _opencode_events(bus: _EventBus, event_type: str):
    return [
        payload["properties"]
        for event_name, payload in bus.events
        if event_name == "opencode_event" and payload.get("type") == event_type
    ]


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


@pytest.mark.asyncio
async def test_tool_only_lifecycle_balances_session_status_and_completes_message():
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_tool")

    part_id = await adapter.on_tool_start(
        "bash",
        {"command": "pwd"},
        tool_call_id="call_1",
    )
    await adapter.on_tool_end(part_id, "ok")

    status_events = _opencode_events(bus, "session.status")
    assert [item["status"]["type"] for item in status_events] == ["busy", "idle"]

    assistant_updates = [
        item
        for item in _opencode_events(bus, "message.updated")
        if item.get("role") == "assistant"
    ]
    assert assistant_updates
    assert assistant_updates[-1]["time"]["completed"] is not None


@pytest.mark.asyncio
async def test_adapter_abort_marks_running_tool_as_error_and_idles():
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_abort")

    await adapter.on_tool_start(
        "bash",
        {"command": "sleep 30"},
        tool_call_id="call_abort",
    )

    changed = await adapter.abort()
    assert changed is True

    status_events = _opencode_events(bus, "session.status")
    assert [item["status"]["type"] for item in status_events] == ["busy", "idle"]

    tool_updates = [
        item.get("part", {})
        for item in _opencode_events(bus, "message.part.updated")
        if item.get("part", {}).get("type") == "tool"
    ]
    assert tool_updates
    final_tool = tool_updates[-1]
    assert final_tool["state"]["status"] == "error"
    assert final_tool["state"]["error"] == "Tool execution was interrupted"
    assert final_tool["state"]["metadata"]["aborted"] is True


@pytest.mark.asyncio
async def test_tool_events_attach_to_completed_stream_message_when_available():
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_stream")

    message_id, part_id = await adapter.on_stream_start(agent_id="default")
    await adapter.on_stream_chunk(message_id, part_id, "hello", "assistant")
    await adapter.on_stream_end(message_id, part_id)

    tool_part_id = await adapter.on_tool_start(
        "bash",
        {"command": "pwd"},
        tool_call_id="call_2",
        message_id=message_id,
    )
    await adapter.on_tool_end(tool_part_id, "ok")

    tool_updates = _opencode_events(bus, "message.part.updated")
    tool_parts = [
        item.get("part", {})
        for item in tool_updates
        if item.get("part", {}).get("type") == "tool"
    ]
    assert tool_parts
    assert tool_parts[0]["messageID"] == message_id
