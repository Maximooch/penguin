"""Offline crash-boundary contracts for durable chat acceptance."""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from penguin.web.services.chat_requests import ChatRequestStore, execute_chat_request


def test_cross_connection_claim_and_conflict(tmp_path):
    path = tmp_path / "requests.sqlite3"
    ChatRequestStore(path)
    with ThreadPoolExecutor(max_workers=8) as pool:
        claims = list(
            pool.map(
                lambda _: ChatRequestStore(path).accept(
                    "session", "message", {"text": "hello"}
                ),
                range(16),
            )
        )
    assert sum(claims) == 1
    with pytest.raises(HTTPException) as error:
        ChatRequestStore(path).accept("session", "message", {"text": "different"})
    assert error.value.status_code == 409
    assert ChatRequestStore(path).accept("other-session", "message", {"text": "hello"})


@pytest.mark.asyncio
async def test_disconnect_does_not_cancel_execution_and_result_survives_restart(
    tmp_path,
):
    path = tmp_path / "requests.sqlite3"
    store = ChatRequestStore(path)
    started, release, finished = asyncio.Event(), asyncio.Event(), asyncio.Event()
    calls = 0

    async def execute():
        nonlocal calls
        calls += 1
        started.set()
        await release.wait()
        finished.set()
        return {"response": "done", "status": "completed"}

    observer = asyncio.create_task(execute_chat_request(store, "s", "m", {}, execute))
    await started.wait()
    observer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await observer
    assert store.lookup("s", "m") == {"state": "accepted"}
    duplicate = await execute_chat_request(store, "s", "m", {}, execute)
    assert duplicate["status"] == "recovering"
    assert calls == 1
    release.set()
    await finished.wait()
    # The continuation commits synchronously before it yields back to this test.
    reopened = ChatRequestStore(path)
    assert reopened.lookup("s", "m")["response"]["response"] == "done"
    assert await execute_chat_request(reopened, "s", "m", {}, execute) == {
        "response": "done",
        "status": "completed",
    }
    assert calls == 1


@pytest.mark.asyncio
async def test_crash_after_acceptance_never_blindly_reexecutes(tmp_path):
    path = tmp_path / "requests.sqlite3"
    assert ChatRequestStore(path).accept("s", "m", {})

    async def forbidden():
        pytest.fail("An accepted request must not execute again")

    reopened = ChatRequestStore(path)
    assert reopened.lookup("s", "other") == {"state": "absent"}
    assert (await execute_chat_request(reopened, "s", "m", {}, forbidden))[
        "status"
    ] == "recovering"


@pytest.mark.asyncio
async def test_result_write_failure_preserves_uncertain_acceptance(
    tmp_path, monkeypatch
):
    store = ChatRequestStore(tmp_path / "requests.sqlite3")

    def failed_write(*args, **kwargs):
        raise OSError("injected disk failure")

    monkeypatch.setattr(store, "complete", failed_write)

    async def execute():
        return {"response": "tool already executed"}

    with pytest.raises(OSError, match="disk failure"):
        await execute_chat_request(store, "s", "m", {}, execute)
    assert store.lookup("s", "m") == {"state": "accepted"}


def test_first_result_is_immutable(tmp_path):
    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    store.accept("s", "m", {})
    store.complete("s", "m", {"response": "first"})
    store.complete("s", "m", {"response": "second"})
    assert store.lookup("s", "m")["response"] == {"response": "first"}


def test_http_contract_auth_replay_conflict_and_lookup(tmp_path, monkeypatch):
    from penguin.web import routes
    from penguin.web.middleware.auth import AuthConfig, AuthenticationMiddleware

    monkeypatch.setenv("LINK_API_KEY", "dedicated-test-key")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-test-key")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    core = SimpleNamespace(config=SimpleNamespace(workspace_path=tmp_path))
    calls = []

    async def fake_process(request, core, http_request):
        calls.append(request.text)
        if request.text == "fail":
            raise HTTPException(400, "runtime rejected", headers={"X-Reason": "test"})
        return {"response": "done", "status": "completed"}

    monkeypatch.setattr(routes, "_process_chat_message", fake_process)
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
    with TestClient(app) as client:
        headers = {"X-API-Key": "dedicated-test-key"}
        query = {"session_id": "s", "client_message_id": "m"}
        invalid = client.post(
            "/api/v1/chat/message",
            json={**body, "agent_mode": "invalid"},
            headers=headers,
        )
        assert invalid.status_code == 400
        assert client.get(
            "/api/v1/link/chat-request", params=query, headers=headers
        ).json() == {"state": "absent"}
        for _ in range(2):
            result = client.post("/api/v1/chat/message", json=body, headers=headers)
            assert result.status_code == 200
            assert result.json()["response"] == "done"
        assert calls == ["hello"]
        result = client.post(
            "/api/v1/chat/message", json={**body, "text": "changed"}, headers=headers
        )
        assert result.status_code == 409
        receipt = client.get("/api/v1/link/chat-request", params=query, headers=headers)
        assert receipt.json()["state"] == "completed"
        assert receipt.json()["response"]["response"] == "done"
        assert (
            client.get(
                "/api/v1/link/chat-request",
                params=query,
                headers={"X-API-Key": "ordinary-test-key"},
            ).status_code
            == 403
        )
        assert (
            client.post(
                "/api/v1/chat/message",
                json=body,
                headers={"X-API-Key": "ordinary-test-key"},
            ).status_code
            == 403
        )
        assert (
            client.get("/api/v1/link/capabilities", headers=headers).json()[
                "durable_chat_requests"
            ]["version"]
            == 1
        )
        assert calls == ["hello"]
        for field in ("session_id", "client_message_id"):
            assert (
                client.post(
                    "/api/v1/chat/message", json={**body, field: " "}, headers=headers
                ).status_code
                == 422
            )
        for _ in range(2):
            assert (
                client.post(
                    "/api/v1/chat/message",
                    json={**body, "durable_request": False},
                    headers=headers,
                ).status_code
                == 200
            )
        assert calls == ["hello", "hello", "hello"]
        failure_body = {**body, "text": "fail", "client_message_id": "failure"}
        for _ in range(2):
            failure = client.post(
                "/api/v1/chat/message", json=failure_body, headers=headers
            )
            assert failure.status_code == 400
            assert failure.json() == {"detail": "runtime rejected"}
            assert failure.headers["X-Reason"] == "test"
        assert calls.count("fail") == 1
        receipt = client.get(
            "/api/v1/link/chat-request",
            params={**query, "client_message_id": "failure"},
            headers=headers,
        ).json()
        assert receipt["state"] == "completed"
        assert receipt["http_error"]["status_code"] == 400


@pytest.mark.asyncio
async def test_http_failure_survives_restart_and_replays_headers(tmp_path):
    path = tmp_path / "requests.sqlite3"
    calls = 0

    async def execute():
        nonlocal calls
        calls += 1
        raise HTTPException(429, {"error": "busy"}, headers={"Retry-After": "5"})

    for _ in range(2):
        with pytest.raises(HTTPException) as error:
            await execute_chat_request(ChatRequestStore(path), "s", "m", {}, execute)
        assert error.value.status_code == 429
        assert error.value.detail == {"error": "busy"}
        assert error.value.headers == {"Retry-After": "5"}
    assert calls == 1
    assert ChatRequestStore(path).lookup("s", "m") == {
        "state": "completed",
        "response": {"detail": {"error": "busy"}},
        "http_error": {"status_code": 429, "headers": {"Retry-After": "5"}},
    }


@pytest.mark.asyncio
@pytest.mark.parametrize("explicit", [True, False])
@pytest.mark.parametrize("swallow", ["response", "http_error", "propagate"])
async def test_execution_cancellation_distinguishes_abort_from_shutdown(
    tmp_path,
    monkeypatch,
    explicit,
    swallow,
):
    import logging
    from unittest.mock import AsyncMock

    from penguin.core_runtime import stream_events

    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    started = asyncio.Event()
    cleaned = asyncio.Event()
    owner = SimpleNamespace(
        _opencode_process_tasks={},
        _get_tui_adapter=lambda sid: SimpleNamespace(),
        _stream_manager=SimpleNamespace(get_active_agents=lambda: []),
    )
    monkeypatch.setattr(stream_events, "emit_opencode_session_status", AsyncMock())

    async def execute():
        owner._opencode_process_tasks["s"] = {asyncio.current_task()}
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            if swallow == "propagate":
                raise
            if swallow == "http_error":
                raise HTTPException(503, "shutdown converted to HTTP")
            return {"aborted": True}
        finally:
            cleaned.set()

    observer = asyncio.create_task(execute_chat_request(store, "s", "m", {}, execute))
    await started.wait()
    if explicit:
        await stream_events.abort_session(
            owner, "s", logger=logging.getLogger(__name__)
        )
        result = await observer
        assert cleaned.is_set()
        assert result["status"] == "stopped"
        assert result["abort_reason"] == "user_interrupted"
        assert ChatRequestStore(store.path).lookup("s", "m")["response"] == result
        assert await execute_chat_request(store, "s", "m", {}, execute) == result
    else:
        next(iter(owner._opencode_process_tasks["s"])).cancel()
        with pytest.raises(asyncio.CancelledError):
            await observer
        assert store.lookup("s", "m") == {"state": "accepted"}


@pytest.mark.asyncio
async def test_shutdown_cannot_be_relabelled_by_later_user_abort(tmp_path):
    from penguin.system.task_cancellation import AbortReason, abort_task

    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    started, interrupted, release = asyncio.Event(), asyncio.Event(), asyncio.Event()
    tasks = []

    async def execute():
        tasks.append(asyncio.current_task())
        started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            interrupted.set()
            await release.wait()
            return {"status": "completed", "response": "not authoritative"}

    observer = asyncio.create_task(execute_chat_request(store, "s", "m", {}, execute))
    await started.wait()
    tasks[0].cancel()
    await interrupted.wait()
    abort_task(tasks[0], AbortReason.USER_INTERRUPTED)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await observer
    assert ChatRequestStore(store.path).lookup("s", "m") == {"state": "accepted"}


def test_existing_receipts_migrate_without_changing_results(tmp_path):
    import sqlite3

    path = tmp_path / "requests.sqlite3"
    with sqlite3.connect(path) as db:
        db.execute(
            "CREATE TABLE chat_requests (session_id TEXT, request_id TEXT, "
            "fingerprint TEXT, response TEXT, updated_at TEXT, "
            "PRIMARY KEY(session_id, request_id))"
        )
        db.execute("INSERT INTO chat_requests VALUES ('s', 'm', 'hash', '{}', NULL)")
    assert ChatRequestStore(path).lookup("s", "m") == {
        "state": "completed",
        "response": {},
    }


def test_event_loop_shutdown_does_not_persist_swallowed_completion(tmp_path):
    store = ChatRequestStore(tmp_path / "requests.sqlite3")

    async def main():
        started = asyncio.Event()

        async def execute():
            started.set()
            try:
                await asyncio.Event().wait()
            except asyncio.CancelledError:
                return {"status": "completed", "response": "not authoritative"}

        observer = asyncio.create_task(
            execute_chat_request(store, "s", "m", {}, execute)
        )
        await started.wait()
        assert not observer.done()

    # asyncio.run cancels pending tasks itself, outside Penguin's abort helper.
    asyncio.run(main())
    assert ChatRequestStore(store.path).lookup("s", "m") == {"state": "accepted"}


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["error", "abort"])
@pytest.mark.parametrize("write_fails", [False, True])
async def test_disconnected_observer_terminal_outcome(
    tmp_path, monkeypatch, outcome, write_fails
):
    from penguin.system.task_cancellation import AbortReason, abort_task

    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    started, release = asyncio.Event(), asyncio.Event()
    execution_tasks = []

    async def execute():
        execution_tasks.append(asyncio.current_task())
        started.set()
        await release.wait()
        raise HTTPException(400, "rejected")

    if write_fails:

        def fail_write(*args, **kwargs):
            raise OSError("disk unavailable")

        monkeypatch.setattr(store, "complete", fail_write)

    observer = asyncio.create_task(execute_chat_request(store, "s", "m", {}, execute))
    await started.wait()
    observer.cancel()
    with pytest.raises(asyncio.CancelledError):
        await observer
    execution = execution_tasks[0]
    if outcome == "abort":
        abort_task(execution, AbortReason.USER_INTERRUPTED)
    else:
        release.set()
    if write_fails:
        with pytest.raises(OSError, match="disk unavailable"):
            await execution
        assert store.lookup("s", "m") == {"state": "accepted"}
    else:
        if outcome == "error":
            with pytest.raises(HTTPException):
                await execution
        else:
            assert (await execution)["status"] == "stopped"
        assert ChatRequestStore(store.path).lookup("s", "m")["state"] == "completed"
