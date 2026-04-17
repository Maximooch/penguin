from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastapi import FastAPI, WebSocketException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from penguin.web.middleware.auth import (
    AuthConfig,
    AuthenticationError,
    authenticate_connection,
    require_websocket_auth,
)
from penguin.web.routes import router


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PENGUIN_JWT_SECRET", raising=False)
    monkeypatch.delenv("PENGUIN_PUBLIC_ENDPOINTS", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)


@pytest.fixture
def auth_config(monkeypatch: pytest.MonkeyPatch) -> AuthConfig:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "test-key-123")
    return AuthConfig()


def test_public_endpoint_root_is_exact_match_only(auth_config: AuthConfig) -> None:
    assert auth_config.is_public_endpoint("/") is True
    assert auth_config.is_public_endpoint("/api/v1/health") is True
    assert auth_config.is_public_endpoint("/api/v1/capabilities") is False
    assert auth_config.is_public_endpoint("/static/index.html") is True
    assert auth_config.is_public_endpoint("/static-assets") is False


def test_authenticate_connection_rejects_query_param_api_keys(
    auth_config: AuthConfig,
) -> None:
    connection = SimpleNamespace(
        headers={},
        query_params={"api_key": "test-key-123"},
    )

    with pytest.raises(AuthenticationError, match="No valid authentication"):
        authenticate_connection(connection, auth_config)


@pytest.mark.asyncio
async def test_require_websocket_auth_accepts_header_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ws-test-key")
    websocket = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/events/ws"),
        headers={"X-API-Key": "ws-test-key"},
        state=SimpleNamespace(),
    )

    result = await require_websocket_auth(websocket)

    assert result["method"] == "api_key"
    assert websocket.state.authenticated is True
    assert websocket.state.auth_method == "api_key"


@pytest.mark.asyncio
async def test_require_websocket_auth_rejects_missing_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ws-test-key")
    websocket = SimpleNamespace(
        url=SimpleNamespace(path="/api/v1/events/ws"),
        headers={},
        state=SimpleNamespace(),
    )

    with pytest.raises(WebSocketException) as exc_info:
        await require_websocket_auth(websocket)

    assert exc_info.value.code == 1008


@pytest.fixture
def websocket_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "ws-test-key")
    router.core = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id=None),
        get_telemetry_summary=None,
    )
    app = FastAPI()
    app.include_router(router)
    return app


def test_events_websocket_rejects_unauthenticated_client(
    websocket_app: FastAPI,
) -> None:
    client = TestClient(websocket_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect("/api/v1/events/ws"):
            pass

    assert exc_info.value.code == 1008


def test_events_websocket_accepts_authenticated_client(
    websocket_app: FastAPI,
) -> None:
    client = TestClient(websocket_app)

    with client.websocket_connect(
        "/api/v1/events/ws",
        headers={"X-API-Key": "ws-test-key"},
    ) as websocket:
        assert websocket is not None


def test_chat_stream_websocket_rejects_query_param_api_key(
    websocket_app: FastAPI,
) -> None:
    client = TestClient(websocket_app)

    with pytest.raises(WebSocketDisconnect) as exc_info:
        with client.websocket_connect(
            "/api/v1/chat/stream?api_key=ws-test-key",
        ):
            pass

    assert exc_info.value.code == 1008



def test_http_auth_returns_401_without_credentials(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "http-test-key")

    from penguin.web.app import create_app

    client = TestClient(create_app())
    response = client.get("/api/v1/capabilities")

    assert response.status_code == 401
    assert response.json()["detail"]["error"]["code"] == "AUTHENTICATION_FAILED"
