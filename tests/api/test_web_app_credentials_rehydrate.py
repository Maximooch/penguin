"""Tests for provider credential runtime rehydration on web startup."""

from __future__ import annotations

import os
from types import SimpleNamespace

from penguin.web import app as web_app


def test_rehydrate_provider_credentials_applies_all_valid_records(monkeypatch) -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    class _Core:
        pass

    def _fake_get_provider_credentials() -> dict[str, dict[str, object]]:
        return {
            "anthropic": {"type": "api", "key": "sk-ant"},
            "openai": {"type": "api", "key": "sk-openai"},
            "bad": "ignore",  # type: ignore[dict-item]
        }

    def _fake_apply(core: object, provider_id: str, record: dict[str, object]) -> None:
        assert isinstance(core, _Core)
        calls.append((provider_id, record))

    monkeypatch.setattr(
        web_app,
        "get_provider_credentials",
        _fake_get_provider_credentials,
    )
    monkeypatch.setattr(
        web_app,
        "apply_credentials_to_runtime",
        _fake_apply,
    )

    core = _Core()
    web_app._rehydrate_provider_credentials(core)  # type: ignore[arg-type]

    assert calls == [
        ("anthropic", {"type": "api", "key": "sk-ant"}),
        ("openai", {"type": "api", "key": "sk-openai"}),
    ]


def test_prime_provider_credentials_environment_sets_env(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_EXPIRES_AT_MS", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr(
        web_app,
        "get_provider_credentials",
        lambda: {
            "openrouter": {"type": "api", "key": "sk-or-v1-fixture"},
            "openai": {
                "type": "oauth",
                "access": "oauth-access",
                "refresh": "oauth-refresh",
                "expires": 9_999_999_999_000,
                "accountId": "acct-123",
            },
        },
    )

    web_app._prime_provider_credentials_environment()

    assert os.environ["OPENROUTER_API_KEY"] == "sk-or-v1-fixture"
    assert os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] == "oauth-access"
    assert os.environ["OPENAI_OAUTH_REFRESH_TOKEN"] == "oauth-refresh"
    assert os.environ["OPENAI_OAUTH_EXPIRES_AT_MS"] == "9999999999000"
    assert os.environ["OPENAI_ACCOUNT_ID"] == "acct-123"


def test_create_core_primes_credentials_before_loading_config(monkeypatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    monkeypatch.setattr(web_app, "_ensure_env_loaded", lambda: None)
    monkeypatch.setattr(
        web_app,
        "get_provider_credentials",
        lambda: {"openrouter": {"type": "api", "key": "sk-or-boot"}},
    )

    class _ConfigObj:
        def __init__(self) -> None:
            self.model_config = SimpleNamespace(
                model="z-ai/glm-5-turbo",
                provider="openrouter",
                client_preference="openrouter",
            )

        def to_dict(self) -> dict[str, object]:
            return {}

    def _load_config() -> _ConfigObj:
        assert os.environ["OPENROUTER_API_KEY"] == "sk-or-boot"
        return _ConfigObj()

    monkeypatch.setattr(web_app.Config, "load_config", staticmethod(_load_config))
    monkeypatch.setattr(
        web_app,
        "APIClient",
        lambda model_config: SimpleNamespace(
            set_system_prompt=lambda _prompt: None, model_config=model_config
        ),
    )
    monkeypatch.setattr(
        web_app, "ToolManager", lambda *_args, **_kwargs: SimpleNamespace()
    )

    class _Core:
        def __init__(self, **kwargs) -> None:
            self.kwargs = kwargs

    monkeypatch.setattr(web_app, "PenguinCore", _Core)

    core = web_app._create_core()

    assert isinstance(core, _Core)
