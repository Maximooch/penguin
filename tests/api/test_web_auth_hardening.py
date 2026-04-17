from __future__ import annotations

import io
import json
from pathlib import Path
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
from penguin.web.routes import ALLOWED_UPLOAD_CONTENT_TYPES, router
from penguin.web.services import provider_credentials as provider_credentials_service


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PENGUIN_JWT_SECRET", raising=False)
    monkeypatch.delenv("PENGUIN_PUBLIC_ENDPOINTS", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("PENGUIN_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", raising=False)
    monkeypatch.delenv("PENGUIN_PROVIDER_AUTH_STORE", raising=False)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("OLLAMA_HOST", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_EXPIRES_AT_MS", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    provider_credentials_service._WARNED_LEGACY_PATHS.clear()


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


def test_default_cors_origins_do_not_use_wildcard(monkeypatch: pytest.MonkeyPatch) -> None:
    from penguin.web.app import DEFAULT_DEV_CORS_ORIGINS, create_app

    app = create_app()
    cors_middleware = next(
        middleware
        for middleware in app.user_middleware
        if middleware.cls.__name__ == "CORSMiddleware"
    )

    assert cors_middleware.kwargs["allow_origins"] == DEFAULT_DEV_CORS_ORIGINS
    assert "*" not in cors_middleware.kwargs["allow_origins"]


def test_upload_rejects_non_image_content_type() -> None:
    router.core = SimpleNamespace()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("notes.txt", io.BytesIO(b"hello"), "text/plain")},
    )

    assert response.status_code == 415


def test_upload_rejects_oversized_file(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("PENGUIN_MAX_UPLOAD_BYTES", "8")
    router.core = SimpleNamespace()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("image.png", io.BytesIO(b"123456789"), "image/png")},
    )

    assert response.status_code == 413


def test_upload_accepts_supported_image(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
) -> None:
    monkeypatch.setattr("penguin.web.routes.WORKSPACE_PATH", str(tmp_path))
    router.core = SimpleNamespace()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("image.png", io.BytesIO(b"pngdata"), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content_type"] in ALLOWED_UPLOAD_CONTENT_TYPES
    assert payload["size_bytes"] == 7
    assert Path(payload["path"]).exists()


def test_provider_credentials_prefer_environment_over_legacy_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "providers.json"
    store_path.write_text(
        json.dumps({"version": 1, "providers": {"openai": {"type": "api", "key": "file-key"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", str(store_path))
    monkeypatch.setenv("OPENAI_API_KEY", "env-key")

    records = provider_credentials_service.get_provider_credentials()

    assert records["openai"]["type"] == "api"
    assert records["openai"]["key"] == "env-key"


def test_provider_credentials_warn_on_legacy_store_usage(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "providers.json"
    store_path.write_text(
        json.dumps({"version": 1, "providers": {"anthropic": {"type": "api", "key": "file-key"}}}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", str(store_path))

    with pytest.warns(UserWarning, match="plaintext JSON store"):
        records = provider_credentials_service.get_provider_credentials()

    assert records["anthropic"]["key"] == "file-key"


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
