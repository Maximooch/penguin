from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from penguin.web.services.request_gate import (
    SessionRequestGateTimeout,
    session_request_gate,
)


@pytest.mark.asyncio
async def test_session_request_gate_times_out_without_running_waiter_forever() -> None:
    core = SimpleNamespace()

    async with session_request_gate(core, "session-1", timeout_seconds=1):
        with pytest.raises(SessionRequestGateTimeout):
            async with session_request_gate(core, "session-1", timeout_seconds=0.01):
                pytest.fail("a queued request must not enter the protected section")


@pytest.mark.asyncio
async def test_session_request_gate_releases_and_prunes_after_success() -> None:
    core = SimpleNamespace()

    async with session_request_gate(core, "session-1", timeout_seconds=1) as wait_ms:
        assert wait_ms >= 0

    assert core._opencode_request_gates == {}
    assert core._opencode_request_gate_users == {}


@pytest.mark.asyncio
async def test_session_request_gate_allows_parallel_different_sessions() -> None:
    core = SimpleNamespace()
    entered: list[str] = []
    both_entered = asyncio.Event()

    async def run(session_id: str) -> None:
        async with session_request_gate(core, session_id, timeout_seconds=1):
            entered.append(session_id)
            if len(entered) == 2:
                both_entered.set()
            await asyncio.wait_for(both_entered.wait(), timeout=0.5)

    await asyncio.gather(run("session-a"), run("session-b"))
    assert set(entered) == {"session-a", "session-b"}


@pytest.mark.asyncio
async def test_session_request_gate_tracks_and_releases_queued_task_for_abort() -> None:
    core = SimpleNamespace()
    entered = False

    async with session_request_gate(core, "session-1", timeout_seconds=1):

        async def queued() -> None:
            nonlocal entered
            async with session_request_gate(
                core,
                "session-1",
                timeout_seconds=1,
            ):
                entered = True

        queued_task = asyncio.create_task(queued())
        for _ in range(20):
            tracked = getattr(core, "_opencode_process_tasks", {}).get("session-1")
            if isinstance(tracked, set) and queued_task in tracked:
                break
            await asyncio.sleep(0)
        else:
            pytest.fail("queued gate waiter was not registered for session abort")

        queued_task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await queued_task

    assert entered is False
    assert getattr(core, "_opencode_process_tasks", {}) == {}
