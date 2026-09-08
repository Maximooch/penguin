"""Real SQLite contention and cancellation at the durable request boundary."""

from __future__ import annotations

import asyncio
import sqlite3
import threading
from contextlib import closing
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI, HTTPException
from starlette.requests import Request

from penguin.web.services import chat_requests


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "phase", ["initialize", "accept", "replay", "complete", "lookup"]
)
async def test_sqlite_lock_does_not_block_event_loop(tmp_path, monkeypatch, phase):
    from penguin.web import routes

    path = tmp_path / "chat-requests.sqlite3"
    store = chat_requests.ChatRequestStore(path)
    if phase == "replay":
        store.accept("s", "m", {})
    core = SimpleNamespace(config=SimpleNamespace(workspace_path=tmp_path))
    loop = asyncio.get_running_loop()
    loop_thread = threading.get_ident()
    heartbeat = threading.Event()
    acquired, release = threading.Event(), threading.Event()
    connect = sqlite3.connect

    # Keep the failing regression quick. This is not a production busy timeout.
    def short_connect(*args, **kwargs):
        return connect(*args, **{**kwargs, "timeout": 0.25})

    monkeypatch.setattr(sqlite3, "connect", short_connect)

    def hold_lock():
        with closing(connect(path)) as db:
            db.execute("BEGIN EXCLUSIVE")
            acquired.set()
            assert release.wait(3), "Test did not release SQLite lock"
            db.rollback()

    method = {
        "initialize": "__init__",
        "accept": "accept",
        "replay": "lookup",
        "complete": "complete",
        "lookup": "lookup",
    }[phase]
    original = getattr(chat_requests.ChatRequestStore, method)

    def tick():
        heartbeat.set()
        release.set()

    def contended(*args, **kwargs):
        holder = threading.Thread(target=hold_lock)
        holder.start()
        try:
            assert acquired.wait(3), "Test did not acquire SQLite lock"
            loop.call_soon_threadsafe(tick)
            result = original(*args, **kwargs)
            assert heartbeat.is_set(), "SQLite blocked the event-loop heartbeat"
            assert threading.get_ident() != loop_thread
            return result
        finally:
            release.set()
            holder.join(3)
            assert not holder.is_alive()

    monkeypatch.setattr(chat_requests.ChatRequestStore, method, contended)

    async def execute():
        return {"response": "done"}

    if phase in {"initialize", "lookup"}:
        monkeypatch.setattr(routes, "authenticate_link_service_request", lambda _: None)
        result = await routes.lookup_link_chat_request(
            "s", "m", Request({"type": "http"}), core
        )
        assert result == {"state": "absent"}
    else:
        result = await chat_requests.execute_chat_request(
            lambda: store, "s", "m", {}, execute
        )
        assert result == (
            {"status": "recovering", "request_state": "accepted", "session_id": "s"}
            if phase == "replay"
            else {"response": "done"}
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("phase", ["initialize", "accept"])
@pytest.mark.parametrize("cancel_owner", [False, True])
@pytest.mark.parametrize("operation_fails", [False, True])
async def test_cancel_during_admission(
    tmp_path, monkeypatch, phase, cancel_owner, operation_fails
):
    store = chat_requests.ChatRequestStore(tmp_path / "requests.sqlite3")
    loop = asyncio.get_running_loop()
    reached, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    calls = 0
    accept = store.accept

    def blocked(operation, *args):
        loop.call_soon_threadsafe(reached.set)
        try:
            assert release.wait(3), "Test did not release the database operation"
            if operation_fails:
                raise OSError("injected storage failure")
            return operation(*args)
        finally:
            loop.call_soon_threadsafe(finished.set)

    def get_store():
        if phase == "initialize":
            return blocked(lambda: store)
        return store

    if phase == "accept":
        monkeypatch.setattr(store, "accept", lambda *args: blocked(accept, *args))

    async def execute():
        nonlocal calls
        calls += 1
        assert store.lookup("s", "m") == {"state": "accepted"}
        return {"response": "done"}

    observer = asyncio.create_task(
        chat_requests.execute_chat_request(get_store, "s", "m", {}, execute)
    )
    try:
        await asyncio.wait_for(reached.wait(), 3)
        owner = next(
            task
            for task in asyncio.all_tasks()
            if task.get_name() == "chat-request:s:m"
        )
        assert calls == 0
        (owner if cancel_owner else observer).cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        release.set()
        await asyncio.wait_for(finished.wait(), 3)
        if not cancel_owner:
            if operation_fails:
                with pytest.raises(OSError, match="injected storage failure"):
                    await owner
            else:
                assert await owner == {"response": "done"}
        else:
            assert owner.cancelled()
    finally:
        release.set()

    receipt = store.lookup("s", "m")
    if operation_fails or (cancel_owner and phase == "initialize"):
        assert receipt == {"state": "absent"}
        assert calls == 0
    elif cancel_owner:
        assert receipt == {"state": "accepted"}
        assert calls == 0
        assert (
            await chat_requests.execute_chat_request(
                lambda: store, "s", "m", {}, execute
            )
        )["status"] == "recovering"
        assert calls == 0
    else:
        assert receipt == {"state": "completed", "response": {"response": "done"}}
        assert await chat_requests.execute_chat_request(
            lambda: store, "s", "m", {}, execute
        ) == {"response": "done"}
        assert calls == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("cancel", ["observer", "shutdown", "late_abort"])
@pytest.mark.parametrize("http_error", [False, True])
@pytest.mark.parametrize("write_fails", [False, True])
async def test_cancel_during_result_write(
    tmp_path, monkeypatch, cancel, http_error, write_fails
):
    from penguin.system.task_cancellation import AbortReason, abort_task

    store = chat_requests.ChatRequestStore(tmp_path / "requests.sqlite3")
    loop = asyncio.get_running_loop()
    reached, finished = asyncio.Event(), asyncio.Event()
    release = threading.Event()
    complete = store.complete
    tasks = []

    def blocked_complete(*args, **kwargs):
        loop.call_soon_threadsafe(reached.set)
        try:
            assert release.wait(3), "Test did not release the result write"
            if write_fails:
                raise OSError("injected result write failure")
            complete(*args, **kwargs)
        finally:
            loop.call_soon_threadsafe(finished.set)

    monkeypatch.setattr(store, "complete", blocked_complete)

    async def execute():
        tasks.append(asyncio.current_task())
        if http_error:
            raise HTTPException(429, "busy", headers={"Retry-After": "5"})
        return {"response": "done"}

    observer = asyncio.create_task(
        chat_requests.execute_chat_request(lambda: store, "s", "m", {}, execute)
    )
    try:
        await asyncio.wait_for(reached.wait(), 3)
        assert store.lookup("s", "m") == {"state": "accepted"}
        owner = tasks[0]
        if cancel == "late_abort":
            abort_task(owner, AbortReason.USER_INTERRUPTED)
        else:
            (observer if cancel == "observer" else owner).cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        release.set()
        await asyncio.wait_for(finished.wait(), 3)
        if cancel == "observer":
            if write_fails:
                with pytest.raises(OSError, match="injected result write failure"):
                    await owner
            elif http_error:
                with pytest.raises(HTTPException):
                    await owner
            else:
                assert await owner == {"response": "done"}
        else:
            assert owner.cancelled()
    finally:
        release.set()

    receipt = chat_requests.ChatRequestStore(store.path).lookup("s", "m")
    if write_fails:
        assert receipt == {"state": "accepted"}
        assert (
            await chat_requests.execute_chat_request(
                lambda: store, "s", "m", {}, execute
            )
        )["status"] == "recovering"
    elif http_error:
        assert receipt == {
            "state": "completed",
            "response": {"detail": "busy"},
            "http_error": {"status_code": 429, "headers": {"Retry-After": "5"}},
        }
        with pytest.raises(HTTPException) as error:
            await chat_requests.execute_chat_request(
                lambda: store, "s", "m", {}, execute
            )
        assert error.value.status_code == 429
        assert error.value.headers == {"Retry-After": "5"}
    else:
        assert receipt == {"state": "completed", "response": {"response": "done"}}
        assert await chat_requests.execute_chat_request(
            lambda: store, "s", "m", {}, execute
        ) == {"response": "done"}
    assert len(tasks) == 1


@pytest.mark.asyncio
async def test_http_requests_progress_during_acceptance(tmp_path, monkeypatch):
    from penguin.web import routes
    from penguin.web.middleware.auth import AuthConfig, AuthenticationMiddleware

    monkeypatch.setenv("LINK_API_KEY", "dedicated-test-key")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    core = SimpleNamespace(config=SimpleNamespace(workspace_path=tmp_path))
    reached = asyncio.Event()
    release = threading.Event()
    loop = asyncio.get_running_loop()
    accept = chat_requests.ChatRequestStore.accept
    calls = []

    def blocked_accept(store, *args):
        loop.call_soon_threadsafe(reached.set)
        assert release.wait(3), "Test did not release acceptance"
        return accept(store, *args)

    async def execute(request, core, http_request):
        calls.append(request.client_message_id)
        return {"response": "done"}

    monkeypatch.setattr(chat_requests.ChatRequestStore, "accept", blocked_accept)
    monkeypatch.setattr(routes, "_process_chat_message", execute)
    app = FastAPI()
    app.include_router(routes.router)
    app.dependency_overrides[routes.get_core] = lambda: core
    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    body = {
        "text": "hello",
        "session_id": "s",
        "client_message_id": "m",
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
        headers={"X-API-Key": "dedicated-test-key"},
    ) as client:
        pending = asyncio.create_task(client.post("/api/v1/chat/message", json=body))
        try:
            await asyncio.wait_for(reached.wait(), 3)
            capabilities = await asyncio.wait_for(
                client.get("/api/v1/link/capabilities"), 1
            )
            assert capabilities.status_code == 200
            lookup = await asyncio.wait_for(
                client.get(
                    "/api/v1/link/chat-request",
                    params={"session_id": "s", "client_message_id": "m"},
                ),
                1,
            )
            assert lookup.json() == {"state": "absent"}
            assert not pending.done()
            assert calls == []
        finally:
            release.set()
            result = await pending
        assert result.status_code == 200
        retries = await asyncio.gather(
            *(client.post("/api/v1/chat/message", json=body) for _ in range(16))
        )
        assert all(response.json() == {"response": "done"} for response in retries)
        assert calls == ["m"]
