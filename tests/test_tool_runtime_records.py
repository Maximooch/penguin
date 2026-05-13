from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.engine import Engine
from penguin.llm.runtime import execute_pending_tool_calls
from penguin.system.state import Session
from penguin.tools.runtime import (
    ToolCall,
    ToolResult,
    hash_tool_arguments,
    tool_call_record_from_tool_call,
    tool_result_record_from_tool_result,
)
from penguin.utils.parser import CodeActAction


def test_tool_call_record_carries_replay_metadata_without_output() -> None:
    call = ToolCall(
        id="call_read",
        name="read_file",
        arguments={"max_lines": 20, "path": "README.md"},
        source="responses",
        raw={"provider": "openai"},
        mutates_state=False,
        requires_approval=False,
    )

    record = tool_call_record_from_tool_call(call).to_dict()

    assert record["record_type"] == "tool_call"
    assert record["call_id"] == "call_read"
    assert record["name"] == "read_file"
    assert record["source"] == "responses"
    assert record["arguments"] == {"max_lines": 20, "path": "README.md"}
    assert record["arguments_hash"] == hash_tool_arguments(
        {"path": "README.md", "max_lines": 20}
    )
    assert record["parallel_safe"] is False
    assert record["requires_approval"] is False


def test_tool_result_record_keeps_metadata_and_bounds_output_preview() -> None:
    full_output = "x" * 900
    result = ToolResult(
        call_id="call_cmd",
        name="execute_command",
        status="completed",
        output=full_output,
        started_at=10.0,
        ended_at=12.0,
        truncated=True,
        truncation_direction="tail",
        artifact_path="/tmp/tool-output-call_cmd.txt",
    )
    call = ToolCall(
        id="call_cmd",
        name="execute_command",
        arguments="pwd",
        source="action_xml",
    )

    record = tool_result_record_from_tool_result(result, tool_call=call).to_dict()

    assert record["record_type"] == "tool_result"
    assert record["call_id"] == "call_cmd"
    assert record["status"] == "completed"
    assert record["duration_ms"] == 2000.0
    assert record["byte_count"] == 900
    assert record["line_count"] == 1
    assert record["truncated"] is True
    assert record["artifact_path"] == "/tmp/tool-output-call_cmd.txt"
    assert record["arguments_hash"] == hash_tool_arguments("pwd")
    assert len(record["output_preview"]) == 500
    assert record["output_preview"] == "x" * 500


def test_session_persists_and_deduplicates_tool_records() -> None:
    session = Session(id="session_records")
    call_record = tool_call_record_from_tool_call(
        ToolCall(
            id="call_1",
            name="read_file",
            arguments={"path": "README.md"},
            source="responses",
        )
    )

    session.add_tool_call_record(call_record)
    session.add_tool_call_record(
        {
            "record_type": "tool_call",
            "call_id": "call_1",
            "name": "read_file",
            "source": "responses",
            "arguments_hash": "updated",
        }
    )
    session.add_tool_result_record(
        tool_result_record_from_tool_result(
            ToolResult(
                call_id="call_1",
                name="read_file",
                status="cancelled",
                output="cancelled before completion",
            )
        )
    )

    assert len(session.tool_call_records) == 1
    assert session.tool_call_records[0]["arguments_hash"] == "updated"
    assert len(session.tool_result_records) == 1
    assert session.metadata["tool_call_record_count"] == 1
    assert session.metadata["tool_result_record_count"] == 1

    reloaded = Session.from_json(session.to_json())

    assert reloaded.tool_call_records == session.tool_call_records
    assert reloaded.tool_result_records == session.tool_result_records


@pytest.mark.asyncio
async def test_native_tool_runtime_persists_call_before_execution_and_result_after() -> None:
    class _Handler:
        def __init__(self) -> None:
            self._tool_calls = [
                {
                    "name": "execute",
                    "arguments": '{"command":"pwd"}',
                    "call_id": "call_pwd",
                }
            ]

        def get_and_clear_pending_tool_calls(self) -> list[dict[str, str]]:
            result = self._tool_calls
            self._tool_calls = []
            return result

    events: list[tuple[str, str]] = []

    def _execute_tool(_tool_name: str, tool_args: dict[str, object]) -> str:
        events.append(("execute", str(tool_args["command"])))
        return "ran pwd"

    results = await execute_pending_tool_calls(
        api_client=SimpleNamespace(
            client_handler=_Handler(),
            model_config=SimpleNamespace(provider="openai", model="gpt-5.5"),
        ),
        tool_manager=SimpleNamespace(execute_tool=_execute_tool),
        persist_action_result=lambda *_args: None,
        persist_tool_call_record=lambda call: events.append(("call", call.id)),
        persist_tool_result_record=lambda call, result: events.append(
            ("result", f"{call.id}:{result.status}")
        ),
    )

    assert results[0]["tool_call_id"] == "call_pwd"
    assert events == [
        ("call", "call_pwd"),
        ("execute", "pwd"),
        ("result", "call_pwd:completed"),
    ]


@pytest.mark.asyncio
async def test_actionxml_tool_runtime_persists_selected_call_and_result() -> None:
    engine = Engine.__new__(Engine)
    session = Session(id="session_actionxml_records")

    async def _emit_tool_event(_cm: object, _action_result: dict[str, object]) -> None:
        return None

    engine._emit_tool_event = _emit_tool_event  # type: ignore[method-assign]

    class _ConversationManager:
        def get_current_session(self) -> Session:
            return session

        def add_action_result(self, **_kwargs: object) -> None:
            return None

    class _ActionExecutor:
        async def execute_action(self, action: CodeActAction) -> str:
            return f"ran:{action.action_type.value}"

    await Engine._execute_codeact_actions(
        engine,
        _ConversationManager(),
        _ActionExecutor(),
        """
        <read_file>{"path":"README.md","max_lines":10}</read_file>
        <execute_command>pwd</execute_command>
        """,
    )

    assert [record["call_id"] for record in session.tool_call_records] == [
        "action_xml_0_read_file"
    ]
    assert session.tool_call_records[0]["source"] == "action_xml"
    assert [record["call_id"] for record in session.tool_result_records] == [
        "action_xml_0_read_file"
    ]
    assert session.tool_result_records[0]["status"] == "completed"
