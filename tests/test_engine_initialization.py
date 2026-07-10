"""Regression tests for Engine initialization order."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.engine import Engine, EngineSettings, _ScopedConversationManager
from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMProviderError,
    LLMRequestLifecycle,
    ProviderRequestStatus,
)
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.system.state import Session
from penguin.utils.errors import (
    LLMEmptyResponseError,
    NativeToolHistoryPersistenceError,
)


def test_engine_initializes_without_run_state_attribute_error() -> None:
    conversation_manager = MagicMock()
    api_client = MagicMock()
    tool_manager = MagicMock()
    action_executor = MagicMock()

    engine = Engine(
        EngineSettings(),
        conversation_manager,
        api_client,
        tool_manager,
        action_executor,
    )

    assert engine.current_agent_id is None
    assert engine.default_agent_id == "default"
    assert "default" in engine.agents


def test_scoped_conversation_clone_preserves_typed_records() -> None:
    typed_lifecycle = object()
    typed_tool_call = object()
    typed_tool_result = object()
    session = Session()
    session.llm_request_lifecycles = [typed_lifecycle, {"request_id": "req_1"}]
    session.tool_call_records = [typed_tool_call, {"call_id": "call_1"}]
    session.tool_result_records = [typed_tool_result, {"call_id": "call_1"}]
    conversation = SimpleNamespace(session=session)
    manager = SimpleNamespace(
        get_agent_conversation=lambda *_args, **_kwargs: conversation
    )

    scoped = _ScopedConversationManager(manager, "default")
    cloned_session = scoped.conversation.session

    assert cloned_session is not session
    assert cloned_session.llm_request_lifecycles[0] is typed_lifecycle
    assert cloned_session.llm_request_lifecycles[1] == {"request_id": "req_1"}
    assert cloned_session.tool_call_records[0] is typed_tool_call
    assert cloned_session.tool_result_records[0] is typed_tool_result


def test_tool_output_cap_non_positive_env_disables_truncation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = Engine.__new__(Engine)
    monkeypatch.setenv("PENGUIN_TOOL_OUTPUT_MAX_CHARS", "0")

    assert engine._resolve_tool_output_max_chars() is None


def test_tool_output_artifact_dir_sanitizes_session_id(tmp_path) -> None:
    engine = Engine.__new__(Engine)
    cm = SimpleNamespace(
        workspace_path=str(tmp_path),
        get_current_session=MagicMock(
            return_value=SimpleNamespace(id="../bad/session")
        ),
    )

    artifact_dir = engine._tool_output_artifact_dir(cast(Any, cm))

    assert artifact_dir == (tmp_path / "conversations" / "tool-results" / "bad_session")


@pytest.mark.asyncio
async def test_finalize_streaming_response_persists_non_chunk_output() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    conversation = SimpleNamespace(
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    core = SimpleNamespace(finalize_streaming_message=MagicMock(return_value=None))
    cm = SimpleNamespace(
        conversation=conversation,
        core=core,
        get_current_session=MagicMock(return_value=SimpleNamespace(id="session_1")),
    )

    result = await engine._finalize_streaming_response(
        cast(Any, cm),
        "[Error: Model rejected image input]",
        streaming=True,
        agent_id="default",
    )

    assert result == "[Error: Model rejected image input]"
    conversation.add_assistant_message.assert_called_once_with(
        "[Error: Model rejected image input]"
    )


@pytest.mark.asyncio
async def test_finalize_streaming_response_uses_finalized_content_without_duplicate_save() -> (
    None
):
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    conversation = SimpleNamespace(
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    core = SimpleNamespace(
        finalize_streaming_message=MagicMock(
            return_value={"content": "streamed answer"}
        )
    )
    cm = SimpleNamespace(
        conversation=conversation,
        core=core,
        get_current_session=MagicMock(return_value=SimpleNamespace(id="session_1")),
    )

    result = await engine._finalize_streaming_response(
        cast(Any, cm),
        "fallback answer",
        streaming=True,
        agent_id="default",
    )

    assert result == "streamed answer"
    conversation.add_assistant_message.assert_not_called()


@pytest.mark.asyncio
async def test_call_llm_with_retry_skips_non_stream_retry_after_streamed_chunks() -> (
    None
):
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    streamed: list[tuple[str, str]] = []

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, kwargs
        if stream:
            assert stream_callback is not None
            await stream_callback("hello", "assistant")
            return ""
        raise AssertionError(
            "non-stream retry should not happen after streamed assistant chunks"
        )

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        client_handler=SimpleNamespace(),
    )

    async def _collector(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    result = await engine._call_llm_with_retry(
        cast(Any, api_client),
        [{"role": "user", "content": "hi"}],
        streaming=True,
        stream_callback=_collector,
        extra_kwargs={},
    )

    assert result == ""
    assert streamed == [("hello", "assistant")]
    assert api_client.get_response.await_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_replays_non_stream_retry_into_stream_callback() -> (
    None
):
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    streamed: list[tuple[str, str]] = []

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, stream_callback, kwargs
        if stream:
            return ""
        return "fallback answer"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        client_handler=SimpleNamespace(),
    )

    async def _collector(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    result = await engine._call_llm_with_retry(
        cast(Any, api_client),
        [{"role": "user", "content": "hi"}],
        streaming=True,
        stream_callback=_collector,
        extra_kwargs={},
    )

    assert result == "fallback answer"
    assert streamed == [("fallback answer", "assistant")]
    assert api_client.get_response.await_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_replays_retryable_provider_failure_once() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    retryable_error = LLMError(
        message="stream disconnected",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )
    current_error: LLMError | None = None

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        nonlocal current_error
        del messages, stream_callback, kwargs
        if stream:
            current_error = retryable_error
            return "Error: LLM network request failed. Diagnostic ID: test"
        current_error = None
        return "recovered answer"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: current_error,
        client_handler=SimpleNamespace(),
    )

    result = await engine._call_llm_with_retry(
        cast(Any, api_client),
        [{"role": "user", "content": "hi"}],
        streaming=True,
        stream_callback=None,
        extra_kwargs={},
    )

    assert result == "recovered answer"
    assert api_client.get_response.await_count == 2
    assert api_client.get_response.await_args_list[1].kwargs["stream"] is False


@pytest.mark.asyncio
async def test_call_llm_with_retry_rejects_partial_assistant_provider_failure() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    retryable_error = LLMError(
        message="stream disconnected after partial output",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )
    current_error: LLMError | None = None

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        nonlocal current_error
        del messages, stream_callback, kwargs
        if stream:
            current_error = retryable_error
            return "partial before disconnect"
        current_error = None
        return "recovered answer"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: current_error,
        client_handler=SimpleNamespace(),
    )

    with pytest.raises(LLMProviderError):
        await engine._call_llm_with_retry(
            cast(Any, api_client),
            [{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=None,
            extra_kwargs={},
        )

    assert api_client.get_response.await_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_surfaces_non_retryable_provider_failure() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    current_error = LLMError(
        message="bad request",
        category=ErrorCategory.BAD_REQUEST,
        retryable=False,
        provider="openai",
        model="gpt-test",
    )

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, stream, stream_callback, kwargs
        return "Error: LLM upstream rejected the request. Diagnostic ID: test"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: current_error,
        client_handler=SimpleNamespace(),
    )

    with pytest.raises(LLMProviderError):
        await engine._call_llm_with_retry(
            cast(Any, api_client),
            [{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=None,
            extra_kwargs={},
        )
    assert api_client.get_response.await_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_skips_retryable_failure_when_tool_pending() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    current_error = LLMError(
        message="stream disconnected after tool call",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, stream, stream_callback, kwargs
        return "Error: LLM network request failed. Diagnostic ID: test"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: current_error,
        client_handler=SimpleNamespace(has_pending_tool_call=lambda: True),
    )

    with pytest.raises(LLMProviderError):
        await engine._call_llm_with_retry(
            cast(Any, api_client),
            [{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=None,
            extra_kwargs={},
        )
    assert api_client.get_response.await_count == 1


@pytest.mark.asyncio
async def test_call_llm_with_retry_surfaces_retry_exhaustion_once() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    retryable_error = LLMError(
        message="stream disconnected",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )
    responses = [
        "Error: LLM network request failed. Diagnostic ID: first",
        "Error: LLM network request failed. Diagnostic ID: second",
    ]

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, stream, stream_callback, kwargs
        return responses.pop(0)

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: retryable_error,
        client_handler=SimpleNamespace(),
    )

    with pytest.raises(LLMProviderError):
        await engine._call_llm_with_retry(
            cast(Any, api_client),
            [{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=None,
            extra_kwargs={},
        )
    assert api_client.get_response.await_count == 2


@pytest.mark.asyncio
async def test_call_llm_with_retry_rejects_failed_partial_stream() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    retryable_error = LLMError(
        message="stream disconnected after partial output",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )
    streamed: list[tuple[str, str]] = []

    async def _fake_get_response(messages, stream=None, stream_callback=None, **kwargs):
        del messages, kwargs
        if stream_callback:
            await stream_callback("partial", "assistant")
        return "partial"

    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=_fake_get_response),
        get_last_error=lambda: retryable_error,
        client_handler=SimpleNamespace(),
    )

    async def _collector(chunk: str, message_type: str = "assistant") -> None:
        streamed.append((chunk, message_type))

    with pytest.raises(LLMProviderError):
        await engine._call_llm_with_retry(
            cast(Any, api_client),
            [{"role": "user", "content": "hi"}],
            streaming=True,
            stream_callback=_collector,
            extra_kwargs={},
        )

    assert streamed == [("partial", "assistant")]
    assert api_client.get_response.await_count == 1


@pytest.mark.asyncio
async def test_llm_step_aborts_stream_on_provider_failure() -> None:
    provider_error = LLMError(
        message="stream disconnected",
        category=ErrorCategory.NETWORK,
        retryable=True,
        provider="openai",
        model="gpt-test",
    )
    cm = MagicMock()
    cm.conversation.get_formatted_messages.return_value = [
        {"role": "user", "content": "hi"}
    ]
    cm.get_current_session.return_value = SimpleNamespace(id="session_1")
    cm.core = MagicMock()
    engine = Engine(
        EngineSettings(),
        cm,
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    engine._prepare_responses_tools = MagicMock(return_value={})  # type: ignore[method-assign]
    engine._call_llm_with_retry = AsyncMock(  # type: ignore[method-assign]
        side_effect=LLMProviderError(provider_error)
    )

    with pytest.raises(LLMProviderError):
        await engine._llm_step(
            tools_enabled=True,
            streaming=True,
            stream_callback=AsyncMock(),
            agent_id="default",
        )

    cm.core.abort_streaming_message.assert_called_once()
    assert cm.core.abort_streaming_message.call_args.kwargs["agent_id"] == "default"


@pytest.mark.asyncio
async def test_llm_step_aborts_stream_on_empty_response_failure() -> None:
    cm = MagicMock()
    cm.conversation.get_formatted_messages.return_value = [
        {"role": "user", "content": "hi"}
    ]
    cm.get_current_session.return_value = SimpleNamespace(id="session_1")
    cm.core = MagicMock()
    engine = Engine(
        EngineSettings(),
        cm,
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    engine._prepare_responses_tools = MagicMock(return_value={})  # type: ignore[method-assign]
    engine._call_llm_with_retry = AsyncMock(  # type: ignore[method-assign]
        side_effect=LLMEmptyResponseError("provider returned no usable output")
    )

    with pytest.raises(LLMEmptyResponseError):
        await engine._llm_step(
            tools_enabled=True,
            streaming=True,
            stream_callback=AsyncMock(),
            agent_id="default",
        )

    cm.core.abort_streaming_message.assert_called_once()
    assert cm.core.abort_streaming_message.call_args.kwargs["agent_id"] == "default"


def test_session_persists_llm_request_lifecycle_records() -> None:
    lifecycle = LLMRequestLifecycle(
        request_id="req-lifecycle-1",
        provider="openai",
        model="gpt-test",
        status=ProviderRequestStatus.COMPLETED,
        stream=True,
        transport="responses",
        attempt=2,
        started_at=10.0,
        last_event_at=12.0,
        ended_at=12.5,
        provider_response_id="resp_1",
        last_event_type="response.completed",
        finish_reason=FinishReason.STOP,
        provider_data={"message_count": 3},
    )

    session = Session()
    session.add_llm_request_lifecycle(lifecycle)
    session.add_llm_request_lifecycle(
        {
            **lifecycle.to_dict(),
            "status": ProviderRequestStatus.FAILED.value,
        }
    )

    assert len(session.llm_request_lifecycles) == 1
    assert session.llm_request_lifecycles[0]["status"] == "failed"
    assert session.metadata["llm_request_lifecycle_count"] == 1

    reloaded = Session.from_dict(session.to_dict())

    assert reloaded.llm_request_lifecycles == session.llm_request_lifecycles


def test_engine_persists_latest_provider_lifecycle_on_active_session() -> None:
    engine = Engine(
        EngineSettings(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    lifecycle = LLMRequestLifecycle(
        request_id="req-engine-1",
        provider="openrouter",
        model="openai/gpt-test",
        status=ProviderRequestStatus.DISCONNECTED,
        stream=True,
        started_at=20.0,
        last_event_at=21.0,
        ended_at=21.0,
        error=LLMError(
            message="stream stalled",
            category=ErrorCategory.TIMEOUT,
            retryable=True,
        ),
    )
    session = Session()
    cm = SimpleNamespace(get_current_session=lambda: session)
    api_client = SimpleNamespace(get_last_request_lifecycle=lambda: lifecycle)

    engine._persist_llm_request_lifecycle(cast(Any, cm), cast(Any, api_client))

    assert session.llm_request_lifecycles == [lifecycle.to_dict()]


@pytest.mark.asyncio
async def test_llm_step_persists_lifecycle_even_when_provider_raises() -> None:
    session = Session()
    conversation = SimpleNamespace(
        get_formatted_messages=MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        ),
        session=session,
        add_assistant_message=MagicMock(),
    )
    conversation_manager = SimpleNamespace(
        conversation=conversation,
        core=None,
        get_current_session=lambda: session,
    )
    lifecycle = LLMRequestLifecycle(
        request_id="req-failed-1",
        provider="anthropic",
        model="claude-test",
        status=ProviderRequestStatus.FAILED,
        stream=False,
        started_at=30.0,
        last_event_at=30.1,
        ended_at=30.1,
        error=LLMError(
            message="upstream rejected request",
            category=ErrorCategory.BAD_REQUEST,
            retryable=False,
        ),
    )
    api_client = SimpleNamespace(
        get_response=AsyncMock(side_effect=RuntimeError("boom")),
        get_last_request_lifecycle=lambda: lifecycle,
        get_last_error=lambda: lifecycle.error,
        client_handler=SimpleNamespace(),
    )
    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        cast(Any, api_client),
        MagicMock(),
        MagicMock(),
    )

    with pytest.raises(RuntimeError):
        await engine._llm_step(tools_enabled=False, streaming=False)

    assert session.llm_request_lifecycles == [lifecycle.to_dict()]


def test_scoped_conversation_manager_clones_default_agent_session() -> None:
    base_session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=base_session,
        save=MagicMock(return_value=True),
        add_action_result=MagicMock(),
    )
    base_manager = SimpleNamespace(
        core=None,
        get_agent_conversation=MagicMock(return_value=conversation),
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=base_session),
        agent_context_windows={},
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, base_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    scoped = engine.get_conversation_manager("default")
    assert scoped is not None
    assert scoped.conversation is not conversation
    assert scoped.get_current_session() is not base_session
    assert scoped.get_current_session().id == "session-a"


def test_scoped_conversation_manager_is_reused_within_run_state() -> None:
    base_session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=base_session,
        save=MagicMock(return_value=True),
        add_action_result=MagicMock(),
    )
    base_manager = SimpleNamespace(
        core=None,
        get_agent_conversation=MagicMock(return_value=conversation),
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=base_session),
        agent_context_windows={},
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, base_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    with engine._run_state_scope("default"):
        first = engine.get_conversation_manager("default")
        second = engine.get_conversation_manager("default")

    assert first is not None
    assert second is not None
    assert first is second


def test_preloaded_scoped_conversation_manager_is_adopted_within_run_state() -> None:
    base_session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=base_session,
        save=MagicMock(return_value=True),
        add_action_result=MagicMock(),
    )
    base_manager = SimpleNamespace(
        core=None,
        get_agent_conversation=MagicMock(return_value=conversation),
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=base_session),
        agent_context_windows={},
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, base_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )

    preloaded = engine.get_conversation_manager("default")
    assert preloaded is not None

    with execution_context_scope(
        ExecutionContext(session_id="session-a", request_id="req-1")
    ):
        engine.prime_scoped_conversation_manager("default", preloaded)
        with engine._run_state_scope("default"):
            adopted = engine.get_conversation_manager("default")

    assert adopted is preloaded


def test_scoped_conversation_manager_reports_scoped_context_window_usage() -> None:
    from penguin.system.context_window import ContextWindowManager
    from penguin.system.state import MessageCategory

    scoped_window = ContextWindowManager(token_counter=lambda _content: 0)
    scoped_window.max_context_window_tokens = 1_000
    scoped_window.update_usage(MessageCategory.DIALOG, 125)
    scoped_window.truncation_tracker.record_truncation(
        MessageCategory.DIALOG,
        messages_removed=2,
        tokens_freed=300,
        total_messages_before=5,
        total_messages_after=3,
    )
    global_window = ContextWindowManager(token_counter=lambda _content: 0)
    global_window.max_context_window_tokens = 1_000
    global_window.update_usage(MessageCategory.DIALOG, 900)
    global_window.truncation_tracker.record_truncation(
        MessageCategory.DIALOG,
        messages_removed=47,
        tokens_freed=67_000,
        total_messages_before=50,
        total_messages_after=3,
    )
    session = SimpleNamespace(id="session-scoped", messages=[])
    conversation = SimpleNamespace(session=session, context_window=scoped_window)
    base_manager = SimpleNamespace(
        core=None,
        get_agent_conversation=MagicMock(return_value=conversation),
        context_window=global_window,
        agent_context_windows={},
    )

    scoped = _ScopedConversationManager(cast(Any, base_manager), "agent-a")
    usage = scoped.get_token_usage()

    assert usage["current_total_tokens"] == 125
    assert usage["categories"]["DIALOG"] == 125
    assert usage["truncations"]["messages_removed"] == 2
    assert usage["truncations"]["tokens_freed"] == 300


def test_scoped_conversation_manager_does_not_fall_back_to_global_window() -> None:
    from penguin.system.context_window import ContextWindowManager
    from penguin.system.state import Message, MessageCategory

    global_window = ContextWindowManager(token_counter=lambda _content: 0)
    global_window.max_context_window_tokens = 1_000
    global_window.update_usage(MessageCategory.DIALOG, 900)
    global_window.truncation_tracker.record_truncation(
        MessageCategory.DIALOG,
        messages_removed=47,
        tokens_freed=67_000,
        total_messages_before=50,
        total_messages_after=3,
    )
    session = SimpleNamespace(
        id="session-scoped",
        messages=[
            Message(
                role="user",
                content="hi",
                category=MessageCategory.DIALOG,
                tokens=12,
            )
        ],
    )
    conversation = SimpleNamespace(session=session, context_window=None)
    base_manager = SimpleNamespace(
        core=None,
        get_agent_conversation=MagicMock(return_value=conversation),
        context_window=global_window,
        agent_context_windows={},
    )

    scoped = _ScopedConversationManager(cast(Any, base_manager), "agent-a")
    usage = scoped.get_token_usage()

    assert usage["current_total_tokens"] == 12
    assert usage["categories"]["DIALOG"] == 12
    assert usage["truncations"]["messages_removed"] == 0
    assert usage["truncations"]["tokens_freed"] == 0


@pytest.mark.asyncio
async def test_llm_step_returns_usage_from_active_api_client() -> None:
    conversation = SimpleNamespace(
        get_formatted_messages=MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        ),
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    conversation_manager = SimpleNamespace(conversation=conversation, core=None)

    handler = SimpleNamespace(
        get_last_usage=MagicMock(
            return_value={
                "input_tokens": 12,
                "output_tokens": 5,
                "reasoning_tokens": 2,
                "cache_read_tokens": 0,
                "cache_write_tokens": 0,
                "total_tokens": 17,
                "cost": 0.0003,
            }
        )
    )
    api_client = SimpleNamespace(
        get_response=AsyncMock(return_value="hello"),
        client_handler=handler,
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        cast(Any, api_client),
        MagicMock(),
        MagicMock(),
    )

    result = await engine._llm_step(tools_enabled=False, streaming=False)

    assert result["assistant_response"] == "hello"
    assert result["usage"] == {
        "input_tokens": 12,
        "output_tokens": 5,
        "reasoning_tokens": 2,
        "cache_read_tokens": 0,
        "cache_write_tokens": 0,
        "total_tokens": 17,
        "cost": 0.0003,
    }


@pytest.mark.asyncio
async def test_run_response_uses_request_scoped_api_client_override() -> None:
    session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=session,
        get_formatted_messages=MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        ),
        prepare_conversation=MagicMock(),
        add_assistant_message=MagicMock(),
        save=MagicMock(return_value=True),
    )
    conversation_manager = SimpleNamespace(
        core=None,
        conversation=conversation,
        get_agent_conversation=lambda *args, **kwargs: conversation,
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=session),
        agent_context_windows={},
    )

    default_api = SimpleNamespace(
        get_response=AsyncMock(return_value="default"),
        client_handler=SimpleNamespace(get_last_usage=MagicMock(return_value={})),
    )
    override_api = SimpleNamespace(
        get_response=AsyncMock(return_value="override"),
        client_handler=SimpleNamespace(get_last_usage=MagicMock(return_value={})),
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        cast(Any, default_api),
        MagicMock(),
        MagicMock(),
    )

    result = await engine.run_response(
        "hi",
        streaming=False,
        max_iterations=1,
        api_client_override=cast(Any, override_api),
    )

    assert result["assistant_response"] == "override"
    assert result["status"] == "completed"
    assert default_api.get_response.await_count == 0
    assert override_api.get_response.await_count == 1


@pytest.mark.asyncio
async def test_run_response_repairs_malformed_partial_tool_output() -> None:
    session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=session,
        prepare_conversation=MagicMock(),
        add_message=MagicMock(),
        save=MagicMock(return_value=True),
    )
    conversation_manager = SimpleNamespace(
        core=None,
        conversation=conversation,
        get_agent_conversation=lambda *args, **kwargs: conversation,
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=session),
        agent_context_windows={},
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        side_effect=[
            {
                "assistant_response": '-contract.md","show_line_numbers":true}</read_file>\n\n',
                "action_results": [],
                "usage": {},
            },
            {
                "assistant_response": "Recovered answer",
                "action_results": [
                    {"action": "finish_response", "result": "", "status": "completed"}
                ],
                "usage": {},
            },
        ]
    )
    engine._save_conversation = AsyncMock()  # type: ignore[method-assign]

    result = await engine.run_response("continue", streaming=False)

    assert result["assistant_response"] == "Recovered answer"
    assert result["iterations"] == 2
    conversation.add_message.assert_called()
    assert conversation.add_message.call_args.kwargs["metadata"]["type"] == (
        "malformed_action_output"
    )


@pytest.mark.asyncio
async def test_run_response_surfaces_native_tool_history_failure_without_retrying() -> (
    None
):
    """The direct response loop preserves the non-retryable history failure."""

    session = SimpleNamespace(id="session-a", messages=[])
    conversation = SimpleNamespace(
        session=session,
        prepare_conversation=MagicMock(),
        save=MagicMock(return_value=True),
    )
    conversation_manager = SimpleNamespace(
        core=None,
        conversation=conversation,
        get_agent_conversation=lambda *args, **kwargs: conversation,
        save=MagicMock(return_value=True),
        get_current_session=MagicMock(return_value=session),
        agent_context_windows={},
    )
    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        MagicMock(),
        MagicMock(),
        MagicMock(),
    )
    engine._llm_step = AsyncMock(  # type: ignore[method-assign]
        side_effect=NativeToolHistoryPersistenceError(["call_pwd"])
    )

    result = await engine.run_response("continue", streaming=False, max_iterations=2)

    engine._llm_step.assert_awaited_once()
    assert result["status"] == "native_tool_history_error"
    assert result["recoverable"] is False
    assert result["error"]["code"] == "NATIVE_TOOL_HISTORY_PERSISTENCE_FAILED"


@pytest.mark.asyncio
async def test_llm_step_injects_plan_mode_notice() -> None:
    conversation = SimpleNamespace(
        get_formatted_messages=MagicMock(
            return_value=[{"role": "user", "content": "hi"}]
        ),
        session=SimpleNamespace(messages=[]),
        add_assistant_message=MagicMock(),
    )
    conversation_manager = SimpleNamespace(conversation=conversation, core=None)

    handler = SimpleNamespace(get_last_usage=MagicMock(return_value=None))
    api_client = SimpleNamespace(
        get_response=AsyncMock(return_value="hello"),
        client_handler=handler,
    )

    engine = Engine(
        EngineSettings(),
        cast(Any, conversation_manager),
        cast(Any, api_client),
        MagicMock(),
        MagicMock(),
    )

    with execution_context_scope(
        ExecutionContext(
            session_id="session-plan", agent_id="default", agent_mode="plan"
        )
    ):
        await engine._llm_step(tools_enabled=False, streaming=False)

    messages = api_client.get_response.await_args.args[0]
    assert isinstance(messages, list)
    assert any(
        isinstance(msg, dict)
        and msg.get("role") == "system"
        and "PENGUIN_AGENT_MODE_PLAN" in str(msg.get("content", ""))
        for msg in messages
    )
