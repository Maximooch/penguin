"""General-purpose provider auth workflow orchestration."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import json
import logging
import os
import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any
from urllib.parse import parse_qs, urlencode, urlparse

import httpx

from penguin.web.services.provider_credentials import (
    get_provider_credential,
    set_provider_credential,
)

_OPENAI_OAUTH_CLIENT_ID_ENV = "PENGUIN_OPENAI_OAUTH_CLIENT_ID"
_OPENAI_OAUTH_CLIENT_ID_DEFAULT = "app_EMoamEEZ73f0CkXaXp7hrann"
_OPENAI_OAUTH_ISSUER = "https://auth.openai.com"
_OPENAI_OAUTH_AUTHORIZE_URL = f"{_OPENAI_OAUTH_ISSUER}/oauth/authorize"
_OPENAI_OAUTH_DEVICE_URL = f"{_OPENAI_OAUTH_ISSUER}/codex/device"
_OPENAI_OAUTH_BROWSER_REDIRECT_URI_ENV = "PENGUIN_OPENAI_OAUTH_REDIRECT_URI"
_OPENAI_OAUTH_BROWSER_REDIRECT_URI_DEFAULT = "http://localhost:1455/auth/callback"
_OPENAI_OAUTH_POLLING_SAFETY_MS = 3000
_OPENAI_OAUTH_TIMEOUT_SECONDS = 300
_PENDING_OAUTH_TTL_SECONDS = 15 * 60

_AUTH_LOCK = RLock()
_PENDING_OAUTH: dict[str, dict[str, Any]] = {}
_CALLBACK_LOCKS_GUARD = RLock()
_CALLBACK_LOCKS: dict[str, asyncio.Lock] = {}

logger = logging.getLogger(__name__)


class ProviderOAuthError(ValueError):
    """Explicit OAuth error with stage metadata for diagnostics."""

    def __init__(
        self,
        *,
        stage: str,
        detail: str,
        provider_id: str,
        method_index: int | None = None,
        status_code: int | None = None,
    ) -> None:
        self.stage = stage
        self.provider_id = provider_id
        self.method_index = method_index
        self.status_code = status_code
        self.detail = detail

        parts = [f"oauth_stage={stage}", f"provider={provider_id}"]
        if method_index is not None:
            parts.append(f"method={method_index}")
        if status_code is not None:
            parts.append(f"status={status_code}")
        parts.append(f"detail={detail}")
        super().__init__(" | ".join(parts))


def _openai_oauth_client_id() -> str:
    configured = os.getenv(_OPENAI_OAUTH_CLIENT_ID_ENV)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return _OPENAI_OAUTH_CLIENT_ID_DEFAULT


def _openai_oauth_client_id_with_source() -> tuple[str, str]:
    configured = os.getenv(_OPENAI_OAUTH_CLIENT_ID_ENV)
    if isinstance(configured, str) and configured.strip():
        return configured.strip(), "env_override"
    return _OPENAI_OAUTH_CLIENT_ID_DEFAULT, "compat_default"


def _openai_oauth_redirect_uri() -> str:
    configured = os.getenv(_OPENAI_OAUTH_BROWSER_REDIRECT_URI_ENV)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return _OPENAI_OAUTH_BROWSER_REDIRECT_URI_DEFAULT


@dataclass
class OAuthAuthorization:
    """Authorization payload returned by provider OAuth authorize calls."""

    url: str
    method: str
    instructions: str

    def to_dict(self) -> dict[str, str]:
        return {
            "url": self.url,
            "method": self.method,
            "instructions": self.instructions,
        }


def _callback_lock(provider_id: str) -> asyncio.Lock:
    with _CALLBACK_LOCKS_GUARD:
        existing = _CALLBACK_LOCKS.get(provider_id)
        if existing is not None:
            return existing
        created = asyncio.Lock()
        _CALLBACK_LOCKS[provider_id] = created
        return created


def _method_definition(provider_id: str, method_index: int) -> dict[str, str]:
    methods = provider_auth_methods({provider_id}).get(provider_id, [])
    if method_index < 0 or method_index >= len(methods):
        raise ProviderOAuthError(
            stage="method_validation",
            detail=(
                f"Invalid auth method index {method_index}; "
                f"available indexes: 0..{max(len(methods) - 1, 0)}"
            ),
            provider_id=provider_id,
            method_index=method_index,
        )
    return methods[method_index]


def _oauth_flow_for_method(provider_id: str, method_index: int) -> str:
    if provider_id != "openai":
        raise ProviderOAuthError(
            stage="method_validation",
            detail="OAuth authorize/callback is implemented for OpenAI only",
            provider_id=provider_id,
            method_index=method_index,
        )
    if method_index == 0:
        return "openai_browser"
    if method_index == 1:
        return "openai_headless"
    raise ProviderOAuthError(
        stage="method_validation",
        detail=(
            "Selected method is not OAuth for OpenAI; "
            "expected method index 0 (browser) or 1 (headless)"
        ),
        provider_id=provider_id,
        method_index=method_index,
    )


def _response_detail(response: httpx.Response) -> str:
    payload_text = ""
    try:
        payload = response.json()
        if isinstance(payload, dict):
            raw_error = payload.get("error")
            if isinstance(raw_error, str) and raw_error.strip():
                payload_text = raw_error.strip()
            elif isinstance(raw_error, dict):
                message = raw_error.get("message")
                code = raw_error.get("code")
                description = raw_error.get("description")
                parts = [str(item) for item in (message, code, description) if item]
                payload_text = " | ".join(parts)
            else:
                payload_text = json.dumps(payload)[:500]
        elif payload is not None:
            payload_text = str(payload)[:500]
    except Exception:
        payload_text = ""

    if not payload_text:
        try:
            payload_text = response.text[:500]
        except Exception:
            payload_text = ""

    if payload_text:
        return payload_text
    return "No response body"


def _is_transient_status(status_code: int) -> bool:
    return status_code in {408, 409, 425, 429, 500, 502, 503, 504}


def _generate_pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode("utf-8")).digest())
        .decode("utf-8")
        .rstrip("=")
    )
    return verifier, challenge


def _parse_browser_callback_code(raw_code: str) -> tuple[str, str | None]:
    value = raw_code.strip()
    if not value:
        return "", None

    if "://" in value:
        parsed = urlparse(value)
        query = parse_qs(parsed.query)
        code = ""
        state = None
        code_values = query.get("code")
        state_values = query.get("state")
        if code_values and isinstance(code_values[0], str):
            code = code_values[0].strip()
        if state_values and isinstance(state_values[0], str):
            state = state_values[0].strip() or None
        return code, state

    if value.startswith("code=") or "&" in value or value.startswith("?"):
        query = parse_qs(value.lstrip("?"))
        code = ""
        state = None
        code_values = query.get("code")
        state_values = query.get("state")
        if code_values and isinstance(code_values[0], str):
            code = code_values[0].strip()
        if state_values and isinstance(state_values[0], str):
            state = state_values[0].strip() or None
        if code:
            return code, state

    return value, None


def _base64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def _extract_openai_account_id(tokens: dict[str, Any]) -> str | None:
    for token_key in ("id_token", "access_token"):
        raw = tokens.get(token_key)
        if not isinstance(raw, str) or "." not in raw:
            continue
        parts = raw.split(".")
        if len(parts) != 3:
            continue
        try:
            claims = json.loads(_base64url_decode(parts[1]).decode("utf-8"))
        except Exception:
            continue
        if not isinstance(claims, dict):
            continue

        direct = claims.get("chatgpt_account_id")
        if isinstance(direct, str) and direct:
            return direct

        auth_claim = claims.get("https://api.openai.com/auth")
        if isinstance(auth_claim, dict):
            nested = auth_claim.get("chatgpt_account_id")
            if isinstance(nested, str) and nested:
                return nested

        organizations = claims.get("organizations")
        if isinstance(organizations, list) and organizations:
            first = organizations[0]
            if isinstance(first, dict):
                org_id = first.get("id")
                if isinstance(org_id, str) and org_id:
                    return org_id

    return None


def _cleanup_pending_oauth() -> None:
    now = time.monotonic()
    stale = []
    for provider_id, pending in _PENDING_OAUTH.items():
        created_at = pending.get("created_at")
        if isinstance(created_at, (int, float)):
            if now - float(created_at) > _PENDING_OAUTH_TTL_SECONDS:
                stale.append(provider_id)
    for provider_id in stale:
        _PENDING_OAUTH.pop(provider_id, None)


def provider_auth_methods(
    provider_ids: set[str] | None = None,
) -> dict[str, list[dict[str, str]]]:
    """Return auth methods per provider id."""
    ids = set(provider_ids or set())
    ids.add("openai")

    methods: dict[str, list[dict[str, str]]] = {}
    for provider_id in sorted(ids):
        if provider_id == "openai":
            methods[provider_id] = [
                {"type": "oauth", "label": "ChatGPT Pro/Plus (browser)"},
                {"type": "oauth", "label": "ChatGPT Pro/Plus (headless)"},
                {"type": "api", "label": "Manually enter API key"},
            ]
        else:
            methods[provider_id] = [{"type": "api", "label": "API key"}]
    return methods


async def _openai_exchange_authorization_code(
    *,
    client: httpx.AsyncClient,
    authorization_code: str,
    code_verifier: str,
    redirect_uri: str,
    provider_id: str,
    method_index: int,
    stage_prefix: str,
) -> dict[str, Any]:
    client_id, client_id_source = _openai_oauth_client_id_with_source()
    logger.info(
        "openai.oauth.%s exchanging authorization code "
        "provider=%s method=%s client_id_source=%s",
        stage_prefix,
        provider_id,
        method_index,
        client_id_source,
    )

    token_response = await client.post(
        f"{_OPENAI_OAUTH_ISSUER}/oauth/token",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        data={
            "grant_type": "authorization_code",
            "code": authorization_code,
            "redirect_uri": redirect_uri,
            "client_id": client_id,
            "code_verifier": code_verifier,
        },
    )
    if token_response.status_code >= 400:
        detail = _response_detail(token_response)
        raise ProviderOAuthError(
            stage=f"{stage_prefix}.token_exchange",
            detail=(f"OpenAI OAuth token exchange failed. response_detail={detail}"),
            provider_id=provider_id,
            method_index=method_index,
            status_code=token_response.status_code,
        )

    tokens = token_response.json() if token_response.content else {}
    access = tokens.get("access_token")
    refresh = tokens.get("refresh_token")
    expires_in = tokens.get("expires_in")

    if not isinstance(access, str) or not access:
        raise ProviderOAuthError(
            stage=f"{stage_prefix}.token_payload",
            detail="OAuth token payload missing access_token",
            provider_id=provider_id,
            method_index=method_index,
        )
    if not isinstance(refresh, str) or not refresh:
        raise ProviderOAuthError(
            stage=f"{stage_prefix}.token_payload",
            detail="OAuth token payload missing refresh_token",
            provider_id=provider_id,
            method_index=method_index,
        )

    try:
        expires_ms = int(time.time() * 1000) + int(expires_in or 3600) * 1000
    except Exception:
        expires_ms = int(time.time() * 1000) + 3600 * 1000

    record: dict[str, Any] = {
        "type": "oauth",
        "access": access,
        "refresh": refresh,
        "expires": expires_ms,
    }
    account_id = _extract_openai_account_id(tokens)
    if account_id:
        record["accountId"] = account_id
    return record


async def _openai_refresh_oauth_record(
    *,
    refresh_token: str,
    provider_id: str,
    method_index: int | None,
) -> dict[str, Any]:
    client_id, client_id_source = _openai_oauth_client_id_with_source()
    logger.info(
        "openai.oauth.refresh begin provider=%s method=%s client_id_source=%s",
        provider_id,
        method_index,
        client_id_source,
    )

    max_attempts = 2
    backoff_seconds = 0.4
    async with httpx.AsyncClient(timeout=20.0) as client:
        for attempt in range(1, max_attempts + 1):
            response = await client.post(
                f"{_OPENAI_OAUTH_ISSUER}/oauth/token",
                headers={"Content-Type": "application/x-www-form-urlencoded"},
                data={
                    "grant_type": "refresh_token",
                    "refresh_token": refresh_token,
                    "client_id": client_id,
                },
            )

            if response.status_code < 400:
                payload = response.json() if response.content else {}
                access = payload.get("access_token")
                refresh = payload.get("refresh_token")
                expires_in = payload.get("expires_in")

                if not isinstance(access, str) or not access:
                    raise ProviderOAuthError(
                        stage="refresh.token_payload",
                        detail="OAuth refresh payload missing access_token",
                        provider_id=provider_id,
                        method_index=method_index,
                    )

                refresh_value = refresh_token
                if isinstance(refresh, str) and refresh.strip():
                    refresh_value = refresh.strip()

                try:
                    expires_ms = (
                        int(time.time() * 1000) + int(expires_in or 3600) * 1000
                    )
                except Exception:
                    expires_ms = int(time.time() * 1000) + 3600 * 1000

                refreshed: dict[str, Any] = {
                    "type": "oauth",
                    "access": access,
                    "refresh": refresh_value,
                    "expires": expires_ms,
                }
                account_id = _extract_openai_account_id(payload)
                if account_id:
                    refreshed["accountId"] = account_id
                return refreshed

            status_code = response.status_code
            detail = _response_detail(response)
            transient = _is_transient_status(status_code)
            logger.error(
                "openai.oauth.refresh failure provider=%s method=%s attempt=%s "
                "status=%s transient=%s detail=%s",
                provider_id,
                method_index,
                attempt,
                status_code,
                transient,
                detail,
            )
            if transient and attempt < max_attempts:
                await asyncio.sleep(backoff_seconds)
                backoff_seconds *= 2
                continue

            raise ProviderOAuthError(
                stage="refresh.token_exchange",
                detail=f"OpenAI OAuth refresh failed. response_detail={detail}",
                provider_id=provider_id,
                method_index=method_index,
                status_code=status_code,
            )

    raise ProviderOAuthError(
        stage="refresh.unreachable",
        detail="OpenAI OAuth refresh failed without response",
        provider_id=provider_id,
        method_index=method_index,
    )


async def _openai_authorize_browser_flow(
    *,
    provider_id: str,
    method_index: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    client_id, client_id_source = _openai_oauth_client_id_with_source()
    redirect_uri = _openai_oauth_redirect_uri()
    state = secrets.token_urlsafe(32)
    code_verifier, code_challenge = _generate_pkce_pair()

    logger.info(
        "openai.oauth.authorize.browser provider=%s method=%s "
        "client_id_source=%s redirect_uri=%s",
        provider_id,
        method_index,
        client_id_source,
        redirect_uri,
    )

    authorize_url = f"{_OPENAI_OAUTH_AUTHORIZE_URL}?" + urlencode(
        {
            "response_type": "code",
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": "openid profile email offline_access",
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
            "id_token_add_organizations": "true",
            "codex_cli_simplified_flow": "true",
            "state": state,
            "originator": "penguin",
        }
    )

    pending = {
        "type": "openai_browser",
        "method_index": method_index,
        "created_at": time.monotonic(),
        "redirect_uri": redirect_uri,
        "state": state,
        "code_verifier": code_verifier,
    }

    auth = OAuthAuthorization(
        url=authorize_url,
        method="code",
        instructions=(
            "Complete authorization in your browser, then paste either the full "
            "callback URL or the authorization code into Penguin."
        ),
    )
    return auth.to_dict(), pending


async def _openai_authorize_device_flow(
    *,
    provider_id: str,
    method_index: int,
) -> tuple[dict[str, str], dict[str, Any]]:
    client_id, client_id_source = _openai_oauth_client_id_with_source()
    logger.info(
        "openai.oauth.authorize.headless provider=%s method=%s client_id_source=%s",
        provider_id,
        method_index,
        client_id_source,
    )

    async with httpx.AsyncClient(timeout=20.0) as client:
        response = await client.post(
            f"{_OPENAI_OAUTH_ISSUER}/api/accounts/deviceauth/usercode",
            headers={
                "Content-Type": "application/json",
                "User-Agent": "penguin-web",
            },
            json={"client_id": client_id},
        )
        if response.status_code >= 400:
            detail = _response_detail(response)
            raise ProviderOAuthError(
                stage="authorize.headless.device_code",
                detail=(
                    f"OpenAI device authorization failed. response_detail={detail}"
                ),
                provider_id=provider_id,
                method_index=method_index,
                status_code=response.status_code,
            )
        payload = response.json() if response.content else {}

    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code")
    interval_raw = payload.get("interval")
    if not isinstance(device_auth_id, str) or not device_auth_id:
        raise ProviderOAuthError(
            stage="authorize.headless.payload",
            detail="OpenAI device authorization payload missing device_auth_id",
            provider_id=provider_id,
            method_index=method_index,
        )
    if not isinstance(user_code, str) or not user_code:
        raise ProviderOAuthError(
            stage="authorize.headless.payload",
            detail="OpenAI device authorization payload missing user_code",
            provider_id=provider_id,
            method_index=method_index,
        )

    try:
        interval_value = (
            int(interval_raw) if isinstance(interval_raw, (int, float, str)) else 5
        )
        interval_seconds = max(interval_value, 1)
    except Exception:
        interval_seconds = 5

    pending = {
        "type": "openai_headless",
        "method_index": method_index,
        "device_auth_id": device_auth_id,
        "user_code": user_code,
        "interval_seconds": interval_seconds,
        "created_at": time.monotonic(),
        "nonce": secrets.token_urlsafe(12),
    }
    auth = OAuthAuthorization(
        url=_OPENAI_OAUTH_DEVICE_URL,
        method="auto",
        instructions=f"Enter code: {user_code}",
    )
    return auth.to_dict(), pending


async def _openai_complete_browser_flow(
    *,
    pending: dict[str, Any],
    provider_id: str,
    method_index: int,
    code: str | None,
) -> dict[str, Any]:
    if not isinstance(code, str) or not code.strip():
        raise ProviderOAuthError(
            stage="callback.browser.code",
            detail=(
                "Browser OAuth callback requires a code. Paste either the full "
                "callback URL or the authorization code."
            ),
            provider_id=provider_id,
            method_index=method_index,
        )

    parsed_code, parsed_state = _parse_browser_callback_code(code)
    if not parsed_code:
        raise ProviderOAuthError(
            stage="callback.browser.code_parse",
            detail="Unable to parse authorization code from callback input",
            provider_id=provider_id,
            method_index=method_index,
        )

    expected_state = pending.get("state")
    if (
        isinstance(expected_state, str)
        and expected_state
        and isinstance(parsed_state, str)
        and parsed_state
        and parsed_state != expected_state
    ):
        raise ProviderOAuthError(
            stage="callback.browser.state",
            detail="Callback state does not match pending authorization state",
            provider_id=provider_id,
            method_index=method_index,
        )

    if not parsed_state:
        logger.warning(
            "openai.oauth.callback.browser missing callback state "
            "provider=%s method=%s",
            provider_id,
            method_index,
        )

    code_verifier = pending.get("code_verifier")
    redirect_uri = pending.get("redirect_uri")
    if not isinstance(code_verifier, str) or not code_verifier:
        raise ProviderOAuthError(
            stage="callback.browser.pending",
            detail="Pending browser OAuth state missing code_verifier",
            provider_id=provider_id,
            method_index=method_index,
        )
    if not isinstance(redirect_uri, str) or not redirect_uri:
        raise ProviderOAuthError(
            stage="callback.browser.pending",
            detail="Pending browser OAuth state missing redirect_uri",
            provider_id=provider_id,
            method_index=method_index,
        )

    async with httpx.AsyncClient(timeout=20.0) as client:
        return await _openai_exchange_authorization_code(
            client=client,
            authorization_code=parsed_code,
            code_verifier=code_verifier,
            redirect_uri=redirect_uri,
            provider_id=provider_id,
            method_index=method_index,
            stage_prefix="callback.browser",
        )


async def _openai_complete_device_flow(
    *,
    pending: dict[str, Any],
    provider_id: str,
    method_index: int,
) -> dict[str, Any]:
    device_auth_id = pending.get("device_auth_id")
    user_code = pending.get("user_code")
    raw_interval = pending.get("interval_seconds")
    try:
        interval_seconds = (
            int(raw_interval) if isinstance(raw_interval, (int, float, str)) else 5
        )
    except Exception:
        interval_seconds = 5

    if not isinstance(device_auth_id, str) or not isinstance(user_code, str):
        raise ProviderOAuthError(
            stage="callback.headless.pending",
            detail="Corrupt pending OAuth state for device flow",
            provider_id=provider_id,
            method_index=method_index,
        )

    deadline = time.monotonic() + _OPENAI_OAUTH_TIMEOUT_SECONDS
    async with httpx.AsyncClient(timeout=20.0) as client:
        while time.monotonic() < deadline:
            poll = await client.post(
                f"{_OPENAI_OAUTH_ISSUER}/api/accounts/deviceauth/token",
                headers={
                    "Content-Type": "application/json",
                    "User-Agent": "penguin-web",
                },
                json={
                    "device_auth_id": device_auth_id,
                    "user_code": user_code,
                },
            )

            if poll.status_code == 200:
                poll_payload = poll.json() if poll.content else {}
                authorization_code = poll_payload.get("authorization_code")
                code_verifier = poll_payload.get("code_verifier")
                if not isinstance(authorization_code, str) or not authorization_code:
                    raise ProviderOAuthError(
                        stage="callback.headless.poll_payload",
                        detail="OpenAI OAuth poll payload missing authorization_code",
                        provider_id=provider_id,
                        method_index=method_index,
                    )
                if not isinstance(code_verifier, str) or not code_verifier:
                    raise ProviderOAuthError(
                        stage="callback.headless.poll_payload",
                        detail="OpenAI OAuth poll payload missing code_verifier",
                        provider_id=provider_id,
                        method_index=method_index,
                    )

                return await _openai_exchange_authorization_code(
                    client=client,
                    authorization_code=authorization_code,
                    code_verifier=code_verifier,
                    redirect_uri=f"{_OPENAI_OAUTH_ISSUER}/deviceauth/callback",
                    provider_id=provider_id,
                    method_index=method_index,
                    stage_prefix="callback.headless",
                )

            if poll.status_code in (403, 404):
                await asyncio.sleep(
                    interval_seconds + _OPENAI_OAUTH_POLLING_SAFETY_MS / 1000.0
                )
                continue

            detail = _response_detail(poll)
            raise ProviderOAuthError(
                stage="callback.headless.poll",
                detail=f"OpenAI OAuth polling failed. response_detail={detail}",
                provider_id=provider_id,
                method_index=method_index,
                status_code=poll.status_code,
            )

    raise ProviderOAuthError(
        stage="callback.headless.timeout",
        detail="OpenAI OAuth device flow timed out waiting for user authorization",
        provider_id=provider_id,
        method_index=method_index,
    )


async def authorize_provider_oauth(
    provider_id: str, method_index: int
) -> dict[str, Any]:
    """Start provider OAuth flow for a specific method index."""
    pid = provider_id.strip().lower()
    method = _method_definition(pid, method_index)
    if method.get("type") != "oauth":
        raise ProviderOAuthError(
            stage="authorize.method",
            detail="Selected auth method is not OAuth",
            provider_id=pid,
            method_index=method_index,
        )

    flow = _oauth_flow_for_method(pid, method_index)
    if flow == "openai_browser":
        auth_payload, pending = await _openai_authorize_browser_flow(
            provider_id=pid,
            method_index=method_index,
        )
    elif flow == "openai_headless":
        auth_payload, pending = await _openai_authorize_device_flow(
            provider_id=pid,
            method_index=method_index,
        )
    else:
        raise ProviderOAuthError(
            stage="authorize.flow",
            detail=f"Unsupported OAuth flow '{flow}'",
            provider_id=pid,
            method_index=method_index,
        )

    with _AUTH_LOCK:
        _cleanup_pending_oauth()
        _PENDING_OAUTH[pid] = pending
    logger.info(
        "provider.oauth.authorize created pending state provider=%s method=%s flow=%s",
        pid,
        method_index,
        flow,
    )
    return auth_payload


async def callback_provider_oauth(
    provider_id: str,
    method_index: int,
    code: str | None = None,
) -> bool:
    """Finish provider OAuth flow for a specific method index."""
    pid = provider_id.strip().lower()
    method = _method_definition(pid, method_index)
    if method.get("type") != "oauth":
        raise ProviderOAuthError(
            stage="callback.method",
            detail="Selected auth method is not OAuth",
            provider_id=pid,
            method_index=method_index,
        )

    lock = _callback_lock(pid)
    async with lock:
        with _AUTH_LOCK:
            _cleanup_pending_oauth()
            pending = dict(_PENDING_OAUTH.get(pid) or {})

        if not pending:
            raise ProviderOAuthError(
                stage="callback.pending",
                detail=(
                    "No pending OAuth authorization for provider. "
                    "Run provider.oauth.authorize before callback."
                ),
                provider_id=pid,
                method_index=method_index,
            )

        pending_method = pending.get("method_index")
        if pending_method != method_index:
            raise ProviderOAuthError(
                stage="callback.method_mismatch",
                detail=(
                    "OAuth callback method does not match pending authorization "
                    f"(pending={pending_method}, callback={method_index})"
                ),
                provider_id=pid,
                method_index=method_index,
            )

        flow = str(pending.get("type") or "").strip().lower()
        if flow == "openai_browser":
            record = await _openai_complete_browser_flow(
                pending=pending,
                provider_id=pid,
                method_index=method_index,
                code=code,
            )
        elif flow == "openai_headless":
            record = await _openai_complete_device_flow(
                pending=pending,
                provider_id=pid,
                method_index=method_index,
            )
        else:
            raise ProviderOAuthError(
                stage="callback.flow",
                detail=f"Unsupported pending OAuth flow '{flow}'",
                provider_id=pid,
                method_index=method_index,
            )

        set_provider_credential(pid, record)
        with _AUTH_LOCK:
            _PENDING_OAUTH.pop(pid, None)
        logger.info(
            "provider.oauth.callback success provider=%s method=%s flow=%s "
            "account_id_present=%s",
            pid,
            method_index,
            flow,
            bool(record.get("accountId")),
        )
        return True


async def refresh_provider_oauth(
    provider_id: str,
    *,
    credential_record: dict[str, Any] | None = None,
    method_index: int | None = None,
) -> dict[str, Any]:
    """Refresh OAuth credentials for a provider and persist the result."""
    pid = provider_id.strip().lower()
    if pid != "openai":
        raise ProviderOAuthError(
            stage="refresh.method_validation",
            detail="OAuth refresh is currently implemented for OpenAI only",
            provider_id=pid,
            method_index=method_index,
        )

    record = dict(credential_record or {})
    if not record:
        existing = get_provider_credential(pid)
        if isinstance(existing, dict):
            record = dict(existing)

    if record.get("type") != "oauth":
        raise ProviderOAuthError(
            stage="refresh.record_validation",
            detail="No OAuth credential record available for provider",
            provider_id=pid,
            method_index=method_index,
        )

    refresh = record.get("refresh")
    if not isinstance(refresh, str) or not refresh.strip():
        raise ProviderOAuthError(
            stage="refresh.record_validation",
            detail="OAuth credential record missing refresh token",
            provider_id=pid,
            method_index=method_index,
        )

    lock = _callback_lock(pid)
    async with lock:
        refreshed = await _openai_refresh_oauth_record(
            refresh_token=refresh.strip(),
            provider_id=pid,
            method_index=method_index,
        )
        if "accountId" not in refreshed:
            account_id = record.get("accountId")
            if isinstance(account_id, str) and account_id.strip():
                refreshed["accountId"] = account_id.strip()

        set_provider_credential(pid, refreshed)
        logger.info(
            "provider.oauth.refresh success provider=%s method=%s "
            "account_id_present=%s",
            pid,
            method_index,
            bool(refreshed.get("accountId")),
        )
        return refreshed
