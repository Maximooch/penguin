"""Tests for provider credential runtime rehydration on web startup."""

from __future__ import annotations

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
