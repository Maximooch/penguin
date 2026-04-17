from __future__ import annotations

import hashlib
import hmac
import json
from types import SimpleNamespace

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.web.integrations.github_webhook import (
    github_webhook,
    remember_github_delivery,
    reset_github_delivery_cache,
    router as github_router,
)


@pytest.fixture(autouse=True)
def clear_webhook_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("GITHUB_WEBHOOK_SECRET", raising=False)
    monkeypatch.delenv("GITHUB_REPOSITORY", raising=False)
    monkeypatch.delenv("PENGUIN_GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS", raising=False)
    reset_github_delivery_cache()


@pytest.fixture
def webhook_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "super-secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    github_router.core = SimpleNamespace()
    app = FastAPI()
    app.include_router(github_router)
    return TestClient(app)


def _signature(secret: str, payload: bytes) -> str:
    digest = hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()
    return f"sha256={digest}"


def _payload_bytes() -> bytes:
    return json.dumps(
        {
            "repository": {"full_name": "owner/repo"},
            "action": "opened",
            "pull_request": {"number": 7},
        }
    ).encode("utf-8")


def test_remember_github_delivery_rejects_replay(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENGUIN_GITHUB_WEBHOOK_DELIVERY_TTL_SECONDS", "60")

    assert remember_github_delivery("delivery-1", now=100.0) is True
    assert remember_github_delivery("delivery-1", now=120.0) is False
    assert remember_github_delivery("delivery-1", now=161.0) is True


def test_github_webhook_rejects_duplicate_delivery(webhook_client: TestClient) -> None:
    payload = _payload_bytes()
    headers = {
        "X-Hub-Signature-256": _signature("super-secret", payload),
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-1",
        "Content-Type": "application/json",
    }

    first = webhook_client.post(
        "/api/v1/integrations/github/webhook",
        data=payload,
        headers=headers,
    )
    second = webhook_client.post(
        "/api/v1/integrations/github/webhook",
        data=payload,
        headers=headers,
    )

    assert first.status_code == 200
    assert second.status_code == 409
    assert second.json()["detail"] == "Duplicate delivery"


def test_github_webhook_requires_delivery_id(webhook_client: TestClient) -> None:
    payload = _payload_bytes()
    headers = {
        "X-Hub-Signature-256": _signature("super-secret", payload),
        "X-GitHub-Event": "ping",
        "Content-Type": "application/json",
    }

    response = webhook_client.post(
        "/api/v1/integrations/github/webhook",
        data=payload,
        headers=headers,
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Missing delivery id"


def test_github_webhook_transient_failure_does_not_poison_delivery(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GITHUB_WEBHOOK_SECRET", "super-secret")
    monkeypatch.setenv("GITHUB_REPOSITORY", "owner/repo")
    github_router.core = None
    app = FastAPI()
    app.include_router(github_router)
    client = TestClient(app)

    payload = _payload_bytes()
    headers = {
        "X-Hub-Signature-256": _signature("super-secret", payload),
        "X-GitHub-Event": "ping",
        "X-GitHub-Delivery": "delivery-transient",
        "Content-Type": "application/json",
    }

    first = client.post(
        "/api/v1/integrations/github/webhook",
        data=payload,
        headers=headers,
    )
    assert first.status_code == 500

    github_router.core = SimpleNamespace()
    second = client.post(
        "/api/v1/integrations/github/webhook",
        data=payload,
        headers=headers,
    )
    assert second.status_code == 200
