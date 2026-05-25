"""Tests for session-store lookup helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core_runtime import session_lookup


class _Manager:
    def __init__(
        self,
        *,
        cached: dict[str, Any] | None = None,
        indexed: dict[str, Any] | None = None,
        fail_load: bool = False,
    ) -> None:
        self.sessions = cached or {}
        self.session_index = {key: {} for key in (indexed or {})}
        self._indexed = indexed or {}
        self.fail_load = fail_load
        self.loaded: list[str] = []

    def load_session(self, session_id: str) -> Any | None:
        self.loaded.append(session_id)
        if self.fail_load:
            raise RuntimeError("load failed")
        return self._indexed.get(session_id)


def _core(default_manager: Any, **agent_managers: Any) -> SimpleNamespace:
    return SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=default_manager,
            agent_session_managers=agent_managers,
        )
    )


def test_iter_session_managers_deduplicates_default_and_agent_managers() -> None:
    manager = _Manager()
    other = _Manager()
    conversation_manager = SimpleNamespace(
        session_manager=manager,
        agent_session_managers={"default": manager, "other": other},
    )

    managers = session_lookup.iter_session_managers(conversation_manager)

    assert managers == [manager, other]


def test_find_session_store_uses_cached_default_session_without_loading() -> None:
    session = SimpleNamespace(id="session_cached")
    manager = _Manager(cached={"session_cached": (session, False)})

    found, owner = session_lookup.find_session_store(_core(manager), "session_cached")

    assert found is session
    assert owner is manager
    assert manager.loaded == []


def test_find_session_store_loads_indexed_agent_session() -> None:
    default = _Manager()
    agent_session = SimpleNamespace(id="session_agent")
    agent = _Manager(indexed={"session_agent": agent_session})

    found, owner = session_lookup.find_session_store(
        _core(default, build=agent),
        "session_agent",
    )

    assert found is agent_session
    assert owner is agent
    assert agent.loaded == ["session_agent"]


def test_find_session_store_continues_after_load_failure() -> None:
    broken = _Manager(indexed={"session_shared": None}, fail_load=True)
    session = SimpleNamespace(id="session_shared")
    fallback = _Manager(indexed={"session_shared": session})

    found, owner = session_lookup.find_session_store(
        _core(broken, fallback=fallback),
        "session_shared",
    )

    assert found is session
    assert owner is fallback
    assert broken.loaded == ["session_shared"]
    assert fallback.loaded == ["session_shared"]


def test_find_session_store_uses_custom_loader_for_view_only_lookup() -> None:
    previous_session = SimpleNamespace(id="previous")
    loaded_session = SimpleNamespace(id="session_disk")
    manager = _Manager(indexed={"session_disk": loaded_session})
    manager.current_session = previous_session

    def view_loader(current_manager: Any, session_id: str) -> Any | None:
        try:
            current_manager.current_session = current_manager.load_session(session_id)
            return current_manager.current_session
        finally:
            current_manager.current_session = previous_session

    found, owner = session_lookup.find_session_store(
        _core(manager),
        "session_disk",
        load_session=view_loader,
    )

    assert found is loaded_session
    assert owner is manager
    assert manager.current_session is previous_session


def test_find_session_store_returns_missing_for_blank_or_absent_manager() -> None:
    assert session_lookup.find_session_store(SimpleNamespace(), "") == (None, None)
    assert session_lookup.find_session_store(SimpleNamespace(), "missing") == (
        None,
        None,
    )
