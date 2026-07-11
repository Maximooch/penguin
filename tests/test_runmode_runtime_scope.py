from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.run_mode import RunMode
from penguin.utils.events import EventBus, TaskEvent


def _core(run_task: Any) -> SimpleNamespace:
    return SimpleNamespace(
        engine=SimpleNamespace(
            run_task=run_task,
            settings=SimpleNamespace(streaming_default=False),
        ),
        project_manager=MagicMock(),
        emit_ui_event=AsyncMock(),
        finalize_streaming_message=MagicMock(return_value=None),
        _handle_stream_chunk=AsyncMock(),
    )


def _subscription_slots(event_bus: EventBus, event_type: str) -> int:
    priorities = event_bus._handlers.get(event_type, {})
    return sum(len(handlers) for handlers in priorities.values())


@pytest.mark.asyncio
async def test_runmode_passes_request_scoped_runtime_overrides_to_engine() -> None:
    api_client = object()
    model_config = object()
    run_task = AsyncMock(
        return_value={
            "status": "pending_review",
            "assistant_response": "done",
        }
    )
    core = _core(run_task)
    run_mode = RunMode(
        core=core,
        api_client_override=api_client,
        model_config_override=model_config,
    )

    await run_mode._execute_task("Scoped task", "Use the persisted model", {})

    call = run_task.await_args.kwargs
    assert call["api_client_override"] is api_client
    assert call["model_config_override"] is model_config


@pytest.mark.asyncio
async def test_runmode_forwards_non_streamed_final_assistant_response() -> None:
    run_task = AsyncMock(
        return_value={
            "status": "pending_review",
            "assistant_response": "Complete non-streamed response",
        }
    )
    core = _core(run_task)

    result = await RunMode(core=core)._execute_task(
        "Non-streamed task",
        "Return the final response without streaming",
        {},
    )

    assert result["message"] == "Complete non-streamed response"
    core._handle_stream_chunk.assert_awaited_once_with(
        "Complete non-streamed response",
        message_type="assistant",
        role="assistant",
    )


@pytest.mark.asyncio
async def test_runmode_does_not_duplicate_streamed_assistant_response() -> None:
    async def run_task(**kwargs: Any) -> dict[str, Any]:
        await kwargs["message_callback"]("Complete streamed response", "assistant")
        return {
            "status": "pending_review",
            "assistant_response": "Complete streamed response",
        }

    core = _core(run_task)

    result = await RunMode(core=core)._execute_task(
        "Streamed task",
        "Stream and return the same final response",
        {},
    )

    assert result["message"] == "Complete streamed response"
    core._handle_stream_chunk.assert_awaited_once_with(
        "Complete streamed response",
        message_type="assistant",
        role="assistant",
    )


@pytest.mark.asyncio
async def test_runmode_projects_typed_provider_error_without_assistant_text() -> None:
    provider_error = {
        "message": "OpenRouter SDK stream stalled",
        "category": "timeout",
        "retryable": True,
        "provider": "openrouter",
        "model": "z-ai/glm-5.2",
    }
    run_task = AsyncMock(
        return_value={
            "status": "provider_recoverable_error",
            "assistant_response": "stale prior response",
            "error": provider_error,
            "recoverable": True,
        }
    )
    core = _core(run_task)
    core._emit_opencode_assistant_error = AsyncMock()

    result = await RunMode(core=core)._execute_task(
        "Provider task",
        "Report the provider failure",
        {},
    )

    core._emit_opencode_assistant_error.assert_awaited_once_with(
        "OpenRouter SDK stream stalled",
        error=provider_error,
    )
    core._handle_stream_chunk.assert_not_awaited()
    assert result["error"] == provider_error
    assert result["recoverable"] is True


def test_runmode_constructor_does_not_mutate_engine_streaming_default() -> None:
    core = _core(AsyncMock())

    RunMode(core=core)

    assert core.engine.settings.streaming_default is False


@pytest.mark.asyncio
async def test_runmode_has_no_iteration_limit_when_omitted() -> None:
    run_task = AsyncMock(
        return_value={
            "status": "pending_review",
            "assistant_response": "done",
        }
    )

    await RunMode(core=_core(run_task))._execute_task(
        "Unbounded task",
        "Continue until complete",
        {},
    )

    assert run_task.await_args.kwargs["max_iterations"] is None


@pytest.mark.asyncio
async def test_runmode_event_subscriptions_are_scoped_to_start(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_bus = EventBus()
    monkeypatch.setattr(EventBus, "_instance", event_bus)
    started_event = TaskEvent.STARTED.value

    async def run_task(**_kwargs: Any) -> dict[str, Any]:
        assert _subscription_slots(event_bus, started_event) == 1
        return {
            "status": "pending_review",
            "assistant_response": "done",
        }

    core = _core(run_task)
    run_mode = RunMode(core=core)

    assert _subscription_slots(event_bus, started_event) == 0

    await run_mode.start(name="Scoped task", description="Do the thing")

    assert _subscription_slots(event_bus, started_event) == 0
    for event_type in (
        TaskEvent.STARTED.value,
        TaskEvent.PROGRESSED.value,
        TaskEvent.COMPLETED.value,
        TaskEvent.NEEDS_INPUT.value,
    ):
        assert _subscription_slots(event_bus, event_type) == 0


@pytest.mark.asyncio
async def test_overlapping_session_goals_do_not_use_global_task_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    event_bus = EventBus()
    monkeypatch.setattr(EventBus, "_instance", event_bus)
    both_started = asyncio.Event()
    release = asyncio.Event()
    calls: list[dict[str, Any]] = []

    async def run_task(**kwargs: Any) -> dict[str, Any]:
        calls.append(kwargs)
        if len(calls) == 2:
            both_started.set()
        await release.wait()
        return {
            "status": "pending_review",
            "assistant_response": "done",
        }

    first = RunMode(core=_core(run_task))
    second = RunMode(core=_core(run_task))
    first_run = asyncio.create_task(
        first.start(
            name="First goal",
            description="Do the first thing",
            context={"run_kind": "session_goal", "session_id": "session-1"},
        )
    )
    second_run = asyncio.create_task(
        second.start(
            name="Second goal",
            description="Do the second thing",
            context={"run_kind": "session_goal", "session_id": "session-2"},
        )
    )

    try:
        await asyncio.wait_for(both_started.wait(), timeout=1)
        for event_type in (
            TaskEvent.STARTED.value,
            TaskEvent.PROGRESSED.value,
            TaskEvent.COMPLETED.value,
            TaskEvent.NEEDS_INPUT.value,
        ):
            assert _subscription_slots(event_bus, event_type) == 0
        assert [call["enable_events"] for call in calls] == [False, False]
    finally:
        release.set()
        await asyncio.gather(first_run, second_run)
