from __future__ import annotations

import asyncio
import io
import json
import logging
import os
import warnings
from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image
from fastapi import FastAPI, WebSocketException
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from penguin.web.middleware.auth import (
    AuthConfig,
    AuthenticationError,
    authenticate_connection,
    get_startup_auth_token,
    require_websocket_auth,
)
from penguin.web.routes import ALLOWED_UPLOAD_CONTENT_TYPES, router
from penguin.web.sse_events import router as sse_router, set_core_instance
from penguin.web.services import provider_credentials as provider_credentials_service


@pytest.fixture(autouse=True)
def clear_auth_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("PENGUIN_JWT_SECRET", raising=False)
    monkeypatch.delenv("PENGUIN_PUBLIC_ENDPOINTS", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_CORS_ORIGINS", raising=False)
    monkeypatch.delenv("PENGUIN_MAX_UPLOAD_BYTES", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)
    monkeypatch.delenv("PENGUIN_SESSION_SECRET", raising=False)
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
    assert auth_config.is_public_endpoint("/authorize") is True
    assert auth_config.is_public_endpoint("/chat") is True
    assert auth_config.is_public_endpoint("/dashboard") is True
    assert auth_config.is_public_endpoint("/openapi.json") is True
    assert auth_config.is_public_endpoint("/api/v1/health") is True
    assert auth_config.is_public_endpoint("/favicon.ico") is True
    assert auth_config.is_public_endpoint("/apple-touch-icon.png") is True
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


def test_authenticate_connection_accepts_startup_token_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "startup-token-123")
    connection = SimpleNamespace(
        headers={"X-API-Key": "startup-token-123"},
        query_params={},
    )

    result = authenticate_connection(connection, AuthConfig())

    assert result["method"] == "startup_token"
    assert result["subject"] == "local_bootstrap"


def test_startup_auth_token_generated_only_without_configured_api_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")

    token = get_startup_auth_token(AuthConfig())

    assert token
    assert os.environ["PENGUIN_AUTH_STARTUP_TOKEN"] == token

    monkeypatch.setenv("PENGUIN_API_KEYS", "configured-key")
    assert get_startup_auth_token(AuthConfig()) is None


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
    assert "This Penguin instance is protected." in exc_info.value.reason


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


def test_default_cors_origins_do_not_use_wildcard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
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


def _png_1x1_bytes() -> bytes:
    buffer = io.BytesIO()
    Image.new("RGB", (1, 1), color=(255, 0, 0)).save(buffer, format="PNG")
    return buffer.getvalue()


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
        files={"file": ("image.png", io.BytesIO(_png_1x1_bytes()), "image/png")},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["content_type"] in ALLOWED_UPLOAD_CONTENT_TYPES
    assert payload["size_bytes"] == len(_png_1x1_bytes())
    assert Path(payload["path"]).exists()


def test_provider_credentials_prefer_environment_over_legacy_file(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "providers.json"
    store_path.write_text(
        json.dumps(
            {"version": 1, "providers": {"openai": {"type": "api", "key": "file-key"}}}
        ),
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
    store_path = tmp_path / "provider_auth.json"
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {"anthropic": {"type": "api", "key": "file-key"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

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
    error = response.json()["detail"]["error"]
    assert error["code"] == "AUTHENTICATION_FAILED"
    assert "This Penguin instance is protected." in error["message"]
    assert "POST /api/v1/auth/session" in error["suggested_action"]


def test_http_auth_logs_warning_once_per_path(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "http-test-key")

    from penguin.web.app import create_app
    from penguin.web.middleware.auth import _SEEN_AUTH_FAILURES

    _SEEN_AUTH_FAILURES.clear()
    client = TestClient(create_app())

    with caplog.at_level(logging.DEBUG, logger="penguin.web.middleware.auth"):
        first = client.get("/api/v1/capabilities")
        second = client.get("/api/v1/capabilities")

    assert first.status_code == 401
    assert second.status_code == 401
    warning_records = [
        record for record in caplog.records if record.levelno == logging.WARNING
    ]
    assert len(warning_records) == 1
    assert "POST /api/v1/auth/session" in warning_records[0].message


def test_openapi_schema_remains_public_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "http-test-key")

    from penguin.web.app import create_app

    client = TestClient(create_app())
    response = client.get("/openapi.json")

    assert response.status_code == 200
    assert response.json()["openapi"].startswith("3.")


def test_browser_icon_requests_are_not_authenticated_when_auth_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "http-test-key")

    from penguin.web.app import create_app

    client = TestClient(create_app())
    response = client.get("/favicon.ico")

    assert response.status_code == 404


def test_root_chat_dashboard_and_authorize_html_disable_caching() -> None:
    from penguin.web.app import create_app

    client = TestClient(create_app())

    root = client.get("/")
    chat = client.get("/chat")
    dashboard = client.get("/dashboard")
    authorize = client.get("/authorize")

    assert root.status_code == 200
    assert root.headers["cache-control"] == "no-store, max-age=0"
    assert root.headers["pragma"] == "no-cache"
    assert chat.status_code == 200
    assert chat.headers["cache-control"] == "no-store, max-age=0"
    assert chat.headers["pragma"] == "no-cache"
    assert dashboard.status_code == 200
    assert dashboard.headers["cache-control"] == "no-store, max-age=0"
    assert dashboard.headers["pragma"] == "no-cache"
    assert authorize.status_code == 200
    assert authorize.headers["cache-control"] == "no-store, max-age=0"
    assert authorize.headers["pragma"] == "no-cache"


def test_authorize_page_loads_when_auth_is_enabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")

    from penguin.web.app import create_app

    client = TestClient(create_app())
    response = client.get("/authorize")

    assert response.status_code == 200
    assert "Authorize this browser" in response.text


def test_chat_ui_includes_fragment_bootstrap_and_local_auth_gate() -> None:
    index_path = (
        Path(__file__).resolve().parents[2]
        / "penguin"
        / "web"
        / "static"
        / "index.html"
    )
    content = index_path.read_text()

    assert "local_token" in content
    assert "/api/v1/auth/session" in content
    assert "Authorize this browser" in content


def test_dashboard_ui_includes_fragment_bootstrap_and_local_auth_gate() -> None:
    dashboard_path = (
        Path(__file__).resolve().parents[2]
        / "penguin"
        / "web"
        / "static"
        / "dashboard.html"
    )
    content = dashboard_path.read_text()

    assert "local_token" in content
    assert "/api/v1/auth/session" in content
    assert "Authorize this browser" in content


def test_authorize_ui_includes_fragment_bootstrap_and_navigation_links() -> None:
    authorize_path = (
        Path(__file__).resolve().parents[2]
        / "penguin"
        / "web"
        / "static"
        / "authorize.html"
    )
    content = authorize_path.read_text()

    assert "local_token" in content
    assert "/api/v1/auth/session" in content
    assert "/chat" in content
    assert "/dashboard" in content


def test_upload_rejects_spoofed_image_bytes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr("penguin.web.routes.WORKSPACE_PATH", str(tmp_path))
    router.core = SimpleNamespace()
    app = FastAPI()
    app.include_router(router)
    client = TestClient(app)

    response = client.post(
        "/api/v1/upload",
        files={"file": ("fake.png", io.BytesIO(b"not-a-real-image"), "image/png")},
    )

    assert response.status_code == 415
    uploads_dir = tmp_path / "uploads"
    assert not uploads_dir.exists() or list(uploads_dir.iterdir()) == []


def test_provider_credentials_custom_store_path_does_not_warn(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    store_path = tmp_path / "providers.json"
    store_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {"anthropic": {"type": "api", "key": "file-key"}},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", str(store_path))

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        records = provider_credentials_service.get_provider_credentials()

    assert records["anthropic"]["key"] == "file-key"
    assert not caught


def test_provider_credentials_do_not_treat_ollama_host_as_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

    records = provider_credentials_service.get_provider_credentials()

    assert "ollama" not in records


def test_http_auth_does_not_mask_downstream_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "http-test-key")

    from penguin.web.app import create_app

    app = create_app()

    @app.get("/boom")
    async def boom():
        raise RuntimeError("boom")

    client = TestClient(app, raise_server_exceptions=False)
    response = client.get("/boom", headers={"X-API-Key": "http-test-key"})

    assert response.status_code == 500
    assert "AUTHENTICATION_ERROR" not in response.text


@pytest.fixture
def local_auth_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from penguin.web.middleware.auth import AuthenticationMiddleware

    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    router.core = SimpleNamespace(
        conversation_manager=SimpleNamespace(current_agent_id=None)
    )
    app = FastAPI()

    @app.get("/protected")
    async def protected() -> dict[str, bool]:
        return {"ok": True}

    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    app.include_router(router)
    return app


@pytest.fixture
def local_auth_sse_app(monkeypatch: pytest.MonkeyPatch) -> FastAPI:
    from penguin.web.middleware.auth import AuthenticationMiddleware

    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    event_bus = SimpleNamespace(
        subscribe=lambda *args, **kwargs: None,
        unsubscribe=lambda *args, **kwargs: None,
    )
    set_core_instance(SimpleNamespace(event_bus=event_bus))
    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    app.include_router(router)
    app.include_router(sse_router)
    return app


def test_auth_session_endpoint_accepts_startup_token_and_sets_cookie(
    local_auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "startup-token-123")
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    response = client.post(
        "/api/v1/auth/session",
        json={"token": "startup-token-123"},
    )

    assert response.status_code == 200
    assert response.json()["authenticated"] is True
    assert response.json()["method"] == "startup_token"
    assert "penguin_session=" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]


def test_auth_session_get_returns_bootstrap_instructions(
    local_auth_app: FastAPI,
) -> None:
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    response = client.get("/api/v1/auth/session")

    assert response.status_code == 200
    assert "Use POST /api/v1/auth/session" in response.text
    assert "startup token printed by penguin-web" in response.text


def test_auth_session_endpoint_accepts_configured_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from penguin.web.middleware.auth import AuthenticationMiddleware

    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.setenv("PENGUIN_API_KEYS", "configured-key")
    app = FastAPI()
    app.add_middleware(AuthenticationMiddleware, config=AuthConfig())
    app.include_router(router)
    client = TestClient(app, base_url="http://127.0.0.1:9000")

    response = client.post(
        "/api/v1/auth/session",
        json={"token": "configured-key"},
    )

    assert response.status_code == 200
    assert response.json()["method"] == "api_key"
    assert "penguin_session=" in response.headers["set-cookie"]


def test_auth_session_endpoint_is_public_but_rejects_invalid_token(
    local_auth_app: FastAPI,
) -> None:
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    response = client.post("/api/v1/auth/session", json={"token": "bad-token"})

    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid local authorization token"


def test_auth_logout_clears_cookie(local_auth_app: FastAPI) -> None:
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    response = client.post("/api/v1/auth/logout")

    assert response.status_code == 200
    assert response.json() == {"authenticated": False}
    assert "penguin_session=" in response.headers["set-cookie"]
    assert "Max-Age=0" in response.headers["set-cookie"]


def test_http_protected_endpoint_accepts_session_cookie(
    local_auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "startup-token-123")
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    auth_response = client.post(
        "/api/v1/auth/session",
        json={"token": "startup-token-123"},
    )
    assert auth_response.status_code == 200

    response = client.get("/protected")

    assert response.status_code == 200
    assert response.json() == {"ok": True}


@pytest.mark.asyncio
async def test_sse_endpoint_accepts_session_cookie(
    local_auth_sse_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "startup-token-123")
    client = TestClient(local_auth_sse_app, base_url="http://127.0.0.1:9000")

    auth_response = client.post(
        "/api/v1/auth/session",
        json={"token": "startup-token-123"},
    )
    assert auth_response.status_code == 200

    cookie_header = (
        auth_response.headers["set-cookie"].split(";", 1)[0].encode("latin-1")
    )
    messages: list[dict[str, object]] = []
    request_sent = False

    async def receive() -> dict[str, object]:
        nonlocal request_sent
        if not request_sent:
            request_sent = True
            return {"type": "http.request", "body": b"", "more_body": False}
        await asyncio.sleep(0)
        return {"type": "http.disconnect"}

    async def send(message: dict[str, object]) -> None:
        messages.append(message)

    scope = {
        "type": "http",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/api/v1/events/sse",
        "raw_path": b"/api/v1/events/sse",
        "query_string": b"",
        "root_path": "",
        "headers": [(b"cookie", cookie_header)],
        "client": ("127.0.0.1", 9000),
        "server": ("127.0.0.1", 9000),
        "state": {},
    }

    await local_auth_sse_app(scope, receive, send)

    assert any(
        message.get("type") == "http.response.start" and message.get("status") == 200
        for message in messages
    )
    body = b"".join(
        message.get("body", b"")
        for message in messages
        if message.get("type") == "http.response.body"
    )
    assert b"server.connected" in body


def test_websocket_accepts_session_cookie(
    local_auth_app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_AUTH_STARTUP_TOKEN", "startup-token-123")
    client = TestClient(local_auth_app, base_url="http://127.0.0.1:9000")

    auth_response = client.post(
        "/api/v1/auth/session",
        json={"token": "startup-token-123"},
    )
    assert auth_response.status_code == 200
    cookie_header = auth_response.headers["set-cookie"].split(";", 1)[0]

    with client.websocket_connect(
        "/api/v1/events/ws",
        headers={"Cookie": cookie_header},
    ) as websocket:
        assert websocket is not None
