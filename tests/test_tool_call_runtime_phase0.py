from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.engine import Engine, LoopState
from penguin.llm.runtime import execute_pending_tool_call
from penguin.utils.parser import ActionType, CodeActAction, parse_action


def test_parse_action_preserves_multiple_actionxml_tags_in_order() -> None:
    content = """
    I will inspect the file, then check the environment.
    <read_file>{"path":"README.md","max_lines":40}</read_file>
    <execute_command>pwd</execute_command>
    """.strip()

    actions = parse_action(content)

    assert [action.action_type for action in actions] == [
        ActionType.READ_FILE,
        ActionType.EXECUTE_COMMAND,
    ]
    assert actions[0].params == '{"path":"README.md","max_lines":40}'
    assert actions[1].params == "pwd"


@pytest.mark.asyncio
async def test_engine_executes_only_first_actionxml_action_per_iteration() -> None:
    engine = Engine.__new__(Engine)
    emitted: list[dict[str, Any]] = []

    async def _emit_tool_event(_cm: Any, action_result: dict[str, Any]) -> None:
        emitted.append(action_result)

    engine._emit_tool_event = _emit_tool_event  # type: ignore[method-assign]

    persisted: list[dict[str, str]] = []
    cm = SimpleNamespace(
        add_action_result=lambda **kwargs: persisted.append(dict(kwargs))
    )
    executed: list[CodeActAction] = []

    class _ActionExecutor:
        async def execute_action(self, action: CodeActAction) -> str:
            executed.append(action)
            return f"ran:{action.action_type.value}"

    action_results = await Engine._execute_codeact_actions(
        engine,
        cm,
        _ActionExecutor(),
        """
        <read_file>{"path":"README.md","max_lines":10}</read_file>
        <execute_command>pwd</execute_command>
        """,
    )

    assert [action.action_type for action in executed] == [ActionType.READ_FILE]
    assert len(action_results) == 1
    assert action_results[0]["action"] == "read_file"
    assert action_results[0]["result"] == "ran:read_file"
    assert action_results[0]["status"] == "completed"
    assert action_results[0]["tool_call_id"] == "action_xml_0_read_file"
    assert action_results[0]["tool_arguments"] == (
        '{"path":"README.md","max_lines":10}'
    )
    assert isinstance(action_results[0]["output_hash"], str)
    assert persisted == [
        {
            "action_type": "read_file",
            "result": "ran:read_file",
            "status": "completed",
            "tool_call_id": "action_xml_0_read_file",
            "tool_arguments": '{"path":"README.md","max_lines":10}',
        }
    ]
    assert emitted == [
        {
            "action": "read_file",
            "result": "ran:read_file",
            "status": "completed",
        }
    ]


@pytest.mark.asyncio
async def test_responses_tool_call_execution_preserves_provider_identity() -> None:
    persisted: list[dict[str, Any]] = []
    started: list[dict[str, Any]] = []
    completed: list[dict[str, Any]] = []
    timeline: list[dict[str, Any]] = []

    async def _emit_start(payload: dict[str, Any]) -> None:
        started.append(payload)

    async def _emit_result(payload: dict[str, Any]) -> None:
        completed.append(payload)

    async def _emit_timeline(payload: dict[str, Any]) -> None:
        timeline.append(payload)

    result = await execute_pending_tool_call(
        api_client=SimpleNamespace(
            model_config=SimpleNamespace(provider="openai", model="gpt-5.5"),
            client_handler=SimpleNamespace(
                get_and_clear_last_tool_call=lambda: {
                    "call_id": "call_read_123",
                    "name": "read_file",
                    "arguments": '{"path":"README.md","max_lines":5}',
                }
            ),
        ),
        tool_manager=SimpleNamespace(
            execute_tool=lambda tool_name, tool_args: (
                f"{tool_name}:{tool_args['path']}:{tool_args['max_lines']}"
            )
        ),
        persist_action_result=lambda action_result, tool_context: persisted.append(
            {"action_result": action_result, "tool_context": tool_context}
        ),
        emit_action_start=_emit_start,
        emit_action_result=_emit_result,
        emit_tool_timeline=_emit_timeline,
    )

    assert result is not None
    assert result["action"] == "read_file"
    assert result["result"] == "read_file:README.md:5"
    assert result["status"] == "completed"
    assert result["tool_call_id"] == "call_read_123"
    assert result["tool_arguments"] == '{"path":"README.md","max_lines":5}'
    assert isinstance(result["output_hash"], str)
    assert persisted == [
        {
            "action_result": {
                "action": "read_file",
                "result": "read_file:README.md:5",
                "status": "completed",
            },
            "tool_context": {
                "tool_call_id": "call_read_123",
                "tool_arguments": '{"path":"README.md","max_lines":5}',
            },
        }
    ]
    assert started[0]["id"] == "call_read_123"
    assert completed[0]["id"] == "call_read_123"
    assert timeline == [
        {
            "action": "read_file",
            "result": "read_file:README.md:5",
            "status": "completed",
        }
    ]


def test_loop_state_detects_repeated_empty_tool_only_results() -> None:
    loop_state = LoopState()
    result = [{"action": "read_file", "result": "same output", "status": "completed"}]

    assert loop_state.check_empty_tool_only("", result) == (False, None)
    assert loop_state.check_empty_tool_only("", result) == (False, None)
    assert loop_state.check_empty_tool_only("", result) == (
        True,
        "repeated_empty_tool_only_iterations",
    )


def test_loop_state_resets_empty_tool_only_tracking_on_text_response() -> None:
    loop_state = LoopState()
    result = [{"action": "read_file", "result": "same output", "status": "completed"}]

    assert loop_state.check_empty_tool_only("", result) == (False, None)
    assert loop_state.check_empty_tool_only("Done.", result) == (False, None)

    assert loop_state.empty_tool_only_count == 0
    assert loop_state.repeated_tool_only_count == 0
    assert loop_state.last_tool_only_signature is None
