"""Request cancellation survives observers and never targets another turn."""

import asyncio
import multiprocessing
import socket
import sqlite3
from pathlib import Path
from typing import Any

import pytest
from fastapi import HTTPException

from penguin.web.services.chat_requests import ChatRequestStore, execute_chat_request


def _serve_http(workspace: str, port: int) -> None:
    """Serve real authenticated routes with an inert execution body for this test."""
    import os
    from types import SimpleNamespace

    import uvicorn
    from fastapi import FastAPI

    from penguin.web import routes
    from penguin.web.middleware.auth import AuthConfig, AuthenticationMiddleware

    os.environ["LINK_API_KEY"] = "cancel-http-test"
    os.environ["PENGUIN_API_KEYS"] = "cancel-control-test"
    os.environ["PENGUIN_AUTH_ENABLED"] = "true"
    started = False

    async def execute(*_args: Any) -> dict[str, Any]:
        """Remain active until the real durable owner receives cancellation."""
        nonlocal started
        started = True
        await asyncio.Event().wait()
        return {}

    async def state() -> dict[str, bool]:
        """Report whether this process entered the inert execution body."""
        return {"started": started}

    routes._process_chat_message = execute
    app = FastAPI()
    app.include_router(routes.router)
    app.add_api_route("/test-state", state)
    app.dependency_overrides[routes.get_core] = lambda: SimpleNamespace(
        config=SimpleNamespace(workspace_path=workspace)
    )
    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    uvicorn.run(app, host="127.0.0.1", port=port, log_level="error")


@pytest.mark.asyncio
async def test_stop_over_http_from_another_process(tmp_path: Path) -> None:
    """HTTP Stop on worker B stops worker A through their shared SQLite store."""
    import httpx

    ports = []
    for _ in range(2):
        with socket.socket() as listener:
            listener.bind(("127.0.0.1", 0))
            ports.append(listener.getsockname()[1])
    processes = [
        multiprocessing.get_context("spawn").Process(
            target=_serve_http, args=(str(tmp_path), port)
        )
        for port in ports
    ]
    for process in processes:
        process.start()
    base_a, base_b = [f"http://127.0.0.1:{port}" for port in ports]
    headers = {"X-API-Key": "cancel-http-test"}
    query = {"session_id": "cross-process", "client_message_id": "old"}
    body = {
        "text": "wait",
        **query,
        "durable_request": True,
        "link_execution": {
            "workspace_id": "w",
            "user_id": "u",
            "run_id": "r",
            "requested_model_id": "test",
            "execution_source": "link_gateway",
            "provider_state_owner": "link_managed",
            "settlement_mode": "debit_link_credits",
        },
    }
    try:
        async with httpx.AsyncClient(headers=headers, timeout=20) as client:
            for base in (base_a, base_b):

                async def ready() -> None:
                    """Wait for the test server, bounded by the test deadline."""
                    while True:
                        try:
                            result = await client.get(
                                base + "/api/v1/link/capabilities"
                            )
                            if result.status_code == 200:
                                return
                        except httpx.TransportError:
                            pass
                        await asyncio.sleep(0.05)

                await asyncio.wait_for(ready(), 15)
            run = asyncio.create_task(
                client.post(base_a + "/api/v1/chat/message", json=body)
            )

            async def started() -> None:
                """Observe execution from a second request before sending Stop."""
                while (
                    not (
                        await client.get(
                            base_a + "/test-state",
                            headers={"X-API-Key": "cancel-control-test"},
                        )
                    )
                    .json()
                    .get("started")
                ):
                    await asyncio.sleep(0.05)

            async def accepted() -> None:
                """Observe acceptance through worker B's real receipt endpoint."""
                while (
                    await client.get(base_b + "/api/v1/link/chat-request", params=query)
                ).json()["state"] != "accepted":
                    await asyncio.sleep(0.05)

            await asyncio.wait_for(accepted(), 5)
            await asyncio.wait_for(started(), 5)
            stopped = await client.post(
                base_b + "/api/v1/link/chat-request/cancel", params=query
            )
            assert stopped.status_code == 200
            result = await asyncio.wait_for(run, 5)
            assert result.status_code == 200
            assert result.json()["aborted"] is True
            replay = await client.post(base_b + "/api/v1/chat/message", json=body)
            assert replay.json() == result.json()
            assert (
                await client.get(base_b + "/api/v1/link/chat-request", params=query)
            ).json()["state"] == "completed"
    finally:
        for process in processes:
            process.terminate()
            process.join(5)
            assert not process.is_alive()


@pytest.mark.asyncio
async def test_cancel_before_acceptance_survives_reopen(tmp_path: Path) -> None:
    """A delayed dispatch must not execute after a durable cancellation."""
    path = tmp_path / "requests.sqlite3"
    ChatRequestStore(path).cancel("s", "old")

    async def forbidden() -> dict[str, Any]:
        """Fail if a cancelled identity reaches execution."""
        pytest.fail("Cancelled request executed")

    result = await execute_chat_request(
        lambda: ChatRequestStore(path), "s", "old", {}, forbidden
    )
    assert result["aborted"] is True
    assert ChatRequestStore(path).lookup("s", "old")["state"] == "completed"


@pytest.mark.asyncio
async def test_delayed_acceptance_preserves_stop_without_owner(tmp_path: Path) -> None:
    """Acceptance must preserve a stopped receipt without a later owner write."""
    path = tmp_path / "requests.sqlite3"
    store = ChatRequestStore(path)
    stopped = store.cancel("s", "old")
    assert stopped["state"] == "completed"
    assert stopped["response"]["status"] == "stopped"

    # Simulate owner loss immediately after acceptance: never call complete().
    claimed = store.accept("s", "old", {"text": "hello"})
    reopened = ChatRequestStore(path)
    assert reopened.lookup("s", "old") == stopped
    assert claimed is False

    async def forbidden() -> dict[str, Any]:
        """Fail if replay executes work already stopped before acceptance."""
        pytest.fail("Cancelled request executed")

    assert (
        await execute_chat_request(
            lambda: reopened, "s", "old", {"text": "hello"}, forbidden
        )
        == stopped["response"]
    )
    with pytest.raises(HTTPException) as conflict:
        reopened.accept("s", "old", {"text": "changed"})
    assert conflict.value.status_code == 409
    assert conflict.value.detail == "CHAT_REQUEST_IDEMPOTENCY_CONFLICT"
    assert ChatRequestStore(path).lookup("s", "old") == stopped


@pytest.mark.asyncio
async def test_cancel_running_request_from_other_connection(tmp_path: Path) -> None:
    """Cancellation uses persisted identity, not an HTTP observer or session ID."""
    path = tmp_path / "requests.sqlite3"
    store = ChatRequestStore(path)
    started = asyncio.Event()

    async def execute() -> dict[str, Any]:
        """Wait until request-scoped cancellation reaches the owner."""
        started.set()
        await asyncio.Event().wait()
        return {}

    run = asyncio.create_task(
        execute_chat_request(lambda: store, "s", "old", {}, execute)
    )
    await started.wait()
    await asyncio.to_thread(ChatRequestStore(path).cancel, "s", "old")
    assert (await asyncio.wait_for(run, 5))["aborted"] is True

    async def next_turn() -> dict[str, Any]:
        """Complete despite a late Stop for the previous turn."""
        ChatRequestStore(path).cancel("s", "old")
        await asyncio.sleep(0.05)
        return {"response": "new", "status": "completed"}

    assert (await execute_chat_request(lambda: store, "s", "new", {}, next_turn))[
        "response"
    ] == "new"


def test_cancel_does_not_overwrite_completed_result(tmp_path: Path) -> None:
    """The first completed receipt remains authoritative."""
    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    store.accept("s", "r", {})
    store.complete("s", "r", {"response": "done"})
    assert store.cancel("s", "r")["response"] == {"response": "done"}


@pytest.mark.asyncio
async def test_unknown_owner_is_not_reported_stopped(tmp_path: Path) -> None:
    """An accepted request without its owner remains uncertain, even after Stop."""
    path = tmp_path / "requests.sqlite3"
    ChatRequestStore(path).accept("s", "r", {})
    assert ChatRequestStore(path).cancel("s", "r") == {"state": "accepted"}
    reopened = ChatRequestStore(path)
    assert reopened.accept("s", "r", {}) is False
    assert reopened.lookup("s", "r") == {"state": "accepted"}

    async def forbidden() -> dict[str, Any]:
        """Fail if retry executes work whose original outcome is uncertain."""
        pytest.fail("Accepted request executed twice")

    assert await execute_chat_request(lambda: reopened, "s", "r", {}, forbidden) == {
        "status": "recovering",
        "request_state": "accepted",
        "session_id": "s",
    }


@pytest.mark.asyncio
async def test_poll_retries_after_sqlite_contention(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A transient read failure must not permanently disable cancellation."""
    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    original = store.is_cancelled
    started = asyncio.Event()
    calls = 0

    def read(session_id: str, request_id: str) -> bool:
        """Fail the first watcher read, after the pre-execution check."""
        nonlocal calls
        calls += 1
        if calls == 2:
            raise sqlite3.OperationalError("database is locked")
        return original(session_id, request_id)

    monkeypatch.setattr(store, "is_cancelled", read)

    async def execute() -> dict[str, Any]:
        """Stay active until the retrying watcher stops this request."""
        started.set()
        await asyncio.Event().wait()
        return {}

    run = asyncio.create_task(
        execute_chat_request(lambda: store, "s", "r", {}, execute)
    )
    await started.wait()
    await asyncio.to_thread(store.cancel, "s", "r")
    assert (await asyncio.wait_for(run, 5))["aborted"] is True
    assert calls >= 3
