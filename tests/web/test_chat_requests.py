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

    def failed_write(*args):
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
