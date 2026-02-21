"""Tests for general provider credentials service behavior."""

from __future__ import annotations

import json
import os
from pathlib import Path

from penguin.web.services import provider_credentials


def test_credentials_default_store_path_and_permissions(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", raising=False)
    monkeypatch.delenv("PENGUIN_PROVIDER_AUTH_STORE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    provider_credentials.set_provider_credential(
        "openrouter", {"type": "api", "key": "sk-test"}
    )

    store_path = tmp_path / ".config" / "penguin" / "providers" / "credentials.json"
    assert store_path.exists()
    payload = json.loads(store_path.read_text(encoding="utf-8"))
    assert payload["providers"]["openrouter"]["key"] == "sk-test"

    mode = os.stat(store_path).st_mode & 0o777
    assert mode == 0o600


def test_credentials_reads_legacy_store_when_primary_missing(
    tmp_path: Path,
    monkeypatch,
) -> None:
    monkeypatch.delenv("PENGUIN_PROVIDER_CREDENTIALS_STORE", raising=False)
    monkeypatch.delenv("PENGUIN_PROVIDER_AUTH_STORE", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path))

    legacy_path = tmp_path / ".config" / "penguin" / "provider_auth.json"
    legacy_path.parent.mkdir(parents=True, exist_ok=True)
    legacy_path.write_text(
        json.dumps(
            {
                "version": 1,
                "providers": {
                    "openrouter": {"type": "api", "key": "legacy-key"},
                },
            }
        ),
        encoding="utf-8",
    )

    records = provider_credentials.get_provider_credentials()
    assert records["openrouter"]["key"] == "legacy-key"
