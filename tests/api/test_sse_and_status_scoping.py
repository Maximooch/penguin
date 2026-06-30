"""Tests for SSE and system status directory/session scoping."""

from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from penguin.system.runtime_events import reset_runtime_event_sequences
from penguin.web.services.system_status import get_path_info
from penguin.web.sse_events import events_sse, set_core_instance


class _EventBus:
    def __init__(self):
        self._handlers = {}

    def subscribe(self, event_name, handler):
        self._handlers.setdefault(event_name, []).append(handler)

    def unsubscribe(self, event_name, handler):
        handlers = self._handlers.get(event_name, [])
        if handler in handlers:
            handlers.remove(handler)

    async def emit(self, event_name, payload):
        for handler in list(self._handlers.get(event_name, [])):
            handler(event_name, payload)


def _parse_sse(chunk: str) -> dict:
    for line in chunk.splitlines():
        if line.startswith("data: "):
            return json.loads(line[len("data: ") :])
    raise AssertionError(f"Missing data line in SSE chunk: {chunk}")


@pytest.mark.asyncio
async def test_sse_scopes_session_events_and_allows_global_status_events(
    tmp_path: Path,
):
    reset_runtime_event_sequences()
    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=event_bus,
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator

    connected = _parse_sse(await stream.__anext__())
    assert connected["type"] == "server.connected"
    assert core._opencode_session_directories["session_one"] == str(tmp_path)

    await event_bus.emit(
        "opencode_event",
        {
            "type": "vcs.branch.updated",
            "properties": {"branch": "main"},
        },
    )
    global_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    assert global_event["type"] == "vcs.branch.updated"

    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_other",
                "sessionID": "session_other",
                "role": "assistant",
            },
        },
    )
    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_one",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )
    scoped_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    assert scoped_event["properties"]["id"] == "msg_one"

    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_replays_buffered_events_after_last_event_id(tmp_path: Path):
    reset_runtime_event_sequences()
    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=event_bus,
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator

    _ = _parse_sse(await stream.__anext__())

    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_1",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )
    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_2",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )

    first_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    second_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    await stream.aclose()

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=first_event["id"],
    )
    replay_stream = response.body_iterator

    _ = _parse_sse(await replay_stream.__anext__())
    replayed = _parse_sse(
        await asyncio.wait_for(replay_stream.__anext__(), timeout=0.25)
    )
    assert replayed["id"] == second_event["id"]
    assert replayed["properties"]["id"] == "msg_2"

    await replay_stream.aclose()


@pytest.mark.asyncio
async def test_sse_reports_replay_gap_for_evicted_last_event_id(tmp_path: Path):
    reset_runtime_event_sequences()
    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=event_bus,
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator
    _ = _parse_sse(await stream.__anext__())

    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_1",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )
    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_2",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )

    first_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    second_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    await stream.aclose()

    core._opencode_sse_replay_v1 = [second_event]
    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=first_event["id"],
    )
    replay_stream = response.body_iterator

    _ = _parse_sse(await replay_stream.__anext__())
    gap = _parse_sse(await asyncio.wait_for(replay_stream.__anext__(), timeout=0.25))
    assert gap["type"] == "server.replay_gap"
    assert gap["properties"]["lastEventID"] == first_event["id"]
    assert gap["properties"]["oldestEventID"] == second_event["id"]
    assert gap["properties"]["newestEventID"] == second_event["id"]
    assert gap["properties"]["reason"] == "last_event_id_not_available"

    await replay_stream.aclose()


@pytest.mark.asyncio
async def test_sse_reconnect_does_not_duplicate_live_event_already_in_replay(
    tmp_path: Path,
):
    reset_runtime_event_sequences()
    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = SimpleNamespace(
        event_bus=event_bus,
        runtime_config=runtime,
        _opencode_session_directories={},
    )
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator
    _ = _parse_sse(await stream.__anext__())

    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_1",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )
    await event_bus.emit(
        "opencode_event",
        {
            "type": "message.updated",
            "properties": {
                "id": "msg_2",
                "sessionID": "session_one",
                "role": "assistant",
            },
        },
    )

    first_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    second_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    await stream.aclose()

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
        last_event_id=first_event["id"],
    )
    replay_stream = response.body_iterator
    _ = _parse_sse(await replay_stream.__anext__())

    await event_bus.emit(
        "opencode_event",
        {
            "runtime_event": {
                "id": second_event["id"],
                "type": second_event["type"],
                "payload": second_event["properties"],
                "sequence": second_event["order"],
                "time": second_event["time"],
            },
            "type": second_event["type"],
            "properties": second_event["properties"],
        },
    )

    delivered = _parse_sse(
        await asyncio.wait_for(replay_stream.__anext__(), timeout=0.25)
    )
    assert delivered["id"] == second_event["id"]
    try:
        duplicate = await asyncio.wait_for(replay_stream.__anext__(), timeout=0.05)
    except (asyncio.TimeoutError, StopAsyncIteration):
        duplicate = None
    if duplicate is not None:
        assert _parse_sse(duplicate)["id"] != second_event["id"]

    await replay_stream.aclose()


def test_path_info_prefers_valid_directory_then_session_mapping(tmp_path: Path):
    explicit = tmp_path / "explicit"
    mapped = tmp_path / "mapped"
    fallback = tmp_path / "fallback"
    explicit.mkdir()
    mapped.mkdir()
    fallback.mkdir()

    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(fallback),
        active_root=str(fallback),
    )
    core = SimpleNamespace(
        runtime_config=runtime,
        _opencode_session_directories={"session_one": str(mapped)},
    )

    direct = get_path_info(core, directory=str(explicit), session_id="session_one")
    assert Path(direct["directory"]).resolve() == explicit.resolve()

    from_mapping = get_path_info(
        core,
        directory=str(tmp_path / "missing_dir"),
        session_id="session_one",
    )
    assert Path(from_mapping["directory"]).resolve() == mapped.resolve()


@pytest.mark.asyncio
async def test_sse_streams_clarification_session_status_events(tmp_path: Path):
    from penguin.core import PenguinCore

    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = PenguinCore.__new__(PenguinCore)
    core.event_bus = event_bus
    core.runtime_config = runtime
    core._opencode_session_directories = {}
    core._current_conversation_id = "session_one"
    core.conversation_manager = SimpleNamespace(current_agent_id="default")
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator

    connected = _parse_sse(await stream.__anext__())
    assert connected["type"] == "server.connected"

    await PenguinCore.emit_ui_event(
        core,
        "status",
        {
            "status_type": "clarification_needed",
            "data": {
                "task_id": "task-1",
                "prompt": "Choose auth mode",
            },
        },
    )

    clarification_event = _parse_sse(
        await asyncio.wait_for(stream.__anext__(), timeout=0.25)
    )
    assert clarification_event["type"] == "session.status"
    assert clarification_event["properties"]["sessionID"] == "session_one"
    assert clarification_event["properties"]["status"]["type"] == "clarification_needed"
    assert clarification_event["properties"]["info"]["task_id"] == "task-1"

    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_streams_time_limit_session_status_events(tmp_path: Path):
    from penguin.core import PenguinCore

    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = PenguinCore.__new__(PenguinCore)
    core.event_bus = event_bus
    core.runtime_config = runtime
    core._opencode_session_directories = {}
    core._current_conversation_id = "session_one"
    core.conversation_manager = SimpleNamespace(current_agent_id="default")
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator

    _ = _parse_sse(await stream.__anext__())

    await PenguinCore.emit_ui_event(
        core,
        "status",
        {
            "status_type": "time_limit_reached",
            "data": {
                "summary": (
                    "RunMode stopped because the explicit time limit was reached."
                ),
            },
        },
    )

    time_limit_event = _parse_sse(
        await asyncio.wait_for(stream.__anext__(), timeout=0.25)
    )
    assert time_limit_event["type"] == "session.status"
    assert time_limit_event["properties"]["sessionID"] == "session_one"
    assert time_limit_event["properties"]["status"]["type"] == "time_limit_reached"

    await stream.aclose()


@pytest.mark.asyncio
async def test_sse_streams_idle_no_ready_task_status_events(tmp_path: Path):
    from penguin.core import PenguinCore

    event_bus = _EventBus()
    runtime = SimpleNamespace(
        workspace_root=str(tmp_path),
        project_root=str(tmp_path),
        active_root=str(tmp_path),
    )
    core = PenguinCore.__new__(PenguinCore)
    core.event_bus = event_bus
    core.runtime_config = runtime
    core._opencode_session_directories = {}
    core._current_conversation_id = "session_one"
    core.conversation_manager = SimpleNamespace(current_agent_id="default")
    set_core_instance(core)

    response = await events_sse(
        session_id="session_one",
        conversation_id=None,
        agent_id=None,
        directory=str(tmp_path),
    )
    stream = response.body_iterator

    _ = _parse_sse(await stream.__anext__())

    await PenguinCore.emit_ui_event(
        core,
        "status",
        {
            "status_type": "idle_no_ready_tasks",
            "data": {
                "summary": "RunMode stopped because no ready work remained.",
            },
        },
    )

    idle_event = _parse_sse(await asyncio.wait_for(stream.__anext__(), timeout=0.25))
    assert idle_event["type"] == "session.status"
    assert idle_event["properties"]["sessionID"] == "session_one"
    assert idle_event["properties"]["status"]["type"] == "idle_no_ready_tasks"

    await stream.aclose()
