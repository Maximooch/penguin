from __future__ import annotations

import asyncio
from types import MethodType
from typing import Any

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.integrations.telegram.config import TelegramConfig
from penguin.integrations.telegram.manager import TelegramManager
from penguin.web.integrations.telegram import build_telegram_router


def _app(
    *, body_limit: int = 1024, timeout: float = 1.0
) -> tuple[TestClient, TelegramManager, list[dict[str, Any]]]:
    config = TelegramConfig(
        enabled=True,
        token="test-only-token",
        expected_username="Penguin_agent_bot",
        transport="webhook",
        webhook_public_url="https://example.test",
        webhook_secret="webhook-secret",
        webhook_body_limit_bytes=body_limit,
        webhook_timeout_seconds=timeout,
    )
    manager = TelegramManager(object(), config)
    adopted: list[dict[str, Any]] = []

    async def admit(self: TelegramManager, update: Any) -> bool:
        del self
        adopted.append(update)
        return True

    manager.admit_webhook_update = MethodType(admit, manager)
    app = FastAPI()
    app.state.telegram_manager = manager
    app.include_router(build_telegram_router(config))
    return TestClient(app), manager, adopted


def test_webhook_requires_secret_and_acknowledges_after_adoption() -> None:
    client, _manager, adopted = _app()
    update = {"update_id": 1, "message": {}}

    assert (
        client.post("/api/v1/integrations/telegram/webhook", json=update).status_code
        == 401
    )
    response = client.post(
        "/api/v1/integrations/telegram/webhook",
        json=update,
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
    )

    assert response.status_code == 200
    assert response.json() == {"ok": True, "admitted": True}
    assert adopted == [update]


def test_webhook_rejects_oversized_body_before_adoption() -> None:
    client, _manager, adopted = _app(body_limit=32)
    response = client.post(
        "/api/v1/integrations/telegram/webhook",
        content=b"{" + b'"padding":"' + b"x" * 40 + b'"}',
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": "webhook-secret",
        },
    )

    assert response.status_code == 413
    assert adopted == []


def test_webhook_bounds_streamed_body_without_content_length() -> None:
    client, _manager, adopted = _app(body_limit=32)

    def chunks() -> Any:
        yield b'{"padding":"'
        yield b"x" * 40
        yield b'"}'

    response = client.post(
        "/api/v1/integrations/telegram/webhook",
        content=chunks(),
        headers={
            "Content-Type": "application/json",
            "X-Telegram-Bot-Api-Secret-Token": "webhook-secret",
        },
    )

    assert response.status_code == 413
    assert adopted == []


def test_webhook_does_not_acknowledge_an_adoption_timeout() -> None:
    client, manager, adopted = _app(timeout=0.01)

    async def slow(self: TelegramManager, update: Any) -> bool:
        del self
        adopted.append(update)
        await asyncio.sleep(1)
        return True

    manager.admit_webhook_update = MethodType(slow, manager)
    response = client.post(
        "/api/v1/integrations/telegram/webhook",
        json={"update_id": 2},
        headers={"X-Telegram-Bot-Api-Secret-Token": "webhook-secret"},
    )

    assert response.status_code == 503
