"""A provider OAuth callback only finishes the authorization it belongs to.

Covers SM-49: a completed callback removed the provider's pending entry even
when a newer authorization had replaced it, so the newer one's callback then
failed; and right after a completion, any explicitly pasted code was accepted
as success.
"""

from __future__ import annotations

import time
from typing import Any

import pytest

from penguin.web.services import provider_auth
from penguin.web.services.provider_auth import ProviderOAuthError

PROVIDER = "openai"


@pytest.fixture
def pending(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    table: dict[str, dict[str, Any]] = {}
    monkeypatch.setattr(provider_auth, "_PENDING_OAUTH", table)
    monkeypatch.setattr(provider_auth, "_RECENT_OAUTH_COMPLETIONS", {})
    monkeypatch.setattr(provider_auth, "_persist_provider_credential", lambda *_a: None)
    return table


def _browser_flow(state: str, flow_id: str) -> dict[str, Any]:
    return {
        "type": "openai_browser",
        "method_index": 0,
        "state": state,
        "flow_id": flow_id,
        "created_at": time.time(),
    }


@pytest.mark.asyncio
async def test_completing_an_older_flow_keeps_a_newer_one(
    pending: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    pending[PROVIDER] = _browser_flow("state_a", "flow_a")

    async def exchange(**_kwargs: Any) -> dict[str, Any]:
        # The user starts a second authorization while the first completes.
        pending[PROVIDER] = _browser_flow("state_b", "flow_b")
        return {"type": "oauth", "access": "token"}

    monkeypatch.setattr(provider_auth, "_openai_complete_browser_flow", exchange)

    assert await provider_auth.callback_provider_oauth(PROVIDER, 0, code="code_a")

    assert pending[PROVIDER]["flow_id"] == "flow_b"


@pytest.mark.asyncio
async def test_a_pasted_code_is_not_accepted_on_a_recent_completion(
    pending: dict[str, dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    del pending
    provider_auth._RECENT_OAUTH_COMPLETIONS[PROVIDER] = time.monotonic()

    with pytest.raises(ProviderOAuthError):
        await provider_auth.callback_provider_oauth(PROVIDER, 0, code="stale")


@pytest.mark.asyncio
async def test_waiting_for_a_flow_that_just_completed_succeeds(
    pending: dict[str, dict[str, Any]],
) -> None:
    del pending
    provider_auth._RECENT_OAUTH_COMPLETIONS[PROVIDER] = time.monotonic()

    assert await provider_auth.callback_provider_oauth(PROVIDER, 0) is True
