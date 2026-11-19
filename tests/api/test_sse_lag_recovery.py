"""A slow SSE client still receives every event, and shutdown keeps the ledger.

Covers SM-28: when a client's live queue was full, events were dropped with no
signal, so the client never learned to replay them; and the pending ledger
batch was not flushed at shutdown, so replay after a restart missed it.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

import penguin.web.sse_events as sse_events
from penguin.system.runtime_events import reset_runtime_event_sequences
from penguin.web.sse_events import events_sse, set_core_instance
from tests.api.test_sse_and_status_scoping import (
    _EventBus,
    _install_test_ledger,
    _parse_sse,
)

if TYPE_CHECKING:
    from pathlib import Path


def _core(tmp_path: Path) -> SimpleNamespace:
    reset_runtime_event_sequences()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=_EventBus(),
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    _install_test_ledger(core, tmp_path)
    set_core_instance(core)
    return core


def _message(number: int) -> dict:
    return {
        "type": "message.updated",
        "properties": {
            "id": f"msg_{number}",
            "sessionID": "session_one",
            "role": "assistant",
        },
    }


@pytest.mark.asyncio
async def test_a_client_that_falls_behind_still_gets_every_event_in_order(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = _core(tmp_path)
    monkeypatch.setattr(sse_events, "_SSE_QUEUE_MAX_EVENTS", 1)
    monkeypatch.setattr(sse_events, "_SSE_KEEPALIVE_TIMEOUT_SECONDS", 0.2)
    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator
    _parse_sse(await stream.__anext__())  # server.connected

    for number in range(1, 6):
        await core.event_bus.emit("opencode_event", _message(number))

    received = []
    for _ in range(5):
        frame = await asyncio.wait_for(stream.__anext__(), timeout=1)
        received.append(_parse_sse(frame)["properties"]["id"])
    await stream.aclose()

    assert received == [f"msg_{number}" for number in range(1, 6)]


@pytest.mark.asyncio
async def test_shutdown_flushes_the_pending_ledger_batch(tmp_path: Path) -> None:
    core = _core(tmp_path)
    await core.event_bus.emit("opencode_event", _message(1))
    assert core._runtime_event_ledger_v1.newest(limit=10) == []

    await sse_events.flush_runtime_event_ledger(core)

    stored = core._runtime_event_ledger_v1.newest(limit=10)
    assert [event["payload"]["id"] for event in stored] == ["msg_1"]
