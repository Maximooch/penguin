"""A finish action the capability policy denies does not end the task.

The denial came back from ``ActionExecutor`` as a JSON string, the tool
scheduler recorded any string as a completed result, and the engine ends a
task or response on a completed ``finish_task`` / ``finish_response``. So an
allowlist that excluded the finish actions was ignored for exactly those.
Covers ActionExecutor -> scheduler -> Engine for both actions.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.engine import Engine
from penguin.llm.runtime import execute_pending_tool_calls
from penguin.security.tool_capabilities import ToolCapabilityPolicy
from penguin.system.state import Session
from penguin.utils.parser import ActionExecutor


async def _run(allowed: set[str], response: str) -> list[dict[str, Any]]:
    engine = Engine.__new__(Engine)
    session = Session(id="session_denied_control")

    async def emit_tool_event(_cm: object, _result: dict[str, object]) -> None:
        return None

    engine._emit_tool_event = emit_tool_event  # type: ignore[method-assign]
    conversation = SimpleNamespace(
        get_current_session=lambda: session,
        add_action_result=lambda **_kwargs: None,
    )
    finished = SimpleNamespace(
        finish_task=lambda *_a, **_k: "task finished",
        finish_response=lambda *_a, **_k: "response finished",
    )
    tool_manager = SimpleNamespace(
        tool_capability_policy=ToolCapabilityPolicy(allowed_names=frozenset(allowed)),
        _canonical_tool_name=lambda name: name,
        task_tools=finished,
    )
    executor = ActionExecutor(tool_manager, SimpleNamespace())  # type: ignore[arg-type]
    return await Engine._execute_codeact_actions(
        engine,
        conversation,  # type: ignore[arg-type]
        executor,
        response,
    )


_FINISH_TASK = '<finish_task>{"status":"done","summary":"done"}</finish_task>'
_FINISH_RESPONSE = "<finish_response>done</finish_response>"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "response"),
    [("finish_task", _FINISH_TASK), ("finish_response", _FINISH_RESPONSE)],
)
async def test_a_denied_finish_action_does_not_end_the_loop(
    action: str, response: str
) -> None:
    results = await _run({"read_file"}, response)

    assert [result["status"] for result in results] == ["error"]
    assert "tool_capability_denied" in str(results[0])
    engine = Engine.__new__(Engine)
    assert engine._check_termination_signal(results, action)[0] is False


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("action", "response"),
    [("finish_task", _FINISH_TASK), ("finish_response", _FINISH_RESPONSE)],
)
async def test_an_allowed_finish_action_ends_the_loop(
    action: str, response: str
) -> None:
    results = await _run({"read_file", action}, response)

    assert [result["status"] for result in results] == ["completed"]
    engine = Engine.__new__(Engine)
    assert engine._check_termination_signal(results, action)[0] is True


class _NativeHandler:
    def __init__(self, name: str, arguments: str) -> None:
        self._tool_calls = [{"name": name, "arguments": arguments, "call_id": "c1"}]

    def get_and_clear_pending_tool_calls(self) -> list[dict[str, str]]:
        calls, self._tool_calls = self._tool_calls, []
        return calls


@pytest.mark.asyncio
@pytest.mark.parametrize("allowed", [False, True])
async def test_a_denied_native_finish_task_does_not_end_the_loop(
    allowed: bool,
) -> None:
    policy = ToolCapabilityPolicy(
        allowed_names=frozenset(
            {"read_file", "finish_task"} if allowed else {"read_file"}
        )
    )

    def execute_tool(tool_name: str, _args: dict[str, object]) -> str:
        if not policy.allows(tool_name, tool_name):
            return policy.denial_json(tool_name)  # what ToolManager returns
        return "task finished"

    results = await execute_pending_tool_calls(
        api_client=SimpleNamespace(
            client_handler=_NativeHandler(
                "finish_task", '{"status":"done","summary":"done"}'
            ),
            model_config=SimpleNamespace(provider="openai", model="test"),
        ),
        tool_manager=SimpleNamespace(execute_tool=execute_tool),
        persist_action_result=lambda *_args: None,
    )

    engine = Engine.__new__(Engine)
    assert [result["status"] for result in results] == [
        "completed" if allowed else "error"
    ]
    assert engine._check_termination_signal(results, "finish_task")[0] is allowed
