"""Each reply on the chat WebSocket is its own stream, scoped to its session.

Covers SM-27: one queue was shared by every message on a connection, so
leftovers from one reply leaked into the next; the socket was not read while
a message was processed, so a client that left was not noticed; and tool
events from every session were forwarded to every socket.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient

from penguin.cli.events import EventBus
from penguin.system.execution_context import ExecutionContext
from penguin.web import routes


class _Core:
    streaming_reasoning_content = ""

    def __init__(self, process: Any) -> None:
        self._process = process

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        return await self._process(**kwargs)

    def finalize_streaming_message(self, **_kwargs: Any) -> None:
        return None


async def _none_async(*_args: Any, **_kwargs: Any) -> None:
    return None


async def _no_runtime(*_args: Any, **_kwargs: Any) -> tuple[None, None]:
    return None, None


@pytest.fixture
def connect(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")
    for name, value in {
        "_setup_approval_websocket_callbacks": lambda: None,
        "_setup_question_event_callbacks": lambda: None,
        "_bind_session_directory": lambda *_a, **_k: None,
        "_resolve_agent_mode": lambda *_a, **_k: None,
        "_persist_session_agent_mode": _none_async,
        "_build_execution_context": lambda _core, **kwargs: ExecutionContext(
            session_id=kwargs.get("session_id"),
            conversation_id=kwargs.get("conversation_id"),
            request_id="request",
        ),
        "_extract_paths_from_parts": lambda *_a, **_k: ([], []),
        "_extract_context_files_from_text": lambda *_a, **_k: [],
        "_normalize_context_files": lambda *_a, **_k: [],
        "_resolve_request_runtime_for_model": _no_runtime,
        "_apply_request_service_tier_override": lambda *_a, **_k: None,
        "_apply_reasoning_variant_override": lambda *_a, **_k: None,
        "_restore_reasoning_variant_override": lambda *_a, **_k: None,
        "_persist_session_model_selection": _none_async,
        "resolve_reasoning_payload": lambda *_a, **_k: None,
        "_build_reasoning_visibility_note": lambda **_k: None,
        "_build_reasoning_debug_snapshot": lambda **_k: {},
        "_persist_reasoning_debug_snapshot": lambda *_a, **_k: None,
    }.items():
        monkeypatch.setattr(routes, name, value)

    def open_socket(process: Any):
        app = FastAPI()
        app.include_router(routes.router)
        app.dependency_overrides[routes.get_core] = lambda: _Core(process)
        client = TestClient(app)
        return client.websocket_connect("/api/v1/chat/stream")

    return open_socket


def _reply(socket: Any) -> tuple[str, list[dict[str, Any]]]:
    """Read one reply; return its streamed text and the tool events in it."""
    text, tools = "", []
    while True:
        message = socket.receive_json()
        if message["event"] == "token":
            text += message["data"]["token"]
        elif message["event"] == "tool":
            tools.append(message["data"])
        elif message["event"] == "complete":
            return text, tools


def test_a_late_chunk_from_one_reply_does_not_reach_the_next(connect) -> None:
    async def process(stream_callback: Any, input_data: dict, **_kw: Any) -> dict:
        if input_data["text"] == "first":

            async def late() -> None:
                await asyncio.sleep(0.2)
                await stream_callback("STALE", "assistant")

            process.late = asyncio.get_running_loop().create_task(late())
            await stream_callback("one", "assistant")
            return {"assistant_response": "one"}
        await asyncio.sleep(0.5)
        await stream_callback("fresh", "assistant")
        return {"assistant_response": "fresh"}

    with connect(process) as socket:
        socket.send_json({"text": "first", "session_id": "A"})
        assert _reply(socket)[0] == "one"
        socket.send_json({"text": "second", "session_id": "A"})
        second, _tools = _reply(socket)

    assert second == "fresh"


_DISCONNECT = object()


class _ServerSocket:
    """A socket as uvicorn presents it: a disconnect is seen only on receive."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[Any] = asyncio.Queue()
        self.sent: list[dict[str, Any]] = []
        self.client_state = SimpleNamespace(name="CONNECTED")
        self.url = SimpleNamespace(path="/api/v1/chat/stream")

    async def accept(self) -> None:
        return None

    async def receive_json(self) -> Any:
        item = await self.inbox.get()
        if item is _DISCONNECT:
            self.client_state.name = "DISCONNECTED"
            raise WebSocketDisconnect(1001)
        return item

    async def send_json(self, data: dict[str, Any]) -> None:
        if self.client_state.name != "CONNECTED":
            raise RuntimeError("socket closed")
        self.sent.append(data)


@pytest.mark.asyncio
async def test_a_client_that_leaves_mid_reply_stops_the_work(connect) -> None:
    del connect  # applies the route stubs
    cancelled = asyncio.Event()

    async def process(**_kwargs: Any) -> dict:
        try:
            await asyncio.sleep(3)
        except asyncio.CancelledError:
            cancelled.set()
            raise
        return {"assistant_response": "finished anyway"}

    socket = _ServerSocket()
    handler = asyncio.create_task(routes.stream_chat(socket, core=_Core(process)))
    await socket.inbox.put({"text": "long", "session_id": "A"})
    for _ in range(100):
        if any(message["event"] == "start" for message in socket.sent):
            break
        await asyncio.sleep(0.01)

    await socket.inbox.put(_DISCONNECT)
    try:
        await asyncio.wait_for(cancelled.wait(), 1)
    finally:
        handler.cancel()
        await asyncio.gather(handler, return_exceptions=True)


def test_tool_events_from_other_sessions_are_not_forwarded(connect) -> None:
    async def process(stream_callback: Any, **_kwargs: Any) -> dict:
        bus = EventBus.get_sync()
        await bus.emit("tool", {"session_id": "B", "name": "theirs"})
        await bus.emit("tool", {"session_id": "A", "name": "mine"})
        await stream_callback("done", "assistant")
        return {"assistant_response": "done"}

    with connect(process) as socket:
        socket.send_json({"text": "go", "session_id": "A"})
        _text, tools = _reply(socket)

    assert [tool["name"] for tool in tools] == ["mine"]


def test_a_message_sent_mid_reply_is_answered_next(connect) -> None:
    async def process(stream_callback: Any, input_data: dict, **_kw: Any) -> dict:
        if input_data["text"] == "first":
            await asyncio.sleep(0.3)
        await stream_callback(f"re:{input_data['text']}", "assistant")
        return {"assistant_response": input_data["text"]}

    with connect(process) as socket:
        socket.send_json({"text": "first", "session_id": "A"})
        socket.send_json({"text": "second", "session_id": "A"})
        replies = [_reply(socket)[0], _reply(socket)[0]]

    assert replies == ["re:first", "re:second"]
