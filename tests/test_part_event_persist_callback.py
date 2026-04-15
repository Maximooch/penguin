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
async def test_part_adapter_user_message_preserves_supplied_message_id() -> None:
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_user_id")

    message_id = await adapter.on_user_message_with_metadata(
        "hello",
        message_id="msg_client_1",
        agent_id="build",
        model_id="gpt-5.4",
        provider_id="openai",
        variant="high",
    )

    assert message_id == "msg_client_1"

    user_updates = [
        item
        for item in _opencode_events(bus, "message.updated")
        if item.get("role") == "user"
    ]
    assert user_updates
    latest = user_updates[-1]
    assert latest["id"] == "msg_client_1"
    assert latest["agent"] == "build"
    assert latest["model"]["modelID"] == "gpt-5.4"
    assert latest["model"]["providerID"] == "openai"


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


@pytest.mark.asyncio
async def test_tool_only_turn_followed_by_stream_reuses_same_message() -> None:
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_reuse")

    tool_part_id = await adapter.on_tool_start(
        "read",
        {"filePath": "README.md"},
        tool_call_id="call_reuse",
    )
    await adapter.on_tool_end(tool_part_id, "ok")

    tool_parts = [
        item.get("part", {})
        for item in _opencode_events(bus, "message.part.updated")
        if item.get("part", {}).get("type") == "tool"
    ]
    assert tool_parts
    tool_message_id = tool_parts[-1]["messageID"]

    message_id, part_id = await adapter.on_stream_start(
        agent_id="default",
        model_id="gpt-5.4",
        provider_id="openai",
        variant="high",
    )
    assert message_id == tool_message_id

    await adapter.on_stream_chunk(message_id, part_id, "final answer", "assistant")
    await adapter.on_stream_end(message_id, part_id)

    assistant_updates = [
        item
        for item in _opencode_events(bus, "message.updated")
        if item.get("role") == "assistant" and item.get("id") == message_id
    ]
    assert assistant_updates
    assert assistant_updates[-1]["modelID"] == "gpt-5.4"
    assert assistant_updates[-1]["providerID"] == "openai"
    assert assistant_updates[-1]["variant"] == "high"

    text_parts = [
        item.get("part", {})
        for item in _opencode_events(bus, "message.part.updated")
        if item.get("part", {}).get("type") == "text"
    ]
    assert text_parts
    assert text_parts[-1]["messageID"] == message_id


@pytest.mark.asyncio
async def test_user_message_resets_tool_only_message_target() -> None:
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_turns")

    first_part_id = await adapter.on_tool_start(
        "bash",
        {"command": "pwd"},
        tool_call_id="call_first",
    )
    await adapter.on_tool_end(first_part_id, "ok")

    await adapter.on_user_message("next prompt")

    second_part_id = await adapter.on_tool_start(
        "bash",
        {"command": "ls"},
        tool_call_id="call_second",
    )
    await adapter.on_tool_end(second_part_id, "ok")

    tool_parts = [
        item.get("part", {})
        for item in _opencode_events(bus, "message.part.updated")
        if item.get("part", {}).get("type") == "tool"
    ]
    assert len(tool_parts) >= 2
    assert tool_parts[0]["messageID"] != tool_parts[-1]["messageID"]


@pytest.mark.asyncio
async def test_stream_start_emits_model_provider_and_variant() -> None:
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_model_meta")

    await adapter.on_stream_start(
        agent_id="default",
        model_id="z-ai/glm-5-turbo",
        provider_id="openrouter",
        variant="high",
    )

    assistant_updates = [
        item
        for item in _opencode_events(bus, "message.updated")
        if item.get("role") == "assistant"
    ]
    assert assistant_updates
    latest = assistant_updates[-1]
    assert latest["modelID"] == "z-ai/glm-5-turbo"
    assert latest["providerID"] == "openrouter"
    assert latest["variant"] == "high"


@pytest.mark.asyncio
async def test_update_assistant_usage_creates_missing_message_and_emits_update():
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_usage")

    await adapter.update_assistant_usage(
        "msg_usage_1",
        tokens={
            "input": 21,
            "output": 8,
            "reasoning": 3,
            "cache": {"read": 2, "write": 1},
        },
        cost=0.00042,
    )

    assistant_updates = [
        item
        for item in _opencode_events(bus, "message.updated")
        if item.get("role") == "assistant" and item.get("id") == "msg_usage_1"
    ]
    assert assistant_updates
    latest = assistant_updates[-1]
    assert latest["cost"] == pytest.approx(0.00042)
    assert latest["tokens"]["input"] == 21
    assert latest["tokens"]["output"] == 8
    assert latest["tokens"]["reasoning"] == 3
    assert latest["tokens"]["cache"]["read"] == 2
    assert latest["tokens"]["cache"]["write"] == 1


@pytest.mark.asyncio
async def test_stream_keeps_literal_action_tag_text_without_truncation():
    bus = _EventBus()
    adapter = PartEventAdapter(bus)
    adapter.set_session("session_literal")

    message_id, part_id = await adapter.on_stream_start(agent_id="default")
    await adapter.on_stream_chunk(
        message_id,
        part_id,
        "Use `<spawn_sub_agent>` as inline text. ",
        "assistant",
    )
    await adapter.on_stream_chunk(
        message_id,
        part_id,
        "Response should continue after the literal tag.",
        "assistant",
    )
    await adapter.on_stream_end(message_id, part_id)

    text_parts = [
        item.get("part", {})
        for item in _opencode_events(bus, "message.part.updated")
        if item.get("part", {}).get("type") == "text"
    ]
    assert text_parts
    final_text = text_parts[-1].get("text", "")
    assert "<spawn_sub_agent>" in final_text
    assert "Response should continue after the literal tag." in final_text


def test_part_adapter_ids_include_session_scope() -> None:
    bus = _EventBus()
    adapter_a = PartEventAdapter(bus)
    adapter_a.set_session("session-a")
    adapter_b = PartEventAdapter(bus)
    adapter_b.set_session("session-b")

    id_a = adapter_a._next_id("msg")
    id_b = adapter_b._next_id("msg")

    assert id_a != id_b
    assert "session_a" in id_a
    assert "session_b" in id_b
