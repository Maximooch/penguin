"""Core shim coverage for extracted process helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core import PenguinCore


@pytest.mark.asyncio
async def test_process_facade_shims_delegate_to_runtime(monkeypatch) -> None:
    owner = SimpleNamespace(_interrupted=True)
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    facade_globals = PenguinCore.process.__globals__

    async def fake_process_message(*args: Any, **kwargs: Any) -> str:
        calls.append(("process_message", args, kwargs))
        return "message-result"

    async def fake_get_response(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[dict[str, Any], bool]:
        calls.append(("get_response", args, kwargs))
        return {"assistant_response": "response-result"}, True

    async def fake_execute_action(*args: Any, **kwargs: Any) -> dict[str, Any]:
        calls.append(("execute_action", args, kwargs))
        return {"status": "completed"}

    async def fake_process_with_retry(
        *args: Any,
        **kwargs: Any,
    ) -> dict[str, Any]:
        calls.append(("process", args, kwargs))
        return {"assistant_response": "process-result", "action_results": []}

    monkeypatch.setattr(
        facade_globals["core_message_processing"],
        "process_message",
        fake_process_message,
    )
    monkeypatch.setattr(
        facade_globals["core_response_generation"],
        "get_response",
        fake_get_response,
    )
    monkeypatch.setattr(
        facade_globals["core_action_execution"],
        "execute_action",
        fake_execute_action,
    )
    monkeypatch.setattr(
        facade_globals["core_process_runtime"],
        "process_with_retry",
        fake_process_with_retry,
    )

    assert PenguinCore._check_interrupt(owner) is True
    assert (
        await PenguinCore.process_message(
            owner,
            "hello",
            context={"scope": "test"},
            conversation_id="conversation-1",
            agent_id="agent-1",
            context_files=["README.md"],
            streaming=True,
        )
        == "message-result"
    )
    assert await PenguinCore.get_response(
        owner,
        current_iteration=1,
        max_iterations=3,
        stream_callback=lambda _chunk: None,
        streaming=False,
    ) == ({"assistant_response": "response-result"}, True)
    action = SimpleNamespace(action_type="noop")
    assert await PenguinCore.execute_action(owner, action) == {"status": "completed"}
    assert await PenguinCore.process(
        owner,
        {"text": "hello"},
        context={"scope": "test"},
        conversation_id="conversation-1",
        agent_id="agent-1",
        max_iterations=2,
        context_files=["README.md"],
        streaming=False,
        stream_callback=lambda _chunk: None,
        multi_step=False,
        api_client_override="api-client",
        model_config_override="model-config",
    ) == {"assistant_response": "process-result", "action_results": []}

    process_message_kwargs = calls[0][2]
    assert calls[0][0] == "process_message"
    assert calls[0][1] == (owner,)
    assert process_message_kwargs["message"] == "hello"
    assert process_message_kwargs["context"] == {"scope": "test"}
    assert process_message_kwargs["conversation_id"] == "conversation-1"
    assert process_message_kwargs["agent_id"] == "agent-1"
    assert process_message_kwargs["context_files"] == ["README.md"]
    assert process_message_kwargs["streaming"] is True
    assert process_message_kwargs["resolve_conversation_manager"] is (
        facade_globals["core_conversations"].resolve_conversation_manager
    )
    assert process_message_kwargs["log_error"] is facade_globals["log_error"]

    get_response_kwargs = calls[1][2]
    assert calls[1][0] == "get_response"
    assert calls[1][1] == (owner,)
    assert get_response_kwargs["current_iteration"] == 1
    assert get_response_kwargs["max_iterations"] == 3
    assert get_response_kwargs["streaming"] is False
    assert get_response_kwargs["process_response_actions"] is (
        facade_globals["core_action_execution"].process_response_actions
    )
    assert get_response_kwargs["sleep"] is facade_globals["asyncio"].sleep
    assert get_response_kwargs["log_error"] is facade_globals["log_error"]

    assert calls[2] == ("execute_action", (owner, action), {})

    process_kwargs = calls[3][2]
    assert calls[3][0] == "process"
    assert calls[3][1] == (owner,)
    assert process_kwargs["input_data"] == {"text": "hello"}
    assert process_kwargs["context"] == {"scope": "test"}
    assert process_kwargs["conversation_id"] == "conversation-1"
    assert process_kwargs["agent_id"] == "agent-1"
    assert process_kwargs["max_iterations"] == 2
    assert process_kwargs["context_files"] == ["README.md"]
    assert process_kwargs["streaming"] is False
    assert process_kwargs["multi_step"] is False
    assert process_kwargs["api_client_override"] == "api-client"
    assert process_kwargs["model_config_override"] == "model-config"
    assert process_kwargs["trace_log_info"] is facade_globals["_trace_log_info"]
    assert process_kwargs["log_error_fn"] is facade_globals["log_error"]
