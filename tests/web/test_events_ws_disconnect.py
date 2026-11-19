"""The events WebSocket ends, and unsubscribes, when its client leaves.

Covers SM-75 (``events_ws``): the handler only slept in a loop and never read
the socket, and send errors were swallowed, so a client that left was never
noticed and its event bus subscriptions stayed until the server stopped.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.web import routes


class _Bus:
    def __init__(self) -> None:
        self.handlers: list[tuple[str, Any]] = []

    def subscribe(self, event: str, handler: Any) -> None:
        self.handlers.append((event, handler))

    def unsubscribe(self, event: str, handler: Any) -> None:
        self.handlers.remove((event, handler))


class _ServerSocket:
    """A socket as uvicorn presents it: a disconnect is seen only on receive."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        self.query_params: dict[str, str] = {}

    async def accept(self) -> None:
        return None

    async def send_json(self, _data: Any) -> None:
        raise RuntimeError("client is gone")

    async def receive(self) -> dict[str, Any]:
        return await self.inbox.get()


@pytest.mark.asyncio
async def test_client_disconnect_ends_the_stream_and_unsubscribes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    utils_bus, cli_bus = _Bus(), _Bus()

    async def no_auth(_websocket: Any) -> None:
        return None

    monkeypatch.setattr(routes, "require_websocket_auth", no_auth)
    monkeypatch.setattr(
        routes, "UtilsEventBus", SimpleNamespace(get_instance=lambda: utils_bus)
    )
    monkeypatch.setattr(
        routes, "CLIEventBus", SimpleNamespace(get_sync=lambda: cli_bus)
    )
    socket = _ServerSocket()
    core = SimpleNamespace(conversation_manager=None)

    handler = asyncio.create_task(routes.events_ws(socket, core))
    await asyncio.sleep(0.05)
    assert utils_bus.handlers and cli_bus.handlers

    socket.inbox.put_nowait({"type": "websocket.receive", "text": "ping"})
    socket.inbox.put_nowait({"type": "websocket.disconnect", "code": 1001})
    try:
        await asyncio.wait_for(handler, timeout=2.5)
    finally:
        handler.cancel()

    assert utils_bus.handlers == []
    assert cli_bus.handlers == []
