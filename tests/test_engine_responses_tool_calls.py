from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.engine import Engine, LoopState
from penguin.llm.runtime import execute_pending_tool_call, execute_pending_tool_calls


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


def test_prepare_responses_tools_enables_openrouter_chat_tools() -> None:
    model_config = SimpleNamespace(
        provider="openrouter",
        client_preference="openrouter",
        use_responses_api=False,
        interrupt_on_tool_call=False,
    )
    engine_like = SimpleNamespace(
        model_config=model_config,
        _get_runtime_model_config=lambda: model_config,
    )
    tool_manager = SimpleNamespace(
        get_responses_tools=lambda **_kwargs: [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {"type": "web_search"},
        ]
    )

    extra_kwargs = Engine._prepare_responses_tools(engine_like, tool_manager)

    assert extra_kwargs == {
        "tools": [
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {
                        "type": "object",
                        "properties": {"path": {"type": "string"}},
                    },
                },
            }
        ],
        "tool_choice": "auto",
        "parallel_tool_calls": False,
    }
    assert engine_like.model_config.interrupt_on_tool_call is True


def test_prepare_responses_tools_enables_anthropic_tools() -> None:
    model_config = SimpleNamespace(
        provider="anthropic",
        client_preference="native",
        use_responses_api=False,
        interrupt_on_tool_call=False,
    )
    engine_like = SimpleNamespace(
        model_config=model_config,
        _get_runtime_model_config=lambda: model_config,
    )
    tool_manager = SimpleNamespace(
        get_responses_tools=lambda **_kwargs: [
            {
                "type": "function",
                "name": "read_file",
                "description": "Read a file",
                "parameters": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            },
            {"type": "web_search"},
        ]
    )

    extra_kwargs = Engine._prepare_responses_tools(engine_like, tool_manager)

    assert extra_kwargs == {
        "tools": [
            {
                "name": "read_file",
                "description": "Read a file",
                "input_schema": {
                    "type": "object",
                    "properties": {"path": {"type": "string"}},
                },
            }
        ],
        "tool_choice": {"type": "auto"},
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

    def _has_pending_tool_call(client):
        return Engine._handler_has_pending_tool_call(engine_like, client)

    engine_like = SimpleNamespace(
        _handler_has_pending_tool_call=_has_pending_tool_call,
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


@pytest.mark.asyncio
async def test_finish_response_tool_call_is_not_persisted_or_emitted() -> None:
    class _Handler:
        def __init__(self) -> None:
            self._tool_call = {
                "name": "finish_response",
                "arguments": "{}",
                "call_id": "call_finish_response",
            }

        def get_and_clear_last_tool_call(self):
            result = self._tool_call
            self._tool_call = None
            return result

    persisted: list[dict[str, object]] = []
    started: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    timeline: list[dict[str, object]] = []

    result = await execute_pending_tool_call(
        api_client=SimpleNamespace(
            client_handler=_Handler(),
            model_config=SimpleNamespace(provider="openai", model="gpt-5.4"),
        ),
        tool_manager=SimpleNamespace(
            execute_tool=lambda tool_name, tool_args: "Response complete."
        ),
        persist_action_result=lambda action_result, tool_context: persisted.append(
            {"action_result": action_result, "tool_context": tool_context}
        ),
        emit_action_start=lambda payload: started.append(payload),
        emit_action_result=lambda payload: completed.append(payload),
        emit_tool_timeline=lambda payload: timeline.append(payload),
    )

    assert result == {
        "action": "finish_response",
        "result": "Response complete.",
        "status": "completed",
    }
    assert persisted == []
    assert started == []
    assert completed == []
    assert timeline == []


@pytest.mark.asyncio
async def test_multiple_pending_responses_tool_calls_execute_serially() -> None:
    class _Handler:
        def __init__(self) -> None:
            self._tool_calls = [
                {
                    "name": "execute",
                    "arguments": '{"command":"pwd"}',
                    "call_id": "call_pwd",
                },
                {
                    "name": "execute",
                    "arguments": '{"command":"ls"}',
                    "call_id": "call_ls",
                },
            ]

        def get_and_clear_pending_tool_calls(self):
            result = self._tool_calls
            self._tool_calls = []
            return result

    persisted: list[dict[str, object]] = []
    started: list[dict[str, object]] = []
    completed: list[dict[str, object]] = []
    timeline: list[dict[str, object]] = []
    executed: list[tuple[str, dict[str, object]]] = []

    def _execute_tool(tool_name: str, tool_args: dict[str, object]) -> str:
        executed.append((tool_name, dict(tool_args)))
        return f"ran {tool_args['command']}"

    async def _emit_action_start(payload: dict[str, object]) -> None:
        started.append(payload)

    async def _emit_action_result(payload: dict[str, object]) -> None:
        completed.append(payload)

    async def _emit_tool_timeline(payload: dict[str, object]) -> None:
        timeline.append(payload)

    results = await execute_pending_tool_calls(
        api_client=SimpleNamespace(
            client_handler=_Handler(),
            model_config=SimpleNamespace(provider="openai", model="gpt-5.5"),
        ),
        tool_manager=SimpleNamespace(execute_tool=_execute_tool),
        persist_action_result=lambda action_result, tool_context: persisted.append(
            {"action_result": action_result, "tool_context": tool_context}
        ),
        emit_action_start=_emit_action_start,
        emit_action_result=_emit_action_result,
        emit_tool_timeline=_emit_tool_timeline,
    )

    assert executed == [
        ("execute", {"command": "pwd"}),
        ("execute", {"command": "ls"}),
    ]
    assert [result["tool_call_id"] for result in results] == ["call_pwd", "call_ls"]
    assert [result["result"] for result in results] == ["ran pwd", "ran ls"]
    assert [item["id"] for item in started] == ["call_pwd", "call_ls"]
    assert [item["id"] for item in completed] == ["call_pwd", "call_ls"]
    assert [item["action"] for item in timeline] == ["execute", "execute"]
    assert [
        item["tool_context"]["tool_call_id"] for item in persisted
    ] == ["call_pwd", "call_ls"]


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


def test_wallet_guard_treats_tool_arguments_as_progress() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    for max_lines in (50, 100, 150, 200):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="",
            iteration_results=[
                {
                    "action": "read_file",
                    "tool_arguments": (
                        f'{{"path":"README.md","max_lines":{max_lines}}}'
                    ),
                    "result": "same header",
                    "status": "completed",
                }
            ],
            mode="response",
        )

        assert should_break is False
        assert status is None

    assert loop_state.empty_tool_only_count == 4
    assert loop_state.repeated_tool_only_count == 1


def test_wallet_guard_treats_file_ranges_as_progress() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    for start_line, end_line in ((1, 40), (41, 80), (81, 120), (121, 160)):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="",
            iteration_results=[
                {
                    "action": "read_file",
                    "tool_arguments": {
                        "path": "README.md",
                        "start_line": start_line,
                        "end_line": end_line,
                    },
                    "result": "same repeated header",
                    "status": "completed",
                }
            ],
            mode="response",
        )

        assert should_break is False
        assert status is None

    assert loop_state.empty_tool_only_count == 4
    assert loop_state.repeated_tool_only_count == 1


def test_wallet_guard_ignores_provider_call_ids_for_stale_loop_detection() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]

    for index in range(2):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="",
            iteration_results=[
                {
                    "action": "read_file",
                    "tool_call_id": f"call_{index}",
                    "tool_arguments": '{"path":"README.md","max_lines":50}',
                    "result": "same header",
                    "status": "completed",
                }
            ],
            mode="response",
        )

        assert should_break is False
        assert status is None

    assert Engine._check_wallet_guard_termination(
        engine,
        last_response="",
        iteration_results=[
            {
                "action": "read_file",
                "tool_call_id": "call_3",
                "tool_arguments": '{"path":"README.md","max_lines":50}',
                "result": "same header",
                "status": "completed",
            }
        ],
        mode="response",
    ) == (True, "repeated_empty_tool_only_iterations")


def test_wallet_guard_breaks_on_same_tool_arguments_and_output_hash() -> None:
    engine = Engine.__new__(Engine)
    engine._default_run_state = SimpleNamespace(current_agent_id="default")
    loop_state = LoopState()
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]
    iteration_results = [
        {
            "action": "read_file",
            "tool_arguments": '{"path":"README.md","max_lines":50}',
            "result": "same header",
            "status": "completed",
        }
    ]

    for _ in range(2):
        should_break, status = Engine._check_wallet_guard_termination(
            engine,
            last_response="",
            iteration_results=iteration_results,
            mode="response",
        )

        assert should_break is False
        assert status is None

    assert Engine._check_wallet_guard_termination(
        engine,
        last_response="",
        iteration_results=iteration_results,
        mode="response",
    ) == (True, "repeated_empty_tool_only_iterations")


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
    loop_state = LoopState(last_tool_only_summary="read_file(path=README.md)")
    engine._get_loop_state = lambda: loop_state  # type: ignore[method-assign]
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

    assert result.startswith(
        "Stopping because empty tool-only turns repeated the same tool result "
        "identity; this is probably a stale loop rather than forward progress."
    )
    assert "Repeated tool result: read_file(path=README.md)." in result
    assert "To continue, send a new message" in result
    assert added == [result]
    engine._save_conversation.assert_awaited_once()
