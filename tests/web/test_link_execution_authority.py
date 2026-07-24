from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, HTTPException, WebSocketException
from fastapi.testclient import TestClient
from starlette.requests import Request

from penguin.web.middleware.auth import (
    AuthConfig,
    AuthenticationMiddleware,
    authenticate_connection,
    authenticate_link_service_request,
    require_websocket_auth,
)


def _request(*, api_key: str) -> Request:
    return Request(
        {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/chat/message",
            "headers": [(b"x-api-key", api_key.encode())],
        }
    )


def test_link_execution_requires_the_dedicated_link_service_key(monkeypatch) -> None:
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-client-secret")
    config = AuthConfig()

    auth = authenticate_link_service_request(
        _request(api_key="link-service-secret"),
        config,
    )

    assert auth == {
        "method": "link_service",
        "subject": "link",
        "metadata": {"service": "link"},
    }


def test_ordinary_api_key_cannot_authorize_link_execution(monkeypatch) -> None:
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-client-secret")
    config = AuthConfig()

    with pytest.raises(HTTPException) as raised:
        authenticate_link_service_request(
            _request(api_key="ordinary-client-secret"),
            config,
        )

    assert raised.value.status_code == 403
    assert (
        authenticate_connection(
            _request(api_key="ordinary-client-secret"),
            config,
        )["subject"]
        == "api_client"
    )


def test_link_service_key_cannot_also_be_an_ordinary_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "false")
    monkeypatch.setenv("LINK_API_KEY", "shared-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "shared-secret")

    with pytest.raises(
        ValueError,
        match="LINK_API_KEY must not also appear in PENGUIN_API_KEYS",
    ):
        AuthConfig()


def test_link_service_key_overlap_uses_normalized_comma_separated_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_API_KEY", "  shared-secret  ")
    monkeypatch.setenv(
        "PENGUIN_API_KEYS",
        "ordinary-one,  shared-secret  , ordinary-two",
    )

    with pytest.raises(
        ValueError,
        match="LINK_API_KEY must not also appear in PENGUIN_API_KEYS",
    ):
        AuthConfig()


def test_distinct_normalized_link_and_ordinary_api_keys_still_work(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("LINK_API_KEY", "  link-service-secret  ")
    monkeypatch.setenv(
        "PENGUIN_API_KEYS",
        "ordinary-one, ordinary-client-secret",
    )
    config = AuthConfig()

    assert (
        authenticate_connection(
            _request(api_key="link-service-secret"),
            config,
        )["method"]
        == "link_service"
    )
    assert (
        authenticate_connection(
            _request(api_key="ordinary-client-secret"),
            config,
        )["method"]
        == "api_key"
    )


def _scoped_link_service_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ordinary-client-secret")
    app = FastAPI()

    @app.get("/api/v1/link/capabilities")
    async def capabilities() -> dict[str, bool]:
        return {"allowed": True}

    @app.post("/api/v1/chat/message")
    async def chat_message() -> dict[str, bool]:
        return {"allowed": True}

    for method, path in (
        ("POST", "/api/v1/security/yolo"),
        ("GET", "/api/v1/security/config"),
        ("POST", "/api/v1/system/config/project-root"),
        ("POST", "/api/v1/system/config/llm"),
        ("PUT", "/api/v1/auth/openai"),
    ):
        app.add_api_route(
            path,
            lambda: {"allowed": False},
            methods=[method],
        )

    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    return app


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("POST", "/api/v1/security/yolo"),
        ("GET", "/api/v1/security/config"),
        ("POST", "/api/v1/system/config/project-root"),
        ("POST", "/api/v1/system/config/llm"),
        ("PUT", "/api/v1/auth/openai"),
    ],
)
def test_link_service_key_is_rejected_outside_its_exact_http_scope(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    with TestClient(_scoped_link_service_app(monkeypatch)) as client:
        response = client.request(
            method,
            path,
            headers={"X-API-Key": "link-service-secret"},
        )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "The Link execution credential is not authorized for this endpoint."
    }


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/link/capabilities"),
        ("POST", "/api/v1/chat/message"),
    ],
)
def test_link_service_key_is_accepted_only_for_execution_routes(
    monkeypatch: pytest.MonkeyPatch,
    method: str,
    path: str,
) -> None:
    with TestClient(_scoped_link_service_app(monkeypatch)) as client:
        response = client.request(
            method,
            path,
            headers={"X-API-Key": "link-service-secret"},
        )

    assert response.status_code == 200


@pytest.mark.asyncio
async def test_link_service_key_cannot_authenticate_a_websocket(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("LINK_API_KEY", "link-service-secret")
    websocket = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/events/ws"),
        headers={"X-API-Key": "link-service-secret"},
        state=SimpleNamespace(),
    )

    with pytest.raises(WebSocketException) as raised:
        await require_websocket_auth(websocket)

    assert raised.value.code == 1008
