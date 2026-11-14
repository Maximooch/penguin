"""Session busy status and abort markers have one owner: process_lifecycle."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import process_lifecycle, stream_events
from penguin.llm.stream_handler import AgentStreamingStateManager
from penguin.web.services.session_view import TRANSCRIPT_KEY, list_session_statuses
from tests.api.test_session_view_service import _core, _session


def _stream_owner(**state: Any) -> SimpleNamespace:
    owner = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id="agent-a"),
        _stream_manager=AgentStreamingStateManager(),
        **state,
    )
    owner._filter_internal_markers_from_event = (
        stream_events.filter_internal_markers_from_event
    )

    async def _emit(_event_type: str, _data: dict[str, Any]) -> None:
        return None

    owner.emit_ui_event = _emit

    async def _runmode_callback(_chunk: str, _message_type: str) -> None:
        return None

    owner._invoke_runmode_stream_callback = _runmode_callback
    return owner


async def _chunk(owner: SimpleNamespace, text: str) -> None:
    await stream_events.handle_stream_chunk(
        owner,
        text,
        message_type="assistant",
        role="assistant",
        agent_id="agent-a",
        stream_scope_id="session_1:agent-a",
        session_id="session_1",
        conversation_id="session_1",
        logger=logging.getLogger(__name__),
    )


def test_crashed_stream_does_not_leave_the_session_busy() -> None:
    """An unfinished assistant message on disk is not a running request."""
    session = _session("session_crashed", "Crashed", "2026-02-03T00:00:00")
    session.metadata[TRANSCRIPT_KEY] = {
        "order": ["msg_1"],
        "messages": {
            "msg_1": {
                "info": {
                    "id": "msg_1",
                    "sessionID": session.id,
                    "role": "assistant",
                    "time": {"created": 1},
                },
                "part_order": ["part_1"],
                "parts": {
                    "part_1": {
                        "id": "part_1",
                        "sessionID": session.id,
                        "messageID": "msg_1",
                        "type": "text",
                        "text": "half an ans",
                    }
                },
            }
        },
    }
    core = _core([session])

    assert list_session_statuses(core)[session.id] == {"type": "idle"}


@pytest.mark.asyncio
async def test_stale_abort_marker_cancels_at_most_one_untracked_stream() -> None:
    """With no tracked request to clear it, the marker is used up when it fires."""
    owner = _stream_owner(_opencode_abort_sessions={"session_1"})

    with pytest.raises(asyncio.CancelledError):
        await _chunk(owner, "cancelled")
    await _chunk(owner, "later work")

    assert "session_1" not in owner._opencode_abort_sessions
    assert owner._stream_manager.is_agent_active("session_1:agent-a")


@pytest.mark.asyncio
async def test_abort_marker_holds_for_the_whole_tracked_request() -> None:
    owner = _stream_owner(
        _opencode_abort_sessions={"session_1"},
        _opencode_active_requests={"session_1": 1},
    )

    for _ in range(2):
        with pytest.raises(asyncio.CancelledError):
            await _chunk(owner, "cancelled")

    assert "session_1" in owner._opencode_abort_sessions


@pytest.mark.asyncio
async def test_route_task_tracking_goes_through_the_lifecycle_owner() -> None:
    owner = SimpleNamespace()
    task = asyncio.current_task()
    assert task is not None

    assert process_lifecycle.track_session_task(owner, "session_1", task) is True
    assert owner._opencode_process_tasks == {"session_1": {task}}
    assert process_lifecycle.session_has_active_request(owner, "session_1") is True

    process_lifecycle.untrack_session_task(owner, "session_1", task)
    assert owner._opencode_process_tasks == {}
    assert process_lifecycle.session_has_active_request(owner, "session_1") is False
    assert process_lifecycle.track_session_task(owner, " ", task) is False
