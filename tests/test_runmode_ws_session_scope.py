"""The RunMode WebSocket receives only messages finalized by its own run.

Covers SM-52 (remaining part): while a RunMode run held the event slot, the
stream finalizer sent every finalized message to it, so a RunMode socket
received another session's assistant messages.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core import PenguinCore


def _core() -> Any:
    core: Any = PenguinCore.__new__(PenguinCore)

    def finalize(agent_id: str) -> tuple[Any, list[Any]]:
        message = SimpleNamespace(
            id="m",
            role="assistant",
            content=core.next_content,
            metadata={},
            timestamp="2026-11-17T00:00:00",
            tokens=0,
            agent_id="default",
            recipient_id=None,
            message_type="message",
            was_empty=False,
            to_dict=lambda: {"content": message.content},
        )
        return message, []

    core._stream_manager = SimpleNamespace(
        finalize=finalize, get_active_agents=lambda: []
    )
    session = SimpleNamespace(id="s", messages=[], metadata={})
    session.add_message = session.messages.append
    store = SimpleNamespace(
        sessions={"s": (session, False)},
        session_index={"s": {}},
        save_session=lambda _session: True,
    )
    core.conversation_manager = SimpleNamespace(
        current_agent_id="default",
        session_manager=store,
        agent_session_managers={"default": store},
    )
    core._runmode_stream_callback = None
    core._filter_internal_markers_from_event = lambda data: data
    core._ui_update_callback = None
    core._runmode_active = False
    core._continuous_mode = False
    core.current_runmode_status_summary = ""
    core.run_mode = None
    core._prepare_runmode_stream_callback = lambda callback: callback
    core._handle_run_mode_event = AsyncMock()
    return core


def _finalize(core: Any, content: str) -> None:
    core.next_content = content
    PenguinCore.finalize_streaming_message(
        core, agent_id="default", session_id="s", conversation_id="s"
    )


@pytest.mark.asyncio
async def test_the_runmode_socket_gets_only_its_runs_messages(monkeypatch) -> None:
    core = _core()
    received: list[str] = []
    running = asyncio.Event()
    release = asyncio.Event()

    async def socket(event: dict[str, Any]) -> None:
        received.append(event["content"])

    async def start(**_kwargs: Any) -> None:
        _finalize(core, "from the run")
        running.set()
        await release.wait()

    run_mode = SimpleNamespace(start=start, continuous_mode=False)
    monkeypatch.setitem(
        PenguinCore.start_run_mode.__globals__, "RunMode", lambda *_a, **_k: run_mode
    )

    run = asyncio.create_task(
        PenguinCore.start_run_mode(core, name="Task", websocket_event_callback=socket)
    )
    started = asyncio.create_task(running.wait())
    await asyncio.wait({run, started}, timeout=5, return_when=asyncio.FIRST_COMPLETED)
    if run.done():
        run.result()  # surfaces a failure to start
    assert running.is_set()

    async def other_session_request() -> None:
        _finalize(core, "from another session")

    await asyncio.create_task(other_session_request())
    await asyncio.sleep(0.01)
    release.set()
    await run

    assert received == ["from the run"]
