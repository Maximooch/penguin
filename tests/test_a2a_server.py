"""A2A wire checks with Penguin execution replaced at the model boundary."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from types import SimpleNamespace
from typing import TYPE_CHECKING

import httpx
import pytest
from fastapi import FastAPI, HTTPException

from penguin.web.middleware.auth import AuthConfig, AuthenticationMiddleware
from penguin.web.services.a2a import add_penguin_a2a_routes
from penguin.web.services.chat_requests import ChatRequestStore

if TYPE_CHECKING:
    from pathlib import Path


def build_app(path: Path) -> FastAPI:
    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    core = SimpleNamespace(config=SimpleNamespace(workspace_path=str(path)))
    assert add_penguin_a2a_routes(app, core)
    return app


@pytest.mark.asyncio
async def test_a2a_stream_and_durable_task_lookup(tmp_path, monkeypatch):
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")

    async def answer(_request, _core, _http_request=None):
        return {"response": "Penguin says OK", "status": "complete"}

    monkeypatch.setattr("penguin.web.routes._process_chat_message", answer)
    app = build_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        card = await client.get("/.well-known/agent-card.json")
        assert card.status_code == 200
        assert card.json()["supportedInterfaces"][0]["protocolVersion"] == "1.0"
        assert (
            card.json()["securitySchemes"]["bearer"]["httpAuthSecurityScheme"]["scheme"]
            == "Bearer"
        )
        denied = await client.post("/a2a/rest/message:stream", json={})
        assert denied.status_code == 401
        streamed = await client.post(
            "/a2a/rest/message:stream",
            headers={"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"},
            json={
                "message": {
                    "messageId": "message-1",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}],
                }
            },
        )
        assert streamed.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        task_id = next(event["task"]["id"] for event in events if "task" in event)
        assert any(
            event.get("statusUpdate", {}).get("status", {}).get("state")
            == "TASK_STATE_COMPLETED"
            for event in events
        )
        completion_messages = [
            event.get("statusUpdate", {}).get("status", {}).get("message", {})
            for event in events
        ]
        assert any(
            message.get("parts", [{}])[0].get("text") == "Penguin says OK"
            for message in completion_messages
        )

    restarted = build_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        task = await client.get(
            f"/a2a/rest/tasks/{task_id}",
            headers={"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"},
        )
        assert task.status_code == 200
        assert task.json()["status"]["state"] == "TASK_STATE_COMPLETED"
        assert task.json()["artifacts"][0]["parts"][0]["text"] == "Penguin says OK"
        assert task.json()["status"]["message"]["parts"][0]["text"] == "Penguin says OK"


@pytest.mark.asyncio
async def test_a2a_persists_authoritative_provider_failure(tmp_path, monkeypatch):
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")

    async def fail_before_model(_request, _core, _http_request=None):
        raise HTTPException(400, "Model credential is unavailable")

    monkeypatch.setattr("penguin.web.routes._process_chat_message", fail_before_model)
    headers = {"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"}
    app = build_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        streamed = await client.post(
            "/a2a/rest/message:stream",
            headers=headers,
            json={
                "message": {
                    "messageId": "failed-message",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}],
                }
            },
        )
        assert streamed.status_code == 200
        events = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        task_id = next(event["task"]["id"] for event in events if "task" in event)
        assert any(
            event.get("statusUpdate", {}).get("status", {}).get("state")
            == "TASK_STATE_FAILED"
            for event in events
        )

    restarted = build_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        task = await client.get(f"/a2a/rest/tasks/{task_id}", headers=headers)
        assert task.json()["status"]["state"] == "TASK_STATE_FAILED"


@pytest.mark.asyncio
async def test_a2a_marks_engine_error_result_failed(tmp_path, monkeypatch):
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")

    async def failed_result(_request, _core, _http_request=None):
        return {
            "response": "Error occurred: model returned no answer",
            "status": "error",
        }

    monkeypatch.setattr("penguin.web.routes._process_chat_message", failed_result)
    app = build_app(tmp_path)
    headers = {"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        streamed = await client.post(
            "/a2a/rest/message:stream",
            headers=headers,
            json={
                "message": {
                    "messageId": "engine-error",
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}],
                }
            },
        )
        events = [
            json.loads(line.removeprefix("data: "))
            for line in streamed.text.splitlines()
            if line.startswith("data: ")
        ]
        states = [
            event.get("statusUpdate", {}).get("status", {}).get("state")
            for event in events
        ]
        assert "TASK_STATE_FAILED" in states
        assert "TASK_STATE_COMPLETED" not in states


@pytest.mark.asyncio
async def test_a2a_link_inference_requires_separate_service_authority(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    executions = []

    async def answer(request, _core, _http_request=None):
        executions.append(request.link_execution)
        return {"response": "funded", "status": "complete"}

    monkeypatch.setattr("penguin.web.routes._process_chat_message", answer)
    app = build_app(tmp_path)
    execution = {
        "workspace_id": "workspace-1",
        "user_id": "user-1",
        "run_id": "run-1",
        "requested_model_id": "test-model",
        "max_output_tokens": 100,
        "execution_source": "link_gateway",
        "provider_state_owner": "link_managed",
        "settlement_mode": "debit_link_credits",
        "allow_fallback_to_link_gateway": False,
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        async def send(message_id, service_key=None):
            headers = {
                "Authorization": "Bearer a2a-test-secret",
                "A2A-Version": "1.0",
            }
            if service_key:
                headers["X-Link-Execution-Key"] = service_key
            response = await client.post(
                "/a2a/rest/message:stream",
                headers=headers,
                json={"message": {
                    "messageId": message_id,
                    "role": "ROLE_USER",
                    "parts": [{"text": "Hello"}],
                    "metadata": {"link_execution": execution},
                }},
            )
            assert response.status_code == 200
            return [
                json.loads(line.removeprefix("data: "))
                for line in response.text.splitlines()
                if line.startswith("data: ")
            ]

        denied = await send("unfunded-message")
        assert any(
            event.get("statusUpdate", {}).get("status", {}).get("state")
            == "TASK_STATE_FAILED"
            for event in denied
        )
        assert executions == []
        funded = await send("funded-message", "link-service-secret")
        assert any(
            event.get("statusUpdate", {}).get("status", {}).get("state")
            == "TASK_STATE_COMPLETED"
            for event in funded
        )
        assert len(executions) == 1
        assert executions[0].workspace_id == "workspace-1"
        assert executions[0].requested_model_id == "test-model"


@pytest.mark.asyncio
async def test_a2a_stop_reconciles_after_server_restart(tmp_path, monkeypatch):
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")

    async def slow_answer(_request, _core, _http_request=None):
        await asyncio.sleep(10)
        return {"response": "too late", "status": "complete"}

    monkeypatch.setattr("penguin.web.routes._process_chat_message", slow_answer)
    app = build_app(tmp_path)
    headers = {"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"}
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        sending = asyncio.create_task(
            client.post(
                "/a2a/rest/message:stream",
                headers=headers,
                json={
                    "message": {
                        "messageId": "stopped-message",
                        "role": "ROLE_USER",
                        "parts": [{"text": "slow"}],
                    }
                },
            )
        )
        task_id = None
        context_id = None
        for _ in range(500):
            try:
                with sqlite3.connect(tmp_path / "a2a-tasks.sqlite3") as db:
                    row = db.execute(
                        "SELECT id, context_id FROM tasks LIMIT 1"
                    ).fetchone()
                task_id = row[0] if row else None
                context_id = row[1] if row else None
            except sqlite3.OperationalError:
                pass
            if task_id:
                break
            await asyncio.sleep(0.01)
        assert task_id is not None and context_id is not None
        cancellation = await client.post(
            f"/a2a/rest/tasks/{task_id}:cancel",
            headers=headers,
        )
        assert cancellation.status_code == 200
        await asyncio.wait_for(sending, 5)
        request_store = ChatRequestStore(tmp_path / "a2a-chat-requests.sqlite3")
        receipt = {"state": "accepted"}
        for _ in range(500):
            receipt = request_store.lookup(context_id, "stopped-message")
            if receipt.get("state") == "completed":
                break
            await asyncio.sleep(0.01)
        assert receipt.get("response", {}).get("status") == "stopped"

    restarted = build_app(tmp_path)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=restarted), base_url="http://test"
    ) as client:
        task = await client.get(f"/a2a/rest/tasks/{task_id}", headers=headers)
        assert task.status_code == 200
        assert task.json()["status"]["state"] == "TASK_STATE_CANCELED"
