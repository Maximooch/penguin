from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.engine import Engine
from penguin.system.conversation import ConversationSystem
from penguin.system.state import Session


@pytest.mark.asyncio
async def test_llm_step_includes_responses_tool_call_in_action_results() -> None:
    engine = Engine.__new__(Engine)
    cast(Any, engine)._default_run_state = SimpleNamespace(current_agent_id="default")
    engine.current_agent_id = "default"
    engine.default_agent_id = "default"
    engine._trace_request_fields = lambda: ("req-1", "session-1")  # type: ignore[method-assign]
    engine._apply_agent_mode_notice = lambda messages: messages  # type: ignore[method-assign]
    engine._prepare_responses_tools = lambda _tm: {}  # type: ignore[method-assign]

    async def _call_llm_with_retry(*args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return "Running a tiny Python function now to verify execution."

    async def _handle_responses_tool_call(*args: Any, **kwargs: Any) -> dict[str, str]:
        del args, kwargs
        return {
            "action": "code_execution",
            "result": "7",
            "status": "completed",
        }

    async def _finalize_streaming_response(
        cm: Any,
        response: str,
        streaming: bool,
        agent_id: str | None = None,
        api_client: Any = None,
    ) -> str:
        del cm, streaming, agent_id, api_client
        return response

    async def _execute_codeact_actions(*args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []

    engine._call_llm_with_retry = _call_llm_with_retry  # type: ignore[method-assign]
    engine._handle_responses_tool_call = _handle_responses_tool_call  # type: ignore[method-assign]
    engine._finalize_streaming_response = _finalize_streaming_response  # type: ignore[method-assign]
    engine._execute_codeact_actions = _execute_codeact_actions  # type: ignore[method-assign]
    engine._extract_usage_from_api_client = lambda _api_client: {}  # type: ignore[method-assign]

    cm = SimpleNamespace(
        conversation=SimpleNamespace(
            get_formatted_messages=lambda: [{"role": "user", "content": "hi"}]
        )
    )
    api_client = SimpleNamespace()
    tool_manager = SimpleNamespace()
    action_executor = SimpleNamespace()
    engine._resolve_components = lambda _agent_id: (
        cm,
        api_client,
        tool_manager,
        action_executor,
    )  # type: ignore[method-assign]

    result = await engine._llm_step(
        tools_enabled=True, streaming=True, agent_id="default"
    )

    assert (
        result["assistant_response"]
        == "Running a tiny Python function now to verify execution."
    )
    assert result["action_results"] == [
        {"action": "code_execution", "result": "7", "status": "completed"}
    ]


@pytest.mark.asyncio
async def test_llm_step_persists_assistant_before_responses_tool_result() -> None:
    engine = Engine.__new__(Engine)
    cast(Any, engine)._default_run_state = SimpleNamespace(current_agent_id="default")
    engine.current_agent_id = "default"
    engine.default_agent_id = "default"
    engine._trace_request_fields = lambda: ("req-1", "session-1")  # type: ignore[method-assign]
    engine._apply_agent_mode_notice = lambda messages: messages  # type: ignore[method-assign]
    engine._prepare_responses_tools = lambda _tm: {}  # type: ignore[method-assign]

    async def _call_llm_with_retry(*args: Any, **kwargs: Any) -> str:
        del args, kwargs
        return "Checking git state, then I'll write the roadmap file."

    async def _finalize_streaming_response(
        cm: Any,
        response: str,
        streaming: bool,
        agent_id: str | None = None,
        api_client: Any = None,
    ) -> str:
        del streaming, agent_id, api_client
        cm.conversation.add_assistant_message(response)
        return response

    async def _execute_codeact_actions(*args: Any, **kwargs: Any) -> list[Any]:
        del args, kwargs
        return []

    engine._call_llm_with_retry = _call_llm_with_retry  # type: ignore[method-assign]
    engine._finalize_streaming_response = _finalize_streaming_response  # type: ignore[method-assign]
    engine._execute_codeact_actions = _execute_codeact_actions  # type: ignore[method-assign]
    engine._extract_usage_from_api_client = lambda _api_client: {}  # type: ignore[method-assign]

    session = Session()
    conversation = ConversationSystem(
        session_manager=SimpleNamespace(
            current_session=session,
            mark_session_modified=lambda _session_id: None,
            check_session_boundary=lambda _session: False,
        )
    )
    conversation.session = session

    cm = SimpleNamespace(
        conversation=conversation,
        add_action_result=conversation.add_action_result,
        core=None,
    )
    api_client = SimpleNamespace(
        model_config=SimpleNamespace(provider="openai", model="gpt-5.4"),
        client_handler=SimpleNamespace(
            get_and_clear_last_tool_call=lambda: {
                "call_id": "call_123",
                "name": "write_file",
                "arguments": '{"path":"context/todo.md","content":"hi"}',
            }
        ),
    )
    tool_manager = SimpleNamespace(execute_tool=lambda _name, _args: "ok")
    action_executor = SimpleNamespace()
    engine._resolve_components = lambda _agent_id: (  # type: ignore[method-assign]
        cm,
        api_client,
        tool_manager,
        action_executor,
    )

    result = await engine._llm_step(
        tools_enabled=True, streaming=True, agent_id="default"
    )

    assert (
        result["assistant_response"]
        == "Checking git state, then I'll write the roadmap file."
    )
    assert len(result["action_results"]) == 1
    action_result = result["action_results"][0]
    assert action_result["action"] == "write_file"
    assert action_result["result"] == "ok"
    assert action_result["status"] == "completed"
    assert action_result["tool_call_id"] == "call_123"
    assert (
        action_result["tool_arguments"]
        == '{"path":"context/todo.md","content":"hi"}'
    )
    assert isinstance(action_result["output_hash"], str)
    assert [message.role for message in conversation.session.messages] == [
        "assistant",
        "tool",
    ]
    assistant_message = conversation.session.messages[0]
    tool_message = conversation.session.messages[1]
    assert assistant_message.metadata["tool_calls"] == [
        {
            "id": "call_123",
            "type": "function",
            "function": {
                "name": "write_file",
                "arguments": '{"path":"context/todo.md","content":"hi"}',
            },
        }
    ]
    assert tool_message.metadata["tool_call_id"] == "call_123"
