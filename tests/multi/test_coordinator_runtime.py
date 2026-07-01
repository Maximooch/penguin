"""Tests for multi-agent coordinator access helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.multi.coordinator_runtime import get_core_coordinator


def test_get_core_coordinator_caches_factory_result() -> None:
    calls: list[Any] = []
    core = SimpleNamespace()

    def _factory(owner: Any) -> dict[str, Any]:
        calls.append(owner)
        return {"owner": owner}

    first = get_core_coordinator(core, coordinator_factory=_factory)
    second = get_core_coordinator(core, coordinator_factory=_factory)

    assert first is second
    assert first == {"owner": core}
    assert calls == [core]
    assert core._coordinator is first


def test_get_core_coordinator_reuses_existing_coordinator() -> None:
    existing = object()
    core = SimpleNamespace(_coordinator=existing)

    def _factory(_owner: Any) -> Any:
        raise AssertionError("factory should not be used")

    assert get_core_coordinator(core, coordinator_factory=_factory) is existing


def test_get_core_coordinator_logs_and_reraises_factory_failure() -> None:
    class _Logger:
        def __init__(self) -> None:
            self.errors: list[tuple[str, tuple[Any, ...]]] = []

        def error(self, message: str, *args: Any) -> None:
            self.errors.append((message, args))

    logger = _Logger()
    core = SimpleNamespace()

    def _factory(_owner: Any) -> Any:
        raise RuntimeError("coordinator unavailable")

    with pytest.raises(RuntimeError, match="coordinator unavailable"):
        get_core_coordinator(core, coordinator_factory=_factory, log=logger)

    assert len(logger.errors) == 1
    assert logger.errors[0][0] == "Failed to get coordinator: %s"
    assert str(logger.errors[0][1][0]) == "coordinator unavailable"
