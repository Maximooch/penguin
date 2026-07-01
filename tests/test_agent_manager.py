"""Tests for agent manager facade helpers."""

from __future__ import annotations

from types import SimpleNamespace

from penguin.agent.manager import get_persona_catalog


class _Persona:
    def __init__(self, payload: dict[str, object]) -> None:
        self.payload = payload

    def to_dict(self) -> dict[str, object]:
        return dict(self.payload)


class _BrokenPersona:
    description = "Fallback description"

    def to_dict(self) -> dict[str, object]:
        raise RuntimeError("persona export unavailable")


def test_get_persona_catalog_serializes_and_sorts_configured_personas() -> None:
    config = SimpleNamespace(
        agent_personas={
            "zeta": _Persona({"description": "Last"}),
            "alpha": _Persona({"name": "alpha", "description": "First"}),
            "middle": _BrokenPersona(),
        }
    )

    catalog = get_persona_catalog(config)

    assert catalog == [
        {"name": "alpha", "description": "First"},
        {"name": "middle", "description": "Fallback description"},
        {"description": "Last", "name": "zeta"},
    ]


def test_get_persona_catalog_handles_missing_persona_config() -> None:
    assert get_persona_catalog(SimpleNamespace()) == []
