"""A Modal model is ready only when its proxy tokens are present.

Covers SM-105: the credential precheck accepted any configured ``api_key``
before reaching the Modal rule, but the Modal adapter ignores ``api_key`` and
needs the proxy tokens, so the request failed later with a generic
"could not initialize provider" error instead of the missing-credential one.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.core_runtime.model_runtime import provider_credential_available
from penguin.llm.model_config import ModelConfig

if TYPE_CHECKING:
    import pytest


def test_an_api_key_does_not_satisfy_modal(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in ("MODAL_ENDPOINT", "MODAL_PROXY_TOKEN_ID", "MODAL_PROXY_TOKEN_SECRET"):
        monkeypatch.delenv(name, raising=False)
    config = ModelConfig(
        model="llama", provider="modal", api_key="sk-x", api_base="https://m.example"
    )

    assert provider_credential_available(config) is False

    monkeypatch.setenv("MODAL_PROXY_TOKEN_ID", "id")
    monkeypatch.setenv("MODAL_PROXY_TOKEN_SECRET", "secret")
    assert provider_credential_available(config) is True
