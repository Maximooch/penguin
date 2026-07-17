from __future__ import annotations

import asyncio
import logging

import pytest

from penguin.tools.runtime import (
    ORDERED_TOOL_BATCH_NAME,
    ToolCall,
    ToolExecutionPolicy,
    ToolResult,
    execute_tool_calls_ordered,
    execute_tool_calls_serially,
    hash_tool_output,
    legacy_action_result_from_tool_result,
    ordered_tool_batch_result_from_results,
    parallel_schedule_decision,
    parse_ordered_tool_batch_plan,
    select_ordered_tool_calls_for_policy,
    select_tool_calls_for_policy,
    tool_call_from_responses_info,
    tool_call_with_schedule_metadata,
    tool_calls_from_actionxml,
    tool_result_from_action_result,
    tool_results_loop_identity,
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


def test_scheduler_policy_can_select_first_or_all_calls() -> None:
    calls = tool_calls_from_actionxml(
        """
        <read_file>{"path":"README.md"}</read_file>
        <execute_command>pwd</execute_command>
        """
    )

    assert select_tool_calls_for_policy(calls, ToolExecutionPolicy(max_calls=1)) == [
        calls[0]
    ]
    assert select_tool_calls_for_policy(calls, ToolExecutionPolicy()) == calls


def test_ordered_selection_enriches_effect_and_resources() -> None:
    calls = [
        ToolCall(
            id="read",
            name="read_file",
            arguments={"path": "README.md"},
            source="responses",
        ),
        ToolCall(
            id="git",
            name="execute_command",
            arguments={"command": "git commit -m test"},
            source="responses",
        ),
    ]

    selected = select_ordered_tool_calls_for_policy(calls)

    assert selected[0].effect == "read"
    assert selected[0].mutates_state is False
    assert selected[0].requires_approval is False
    assert selected[0].resources == ("fs:README.md",)
    assert selected[1].effect == "process_mutation"
    assert "process:*" in selected[1].resources
    assert "git:index" in selected[1].resources


def test_runtime_metadata_overrides_inferred_read_defaults() -> None:
    call = tool_call_with_schedule_metadata(
        ToolCall(
            id="read",
            name="read_file",
            arguments={"path": "README.md"},
            source="responses",
        ),
        {
            "mutates_state": True,
            "requires_approval": True,
            "parallel_safe": False,
            "long_running": True,
            "streams_output": True,
        },
    )

    assert call.effect == "read"
    assert call.mutates_state is True
    assert call.requires_approval is True
    assert call.long_running is True
    assert call.streams_output is True


def test_ordered_batch_plan_preflights_child_calls() -> None:
    parent = ToolCall(
        id="batch_1",
        name=ORDERED_TOOL_BATCH_NAME,
        arguments={
            "tool_uses": [
                {"tool": "read_file", "arguments": {"path": "README.md"}},
                {"tool": "execute_command", "arguments": {"command": "pwd"}},
            ]
        },
        source="responses",
    )

    plan = parse_ordered_tool_batch_plan(
        parent,
        available_tool_names={"read_file", "execute_command", ORDERED_TOOL_BATCH_NAME},
    )

    assert plan.error is None
    assert plan.stop_on_error is True
    assert [call.name for call in plan.tool_calls] == [
        "read_file",
        "execute_command",
    ]
    assert [call.parent_call_id for call in plan.tool_calls] == ["batch_1", "batch_1"]
    assert [call.batch_id for call in plan.tool_calls] == ["batch_1", "batch_1"]


def test_ordered_batch_plan_rejects_unknown_and_nested_tools() -> None:
    parent = ToolCall(
        id="batch_1",
        name=ORDERED_TOOL_BATCH_NAME,
        arguments={
            "tool_uses": [
                {
                    "tool": ORDERED_TOOL_BATCH_NAME,
                    "arguments": {"tool_uses": []},
                }
            ]
        },
        source="responses",
    )

    nested = parse_ordered_tool_batch_plan(
        parent,
        available_tool_names={ORDERED_TOOL_BATCH_NAME},
    )

    assert nested.error is not None
    assert "cannot nest batch tool" in nested.error

    unknown = parse_ordered_tool_batch_plan(
        ToolCall(
            id="batch_2",
            name=ORDERED_TOOL_BATCH_NAME,
            arguments={"tool_uses": [{"tool": "missing", "arguments": {}}]},
            source="responses",
        ),
        available_tool_names={"read_file"},
    )

    assert unknown.error == "child #1: unknown tool 'missing'"


def test_ordered_batch_plan_rejects_missing_required_child_fields() -> None:
    plan = parse_ordered_tool_batch_plan(
        ToolCall(
            id="batch_1",
            name=ORDERED_TOOL_BATCH_NAME,
            arguments={"tool_uses": [{"tool": "execute", "arguments": {}}]},
            source="responses",
        ),
        available_tool_names={"execute"},
        available_tool_schemas={
            "execute": {
                "input_schema": {
                    "type": "object",
                    "required": ["command"],
                    "properties": {"command": {"type": "string"}},
                }
            }
        },
    )

    assert plan.error == "child #1: tool 'execute' missing required fields: command"


def test_ordered_batch_result_preserves_child_metadata() -> None:
    parent = ToolCall(
        id="batch_1",
        name=ORDERED_TOOL_BATCH_NAME,
        arguments={"tool_uses": []},
        source="responses",
    )
    plan = parse_ordered_tool_batch_plan(
        ToolCall(
            id="batch_1",
            name=ORDERED_TOOL_BATCH_NAME,
            arguments={
                "tool_uses": [
                    {"tool": "read_file", "arguments": {"path": "README.md"}}
                ]
            },
            source="responses",
        ),
        available_tool_names={"read_file"},
    )

    result = ordered_tool_batch_result_from_results(
        parent,
        plan,
        [
            ToolResult(
                call_id=plan.tool_calls[0].id,
                name="read_file",
                status="completed",
                output="contents",
            )
        ],
    )

    assert result.status == "completed"
    assert "1/1 child calls completed" in result.output
    assert result.structured_output is not None
    assert result.structured_output["ordered_batch"]["children"][0]["tool"] == "read_file"


def test_parallel_schedule_rejects_mutating_or_unknown_calls() -> None:
    decision = parallel_schedule_decision(
        [
            ToolCall(
                id="read",
                name="read_file",
                arguments={"path": "README.md"},
                source="responses",
                parallel_safe=True,
            ),
            ToolCall(
                id="cmd",
                name="execute_command",
                arguments={"command": "git status --short"},
                source="responses",
            ),
        ]
    )

    assert decision.allowed is False
    assert decision.mode == "ordered"
    assert any("process_mutation" in conflict for conflict in decision.conflicts)


@pytest.mark.asyncio
async def test_serial_scheduler_executes_calls_in_order() -> None:
    calls = tool_calls_from_actionxml(
        """
        <read_file>{"path":"README.md"}</read_file>
        <execute_command>pwd</execute_command>
        """
    )
    executed: list[str] = []

    async def _execute(tool_call: ToolCall) -> str:
        executed.append(tool_call.name)
        return f"out:{tool_call.name}"

    results = await execute_tool_calls_serially(calls, _execute)

    assert executed == ["read_file", "execute_command"]
    assert [result.call_id for result in results] == [
        "action_xml_0_read_file",
        "action_xml_1_execute_command",
    ]
    assert [result.output for result in results] == [
        "out:read_file",
        "out:execute_command",
    ]


@pytest.mark.asyncio
async def test_scheduler_parallelizes_independent_read_only_calls() -> None:
    calls = [
        ToolCall(
            id="read_one",
            name="read_file",
            arguments={"path": "one"},
            source="responses",
            mutates_state=False,
            parallel_safe=True,
            requires_approval=False,
            effect="read",
        ),
        ToolCall(
            id="read_two",
            name="read_file",
            arguments={"path": "two"},
            source="responses",
            mutates_state=False,
            parallel_safe=True,
            requires_approval=False,
            effect="read",
        ),
    ]
    started: list[str] = []

    release = asyncio.Event()

    async def _execute(tool_call: ToolCall) -> str:
        started.append(tool_call.id)
        if len(started) == 2:
            release.set()
        await asyncio.wait_for(release.wait(), timeout=0.5)
        return tool_call.id

    results = await execute_tool_calls_serially(calls, _execute)

    assert started == ["read_one", "read_two"]
    assert [result.output for result in results] == ["read_one", "read_two"]


@pytest.mark.asyncio
async def test_ordered_scheduler_stops_on_error_when_configured() -> None:
    calls = [
        ToolCall(id="one", name="read_file", arguments={}, source="responses"),
        ToolCall(id="two", name="read_file", arguments={}, source="responses"),
    ]
    executed: list[str] = []

    async def _execute(tool_call: ToolCall) -> ToolResult:
        executed.append(tool_call.id)
        return ToolResult(
            call_id=tool_call.id,
            name=tool_call.name,
            status="error",
            output="failed",
        )

    results = await execute_tool_calls_ordered(
        calls,
        _execute,
        policy=ToolExecutionPolicy(stop_on_error=True),
    )

    assert executed == ["one"]
    assert [result.call_id for result in results] == ["one"]


@pytest.mark.asyncio
async def test_serial_scheduler_preserves_current_one_call_policy() -> None:
    calls = tool_calls_from_actionxml(
        """
        <read_file>{"path":"README.md"}</read_file>
        <execute_command>pwd</execute_command>
        """
    )
    executed: list[str] = []

    results = await execute_tool_calls_serially(
        calls,
        lambda tool_call: executed.append(tool_call.name) or "ok",
        policy=ToolExecutionPolicy(max_calls=1),
    )

    assert executed == ["read_file"]
    assert [result.name for result in results] == ["read_file"]


@pytest.mark.asyncio
async def test_serial_scheduler_logs_tool_timing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    calls = [
        ToolCall(
            id="call_1",
            name="read_file",
            arguments={"path": "README.md"},
            source="responses",
        )
    ]

    with caplog.at_level(logging.INFO, logger="penguin.tools.runtime"):
        results = await execute_tool_calls_serially(
            calls,
            lambda tool_call: {"action": tool_call.name, "result": "ok"},
        )

    assert results[0].status == "completed"
    assert "tool.exec.start" in caplog.text
    assert "tool.exec.done" in caplog.text
    assert "args_chars=" in caplog.text


def test_tool_loop_identity_ignores_provider_call_id_but_keeps_args() -> None:
    first = tool_results_loop_identity(
        [
            {
                "action": "read_file",
                "tool_call_id": "call_1",
                "tool_arguments": '{"path":"README.md","max_lines":20}',
                "result": "same output",
                "status": "completed",
            }
        ]
    )
    second = tool_results_loop_identity(
        [
            {
                "action": "read_file",
                "tool_call_id": "call_2",
                "tool_arguments": '{"path":"README.md","max_lines":20}',
                "result": "same output",
                "status": "completed",
            }
        ]
    )
    changed_range = tool_results_loop_identity(
        [
            {
                "action": "read_file",
                "tool_call_id": "call_3",
                "tool_arguments": '{"path":"README.md","max_lines":40}',
                "result": "same output",
                "status": "completed",
            }
        ]
    )

    assert first.fingerprint == second.fingerprint
    assert first.fingerprint != changed_range.fingerprint
    assert "read_file(path=README.md, max_lines=20)" in first.summary
