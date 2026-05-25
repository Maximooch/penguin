"""Tests for OpenCode process request lifecycle helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from penguin.core_runtime import process_lifecycle


class _Owner:
    def __init__(self) -> None:
        self.status_events: list[tuple[str, str]] = []
        self.ui_events: list[tuple[str, dict[str, object]]] = []
        self.user_metadata_events: list[dict[str, object]] = []
        self.fail_user_metadata = False

    async def _emit_opencode_session_status(
        self,
        session_id: str,
        status_type: str,
    ) -> None:
        self.status_events.append((session_id, status_type))

    async def emit_ui_event(
        self,
        event_type: str,
        data: dict[str, object],
    ) -> None:
        self.ui_events.append((event_type, data))

    async def _emit_opencode_user_message_with_metadata(
        self,
        message: str,
        *,
        message_id: str | None,
        agent_id: str | None,
    ) -> None:
        if self.fail_user_metadata:
            raise RuntimeError("metadata failed")
        self.user_metadata_events.append(
            {
                "message": message,
                "message_id": message_id,
                "agent_id": agent_id,
            }
        )


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


@pytest.mark.asyncio
async def test_emit_process_user_message_emits_ui_and_metadata_events() -> None:
    owner = _Owner()
    log = SimpleNamespace(debug=lambda *args, **kwargs: None)

    await process_lifecycle.emit_process_user_message(
        owner,
        "hello world",
        message_category="dialog",
        client_message_id="client_1",
        agent_id="planner",
        log=log,
    )

    assert owner.ui_events == [
        (
            "message",
            {
                "role": "user",
                "content": "hello world",
                "category": "dialog",
                "agent_id": "planner",
            },
        )
    ]
    assert owner.user_metadata_events == [
        {
            "message": "hello world",
            "message_id": "client_1",
            "agent_id": "planner",
        }
    ]


@pytest.mark.asyncio
async def test_emit_process_user_message_logs_metadata_failures() -> None:
    owner = _Owner()
    owner.fail_user_metadata = True
    debug_calls: list[tuple[tuple[object, ...], dict[str, object]]] = []
    log = SimpleNamespace(
        debug=lambda *args, **kwargs: debug_calls.append((args, kwargs))
    )

    await process_lifecycle.emit_process_user_message(
        owner,
        "hello world",
        message_category="dialog",
        client_message_id=None,
        agent_id=None,
        log=log,
    )

    assert owner.ui_events == [
        (
            "message",
            {
                "role": "user",
                "content": "hello world",
                "category": "dialog",
            },
        )
    ]
    assert owner.user_metadata_events == []
    assert debug_calls[-1] == (
        ("Failed to emit OpenCode user message",),
        {"exc_info": True},
    )


@pytest.mark.asyncio
async def test_finalize_process_response_saves_and_emits_non_streaming_message() -> (
    None
):
    owner = _Owner()
    conversation_manager = SimpleNamespace(save_calls=0)
    response = {"assistant_response": "Done"}
    token_calls: list[tuple[object, ...]] = []

    def save() -> None:
        conversation_manager.save_calls += 1

    async def collect_token_usage(*args: object, **kwargs: object) -> dict[str, int]:
        token_calls.append((*args, kwargs))
        return {"total": 3}

    conversation_manager.save = save

    token_data = await process_lifecycle.finalize_process_response(
        owner,
        conversation_manager,
        response,
        "session-1",
        streaming=False,
        agent_id="agent-1",
        collect_token_usage=collect_token_usage,
        message_category="dialog",
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
    )

    assert token_data == {"total": 3}
    assert conversation_manager.save_calls == 1
    assert owner.ui_events == [
        (
            "message",
            {
                "role": "assistant",
                "content": "Done",
                "category": "dialog",
                "metadata": {},
                "agent_id": "agent-1",
            },
        ),
        ("token_update", {"total": 3}),
    ]
    assert token_calls[0][2] is response


@pytest.mark.asyncio
async def test_finalize_process_response_suppresses_normal_streaming_message() -> None:
    owner = _Owner()
    conversation_manager = SimpleNamespace(save=lambda: None)

    async def collect_token_usage(*_args: object, **_kwargs: object) -> dict[str, int]:
        return {"total": 3}

    await process_lifecycle.finalize_process_response(
        owner,
        conversation_manager,
        {"assistant_response": "Streamed through chunks"},
        "session-1",
        streaming=True,
        agent_id=None,
        collect_token_usage=collect_token_usage,
        message_category="dialog",
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
    )

    assert owner.ui_events == [("token_update", {"total": 3})]


@pytest.mark.parametrize(
    "assistant_response",
    [
        "[Error: provider failed]",
        "   [Note: empty stream fallback]",
    ],
)
@pytest.mark.asyncio
async def test_finalize_process_response_emits_streaming_error_or_note_fallback(
    assistant_response: str,
) -> None:
    owner = _Owner()
    conversation_manager = SimpleNamespace(save=lambda: None)

    async def collect_token_usage(*_args: object, **_kwargs: object) -> dict[str, int]:
        return {"total": 3}

    await process_lifecycle.finalize_process_response(
        owner,
        conversation_manager,
        {"assistant_response": assistant_response},
        "session-1",
        streaming=True,
        agent_id=None,
        collect_token_usage=collect_token_usage,
        message_category="dialog",
        log=SimpleNamespace(debug=lambda *args, **kwargs: None),
    )

    assert owner.ui_events == [
        (
            "message",
            {
                "role": "assistant",
                "content": assistant_response,
                "category": "dialog",
                "metadata": {},
            },
        ),
        ("token_update", {"total": 3}),
    ]
