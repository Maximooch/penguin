"""General-purpose provider auth workflow orchestration."""

from __future__ import annotations

import asyncio
import base64
import json
import os
import secrets
import time
from dataclasses import dataclass
from threading import RLock
from typing import Any, Optional

import httpx

from penguin.web.services.provider_credentials import set_provider_credential

_OPENAI_OAUTH_CLIENT_ID_ENV = "PENGUIN_OPENAI_OAUTH_CLIENT_ID"
_OPENAI_OAUTH_CLIENT_ID_DEFAULT = "app_EMoamEEZ73f0CkXaXp7hrann"
_OPENAI_OAUTH_ISSUER = "https://auth.openai.com"
_OPENAI_OAUTH_DEVICE_URL = f"{_OPENAI_OAUTH_ISSUER}/codex/device"
_OPENAI_OAUTH_POLLING_SAFETY_MS = 3000
_OPENAI_OAUTH_TIMEOUT_SECONDS = 300
_PENDING_OAUTH_TTL_SECONDS = 15 * 60

_AUTH_LOCK = RLock()
_PENDING_OAUTH: dict[str, dict[str, Any]] = {}


def _openai_oauth_client_id() -> str:
    configured = os.getenv(_OPENAI_OAUTH_CLIENT_ID_ENV)
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    return _OPENAI_OAUTH_CLIENT_ID_DEFAULT


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


def _base64url_decode(data: str) -> bytes:
    padding = "=" * ((4 - len(data) % 4) % 4)
    return base64.urlsafe_b64decode((data + padding).encode("utf-8"))


def _extract_openai_account_id(tokens: dict[str, Any]) -> Optional[str]:
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
    provider_ids: Optional[set[str]] = None,
) -> dict[str, list[dict[str, str]]]:
    """Return auth methods per provider id."""
    ids = set(provider_ids or set())
    ids.add("openai")

    methods: dict[str, list[dict[str, str]]] = {}
    for provider_id in sorted(ids):
        if provider_id == "openai":
            methods[provider_id] = [
                {"type": "oauth", "label": "ChatGPT Pro/Plus (headless)"},
                {"type": "api", "label": "API key"},
            ]
        else:
            methods[provider_id] = [{"type": "api", "label": "API key"}]
    return methods


async def _openai_authorize_device_flow() -> tuple[dict[str, str], dict[str, Any]]:
    client_id = _openai_oauth_client_id()
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
            raise ValueError(
                f"OpenAI device authorization failed ({response.status_code})"
            )
        payload = response.json() if response.content else {}

    device_auth_id = payload.get("device_auth_id")
    user_code = payload.get("user_code")
    interval_raw = payload.get("interval")
    if not isinstance(device_auth_id, str) or not device_auth_id:
        raise ValueError("OpenAI device authorization did not return device_auth_id")
    if not isinstance(user_code, str) or not user_code:
        raise ValueError("OpenAI device authorization did not return user_code")

    try:
        interval_value = (
            int(interval_raw) if isinstance(interval_raw, (int, float, str)) else 5
        )
        interval_seconds = max(interval_value, 1)
    except Exception:
        interval_seconds = 5

    pending = {
        "type": "openai_device",
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


async def _openai_complete_device_flow(pending: dict[str, Any]) -> dict[str, Any]:
    client_id = _openai_oauth_client_id()
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
        raise ValueError("Corrupt pending OAuth state")

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
                    raise ValueError("OpenAI OAuth poll missing authorization_code")
                if not isinstance(code_verifier, str) or not code_verifier:
                    raise ValueError("OpenAI OAuth poll missing code_verifier")

                token_response = await client.post(
                    f"{_OPENAI_OAUTH_ISSUER}/oauth/token",
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    data={
                        "grant_type": "authorization_code",
                        "code": authorization_code,
                        "redirect_uri": f"{_OPENAI_OAUTH_ISSUER}/deviceauth/callback",
                        "client_id": client_id,
                        "code_verifier": code_verifier,
                    },
                )
                if token_response.status_code >= 400:
                    raise ValueError(
                        f"OpenAI OAuth token exchange failed ({token_response.status_code})"
                    )

                tokens = token_response.json() if token_response.content else {}
                access = tokens.get("access_token")
                refresh = tokens.get("refresh_token")
                expires_in = tokens.get("expires_in")

                if not isinstance(access, str) or not access:
                    raise ValueError("OpenAI OAuth response missing access_token")
                if not isinstance(refresh, str) or not refresh:
                    raise ValueError("OpenAI OAuth response missing refresh_token")

                try:
                    expires_ms = (
                        int(time.time() * 1000) + int(expires_in or 3600) * 1000
                    )
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

            if poll.status_code in (403, 404):
                await asyncio.sleep(
                    interval_seconds + _OPENAI_OAUTH_POLLING_SAFETY_MS / 1000.0
                )
                continue

            raise ValueError(f"OpenAI OAuth polling failed ({poll.status_code})")

    raise ValueError("OpenAI OAuth authorization timed out")


async def authorize_provider_oauth(
    provider_id: str, method_index: int
) -> dict[str, Any]:
    """Start provider OAuth flow for a specific method index."""
    pid = provider_id.strip().lower()
    methods = provider_auth_methods({pid}).get(pid, [])
    if method_index < 0 or method_index >= len(methods):
        raise ValueError("Invalid auth method index")
    if methods[method_index].get("type") != "oauth":
        raise ValueError("Selected auth method is not OAuth")

    if pid != "openai":
        raise ValueError("OAuth authorize is currently implemented for OpenAI only")

    auth_payload, pending = await _openai_authorize_device_flow()
    with _AUTH_LOCK:
        _cleanup_pending_oauth()
        _PENDING_OAUTH[pid] = pending
    return auth_payload


async def callback_provider_oauth(
    provider_id: str,
    method_index: int,
    code: Optional[str] = None,
) -> bool:
    """Finish provider OAuth flow for a specific method index."""
    del code  # Not used by current OpenAI device flow.
    pid = provider_id.strip().lower()
    methods = provider_auth_methods({pid}).get(pid, [])
    if method_index < 0 or method_index >= len(methods):
        raise ValueError("Invalid auth method index")
    if methods[method_index].get("type") != "oauth":
        raise ValueError("Selected auth method is not OAuth")

    if pid != "openai":
        raise ValueError("OAuth callback is currently implemented for OpenAI only")

    with _AUTH_LOCK:
        _cleanup_pending_oauth()
        pending = dict(_PENDING_OAUTH.get(pid) or {})
    if not pending:
        raise ValueError("No pending OAuth authorization for provider")
    if pending.get("type") != "openai_device":
        raise ValueError("Unsupported pending OAuth flow")

    record = await _openai_complete_device_flow(pending)
    set_provider_credential(pid, record)

    with _AUTH_LOCK:
        _PENDING_OAUTH.pop(pid, None)
    return True
