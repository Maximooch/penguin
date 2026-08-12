"""Lane-owned Telegram session history and safe rebinding."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Mapping

from penguin.core_runtime import process_lifecycle, session_lookup
from penguin.integrations.telegram._session_runtime import (
    read_session_file_without_activation,
)
from penguin.system.execution_context import normalize_directory

if TYPE_CHECKING:
    from penguin.channels.store import ChannelStore
    from penguin.channels.store_models import BindingRecord

RECENT_SESSIONS_KEY = "_telegram_recent_sessions_v1"
MAX_RECENT_SESSIONS = 20
_MAX_SESSION_ID_CHARS = 512


class SessionAccessError(RuntimeError):
    """Raised when a session is not available to this Telegram lane."""


class SessionBusyError(RuntimeError):
    """Raised when rebinding would race an active session turn."""


@dataclass(frozen=True)
class SessionSummary:
    """Display-safe metadata for one session owned by a Telegram lane."""

    session_id: str
    title: str
    last_active: str | None
    current: bool


def create_bound_session(core: Any, agent_id: str | None) -> str:
    """Create a session through the binding's explicit agent scope."""

    normalized_agent = agent_id.strip() if isinstance(agent_id, str) else ""
    agent_creator = getattr(core, "create_agent_conversation", None)
    if normalized_agent:
        if not callable(agent_creator):
            raise SessionAccessError(
                f"Cannot create a session for agent {normalized_agent!r}."
            )
        session_id = agent_creator(normalized_agent)
    elif callable(agent_creator):
        session_id = agent_creator("default")
    else:
        creator = getattr(core, "create_conversation", None)
        if not callable(creator):
            raise SessionAccessError("Cannot create a session for the default agent.")
        session_id = creator()
    if not isinstance(session_id, str) or not session_id.strip():
        raise SessionAccessError("Penguin did not return a valid session ID.")
    return session_id.strip()


def _normalized_session_id(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = value.strip()
    if not normalized or len(normalized) > _MAX_SESSION_ID_CHARS:
        return None
    return normalized


def _recent_session_ids(settings: Mapping[str, Any] | None) -> tuple[str, ...]:
    raw = settings.get(RECENT_SESSIONS_KEY, []) if isinstance(settings, Mapping) else []
    if not isinstance(raw, (list, tuple)):
        return ()

    result: list[str] = []
    seen: set[str] = set()
    for value in raw:
        session_id = _normalized_session_id(value)
        if session_id is None or session_id in seen:
            continue
        seen.add(session_id)
        result.append(session_id)
        if len(result) == MAX_RECENT_SESSIONS:
            break
    return tuple(result)


def with_recent_session(
    settings: Mapping[str, Any] | None,
    session_id: str,
) -> dict[str, Any]:
    """Return settings with ``session_id`` first in bounded recent history."""

    normalized = _normalized_session_id(session_id)
    if normalized is None:
        raise ValueError("session_id must be a non-empty string")

    updated = dict(settings) if isinstance(settings, Mapping) else {}
    existing = _recent_session_ids(settings)
    updated[RECENT_SESSIONS_KEY] = [
        normalized,
        *(item for item in existing if item != normalized),
    ][:MAX_RECENT_SESSIONS]
    return updated


def with_session_transition(
    settings: Mapping[str, Any] | None,
    *,
    current_session_id: str,
    target_session_id: str,
) -> dict[str, Any]:
    """Record both sides of a transition with its target newest."""

    with_current = with_recent_session(settings, current_session_id)
    return with_recent_session(with_current, target_session_id)


def _find_session(core: Any, session_id: str) -> Any | None:
    if _normalized_session_id(session_id) != session_id:
        return None
    conversation_manager = getattr(core, "conversation_manager", core)
    for manager in session_lookup.iter_session_managers(conversation_manager):
        cached = getattr(manager, "sessions", {})
        if isinstance(cached, dict) and session_id in cached:
            entry = cached[session_id]
            session = entry[0] if isinstance(entry, tuple) and entry else entry
            return session if getattr(session, "id", None) == session_id else None

        current_session = getattr(manager, "current_session", None)
        if getattr(current_session, "id", None) == session_id:
            return current_session

        index = getattr(manager, "session_index", {})
        if not isinstance(index, dict) or session_id not in index:
            continue
        metadata = index[session_id]
        if not isinstance(metadata, Mapping):
            return None
        indexed_id = metadata.get("id")
        if indexed_id is not None and indexed_id != session_id:
            return None
        session = read_session_file_without_activation(manager, session_id)
        if session is None:
            return None
        return session
    return None


def _metadata(session: Any) -> Mapping[str, Any]:
    value = getattr(session, "metadata", {})
    return value if isinstance(value, Mapping) else {}


def _matches_binding(session: Any, binding: BindingRecord) -> bool:
    metadata = _metadata(session)
    raw_directory = metadata.get("directory")
    if isinstance(raw_directory, str) and raw_directory.strip():
        binding_directory = normalize_directory(binding.directory)
        session_directory = normalize_directory(raw_directory)
        if (
            binding_directory is None
            or session_directory is None
            or session_directory != binding_directory
        ):
            return False

    expected_agent = (binding.agent_id or "default").strip()
    for key in ("agent_id", "agentID"):
        raw_agent = metadata.get(key)
        if (
            isinstance(raw_agent, str)
            and raw_agent.strip()
            and raw_agent.strip() != expected_agent
        ):
            return False
    return True


def _session_title(session: Any, session_id: str) -> str:
    title = _metadata(session).get("title")
    if isinstance(title, str) and title.strip():
        return title.strip()

    messages = getattr(session, "messages", [])
    if isinstance(messages, (list, tuple)):
        for message in messages:
            if getattr(message, "role", None) != "user":
                continue
            content = getattr(message, "content", None)
            if isinstance(content, str) and content.strip():
                return content.split("\n", 1)[0].strip()[:64]
    return f"Session {session_id[-8:]}"


def _last_active(session: Any) -> str | None:
    value = getattr(session, "last_active", None)
    if isinstance(value, str) and value.strip():
        return value.strip()
    value = _metadata(session).get("last_active")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


def list_recent_sessions(
    core: Any,
    binding: BindingRecord,
) -> tuple[SessionSummary, ...]:
    """Hydrate only the session IDs recorded for this binding's lane."""

    summaries: list[SessionSummary] = []
    for session_id in _recent_session_ids(binding.settings):
        session = _find_session(core, session_id)
        if session is None or not _matches_binding(session, binding):
            continue
        summaries.append(
            SessionSummary(
                session_id=session_id,
                title=_session_title(session, session_id),
                last_active=_last_active(session),
                current=session_id == binding.session_id,
            )
        )
    return tuple(summaries)


def _owned_target(
    core: Any,
    binding: BindingRecord,
    target_session_id: str,
) -> tuple[str, Any]:
    normalized = _normalized_session_id(target_session_id)
    if normalized is None or normalized not in _recent_session_ids(binding.settings):
        raise SessionAccessError("Session is not available to this Telegram chat.")

    session = _find_session(core, normalized)
    if session is None or not _matches_binding(session, binding):
        raise SessionAccessError("Session is not available to this Telegram chat.")
    return normalized, session


async def rebind_session(
    core: Any,
    store: ChannelStore,
    binding: BindingRecord,
    target_session_id: str,
) -> BindingRecord:
    """CAS-rebind one lane after validating ownership, metadata, and idleness."""

    target_id, _session = _owned_target(core, binding, target_session_id)
    session_ids = sorted({binding.session_id, target_id})
    gates = [
        (session_id, process_lifecycle.get_session_request_gate(core, session_id))
        for session_id in session_ids
    ]
    for session_id, gate in gates:
        if gate.locked():
            raise SessionBusyError(f"Session {session_id} is busy.")

    acquired: list[asyncio.Lock] = []
    try:
        for session_id, gate in gates:
            if gate.locked():
                raise SessionBusyError(f"Session {session_id} is busy.")
            await gate.acquire()
            acquired.append(gate)

        settings = with_session_transition(
            binding.settings,
            current_session_id=binding.session_id,
            target_session_id=target_id,
        )
        cas_task = asyncio.create_task(
            asyncio.to_thread(
                store.upsert_binding,
                binding.address_key,
                target_id,
                directory=binding.directory,
                agent_id=binding.agent_id,
                agent_mode=binding.agent_mode,
                settings=settings,
                expected_version=binding.version,
            )
        )
        cancellation: asyncio.CancelledError | None = None
        while not cas_task.done():
            try:
                await asyncio.shield(cas_task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        if cancellation is not None:
            if not cas_task.cancelled():
                _ = cas_task.exception()
            raise cancellation
        return cas_task.result()
    finally:
        for gate in reversed(acquired):
            gate.release()


__all__ = [
    "MAX_RECENT_SESSIONS",
    "RECENT_SESSIONS_KEY",
    "SessionAccessError",
    "SessionBusyError",
    "SessionSummary",
    "create_bound_session",
    "list_recent_sessions",
    "rebind_session",
    "with_recent_session",
    "with_session_transition",
]
