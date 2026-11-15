"""A durable chat request ends with a recorded result, and A2A reads it one way.

Covers SM-26: server shutdown neither stopped nor awaited in-flight durable
requests, so their receipts stayed accepted; and an A2A task repaired from a
receipt on lookup was mapped by different rules than the executor used.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
from typing import TYPE_CHECKING, Any

import httpx
import pytest

from penguin.web.services import chat_requests
from penguin.web.services.chat_requests import ChatRequestStore, execute_chat_request
from tests.test_a2a_server import build_app

if TYPE_CHECKING:
    from pathlib import Path

HEADERS = {"Authorization": "Bearer a2a-test-secret", "A2A-Version": "1.0"}


@pytest.mark.asyncio
async def test_shutdown_stops_in_flight_requests_and_records_it(
    tmp_path: Path,
) -> None:
    store = ChatRequestStore(tmp_path / "requests.sqlite3")
    started = asyncio.Event()

    async def slow() -> dict[str, Any]:
        started.set()
        await asyncio.sleep(30)
        return {"response": "too late", "status": "completed"}

    observer = asyncio.create_task(
        execute_chat_request(lambda: store, "session", "message", {"t": 1}, slow)
    )
    await asyncio.wait_for(started.wait(), 2)
    observer.cancel()  # the HTTP client went away; the request keeps running

    await asyncio.wait_for(chat_requests.stop_chat_requests(timeout=2), 3)

    receipt = store.lookup("session", "message")
    assert receipt["state"] == "completed"
    assert receipt["response"]["status"] == "stopped"
    assert receipt["response"]["abort_reason"] == "server_shutdown"


async def _open_task(client: httpx.AsyncClient, message_id: str) -> tuple[str, str]:
    streamed = await client.post(
        "/a2a/rest/message:stream",
        headers=HEADERS,
        json={
            "message": {
                "messageId": message_id,
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
    task = next(event["task"] for event in events if "task" in event)
    return task["id"], task["contextId"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "stored",
    [
        {"response": "Error occurred: no answer", "status": "error"},
        {
            "response": "Provider error occurred: denied",
            "status": "provider_error",
            "error": {"message": "denied"},
            "recoverable": False,
        },
    ],
    ids=["engine-error", "provider-error"],
)
async def test_a_receipt_repaired_on_lookup_maps_like_the_executor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any]
) -> None:
    monkeypatch.setenv("PENGUIN_A2A_API_KEY", "a2a-test-secret")
    monkeypatch.setenv("PENGUIN_A2A_BASE_URL", "http://127.0.0.1:18125")

    async def still_running(_request, _core, _http_request=None):
        return {"response": "", "status": "recovering"}

    monkeypatch.setattr("penguin.web.routes._process_chat_message", still_running)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(tmp_path)), base_url="http://test"
    ) as client:
        task_id, context_id = await _open_task(client, "message-1")

    with sqlite3.connect(tmp_path / "a2a-chat-requests.sqlite3") as db:
        db.execute(
            "UPDATE chat_requests SET response=? WHERE session_id=? AND request_id=?",
            (json.dumps(stored), context_id, "message-1"),
        )

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=build_app(tmp_path)), base_url="http://test"
    ) as client:
        task = await client.get(f"/a2a/rest/tasks/{task_id}", headers=HEADERS)

    assert task.json()["status"]["state"] == "TASK_STATE_FAILED"
