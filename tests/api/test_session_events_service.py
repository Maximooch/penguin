"""Tests for OpenCode-compatible session event service helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.web.services.session_events import (
    emit_session_created_event,
    emit_session_deleted_event,
    emit_session_diff_event,
    emit_session_event,
    emit_session_updated_event,
)


class _EventBus:
    def __init__(self, *, fail: bool = False) -> None:
        self.fail = fail
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        if self.fail:
            raise RuntimeError("event bus unavailable")
        self.events.append((event_type, payload))


@pytest.mark.asyncio
async def test_emit_session_lifecycle_event_shapes_payload() -> None:
    event_bus = _EventBus()
    core = SimpleNamespace(event_bus=event_bus)
    info = {"id": "session_1", "title": "Session"}

    await emit_session_created_event(core, info)

    assert event_bus.events == [
        (
            "opencode_event",
            {
                "type": "session.created",
                "properties": {
                    "sessionID": "session_1",
                    "info": info,
                },
            },
        )
    ]


@pytest.mark.asyncio
async def test_emit_session_lifecycle_event_omits_blank_session_id() -> None:
    event_bus = _EventBus()
    core = SimpleNamespace(event_bus=event_bus)

    await emit_session_updated_event(core, {"id": "", "title": "Session"})

    _event_type, payload = event_bus.events[-1]
    assert payload["type"] == "session.updated"
    assert payload["properties"] == {"info": {"id": "", "title": "Session"}}


@pytest.mark.asyncio
async def test_emit_session_deleted_and_diff_events() -> None:
    event_bus = _EventBus()
    core = SimpleNamespace(event_bus=event_bus)

    await emit_session_deleted_event(core, {"id": "session_2"})
    await emit_session_diff_event(
        core,
        "session_2",
        [{"file": "src/app.py", "additions": 1, "deletions": 0}],
    )

    assert event_bus.events[0][1]["type"] == "session.deleted"
    assert event_bus.events[1] == (
        "opencode_event",
        {
            "type": "session.diff",
            "properties": {
                "sessionID": "session_2",
                "diff": [{"file": "src/app.py", "additions": 1, "deletions": 0}],
            },
        },
    )


@pytest.mark.asyncio
async def test_emit_session_events_are_best_effort() -> None:
    await emit_session_event(SimpleNamespace(event_bus=None), "session.updated", {})
    await emit_session_diff_event(SimpleNamespace(), "session_missing", [])

    failing_core = SimpleNamespace(event_bus=_EventBus(fail=True))
    await emit_session_updated_event(failing_core, {"id": "session_3"})
    await emit_session_diff_event(failing_core, "session_3", [])
