from __future__ import annotations

from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.engine import Engine


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
