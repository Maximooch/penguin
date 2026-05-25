"""Tests for process orchestration runtime helpers."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import process_runtime


def _log() -> SimpleNamespace:
    return SimpleNamespace(
        debug=lambda *args, **kwargs: None,
        error=lambda *args, **kwargs: None,
    )


def _trace(calls: list[str]):
    def trace_log_info(message: str, *args: Any) -> None:
        calls.append(message)

    return trace_log_info


def _process_kwargs(**overrides: Any) -> dict[str, Any]:
    kwargs: dict[str, Any] = {
        "input_data": "hello",
        "context": None,
        "conversation_id": None,
        "agent_id": None,
        "max_iterations": 1,
        "context_files": None,
        "streaming": False,
        "stream_callback": None,
        "multi_step": True,
        "api_client_override": None,
        "model_config_override": None,
        "log": _log(),
        "trace_log_info": _trace([]),
        "log_error_fn": lambda *_args, **_kwargs: None,
    }
    kwargs.update(overrides)
    return kwargs


@pytest.mark.asyncio
async def test_process_with_retry_retries_transient_runtime_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    sleeps: list[float] = []

    async def flaky_process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        attempts.append("attempt")
        if len(attempts) == 1:
            raise RuntimeError("transient")
        return {"assistant_response": "done", "action_results": []}

    async def no_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(process_runtime, "process", flaky_process)

    result = await process_runtime.process_with_retry(
        SimpleNamespace(),
        retry_sleep=no_sleep,
        **_process_kwargs(),
    )

    assert result == {"assistant_response": "done", "action_results": []}
    assert attempts == ["attempt", "attempt"]
    assert sleeps == [4.0]


@pytest.mark.asyncio
async def test_process_with_retry_returns_exception_after_retry_exhaustion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts: list[str] = []
    sleeps: list[float] = []

    async def failing_process(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        attempts.append("attempt")
        raise RuntimeError("persistent")

    async def no_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(process_runtime, "process", failing_process)

    result = await process_runtime.process_with_retry(
        SimpleNamespace(),
        retry_sleep=no_sleep,
        **_process_kwargs(),
    )

    assert isinstance(result, RuntimeError)
    assert str(result) == "persistent"
    assert attempts == ["attempt", "attempt", "attempt"]
    assert sleeps == [4.0, 4.0]


@pytest.mark.asyncio
async def test_process_empty_input_returns_without_resolving_conversation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(engine=object())

    def fail_resolve(*_args: Any, **_kwargs: Any) -> None:
        raise AssertionError("empty input should return before runtime setup")

    monkeypatch.setattr(
        process_runtime.core_conversations,
        "resolve_conversation_manager",
        fail_resolve,
    )

    result = await process_runtime.process(
        owner,
        input_data={"text": ""},
        context=None,
        conversation_id=None,
        agent_id=None,
        max_iterations=1,
        context_files=None,
        streaming=False,
        stream_callback=None,
        multi_step=True,
        api_client_override=None,
        model_config_override=None,
        log=_log(),
        trace_log_info=_trace([]),
        log_error_fn=lambda *_args, **_kwargs: None,
    )

    assert result == {"assistant_response": "No input provided", "action_results": []}


@pytest.mark.asyncio
async def test_process_engine_path_orchestrates_and_releases_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(engine=object())
    conversation_manager = SimpleNamespace(
        conversation=SimpleNamespace(session=SimpleNamespace(id="active-session"))
    )
    calls: list[tuple[str, Any]] = []
    trace_calls: list[str] = []

    monkeypatch.setattr(
        process_runtime,
        "get_current_execution_context",
        lambda: SimpleNamespace(
            request_id="request-1",
            session_id="request-session",
            conversation_id="scoped-conversation",
        ),
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "resolve_conversation_manager",
        lambda owner, agent_id, *, log: conversation_manager,
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "load_process_conversation",
        lambda manager, conversation_id, *, log: calls.append(
            ("load_conversation", conversation_id)
        )
        or SimpleNamespace(via="manager", ok=True, scoped_session_id="loaded-session"),
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "load_process_context_files",
        lambda manager, context_files: calls.append(
            ("load_context_files", context_files)
        )
        or 2,
    )

    async def register_request(owner: Any, session_id: str, task: asyncio.Task[Any]):
        calls.append(("register_request", (session_id, task is asyncio.current_task())))
        return True

    async def finalize_request(
        owner: Any,
        session_id: str,
        task: asyncio.Task[Any],
        *,
        request_tracked: bool,
    ) -> None:
        calls.append(
            (
                "finalize_request",
                (session_id, task is asyncio.current_task(), request_tracked),
            )
        )

    async def emit_user_message(owner: Any, message: str, **kwargs: Any) -> None:
        calls.append(("emit_user_message", (message, kwargs)))

    async def run_engine_process(owner: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("run_engine_process", kwargs))
        return {
            "assistant_response": "done",
            "action_results": [{"ok": True}],
            "status": "completed",
            "iterations": 1,
            "usage": {"total": 3},
        }

    async def finalize_response(
        owner: Any, manager: Any, response: Any, session_id: str, **kwargs: Any
    ) -> None:
        calls.append(("finalize_response", (response, session_id, kwargs)))

    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "register_opencode_process_request",
        register_request,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "finalize_opencode_process_request",
        finalize_request,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "emit_process_user_message",
        emit_user_message,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "finalize_process_response",
        finalize_response,
    )
    monkeypatch.setattr(
        process_runtime.core_process_streaming,
        "prepare_engine_process_context",
        lambda *args, **kwargs: calls.append(("prepare_engine_context", kwargs))
        or SimpleNamespace(
            stream_callback="engine-callback",
            scoped_conversation_id="scoped-conversation",
            scoped_session_id="request-session",
            stream_scope_id="scope",
        ),
    )
    monkeypatch.setattr(
        process_runtime.core_process_engine,
        "run_engine_process",
        run_engine_process,
    )

    result = await process_runtime.process(
        owner,
        input_data={
            "text": "hello",
            "image_paths": [" image.png "],
            "client_message_id": "client-1",
        },
        context={"task_mode": False},
        conversation_id="conversation-1",
        agent_id="agent-1",
        max_iterations=3,
        context_files=["ctx.py"],
        streaming=True,
        stream_callback=lambda chunk: None,
        multi_step=True,
        api_client_override="api-client",
        model_config_override="model-config",
        log=_log(),
        trace_log_info=_trace(trace_calls),
        log_error_fn=lambda *_args, **_kwargs: None,
    )

    assert result["assistant_response"] == "done"
    assert [name for name, _ in calls] == [
        "register_request",
        "load_conversation",
        "load_context_files",
        "emit_user_message",
        "prepare_engine_context",
        "run_engine_process",
        "finalize_response",
        "finalize_request",
    ]
    assert calls[0][1] == ("request-session", True)
    run_kwargs = calls[5][1]
    assert run_kwargs["message"] == "hello"
    assert run_kwargs["image_paths"] == ["image.png"]
    assert run_kwargs["engine_stream_callback"] == "engine-callback"
    assert run_kwargs["scoped_conversation_id"] == "scoped-conversation"
    assert calls[-1][1] == ("request-session", True, True)
    assert any("core.process.trace.start" in call for call in trace_calls)
    assert any("core.process.trace.done" in call for call in trace_calls)


@pytest.mark.asyncio
async def test_process_legacy_path_prepares_conversation_and_finalizes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    calls: list[tuple[str, Any]] = []

    async def get_response(**kwargs: Any) -> tuple[dict[str, Any], bool]:
        calls.append(("get_response", kwargs))
        return {"assistant_response": "legacy", "action_results": []}, True

    def prepare_conversation(message: str, *, image_paths: list[str]) -> None:
        calls.append(("prepare_conversation", (message, image_paths)))

    owner = SimpleNamespace(
        engine=None,
        get_response=get_response,
        _handle_stream_chunk="internal-stream-callback",
    )
    conversation_manager = SimpleNamespace(
        conversation=SimpleNamespace(
            session=SimpleNamespace(id="legacy-session"),
            prepare_conversation=prepare_conversation,
        )
    )

    monkeypatch.setattr(process_runtime, "get_current_execution_context", lambda: None)
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "resolve_conversation_manager",
        lambda *_args, **_kwargs: conversation_manager,
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "load_process_context_files",
        lambda *_args, **_kwargs: 0,
    )

    async def register_request(*_args: Any, **_kwargs: Any) -> bool:
        return False

    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "register_opencode_process_request",
        register_request,
    )

    async def emit_user_message(*_args: Any, **_kwargs: Any) -> None:
        calls.append(("emit_user_message", None))

    async def finalize_response(*_args: Any, **_kwargs: Any) -> None:
        calls.append(("finalize_response", None))

    async def finalize_request(*_args: Any, **_kwargs: Any) -> None:
        calls.append(("finalize_request", None))

    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "emit_process_user_message",
        emit_user_message,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "finalize_process_response",
        finalize_response,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "finalize_opencode_process_request",
        finalize_request,
    )

    result = await process_runtime.process(
        owner,
        input_data={"text": "legacy hello", "image_paths": " image.png "},
        context=None,
        conversation_id=None,
        agent_id=None,
        max_iterations=1,
        context_files=None,
        streaming=True,
        stream_callback=None,
        multi_step=True,
        api_client_override=None,
        model_config_override=None,
        log=_log(),
        trace_log_info=_trace([]),
        log_error_fn=lambda *_args, **_kwargs: None,
    )

    assert result == {"assistant_response": "legacy", "action_results": []}
    assert calls == [
        ("emit_user_message", None),
        ("prepare_conversation", ("legacy hello", ["image.png"])),
        (
            "get_response",
            {"stream_callback": "internal-stream-callback", "streaming": True},
        ),
        ("finalize_response", None),
        ("finalize_request", None),
    ]


@pytest.mark.asyncio
async def test_process_cancelled_returns_aborted_payload_and_releases_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    owner = SimpleNamespace(engine=object())
    conversation_manager = SimpleNamespace(
        conversation=SimpleNamespace(session=SimpleNamespace(id="active-session"))
    )
    finalized: list[tuple[str, bool]] = []

    monkeypatch.setattr(
        process_runtime,
        "get_current_execution_context",
        lambda: SimpleNamespace(request_id="request-1", session_id="session-1"),
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "resolve_conversation_manager",
        lambda *_args, **_kwargs: conversation_manager,
    )
    monkeypatch.setattr(
        process_runtime.core_conversations,
        "load_process_context_files",
        lambda *_args, **_kwargs: 0,
    )

    async def register_request(*_args: Any, **_kwargs: Any) -> bool:
        return True

    async def emit_user_message(*_args: Any, **_kwargs: Any) -> None:
        return None

    async def run_engine_process(*_args: Any, **_kwargs: Any) -> None:
        raise asyncio.CancelledError

    async def finalize_request(
        owner: Any,
        session_id: str,
        task: asyncio.Task[Any],
        *,
        request_tracked: bool,
    ) -> None:
        finalized.append((session_id, request_tracked))

    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "register_opencode_process_request",
        register_request,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "emit_process_user_message",
        emit_user_message,
    )
    monkeypatch.setattr(
        process_runtime.core_process_lifecycle,
        "finalize_opencode_process_request",
        finalize_request,
    )
    monkeypatch.setattr(
        process_runtime.core_process_streaming,
        "prepare_engine_process_context",
        lambda *args, **kwargs: SimpleNamespace(
            stream_callback=None,
            scoped_conversation_id="session-1",
        ),
    )
    monkeypatch.setattr(
        process_runtime.core_process_engine,
        "run_engine_process",
        run_engine_process,
    )

    result = await process_runtime.process(
        owner,
        input_data="hello",
        context=None,
        conversation_id=None,
        agent_id=None,
        max_iterations=1,
        context_files=None,
        streaming=False,
        stream_callback=None,
        multi_step=True,
        api_client_override=None,
        model_config_override=None,
        log=_log(),
        trace_log_info=_trace([]),
        log_error_fn=lambda *_args, **_kwargs: None,
    )

    assert result == {
        "assistant_response": "",
        "action_results": [],
        "aborted": True,
    }
    assert finalized == [("session-1", True)]
