"""Tests for RunMode event bridge helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core import PenguinCore
from penguin.core_runtime import runmode_events
from penguin.system.state import MessageCategory


class _Conversation:
    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []

    def add_message(self, **message: Any) -> None:
        self.messages.append(message)


class _ConversationManager:
    def __init__(self) -> None:
        self.conversation = _Conversation()
        self.save_calls = 0

    def save(self) -> None:
        self.save_calls += 1


@pytest.mark.parametrize(
    ("status_type", "data", "expected"),
    [
        ("task_started", {"task_name": "Build API"}, "Task: Build API - Running"),
        (
            "task_started_legacy",
            {"task_prompt": "Fix tests"},
            "Task: Fix tests - Running",
        ),
        (
            "task_progress",
            {"iteration": 2, "max_iterations": 5, "progress": 40},
            "Progress: 40% (Iter: 2/5)",
        ),
        ("task_completed", {"task_name": "Build API"}, "Task: Build API - Completed"),
        ("task_completed_legacy", {}, "Task: Last task - Completed"),
        ("task_completed_eventbus", {}, "Task: Last task - Completed"),
        ("run_mode_ended", {}, "RunMode ended."),
        ("shutdown_completed", {"summary": "Stopped cleanly"}, "Stopped cleanly"),
        ("clarification_needed", {}, "Awaiting user clarification."),
        ("clarification_needed_eventbus", {"summary": "Need input"}, "Need input"),
        (
            "time_limit_reached",
            {},
            "RunMode stopped because the explicit time limit was reached.",
        ),
        (
            "idle_no_ready_tasks",
            {},
            "RunMode stopped because no ready work remained.",
        ),
        (
            "exploratory_continuation",
            {},
            "RunMode is continuing exploratorily by determining next steps.",
        ),
    ],
)
def test_run_mode_status_summary_covers_known_statuses(
    status_type: str,
    data: dict[str, Any],
    expected: str,
) -> None:
    assert runmode_events.run_mode_status_summary(status_type, data) == expected


def test_run_mode_status_summary_ignores_unknown_status() -> None:
    assert runmode_events.run_mode_status_summary("unknown", {}) is None


@pytest.mark.asyncio
async def test_handle_run_mode_event_persists_message_and_notifies_callbacks() -> None:
    conversation_manager = _ConversationManager()
    calls: list[Any] = []

    async def ui_callback() -> None:
        calls.append("ui")

    async def websocket_callback(event: dict[str, Any]) -> None:
        calls.append(("ws", event))

    owner = SimpleNamespace(
        conversation_manager=conversation_manager,
        _ui_update_callback=ui_callback,
        _temp_ws_callback=websocket_callback,
    )
    event = {
        "type": "message",
        "role": "assistant",
        "content": "done",
        "category": "dialog",
        "metadata": {"source": "runmode"},
    }

    await runmode_events.handle_run_mode_event(
        owner,
        event,
        logger=logging.getLogger(__name__),
    )

    assert conversation_manager.save_calls == 1
    assert conversation_manager.conversation.messages == [
        {
            "role": "assistant",
            "content": "done",
            "category": MessageCategory.DIALOG,
            "metadata": {"source": "runmode"},
        }
    ]
    assert calls == ["ui", ("ws", event)]


@pytest.mark.asyncio
async def test_handle_run_mode_event_defaults_invalid_category_to_system() -> None:
    conversation_manager = _ConversationManager()
    owner = SimpleNamespace(conversation_manager=conversation_manager)

    await runmode_events.handle_run_mode_event(
        owner,
        {"type": "message", "category": "not-real"},
        logger=logging.getLogger(__name__),
    )

    assert (
        conversation_manager.conversation.messages[0]["category"]
        is MessageCategory.SYSTEM
    )


@pytest.mark.asyncio
async def test_handle_run_mode_event_updates_status_and_callback_isolation() -> None:
    calls: list[Any] = []

    async def failing_ui_callback() -> None:
        calls.append("ui")
        raise RuntimeError("ui failed")

    async def websocket_callback(event: dict[str, Any]) -> None:
        calls.append(("ws", event["status_type"]))

    owner = SimpleNamespace(
        current_runmode_status_summary="RunMode idle.",
        _ui_update_callback=failing_ui_callback,
        _temp_ws_callback=websocket_callback,
    )
    event = {
        "type": "status",
        "status_type": "task_progress",
        "data": {"iteration": 3, "max_iterations": 9, "progress": 33},
    }

    await runmode_events.handle_run_mode_event(
        owner,
        event,
        logger=logging.getLogger(__name__),
    )

    assert owner.current_runmode_status_summary == "Progress: 33% (Iter: 3/9)"
    assert calls == ["ui", ("ws", "task_progress")]


@pytest.mark.asyncio
async def test_handle_run_mode_event_sets_error_summary() -> None:
    owner = SimpleNamespace(current_runmode_status_summary="RunMode idle.")

    await runmode_events.handle_run_mode_event(
        owner,
        {"type": "error", "message": "provider failed", "source": "runmode"},
        logger=logging.getLogger(__name__),
    )

    assert owner.current_runmode_status_summary == "Error: provider failed"


@pytest.mark.asyncio
async def test_core_handle_run_mode_event_shim_delegates_to_runtime() -> None:
    core = PenguinCore.__new__(PenguinCore)
    core.current_runmode_status_summary = "RunMode idle."

    await core._handle_run_mode_event(
        {"type": "status", "status_type": "idle_no_ready_tasks", "data": {}}
    )

    assert (
        core.current_runmode_status_summary
        == "RunMode stopped because no ready work remained."
    )
