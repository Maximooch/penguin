"""Owner-scoped Telegram session history and rebinding tests."""

from __future__ import annotations

import asyncio
import threading
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.channels.store import ChannelStore, CompareAndSwapError
from penguin.core_runtime import process_lifecycle
from penguin.integrations.telegram._sessions import (
    RECENT_SESSIONS_KEY,
    SessionAccessError,
    SessionBusyError,
    create_bound_session,
    list_recent_sessions,
    rebind_session,
    with_recent_session,
    with_session_transition,
)
from penguin.system.state import Session


def _session(
    session_id: str,
    *,
    title: str | None = None,
    last_active: str = "2026-08-11T12:00:00",
    directory: str | None = None,
    agent_id: str | None = None,
) -> SimpleNamespace:
    metadata: dict[str, Any] = {}
    if title is not None:
        metadata["title"] = title
    if directory is not None:
        metadata["directory"] = directory
    if agent_id is not None:
        metadata["agent_id"] = agent_id
    return SimpleNamespace(
        id=session_id,
        metadata=metadata,
        messages=[],
        last_active=last_active,
    )


def _core(*sessions: SimpleNamespace) -> SimpleNamespace:
    manager = SimpleNamespace(
        sessions={session.id: (session, False) for session in sessions},
        session_index={},
    )
    return SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )


def _binding(
    store: ChannelStore,
    *,
    current: str,
    directory: str,
    agent_id: str = "build-agent",
    history: list[str] | None = None,
) -> Any:
    settings: dict[str, Any] = {"prompt": "Stay concise", "streaming": "live"}
    if history is not None:
        settings[RECENT_SESSIONS_KEY] = history
    return store.upsert_binding(
        "telegram\x1fbot\x1f42\x1f",
        current,
        directory=directory,
        agent_id=agent_id,
        agent_mode="plan",
        settings=settings,
        expected_version=0,
    )


def _write_primary_session(
    manager: Any,
    root: Any,
    requested_id: str,
    *,
    stored_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    last_active: str | None = None,
) -> None:
    manager.base_path = root
    manager.format = "json"
    session = Session(id=stored_id or requested_id, metadata=metadata or {})
    if last_active is not None:
        session.last_active = last_active
    (root / f"{requested_id}.json").write_text(
        session.to_json(),
        encoding="utf-8",
    )


def test_recent_history_preserves_settings_dedupes_and_caps() -> None:
    settings: dict[str, Any] = {
        "prompt": "Keep me",
        RECENT_SESSIONS_KEY: ["session-2", "session-1", "session-2", 7, ""],
    }

    updated = settings
    for index in range(25):
        updated = with_recent_session(updated, f"session-{index}")

    assert updated["prompt"] == "Keep me"
    assert updated[RECENT_SESSIONS_KEY] == [
        f"session-{index}" for index in range(24, 4, -1)
    ]
    assert settings[RECENT_SESSIONS_KEY] == [
        "session-2",
        "session-1",
        "session-2",
        7,
        "",
    ]


def test_transition_records_target_then_current_without_losing_settings() -> None:
    updated = with_session_transition(
        {"activation": "mention", RECENT_SESSIONS_KEY: ["older", "target"]},
        current_session_id="current",
        target_session_id="target",
    )

    assert updated == {
        "activation": "mention",
        RECENT_SESSIONS_KEY: ["target", "current", "older"],
    }


def test_create_bound_session_uses_configured_agent_without_switching_global() -> None:
    calls: list[tuple[str, str | None]] = []
    core = SimpleNamespace(current_agent_id="default")

    def create_agent_conversation(agent_id: str) -> str:
        calls.append(("agent", agent_id))
        return " session-agent "

    def create_conversation() -> str:
        calls.append(("default", None))
        return "session-default"

    core.create_agent_conversation = create_agent_conversation
    core.create_conversation = create_conversation

    assert create_bound_session(core, " worker ") == "session-agent"
    assert calls == [("agent", "worker")]
    assert core.current_agent_id == "default"


def test_create_bound_session_uses_explicit_default_without_switching_global() -> None:
    calls: list[tuple[str, str | None]] = []
    core = SimpleNamespace(
        current_agent_id="worker",
        create_conversation=lambda: calls.append(("legacy", None)) or "session-legacy",
        create_agent_conversation=lambda agent: (
            calls.append(("agent", agent)) or "session-default"
        ),
    )

    assert create_bound_session(core, None) == "session-default"
    assert create_bound_session(core, "  ") == "session-default"
    assert calls == [("agent", "default"), ("agent", "default")]
    assert core.current_agent_id == "worker"


def test_create_bound_session_legacy_default_compatibility() -> None:
    calls: list[str] = []
    core = SimpleNamespace(
        create_conversation=lambda: calls.append("legacy") or "session-default"
    )

    assert create_bound_session(core, None) == "session-default"
    assert calls == ["legacy"]


def test_create_bound_session_fails_closed_when_agent_seam_is_missing() -> None:
    default_calls: list[str] = []
    core = SimpleNamespace(
        create_conversation=lambda: default_calls.append("default") or "session-default"
    )

    with pytest.raises(SessionAccessError, match="agent 'worker'"):
        create_bound_session(core, "worker")

    assert default_calls == []


@pytest.mark.parametrize("result", [None, "", "   ", 123])
def test_create_bound_session_rejects_invalid_session_id(result: Any) -> None:
    core = SimpleNamespace(create_conversation=lambda: result)

    with pytest.raises(SessionAccessError, match="valid session ID"):
        create_bound_session(core, None)


def test_list_recent_sessions_only_hydrates_owned_history(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session(
        "current",
        title="Current work",
        last_active="2026-08-11T12:02:00",
        directory=str(project),
        agent_id="build-agent",
    )
    target = _session(
        "target",
        title="Earlier work",
        last_active="2026-08-11T11:59:00",
        directory=str(project),
        agent_id="build-agent",
    )
    globally_visible_but_unowned = _session(
        "not-in-history",
        title="Someone else's session",
        directory=str(project),
        agent_id="build-agent",
    )
    mismatched = _session(
        "wrong-project",
        directory=str(tmp_path),
        agent_id="build-agent",
    )
    core = _core(current, target, globally_visible_but_unowned, mismatched)
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "missing", "wrong-project", "current"],
    )

    summaries = list_recent_sessions(core, binding)

    assert [
        (item.session_id, item.title, item.last_active, item.current)
        for item in summaries
    ] == [
        ("target", "Earlier work", "2026-08-11T11:59:00", False),
        ("current", "Current work", "2026-08-11T12:02:00", True),
    ]


def test_list_recent_sessions_prefers_uncached_live_current_over_stale_index(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    live = _session(
        "current",
        title="Live current",
        directory=str(project),
        agent_id="build-agent",
    )
    core = _core()
    manager = core.conversation_manager.session_manager
    manager.current_session = live
    manager.session_index = {
        live.id: {
            "title": "Stale index",
            "directory": str(tmp_path),
            "agent_id": "other-agent",
        }
    }
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current=live.id,
        directory=str(project),
        history=[live.id],
    )

    summaries = list_recent_sessions(core, binding)

    assert len(summaries) == 1
    assert summaries[0].title == "Live current"
    assert summaries[0].current is True
    assert manager.current_session is live
    assert manager.sessions == {}


@pytest.mark.asyncio
async def test_index_session_view_never_calls_activating_loader_or_moves_pointer(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    core = _core(current)
    manager = core.conversation_manager.session_manager
    manager.current_session = current
    _write_primary_session(
        manager,
        tmp_path,
        "target",
        metadata={
            "title": "Persisted target",
            "directory": str(project),
            "agent_id": "build-agent",
        },
        last_active="2026-08-11T11:58:00",
    )
    manager.session_index = {
        "target": {
            "title": "Persisted target",
            "last_active": "2026-08-11T11:58:00",
            "directory": str(project),
            "agent_id": "build-agent",
        }
    }

    def activating_loader(session_id: str) -> Any:
        raise AssertionError(f"activating loader called for {session_id}")

    manager.load_session = activating_loader
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )

    summaries = list_recent_sessions(core, binding)
    rebound = await rebind_session(core, store, binding, "target")

    assert [summary.session_id for summary in summaries] == ["target", "current"]
    assert summaries[0].title == "Persisted target"
    assert rebound.session_id == "target"
    assert manager.current_session is current
    assert set(manager.sessions) == {"current"}


@pytest.mark.asyncio
async def test_index_session_view_rejects_mismatched_embedded_id(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    core = _core(current)
    manager = core.conversation_manager.session_manager
    _write_primary_session(manager, tmp_path, "target")
    manager.session_index = {
        "target": {
            "id": "different",
            "directory": str(project),
            "agent_id": "build-agent",
        }
    }
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )

    assert [item.session_id for item in list_recent_sessions(core, binding)] == [
        "current"
    ]
    with pytest.raises(SessionAccessError, match="not available"):
        await rebind_session(core, store, binding, "target")

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
@pytest.mark.parametrize("mismatch", ["directory", "agent"])
async def test_index_claim_cannot_override_primary_session_owner(
    tmp_path,
    mismatch: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    other_project = tmp_path / "other"
    other_project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    core = _core(current)
    manager = core.conversation_manager.session_manager
    primary_metadata = {
        "directory": str(other_project) if mismatch == "directory" else str(project),
        "agent_id": "other-agent" if mismatch == "agent" else "build-agent",
    }
    _write_primary_session(
        manager,
        tmp_path,
        "target",
        metadata=primary_metadata,
    )
    manager.session_index = {
        "target": {
            "directory": str(project),
            "agent_id": "build-agent",
        }
    }
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )

    assert [item.session_id for item in list_recent_sessions(core, binding)] == [
        "current"
    ]
    with pytest.raises(SessionAccessError, match="not available"):
        await rebind_session(core, store, binding, "target")

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "corrupt", "embedded-id"])
async def test_index_session_view_requires_valid_exact_primary_file(
    tmp_path,
    failure: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    core = _core(current)
    manager = core.conversation_manager.session_manager
    manager.base_path = tmp_path
    manager.format = "json"
    manager.session_index = {
        "target": {
            "directory": str(project),
            "agent_id": "build-agent",
        }
    }
    if failure == "corrupt":
        (tmp_path / "target.json").write_text("{not-json", encoding="utf-8")
    elif failure == "embedded-id":
        _write_primary_session(
            manager,
            tmp_path,
            "target",
            stored_id="different",
        )
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )

    assert [item.session_id for item in list_recent_sessions(core, binding)] == [
        "current"
    ]
    with pytest.raises(SessionAccessError, match="not available"):
        await rebind_session(core, store, binding, "target")

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
async def test_rebind_denies_guessed_session_id_even_when_it_exists(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    guessed = _session("guessed", directory=str(project), agent_id="build-agent")
    core = _core(current, guessed)
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["current"],
    )

    with pytest.raises(SessionAccessError, match="not available"):
        await rebind_session(core, store, binding, "guessed")

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
@pytest.mark.parametrize("failure", ["missing", "directory", "agent"])
async def test_rebind_denies_missing_or_mismatched_history_target(
    tmp_path,
    failure: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    other_project = tmp_path / "other"
    other_project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    target: SimpleNamespace | None = None
    if failure == "directory":
        target = _session(
            "target", directory=str(other_project), agent_id="build-agent"
        )
    elif failure == "agent":
        target = _session("target", directory=str(project), agent_id="other-agent")
    core = _core(current, *([target] if target is not None else []))
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )

    with pytest.raises(SessionAccessError, match="not available"):
        await rebind_session(core, store, binding, "target")

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
@pytest.mark.parametrize("busy_session_id", ["current", "target"])
async def test_rebind_rejects_busy_current_or_target_session(
    tmp_path,
    busy_session_id: str,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    target = _session("target", directory=str(project), agent_id="build-agent")
    core = _core(current, target)
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )
    gate = process_lifecycle.get_session_request_gate(core, busy_session_id)
    await gate.acquire()
    try:
        with pytest.raises(SessionBusyError, match=busy_session_id):
            await rebind_session(core, store, binding, "target")
    finally:
        gate.release()

    assert store.get_binding(binding.address_key) == binding


@pytest.mark.asyncio
async def test_rebind_preserves_binding_and_records_transition(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    target = _session("target", directory=str(project), agent_id="build-agent")
    core = _core(current, target)
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["older", "target", "current"],
    )

    rebound = await rebind_session(core, store, binding, "target")

    assert rebound.session_id == "target"
    assert rebound.directory == binding.directory
    assert rebound.agent_id == binding.agent_id
    assert rebound.agent_mode == binding.agent_mode
    assert rebound.settings["prompt"] == "Stay concise"
    assert rebound.settings["streaming"] == "live"
    assert rebound.settings[RECENT_SESSIONS_KEY] == ["target", "current", "older"]
    assert rebound.version == binding.version + 1


@pytest.mark.asyncio
async def test_rebind_fails_closed_when_binding_version_changed(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    target = _session("target", directory=str(project), agent_id="build-agent")
    core = _core(current, target)
    store = ChannelStore(tmp_path / "channel.db")
    stale = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )
    changed = store.upsert_binding(
        stale.address_key,
        stale.session_id,
        directory=stale.directory,
        agent_id=stale.agent_id,
        agent_mode="build",
        settings=stale.settings,
        expected_version=stale.version,
    )

    with pytest.raises(CompareAndSwapError):
        await rebind_session(core, store, stale, "target")

    assert store.get_binding(stale.address_key) == changed


@pytest.mark.asyncio
async def test_cancelled_rebind_waits_for_threaded_cas_before_releasing_gates(
    tmp_path,
) -> None:
    project = tmp_path / "project"
    project.mkdir()
    current = _session("current", directory=str(project), agent_id="build-agent")
    target = _session("target", directory=str(project), agent_id="build-agent")
    core = _core(current, target)
    store = ChannelStore(tmp_path / "channel.db")
    binding = _binding(
        store,
        current="current",
        directory=str(project),
        history=["target", "current"],
    )
    original_upsert = store.upsert_binding
    entered = threading.Event()
    release = threading.Event()

    def delayed_upsert(*args: Any, **kwargs: Any) -> Any:
        entered.set()
        assert release.wait(timeout=5)
        return original_upsert(*args, **kwargs)

    store.upsert_binding = delayed_upsert
    task = asyncio.create_task(rebind_session(core, store, binding, "target"))
    assert await asyncio.to_thread(entered.wait, 5)

    task.cancel()
    await asyncio.sleep(0)
    assert task.done() is False
    assert process_lifecycle.get_session_request_gate(core, "current").locked()
    assert process_lifecycle.get_session_request_gate(core, "target").locked()

    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    rebound = store.get_binding(binding.address_key)
    assert rebound is not None
    assert rebound.session_id == "target"
    assert not process_lifecycle.get_session_request_gate(core, "current").locked()
    assert not process_lifecycle.get_session_request_gate(core, "target").locked()
