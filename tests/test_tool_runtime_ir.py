from __future__ import annotations

from penguin.tools.runtime import (
    ToolCall,
    ToolResult,
    hash_tool_output,
    legacy_action_result_from_tool_result,
    tool_call_from_responses_info,
    tool_calls_from_actionxml,
    tool_result_from_action_result,
)


def test_actionxml_adapter_maps_actions_to_tool_calls() -> None:
    calls = tool_calls_from_actionxml(
        """
        <read_file>{"path":"README.md","max_lines":20}</read_file>
        <execute_command>pwd</execute_command>
        """
    )

    assert calls == [
        ToolCall(
            id="action_xml_0_read_file",
            name="read_file",
            arguments='{"path":"README.md","max_lines":20}',
            source="action_xml",
            raw=calls[0].raw,
        ),
        ToolCall(
            id="action_xml_1_execute_command",
            name="execute_command",
            arguments="pwd",
            source="action_xml",
            raw=calls[1].raw,
        ),
    ]
    assert calls[0].mutates_state is True
    assert calls[0].parallel_safe is False
    assert calls[0].requires_approval is True


def test_responses_adapter_preserves_provider_call_identity() -> None:
    call = tool_call_from_responses_info(
        {
            "call_id": "call_123",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    )

    assert call == ToolCall(
        id="call_123",
        name="read_file",
        arguments='{"path":"README.md"}',
        source="responses",
        raw={
            "call_id": "call_123",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        },
    )


def test_action_result_adapter_maps_legacy_result_to_tool_result() -> None:
    result = tool_result_from_action_result(
        {"action": "read_file", "result": "contents", "status": "completed"},
        call_id="call_read",
        started_at=10.0,
        ended_at=12.0,
    )

    assert result == ToolResult(
        call_id="call_read",
        name="read_file",
        status="completed",
        output="contents",
        started_at=10.0,
        ended_at=12.0,
        output_hash=hash_tool_output("contents"),
    )


def test_tool_result_adapter_round_trips_current_action_result_shape() -> None:
    action_result = {"action": "execute_command", "result": "ok", "status": "error"}

    result = tool_result_from_action_result(action_result, call_id="call_exec")

    assert legacy_action_result_from_tool_result(result) == action_result
