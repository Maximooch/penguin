from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.engine import Engine, LoopState


def test_prepare_responses_tools_enables_openai_native_tools() -> None:
    model_config = SimpleNamespace(
        provider="openai",
        client_preference="native",
        use_responses_api=False,
        interrupt_on_tool_call=False,
    )
    engine_like = SimpleNamespace(
        model_config=model_config,
        _get_runtime_model_config=lambda: model_config,
    )
    tool_manager = SimpleNamespace(
        get_responses_tools=lambda: [{"type": "function", "name": "read_file"}]
    )

    extra_kwargs = Engine._prepare_responses_tools(engine_like, tool_manager)

    assert extra_kwargs == {
        "tools": [
            {
                "type": "function",
                "name": "read_file",
                "description": "",
                "parameters": {"type": "object", "properties": {}},
            }
        ],
        "tool_choice": "auto",
    }
    assert engine_like.model_config.interrupt_on_tool_call is True


@pytest.mark.asyncio
async def test_call_llm_with_retry_skips_retry_when_tool_call_pending() -> None:
    class _Client:
        def __init__(self) -> None:
            self.calls = 0
            self.client_handler = SimpleNamespace(has_pending_tool_call=lambda: True)

        async def get_response(self, *_args, **_kwargs) -> str:
            self.calls += 1
            return ""

    api_client = _Client()
    engine_like = SimpleNamespace(
        _handler_has_pending_tool_call=lambda client: Engine._handler_has_pending_tool_call(
            engine_like,
            client,
        ),
        _build_empty_response_diagnostics=lambda *_args, **_kwargs: {},
    )

    result = await Engine._call_llm_with_retry(
        engine_like,
        api_client,
        [{"role": "user", "content": "hi"}],
        True,
        None,
        {},
    )

    assert result == ""
    assert api_client.calls == 1


def test_wallet_guard_does_not_break_on_tool_only_empty_iteration() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState(empty_response_count=2)
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    should_break, status = Engine._check_wallet_guard_termination(
        engine,
        last_response="",
        iteration_results=[
            {"action": "code_execution", "result": "42", "status": "completed"}
        ],
        mode="response",
    )

    assert should_break is False
    assert status is None
    assert loop_state.empty_response_count == 0
    assert loop_state.empty_tool_only_count == 1


def test_wallet_guard_breaks_on_repeated_empty_tool_only_iterations() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    for _ in range(2):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="[Empty response from model]",
            iteration_results=[
                {
                    "action": "find_file",
                    "result": "No match",
                    "status": "completed",
                }
            ],
            mode="response",
        )

        assert should_break is False
        assert status is None

    should_break, status = Engine._check_wallet_guard_termination(
        engine,
        last_response="[Empty response from model]",
        iteration_results=[
            {"action": "find_file", "result": "No match", "status": "completed"}
        ],
        mode="response",
    )

    assert should_break is True
    assert status == "repeated_empty_tool_only_iterations"
    assert loop_state.empty_tool_only_count == 3
    assert loop_state.repeated_tool_only_count == 3


def test_wallet_guard_keeps_short_empty_tool_only_chain_when_results_change() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    first = Engine._check_wallet_guard_termination(
        engine,
        last_response="",
        iteration_results=[
            {"action": "find_file", "result": "No match", "status": "completed"}
        ],
        mode="response",
    )
    second = Engine._check_wallet_guard_termination(
        engine,
        last_response="",
        iteration_results=[
            {"action": "grep_search", "result": "other result", "status": "completed"}
        ],
        mode="response",
    )

    assert first == (False, None)
    assert second == (False, None)
    assert loop_state.empty_tool_only_count == 2
    assert loop_state.repeated_tool_only_count == 1


def test_wallet_guard_allows_many_empty_tool_only_turns_when_results_change() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    for index in range(12):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="",
            iteration_results=[
                {
                    "action": f"read_file_{index}",
                    "result": f"different result {index}",
                    "status": "completed",
                }
            ],
            mode="response",
        )

        assert should_break is False
        assert status is None

    assert loop_state.empty_tool_only_count == 12
    assert loop_state.repeated_tool_only_count == 1


def test_suppress_empty_tool_only_placeholder_removes_persisted_placeholder() -> None:
    engine = Engine.__new__(Engine)
    session_manager = SimpleNamespace(mark_session_modified=lambda _session_id: None)
    conversation = SimpleNamespace(
        session=SimpleNamespace(
            id="ses_123",
            messages=[
                SimpleNamespace(role="assistant", content="[Empty response from model]")
            ],
        ),
        _modified=False,
        session_manager=session_manager,
    )
    cm = SimpleNamespace(conversation=conversation)

    result = Engine._suppress_empty_tool_only_placeholder(
        engine,
        cm,
        "[Empty response from model]",
        [{"action": "list_files", "result": "files", "status": "completed"}],
    )

    assert result == ""
    assert conversation.session.messages == []
    assert conversation._modified is True


@pytest.mark.asyncio
async def test_record_tool_only_stall_note_persists_clearer_terminal_message() -> None:
    engine = Engine.__new__(Engine)
    engine._save_conversation = AsyncMock()  # type: ignore[method-assign]
    added: list[str] = []

    class _Conversation:
        def __init__(self) -> None:
            self.session = SimpleNamespace(messages=[])

        def add_assistant_message(self, content: str):
            added.append(content)
            self.session.messages.append(
                SimpleNamespace(role="assistant", content=content)
            )

    cm = SimpleNamespace(conversation=_Conversation())

    result = await Engine._record_tool_only_stall_note(
        engine,
        cm,
        "repeated_empty_tool_only_iterations",
    )

    assert (
        result
        == "Stopping because empty tool-only turns are repeating the same tool outputs; this is probably a stale loop rather than forward progress."
    )
    assert added == [result]
    engine._save_conversation.assert_awaited_once()
