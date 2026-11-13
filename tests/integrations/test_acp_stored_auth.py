"""ACP uses only its selected provider's saved credential during startup."""

from types import SimpleNamespace

import pytest

pytest.importorskip("acp")


def test_selected_saved_login_is_activated(monkeypatch):
    from penguin.config import Config
    from penguin.integrations.acp.server import _startup_config
    from penguin.web.services import provider_credentials

    config = SimpleNamespace(model_config=SimpleNamespace(provider="openai"))
    monkeypatch.setattr(Config, "load_config", lambda: config)
    requested = []
    record = {"type": "oauth", "access": "test-only-access"}

    def get(provider):
        requested.append(provider)
        return record

    monkeypatch.setattr(provider_credentials, "get_provider_credential", get)
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.setenv("OPENROUTER_API_KEY", "untouched-test-key")
    assert _startup_config() is config
    import os

    assert requested == ["openai"]
    assert os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] == "test-only-access"
    assert os.environ["OPENROUTER_API_KEY"] == "untouched-test-key"


def test_absent_login_does_not_invent_credentials(monkeypatch):
    from penguin.config import Config
    from penguin.integrations.acp.server import _startup_config
    from penguin.web.services import provider_credentials

    config = SimpleNamespace(model_config=SimpleNamespace(provider="openai"))
    monkeypatch.setattr(Config, "load_config", lambda: config)
    monkeypatch.setattr(provider_credentials, "get_provider_credential", lambda _: None)
    calls = []
    monkeypatch.setattr(
        provider_credentials,
        "apply_credentials_to_environment",
        lambda *args: calls.append(args),
    )
    assert _startup_config() is config
    assert calls == []
