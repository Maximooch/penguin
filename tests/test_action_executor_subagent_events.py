"""Tests for sub-agent lifecycle event emission in ActionExecutor."""

from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.utils.parser import ActionExecutor


class _EventBus:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    async def emit(self, event_type: str, payload: dict[str, Any]) -> None:
        self.events.append((event_type, payload))


class _ConversationManager:
    def __init__(self, session_id: str) -> None:
        self._session_id = session_id

    def get_agent_conversation(self, _agent_id: str) -> Any:
        return SimpleNamespace(session=SimpleNamespace(id=self._session_id))


class _Core:
    def __init__(self, session_id: str) -> None:
        self.event_bus = _EventBus()
        self.conversation_manager = _ConversationManager(session_id)
        self.created: list[dict[str, Any]] = []

    def create_sub_agent(self, agent_id: str, **kwargs: Any) -> None:
        self.created.append({"agent_id": agent_id, **kwargs})


@pytest.mark.asyncio
async def test_spawn_sub_agent_emits_session_created(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core("session_child_1")
    conversation = SimpleNamespace(core=core, current_agent_id="default")
    executor = ActionExecutor(
        tool_manager=SimpleNamespace(),
        task_manager=SimpleNamespace(),
        conversation_system=conversation,
    )

    def _fake_session_info(_core: Any, session_id: str) -> dict[str, Any]:
        return {
            "id": session_id,
            "title": "Child Session",
            "directory": "/tmp/workspace",
            "projectID": "penguin",
            "slug": session_id,
            "version": "test",
            "time": {"created": 1, "updated": 1},
        }

    monkeypatch.setattr(
        "penguin.web.services.session_view.get_session_info",
        _fake_session_info,
    )

    payload = json.dumps(
        {
            "id": "child-agent",
            "share_session": False,
            "share_context_window": False,
        }
    )
    result = await executor._spawn_sub_agent(payload)

    assert "Spawned sub-agent 'child-agent'" in result
    assert core.created
    assert core.created[0]["agent_id"] == "child-agent"

    assert core.event_bus.events
    event_type, payload = core.event_bus.events[-1]
    assert event_type == "opencode_event"
    assert payload["type"] == "session.created"
    assert payload["properties"]["sessionID"] == "session_child_1"
    assert payload["properties"]["info"]["id"] == "session_child_1"
