from __future__ import annotations

import asyncio
import threading
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from penguin.web.services.chat_terminal_state import (
    ChatContinuationConflict,
    ChatTerminalStatePersistenceError,
    activate_chat_continuation,
    consume_chat_continuation,
    get_chat_terminal_state,
    hydrate_chat_terminal_payload,
    invalidate_chat_terminal_state,
    lease_chat_continuation,
    record_chat_terminal_state,
    release_chat_continuation,
)


def _core_with_session(session_id: str = "session-1") -> tuple[object, object, object]:
    session = SimpleNamespace(id=session_id, metadata={})
    manager = SimpleNamespace(
        sessions={session_id: session},
        session_index={},
        mark_session_modified=MagicMock(),
        save_session=MagicMock(),
    )
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )
    return core, session, manager


@pytest.mark.asyncio
async def test_record_and_consume_chat_terminal_state_uses_recoverable_lease() -> None:
    core, session, manager = _core_with_session()

    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="provider_recoverable_error",
        completed=False,
        recoverable=True,
        continuation_actions=["retry"],
    )

    assert marker is not None
    assert marker["generation"] == 1
    assert session.metadata["chat_terminal_state"]["continuation_state"] == "available"

    consumed = await consume_chat_continuation(
        core,
        "session-1",
        action="retry",
        previous_status="provider_recoverable_error",
        request_id="request-1",
        generation=1,
    )
    assert consumed["status"] == "provider_recoverable_error"
    assert session.metadata["chat_terminal_state"]["continuation_state"] == "leased"
    assert manager.save_session.call_count == 2

    with pytest.raises(ChatContinuationConflict, match="already in progress"):
        await consume_chat_continuation(
            core,
            "session-1",
            action="retry",
            previous_status="provider_recoverable_error",
            request_id="request-1",
            generation=1,
        )

    assert await release_chat_continuation(
        core,
        "session-1",
        lease_id=consumed["lease_id"],
    )
    assert session.metadata["chat_terminal_state"]["continuation_state"] == "available"


@pytest.mark.asyncio
async def test_consume_chat_continuation_rejects_stale_or_tampered_marker() -> None:
    core, _session, _manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-2",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )

    with pytest.raises(ChatContinuationConflict, match="generation"):
        await consume_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-2",
            generation=99,
        )

    with pytest.raises(ChatContinuationConflict, match="status"):
        await consume_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="cancelled",
            request_id="request-2",
            generation=1,
        )

    with pytest.raises(ChatContinuationConflict, match="action"):
        await consume_chat_continuation(
            core,
            "session-1",
            action="retry",
            previous_status="max_iterations",
            request_id="request-2",
            generation=1,
        )


@pytest.mark.asyncio
async def test_new_terminal_marker_advances_generation_and_supersedes_old_action() -> (
    None
):
    core, session, _manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-2",
        status="completed",
        completed=True,
        recoverable=False,
        continuation_actions=[],
    )

    assert marker is not None
    assert marker["generation"] == 2
    assert session.metadata["chat_terminal_state"]["request_id"] == "request-2"
    assert session.metadata["chat_terminal_state"]["continuation_actions"] == []


@pytest.mark.asyncio
async def test_normal_request_invalidates_previous_continuation() -> None:
    core, session, _manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )

    assert await invalidate_chat_terminal_state(
        core,
        "session-1",
        superseded_by_request_id="request-2",
    )
    marker = session.metadata["chat_terminal_state"]
    assert marker["continuation_state"] == "invalidated"
    assert marker["superseded_by_request_id"] == "request-2"


@pytest.mark.asyncio
async def test_failed_terminal_save_never_returns_an_advertisable_marker() -> None:
    core, session, manager = _core_with_session()
    manager.save_session.return_value = False

    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )

    assert marker is None
    assert "chat_terminal_state" not in session.metadata


@pytest.mark.asyncio
async def test_hydration_restores_full_terminal_and_exact_continuation_context() -> (
    None
):
    core, _session, _manager = _core_with_session()
    payload = {
        "response": "partial",
        "partial_response": "partial",
        "action_results": [
            {
                "action": "write_file",
                "status": "completed",
                "output_hash": "sha256:one",
            }
        ],
        "action_count": 1,
        "status": "max_iterations",
        "terminal_reason": "max_iterations",
        "state": "max_iterations",
        "completed": False,
        "recoverable": True,
        "aborted": False,
        "cancelled": False,
        "iterations": 9,
        "error": None,
        "continuation": None,
        "actions": [],
    }
    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-9",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
        terminal_payload=payload,
        request_context={
            "directory": "/tmp",
            "model": "openai/gpt-5",
            "agent_id": "general",
            "agent_mode": "build",
            "variant": "high",
            "service_tier": "priority",
        },
        action_results=payload["action_results"],
    )

    assert marker is not None
    hydrated_marker = await get_chat_terminal_state(core, "session-1")
    assert hydrated_marker is not None
    hydrated = hydrate_chat_terminal_payload(
        hydrated_marker,
        session_id="session-1",
    )
    assert hydrated["partial_response"] == "partial"
    assert hydrated["action_results"] == payload["action_results"]
    request = hydrated["continuation"]["request"]
    assert request["directory"] == marker["request_context"]["directory"]
    assert request["model"] == "openai/gpt-5"
    assert request["agent_id"] == "general"
    assert request["agent_mode"] == "build"
    assert request["variant"] == "high"
    assert request["service_tier"] == "priority"
    assert request["continuation"]["tool_boundary"] == marker["tool_boundary"]


@pytest.mark.asyncio
async def test_lease_rejects_context_or_completed_tool_boundary_tampering() -> None:
    core, session, _manager = _core_with_session()
    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
        request_context={"directory": "/tmp", "model": "openai/gpt-5"},
        action_results=[{"action": "write", "status": "completed"}],
    )
    assert marker is not None

    with pytest.raises(ChatContinuationConflict, match="context"):
        await lease_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
            request_context={"directory": "/tmp", "model": "openai/other"},
            tool_boundary=marker["tool_boundary"],
        )
    with pytest.raises(ChatContinuationConflict, match="tool boundary"):
        await lease_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
            request_context=marker["request_context"],
            tool_boundary={
                "completed_action_count": 1,
                "fingerprint": "tampered",
            },
        )
    assert session.metadata["chat_terminal_state"]["continuation_state"] == "available"


@pytest.mark.asyncio
async def test_invalidation_save_failure_fails_closed() -> None:
    core, session, manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    manager.save_session.return_value = False

    with pytest.raises(ChatTerminalStatePersistenceError, match="invalidated"):
        await invalidate_chat_terminal_state(
            core,
            "session-1",
            superseded_by_request_id="request-2",
        )
    assert session.metadata["chat_terminal_state"]["continuation_state"] == "available"


@pytest.mark.asyncio
async def test_hydration_does_not_recover_a_live_foreign_worker_lease() -> None:
    core, session, _manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    leased = await consume_chat_continuation(
        core,
        "session-1",
        action="resume",
        previous_status="max_iterations",
        request_id="request-1",
        generation=1,
    )
    assert leased["continuation_state"] == "leased"
    session.metadata["chat_terminal_state"]["lease_owner"] = "previous-process"

    observed = await get_chat_terminal_state(core, "session-1")

    assert observed is not None
    assert observed["continuation_state"] == "leased"
    assert observed["lease_id"] == leased["lease_id"]

    with pytest.raises(ChatContinuationConflict, match="already in progress"):
        await consume_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
        )


@pytest.mark.asyncio
async def test_hydration_recovers_an_expired_foreign_worker_lease() -> None:
    core, session, _manager = _core_with_session()
    await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    leased = await consume_chat_continuation(
        core,
        "session-1",
        action="resume",
        previous_status="max_iterations",
        request_id="request-1",
        generation=1,
    )
    assert leased["continuation_state"] == "leased"
    marker = session.metadata["chat_terminal_state"]
    marker["lease_owner"] = "previous-process"
    marker["lease_expires_at"] = (
        datetime.now(timezone.utc) - timedelta(seconds=1)
    ).isoformat()

    recovered = await get_chat_terminal_state(core, "session-1")

    assert recovered is not None
    assert recovered["continuation_state"] == "available"
    assert "lease_id" not in recovered


@pytest.mark.asyncio
async def test_cancelled_lease_save_restores_available_marker() -> None:
    core, session, manager = _core_with_session()
    marker = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    assert marker is not None
    save_started = threading.Event()
    release_save = threading.Event()

    def blocking_save(_session: object) -> None:
        save_started.set()
        release_save.wait(timeout=2)

    manager.save_session = blocking_save
    lease_task = asyncio.create_task(
        lease_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
            request_context=marker["request_context"],
            tool_boundary=marker["tool_boundary"],
        )
    )
    await asyncio.wait_for(asyncio.to_thread(save_started.wait), timeout=1)
    lease_task.cancel()
    release_save.set()

    with pytest.raises(asyncio.CancelledError):
        await lease_task
    current = session.metadata["chat_terminal_state"]
    assert current["continuation_state"] == "available"
    assert "lease_id" not in current


@pytest.mark.asyncio
async def test_started_continuation_stays_closed_on_successor_save_failure() -> None:
    core, session, manager = _core_with_session()
    initial = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-1",
        status="max_iterations",
        completed=False,
        recoverable=True,
        continuation_actions=["resume"],
    )
    assert initial is not None
    lease = await lease_chat_continuation(
        core,
        "session-1",
        action="resume",
        previous_status="max_iterations",
        request_id="request-1",
        generation=1,
        request_context=initial["request_context"],
        tool_boundary=initial["tool_boundary"],
    )
    await activate_chat_continuation(
        core,
        "session-1",
        lease_id=lease["lease_id"],
    )
    manager.save_session.return_value = False

    successor = await record_chat_terminal_state(
        core,
        "session-1",
        request_id="request-2",
        status="completed",
        completed=True,
        recoverable=False,
        continuation_actions=[],
    )

    assert successor is None
    marker = session.metadata["chat_terminal_state"]
    assert marker["continuation_state"] == "executing"
    assert (
        await release_chat_continuation(
            core,
            "session-1",
            lease_id=lease["lease_id"],
        )
        is False
    )
    reloaded = await get_chat_terminal_state(core, "session-1")
    assert reloaded is not None
    assert reloaded["continuation_state"] == "executing"
    hydrated = hydrate_chat_terminal_payload(reloaded, session_id="session-1")
    assert hydrated["continuation"] is None

    with pytest.raises(ChatContinuationConflict, match="no longer available"):
        await lease_chat_continuation(
            core,
            "session-1",
            action="resume",
            previous_status="max_iterations",
            request_id="request-1",
            generation=1,
            request_context=initial["request_context"],
            tool_boundary=initial["tool_boundary"],
        )
