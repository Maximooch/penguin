"""Request preparation and the request itself read OAuth credentials one way.

Covers SM-50: ``_peek_oauth_record_for_prepare`` and
``_resolve_oauth_record_for_request`` each parsed the stored and environment
credentials, with different rules, so preparation could route on one
credential while the request used another.
"""

from __future__ import annotations

from typing import Any

import pytest

from penguin.llm.adapters import openai as openai_adapter
from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig


def _adapter(monkeypatch: pytest.MonkeyPatch, stored: dict[str, Any] | None):
    monkeypatch.setattr(openai_adapter, "get_provider_credential", lambda _p: stored)
    return OpenAIAdapter(
        ModelConfig(model="gpt-5.2", provider="openai", client_preference="native")
    )


@pytest.mark.asyncio
async def test_preparation_and_request_use_the_same_credential(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    stored = {"type": "oauth", "access": "", "refresh": "stored_refresh"}
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "env_access")
    adapter = _adapter(monkeypatch, stored)
    refreshed: list[dict[str, Any]] = []

    async def refresh(_provider: str, *, credential_record: dict[str, Any]):
        refreshed.append(credential_record)
        return {**credential_record, "access": "new_access", "expires": 2**62}

    monkeypatch.setattr(openai_adapter, "refresh_provider_oauth", refresh)

    peeked = adapter._peek_oauth_record_for_prepare()
    resolved = await adapter._resolve_oauth_record_for_request()

    assert refreshed and refreshed[0]["refresh"] == "stored_refresh"
    assert resolved["refresh"] == "stored_refresh"
    assert peeked is not None and peeked.get("refresh") == "stored_refresh"


def test_environment_credentials_are_read_the_same_way(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "env_access")
    monkeypatch.setenv("OPENAI_OAUTH_REFRESH_TOKEN", "env_refresh")
    monkeypatch.setenv("OPENAI_OAUTH_EXPIRES_AT_MS", "not-a-number")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "account_1")
    adapter = _adapter(monkeypatch, None)

    assert adapter._peek_oauth_record_for_prepare() == {
        "type": "oauth",
        "access": "env_access",
        "refresh": "env_refresh",
        "accountId": "account_1",
    }
