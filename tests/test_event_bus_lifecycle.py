"""Regression tests for UI lifecycle event delivery."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.cli.events import EventBus


@pytest.mark.asyncio
async def test_action_result_events_are_not_deduplicated_without_content() -> None:
    bus = EventBus()
    received: list[dict[str, Any]] = []

    async def handler(_event_type: str, data: dict[str, Any]) -> None:
        received.append(data)

    bus.subscribe("action_result", handler)

    await bus.emit(
        "action_result",
        {"id": "call_child", "action": "read_file", "status": "completed"},
    )
    await bus.emit(
        "action_result",
        {
            "id": "call_parent",
            "action": "ordered_tool_batch",
            "status": "completed",
        },
    )

    assert [item["id"] for item in received] == ["call_child", "call_parent"]


@pytest.mark.asyncio
async def test_action_events_are_not_deduplicated_without_content() -> None:
    bus = EventBus()
    received: list[dict[str, Any]] = []

    async def handler(_event_type: str, data: dict[str, Any]) -> None:
        received.append(data)

    bus.subscribe("action", handler)

    await bus.emit("action", {"id": "call_parent", "action": "ordered_tool_batch"})
    await bus.emit("action", {"id": "call_child", "action": "read_file"})

    assert [item["id"] for item in received] == ["call_parent", "call_child"]
