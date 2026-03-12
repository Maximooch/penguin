"""Tests for OpenCode provider auth service helpers."""

from __future__ import annotations

import base64
import json
import time
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from pathlib import Path

import pytest

from penguin.web.services import opencode_provider as provider_service


class _FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any] | None = None) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.content = (
            json.dumps(self._payload).encode("utf-8") if payload is not None else b""
        )

    def json(self) -> dict[str, Any]:
        return dict(self._payload)


def _b64url(data: dict[str, Any]) -> str:
    raw = json.dumps(data, separators=(",", ":")).encode("utf-8")
    return base64.urlsafe_b64encode(raw).decode("utf-8").rstrip("=")


def _jwt(payload: dict[str, Any]) -> str:
    return f"{_b64url({'alg': 'none', 'typ': 'JWT'})}.{_b64url(payload)}.signature"


@pytest.fixture(autouse=True)
def _clear_pending_oauth() -> None:
    provider_service._PENDING_OAUTH.clear()
    yield
    provider_service._PENDING_OAUTH.clear()


@pytest.mark.asyncio
async def test_provider_oauth_authorize_headless_sets_pending_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        async def post(self, url: str, headers=None, json=None, data=None):  # type: ignore[no-untyped-def]
            del headers, json, data
            calls.append(url)
            return _FakeResponse(
                200,
                {
                    "device_auth_id": "device-auth-123",
                    "user_code": "ABCD-EFGH",
                    "interval": 5,
                },
            )

    monkeypatch.setattr(provider_service.httpx, "AsyncClient", _FakeAsyncClient)

    result = await provider_service.provider_oauth_authorize("openai", 1)

    assert calls
    assert result["url"] == provider_service._OPENAI_OAUTH_DEVICE_URL
    assert result["method"] == "auto"
    assert "ABCD-EFGH" in result["instructions"]
    assert (
        provider_service._PENDING_OAUTH["openai"]["device_auth_id"] == "device-auth-123"
    )
    assert provider_service._PENDING_OAUTH["openai"]["type"] == "openai_headless"
    assert provider_service._PENDING_OAUTH["openai"]["method_index"] == 1


@pytest.mark.asyncio
async def test_provider_oauth_authorize_browser_is_method_zero() -> None:
    result = await provider_service.provider_oauth_authorize("openai", 0)

    assert result["method"] == "code"
    assert "oauth/authorize" in result["url"]
    assert "authorization code" in result["instructions"].lower()
    assert provider_service._PENDING_OAUTH["openai"]["type"] == "openai_browser"
    assert provider_service._PENDING_OAUTH["openai"]["method_index"] == 0


@pytest.mark.asyncio
async def test_provider_oauth_callback_browser_requires_code() -> None:
    await provider_service.provider_oauth_authorize("openai", 0)

    with pytest.raises(ValueError) as exc:
        await provider_service.provider_oauth_callback("openai", 0)

    assert "requires a code" in str(exc.value)


@pytest.mark.asyncio
async def test_provider_oauth_callback_browser_rejects_state_mismatch() -> None:
    await provider_service.provider_oauth_authorize("openai", 0)

    with pytest.raises(ValueError) as exc:
        await provider_service.provider_oauth_callback(
            "openai",
            0,
            code="http://localhost:1455/auth/callback?code=abc123&state=wrong",
        )

    assert "state does not match" in str(exc.value)


@pytest.mark.asyncio
async def test_provider_oauth_callback_persists_oauth_record(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_oauth.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

    id_token = _jwt({"chatgpt_account_id": "acct_123"})
    calls: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        async def post(self, url: str, headers=None, json=None, data=None):  # type: ignore[no-untyped-def]
            del headers, json, data
            calls.append(url)
            if url.endswith("/api/accounts/deviceauth/usercode"):
                return _FakeResponse(
                    200,
                    {
                        "device_auth_id": "device-auth-abc",
                        "user_code": "WXYZ-1234",
                        "interval": 1,
                    },
                )
            if url.endswith("/api/accounts/deviceauth/token"):
                return _FakeResponse(
                    200,
                    {
                        "authorization_code": "auth-code-xyz",
                        "code_verifier": "code-verifier-xyz",
                    },
                )
            if url.endswith("/oauth/token"):
                return _FakeResponse(
                    200,
                    {
                        "access_token": "access-token-xyz",
                        "refresh_token": "refresh-token-xyz",
                        "expires_in": 1800,
                        "id_token": id_token,
                    },
                )
            return _FakeResponse(500, {})

    monkeypatch.setattr(provider_service.httpx, "AsyncClient", _FakeAsyncClient)

    await provider_service.provider_oauth_authorize("openai", 1)
    success = await provider_service.provider_oauth_callback("openai", 1)

    assert success is True
    assert any(url.endswith("/oauth/token") for url in calls)
    records = provider_service.get_provider_auth_records()
    openai_record = records["openai"]
    assert openai_record["type"] == "oauth"
    assert openai_record["access"] == "access-token-xyz"
    assert openai_record["refresh"] == "refresh-token-xyz"
    assert openai_record["accountId"] == "acct_123"
    assert openai_record["expires"] > int(time.time() * 1000)
    assert "openai" not in provider_service._PENDING_OAUTH


@pytest.mark.asyncio
async def test_provider_oauth_respects_client_id_env_override(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(tmp_path / "auth_env.json"))
    monkeypatch.setenv("PENGUIN_OPENAI_OAUTH_CLIENT_ID", "penguin-client-id-test")

    seen: dict[str, str] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        async def post(self, url: str, headers=None, json=None, data=None):  # type: ignore[no-untyped-def]
            del headers
            if url.endswith("/api/accounts/deviceauth/usercode"):
                if isinstance(json, dict):
                    seen["authorize_client_id"] = str(json.get("client_id"))
                return _FakeResponse(
                    200,
                    {
                        "device_auth_id": "device-auth-env",
                        "user_code": "ENV-1234",
                        "interval": 1,
                    },
                )
            if url.endswith("/api/accounts/deviceauth/token"):
                return _FakeResponse(
                    200,
                    {
                        "authorization_code": "auth-code-env",
                        "code_verifier": "code-verifier-env",
                    },
                )
            if url.endswith("/oauth/token"):
                if isinstance(data, dict):
                    seen["token_client_id"] = str(data.get("client_id"))
                return _FakeResponse(
                    200,
                    {
                        "access_token": "access-token-env",
                        "refresh_token": "refresh-token-env",
                        "expires_in": 1800,
                    },
                )
            return _FakeResponse(500, {})

    monkeypatch.setattr(provider_service.httpx, "AsyncClient", _FakeAsyncClient)

    await provider_service.provider_oauth_authorize("openai", 1)
    ok = await provider_service.provider_oauth_callback("openai", 1)
    assert ok is True
    assert seen["authorize_client_id"] == "penguin-client-id-test"
    assert seen["token_client_id"] == "penguin-client-id-test"


@pytest.mark.asyncio
async def test_provider_oauth_callback_requires_pending_state() -> None:
    with pytest.raises(ValueError) as exc:
        await provider_service.provider_oauth_callback("openai", 1)
    assert "No pending OAuth authorization" in str(exc.value)


@pytest.mark.asyncio
async def test_provider_oauth_refresh_updates_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_refresh.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

    provider_service.set_provider_auth_record(
        "openai",
        {
            "type": "oauth",
            "access": "access-old",
            "refresh": "refresh-old",
            "expires": 1,
            "accountId": "acct_old",
        },
    )

    calls: list[str] = []

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        async def post(self, url: str, headers=None, json=None, data=None):  # type: ignore[no-untyped-def]
            del headers, json
            calls.append(url)
            if url.endswith("/oauth/token"):
                assert isinstance(data, dict)
                assert data["grant_type"] == "refresh_token"
                assert data["refresh_token"] == "refresh-old"
                return _FakeResponse(
                    200,
                    {
                        "access_token": "access-new",
                        "expires_in": 1800,
                    },
                )
            return _FakeResponse(500, {})

    monkeypatch.setattr(provider_service.httpx, "AsyncClient", _FakeAsyncClient)

    refreshed = await provider_service.provider_auth_service.refresh_provider_oauth(
        "openai"
    )
    assert refreshed["access"] == "access-new"
    assert refreshed["refresh"] == "refresh-old"
    assert refreshed["accountId"] == "acct_old"
    assert any(url.endswith("/oauth/token") for url in calls)

    persisted = provider_service.get_provider_auth_records()["openai"]
    assert persisted["access"] == "access-new"
    assert persisted["refresh"] == "refresh-old"
    assert persisted["accountId"] == "acct_old"


@pytest.mark.asyncio
async def test_provider_oauth_refresh_requires_refresh_token() -> None:
    with pytest.raises(ValueError) as exc:
        await provider_service.provider_auth_service.refresh_provider_oauth(
            "openai",
            credential_record={
                "type": "oauth",
                "access": "access-only",
                "expires": 1,
            },
        )

    assert "missing refresh token" in str(exc.value)
