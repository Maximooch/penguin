"""Tests for OpenCode process request lifecycle helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from penguin.core_runtime import process_lifecycle


class _Owner:
    def __init__(self) -> None:
        self.status_events: list[tuple[str, str]] = []

    async def _emit_opencode_session_status(
        self,
        session_id: str,
        status_type: str,
    ) -> None:
        self.status_events.append((session_id, status_type))


async def _sleeping_task() -> None:
    await asyncio.sleep(60)


@pytest.mark.asyncio
async def test_register_initializes_state_tracks_task_and_emits_busy() -> None:
    owner = _Owner()
    task = asyncio.create_task(_sleeping_task())
    try:
        tracked = await process_lifecycle.register_opencode_process_request(
            owner,
            "session_1",
            task,
        )

        assert tracked is True
        assert owner._opencode_abort_sessions == set()
        assert owner._opencode_process_tasks == {"session_1": {task}}
        assert owner._opencode_active_requests == {"session_1": 1}
        assert owner.status_events == [("session_1", "busy")]
    finally:
        task.cancel()
        await asyncio.gather(task, return_exceptions=True)


@pytest.mark.asyncio
async def test_register_second_request_does_not_emit_duplicate_busy() -> None:
    owner = _Owner()
    first = asyncio.create_task(_sleeping_task())
    second = asyncio.create_task(_sleeping_task())
    try:
        assert (
            await process_lifecycle.register_opencode_process_request(
                owner,
                "session_1",
                first,
            )
            is True
        )
        assert (
            await process_lifecycle.register_opencode_process_request(
                owner,
                "session_1",
                second,
            )
            is True
        )

        assert owner._opencode_process_tasks == {"session_1": {first, second}}
        assert owner._opencode_active_requests == {"session_1": 2}
        assert owner.status_events == [("session_1", "busy")]
    finally:
        for task in (first, second):
            task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_finalize_only_emits_idle_after_last_active_request() -> None:
    owner = _Owner()
    first = asyncio.create_task(_sleeping_task())
    second = asyncio.create_task(_sleeping_task())
    try:
        await process_lifecycle.register_opencode_process_request(
            owner,
            "session_1",
            first,
        )
        await process_lifecycle.register_opencode_process_request(
            owner,
            "session_1",
            second,
        )
        owner._opencode_abort_sessions.add("session_1")

        await process_lifecycle.finalize_opencode_process_request(
            owner,
            "session_1",
            first,
            request_tracked=True,
        )

        assert owner._opencode_process_tasks == {"session_1": {second}}
        assert owner._opencode_active_requests == {"session_1": 1}
        assert owner._opencode_abort_sessions == {"session_1"}
        assert owner.status_events == [("session_1", "busy")]

        await process_lifecycle.finalize_opencode_process_request(
            owner,
            "session_1",
            second,
            request_tracked=True,
        )

        assert owner._opencode_process_tasks == {}
        assert owner._opencode_active_requests == {}
        assert owner._opencode_abort_sessions == set()
        assert owner.status_events == [
            ("session_1", "busy"),
            ("session_1", "idle"),
        ]
    finally:
        for task in (first, second):
            task.cancel()
        await asyncio.gather(first, second, return_exceptions=True)


@pytest.mark.asyncio
async def test_blank_session_or_missing_task_does_not_track_request() -> None:
    owner = _Owner()

    assert (
        await process_lifecycle.register_opencode_process_request(owner, "", None)
        is False
    )
    assert (
        await process_lifecycle.register_opencode_process_request(
            owner,
            "session_1",
            None,
        )
        is False
    )
    await process_lifecycle.finalize_opencode_process_request(
        owner,
        "session_1",
        None,
        request_tracked=False,
    )

    assert owner._opencode_process_tasks == {}
    assert owner._opencode_active_requests == {}
    assert owner.status_events == []


def test_discard_abort_session_ignores_blank_session_and_repairs_state() -> None:
    owner = SimpleNamespace(
        _opencode_abort_sessions=["bad"],
        _opencode_process_tasks=["bad"],
        _opencode_active_requests=["bad"],
    )

    process_lifecycle.discard_opencode_abort_session(owner, "")
    assert owner._opencode_abort_sessions == ["bad"]

    process_lifecycle.discard_opencode_abort_session(owner, "session_1")
    assert owner._opencode_abort_sessions == set()
    assert owner._opencode_process_tasks == {}
    assert owner._opencode_active_requests == {}
