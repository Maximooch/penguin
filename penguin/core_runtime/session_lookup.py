"""Session-store lookup helpers shared by core and web services."""

from __future__ import annotations

from typing import Any, Callable

SessionLoader = Callable[[Any, str], Any | None]

__all__ = [
    "SessionLoader",
    "find_session_store",
    "iter_session_managers",
]


def iter_session_managers(conversation_manager: Any) -> list[Any]:
    """Return unique session manager instances across default and agent stores."""

    if conversation_manager is None:
        return []

    candidates: list[Any] = []
    default_manager = getattr(conversation_manager, "session_manager", None)
    if default_manager is not None:
        candidates.append(default_manager)

    agent_managers = getattr(conversation_manager, "agent_session_managers", {})
    if isinstance(agent_managers, dict):
        candidates.extend(agent_managers.values())

    unique: list[Any] = []
    seen: set[int] = set()
    for manager in candidates:
        manager_id = id(manager)
        if manager_id in seen:
            continue
        seen.add(manager_id)
        unique.append(manager)
    return unique


def find_session_store(
    owner: Any,
    session_id: str,
    *,
    load_session: SessionLoader | None = None,
) -> tuple[Any | None, Any | None]:
    """Locate a session and its owning session manager."""

    if not session_id:
        return None, None

    conversation_manager = getattr(owner, "conversation_manager", owner)
    for manager in iter_session_managers(conversation_manager):
        cached = getattr(manager, "sessions", {})
        if isinstance(cached, dict) and session_id in cached:
            cached_entry = cached[session_id]
            if isinstance(cached_entry, tuple) and cached_entry:
                return cached_entry[0], manager
            return cached_entry, manager

        index = getattr(manager, "session_index", {})
        if not isinstance(index, dict) or session_id not in index:
            continue

        loader = load_session or _default_load_session
        session = loader(manager, session_id)
        if session is not None:
            return session, manager

    return None, None


def _default_load_session(manager: Any, session_id: str) -> Any | None:
    loader = getattr(manager, "load_session", None)
    if not callable(loader):
        return None
    try:
        return loader(session_id)
    except Exception:
        return None
