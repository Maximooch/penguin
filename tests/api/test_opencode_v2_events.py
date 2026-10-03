from __future__ import annotations

from typing import Any

from penguin.web.services.opencode_v2_events import (
    OpenCodeV2EventProjector,
    server_connected_event,
)

SESSION_ID = "session_prompt"
USER_ID = "msg_user"
ASSISTANT_ID = "msg_assistant"


def _source_events(directory: str) -> list[dict[str, Any]]:
    return [
        {
            "id": "source-session",
            "time": 1,
            "type": "session.created",
            "properties": {
                "sessionID": SESSION_ID,
                "info": {
                    "id": SESSION_ID,
                    "projectID": "penguin",
                    "directory": directory,
                    "title": "Prompt contract",
                    "agent": "build",
                    "providerID": "openai",
                    "modelID": "gpt-test",
                    "version": "2.0-test",
                },
            },
        },
        {
            "id": "source-busy",
            "time": 2,
            "type": "session.status",
            "properties": {
                "sessionID": SESSION_ID,
                "status": {"type": "busy"},
            },
        },
        {
            "id": "source-user",
            "time": 3,
            "type": "message.updated",
            "properties": {
                "id": USER_ID,
                "sessionID": SESSION_ID,
                "role": "user",
                "time": {"created": 3},
            },
        },
        {
            "id": "source-user-part",
            "time": 4,
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_user",
                    "messageID": USER_ID,
                    "sessionID": SESSION_ID,
                    "type": "text",
                    "text": "Say hello",
                }
            },
        },
        {
            "id": "source-assistant",
            "time": 5,
            "type": "message.updated",
            "properties": {
                "id": ASSISTANT_ID,
                "sessionID": SESSION_ID,
                "role": "assistant",
                "agent": "build",
                "providerID": "openai",
                "modelID": "gpt-test",
                "time": {"created": 5, "completed": None},
                "cost": 0,
                "tokens": {},
            },
        },
        {
            "id": "source-delta-1",
            "time": 6,
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_assistant",
                    "messageID": ASSISTANT_ID,
                    "sessionID": SESSION_ID,
                    "type": "text",
                    "text": "Hel",
                },
                "delta": "Hel",
            },
        },
        {
            "id": "source-delta-2",
            "time": 7,
            "type": "message.part.updated",
            "properties": {
                "part": {
                    "id": "part_assistant",
                    "messageID": ASSISTANT_ID,
                    "sessionID": SESSION_ID,
                    "type": "text",
                    "text": "Hello",
                },
                "delta": "lo",
            },
        },
        {
            "id": "source-assistant-complete",
            "time": 8,
            "type": "message.updated",
            "properties": {
                "id": ASSISTANT_ID,
                "sessionID": SESSION_ID,
                "role": "assistant",
                "agent": "build",
                "providerID": "openai",
                "modelID": "gpt-test",
                "time": {"created": 5, "completed": 8},
                "finish": "stop",
                "cost": 0.25,
                "tokens": {
                    "input": 4,
                    "output": 2,
                    "reasoning": 1,
                    "cache": {"read": 3, "write": 0},
                },
            },
        },
        {
            "id": "source-idle",
            "time": 9,
            "type": "session.status",
            "properties": {
                "sessionID": SESSION_ID,
                "status": {"type": "idle"},
            },
        },
    ]


def _project(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
    projector = OpenCodeV2EventProjector()
    return [projected for source in events for projected in projector.project(source)]


def _tool_part_event(
    source_id: str,
    status: str,
    *,
    call_id: str = "call_read",
    part_id: str = "part_tool_read",
    name: str = "read",
    tool_input: dict[str, Any] | None = None,
    output: Any = None,
    error: str | None = None,
    metadata: dict[str, Any] | None = None,
    created: int = 7,
) -> dict[str, Any]:
    state: dict[str, Any] = {
        "status": status,
        "input": tool_input or {"path": "README.md"},
        "time": {"start": 7},
    }
    if status == "completed":
        state["output"] = output
        state["time"]["end"] = created
    if status == "error":
        state["error"] = error
        state["time"]["end"] = created
    if metadata is not None:
        state["metadata"] = metadata
    return {
        "id": source_id,
        "time": created,
        "type": "message.part.updated",
        "properties": {
            "part": {
                "id": part_id,
                "messageID": ASSISTANT_ID,
                "sessionID": SESSION_ID,
                "type": "tool",
                "callID": call_id,
                "tool": name,
                "state": state,
            }
        },
    }


def _retarget(
    value: Any,
    *,
    session_id: str,
    user_id: str,
    assistant_id: str,
) -> Any:
    if isinstance(value, dict):
        return {
            key: _retarget(
                item,
                session_id=session_id,
                user_id=user_id,
                assistant_id=assistant_id,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            _retarget(
                item,
                session_id=session_id,
                user_id=user_id,
                assistant_id=assistant_id,
            )
            for item in value
        ]
    replacements = {
        SESSION_ID: session_id,
        USER_ID: user_id,
        ASSISTANT_ID: assistant_id,
    }
    if isinstance(value, str) and value.startswith("source-"):
        return f"{value}-{session_id}"
    return replacements.get(value, value)


def test_prompt_events_match_native_v2_lifecycle(tmp_path: Any) -> None:
    output = _project(_source_events(str(tmp_path)))

    assert [event["type"] for event in output] == [
        "session.created",
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
        "session.step.started",
        "session.text.started",
        "session.text.delta",
        "session.text.delta",
        "session.text.ended",
        "session.step.ended",
        "session.execution.succeeded",
    ]
    admitted = output[1]
    assert admitted["data"] == {
        "sessionID": SESSION_ID,
        "inputID": USER_ID,
        "input": {
            "type": "user",
            "data": {"text": "Say hello"},
            "delivery": "steer",
        },
    }
    assert output[4]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "agent": "build",
        "model": {"providerID": "openai", "id": "gpt-test"},
    }
    assert [event["data"]["delta"] for event in output[6:8]] == ["Hel", "lo"]
    assert output[8]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "ordinal": 0,
        "text": "Hello",
    }
    assert output[9]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "finish": "stop",
        "cost": 0.25,
        "tokens": {
            "input": 4,
            "output": 2,
            "reasoning": 1,
            "cache": {"read": 3, "write": 0},
        },
    }

    assert all(event["id"].startswith("evt_") for event in output)
    assert len({event["id"] for event in output}) == len(output)
    durable = [event["durable"] for event in output if "durable" in event]
    assert durable == [
        {"aggregateID": SESSION_ID, "seq": sequence, "version": 1}
        for sequence in range(9)
    ]
    assert all(
        "durable" not in event for event in output if event["type"].endswith(".delta")
    )


def test_projection_is_deterministic_and_sequences_are_per_session(
    tmp_path: Any,
) -> None:
    events = _source_events(str(tmp_path))
    assert _project(events) == _project(events)

    projector = OpenCodeV2EventProjector()
    first = projector.project(events[0])[0]
    second_source = {
        **events[0],
        "id": "source-other-session",
        "properties": {
            **events[0]["properties"],
            "sessionID": "session_other",
            "info": {
                **events[0]["properties"]["info"],
                "id": "session_other",
            },
        },
    }
    second = projector.project(second_source)[0]

    assert first["durable"]["seq"] == 0
    assert second["durable"]["seq"] == 0


def test_duplicate_terminal_events_do_not_restart_execution(tmp_path: Any) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    output = [event for source in events for event in projector.project(source)]

    assert projector.project(events[3]) == []
    assert projector.project(events[7]) == []
    assert projector.project(events[8]) == []
    assert projector.project({"type": "unknown", "properties": {}}) == []
    assert output[-1]["type"] == "session.execution.succeeded"


def test_interleaved_sessions_keep_state_and_sequences_isolated(tmp_path: Any) -> None:
    first = _retarget(
        _source_events(str(tmp_path / "first")),
        session_id="session_first",
        user_id="msg_user_first",
        assistant_id="msg_assistant_first",
    )
    second = _retarget(
        _source_events(str(tmp_path / "second")),
        session_id="session_second",
        user_id="msg_user_second",
        assistant_id="msg_assistant_second",
    )
    interleaved = [source for pair in zip(first, second) for source in pair]

    output = _project(interleaved)

    for session_id, assistant_id, directory in (
        ("session_first", "msg_assistant_first", str(tmp_path / "first")),
        ("session_second", "msg_assistant_second", str(tmp_path / "second")),
    ):
        session_events = [
            event for event in output if event["data"]["sessionID"] == session_id
        ]
        durable = [event["durable"] for event in session_events if "durable" in event]
        assert [item["seq"] for item in durable] == list(range(9))
        assert all(item["aggregateID"] == session_id for item in durable)
        assert all(
            event["location"]["directory"] == directory for event in session_events
        )
        assert all(
            event["data"].get("assistantMessageID", assistant_id) == assistant_id
            for event in session_events
        )


def test_duplicate_late_and_out_of_order_inputs_are_ignored(tmp_path: Any) -> None:
    events = _source_events(str(tmp_path))
    out_of_order = OpenCodeV2EventProjector()

    assert out_of_order.project(events[3]) == []
    assert out_of_order.project(events[6]) == []
    assert out_of_order.project(events[8]) == []

    projector = OpenCodeV2EventProjector()
    initial = [event for source in events[:6] for event in projector.project(source)]
    assert initial[-1]["type"] == "session.text.delta"
    assert projector.project(events[5]) == []

    terminal = projector.project(events[8])
    assert [event["type"] for event in terminal] == [
        "session.text.ended",
        "session.step.ended",
        "session.execution.succeeded",
    ]
    assert terminal[0]["data"]["text"] == "Hel"
    assert projector.project(events[6]) == []
    assert projector.project(events[7]) == []
    assert projector.project(events[8]) == []


def test_idle_closes_an_incomplete_text_boundary(tmp_path: Any) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    for source in events[:6]:
        projector.project(source)

    output = projector.project(events[8])

    assert [event["type"] for event in output] == [
        "session.text.ended",
        "session.step.ended",
        "session.execution.succeeded",
    ]
    assert output[0]["data"]["text"] == "Hel"


def test_completion_closes_an_empty_text_boundary(tmp_path: Any) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    for source in events[:5]:
        projector.project(source)
    empty_part = {
        "id": "source-empty-text",
        "time": 6,
        "type": "message.part.updated",
        "properties": {
            "part": {
                "id": "part_empty",
                "messageID": ASSISTANT_ID,
                "sessionID": SESSION_ID,
                "type": "text",
                "text": "",
            }
        },
    }

    started = projector.project(empty_part)
    completed = projector.project(events[7])

    assert [event["type"] for event in started] == ["session.text.started"]
    assert [event["type"] for event in completed] == [
        "session.text.ended",
        "session.step.ended",
    ]
    assert completed[0]["data"]["text"] == ""


def test_provider_error_emits_failed_boundaries_without_late_success(
    tmp_path: Any,
) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    output = [event for source in events[:6] for event in projector.project(source)]
    provider_error = {
        **events[7],
        "id": "source-provider-error",
        "properties": {
            **events[7]["properties"],
            "error": {
                "name": "APIError",
                "data": {
                    "message": "Provider unavailable",
                    "isRetryable": True,
                    "statusCode": 503,
                    "metadata": {"provider": "openai"},
                },
            },
        },
    }

    failed = projector.project(provider_error)
    output.extend(failed)

    assert [event["type"] for event in failed] == [
        "session.text.ended",
        "session.step.failed",
        "session.execution.failed",
    ]
    error = {"type": "APIError", "message": "Provider unavailable", "status": 503}
    assert failed[1]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "error": error,
    }
    assert failed[2]["data"] == {"sessionID": SESSION_ID, "error": error}
    assert [event["durable"]["seq"] for event in output if "durable" in event] == list(
        range(9)
    )
    assert all(event["type"] != "session.execution.succeeded" for event in output)

    late_completion = {**events[7], "id": "source-late-success"}
    stale_other_completion = {
        **events[7],
        "id": "source-stale-other-success",
        "properties": {
            **events[7]["properties"],
            "id": "msg_stale_assistant",
        },
    }
    second_idle = {**events[8], "id": "source-idle-again", "time": 10}
    assert projector.project(late_completion) == []
    assert projector.project(stale_other_completion) == []
    assert projector.project(events[8]) == []
    assert projector.project(second_idle) == []

    retry_user = {
        **events[2],
        "id": "source-retry-user",
        "properties": {**events[2]["properties"], "id": "msg_retry_user"},
    }
    retry_part = {
        **events[3],
        "id": "source-retry-part",
        "properties": {
            "part": {
                **events[3]["properties"]["part"],
                "id": "part_retry_user",
                "messageID": "msg_retry_user",
            }
        },
    }
    assert projector.project(retry_user) == []
    retry = projector.project(retry_part)
    assert [event["type"] for event in retry] == [
        "session.input.admitted",
        "session.input.promoted",
        "session.execution.started",
    ]
    assert [event["durable"]["seq"] for event in retry] == [9, 10, 11]


def test_missing_legacy_delivery_uses_explicit_projector_default(
    tmp_path: Any,
) -> None:
    projector = OpenCodeV2EventProjector(default_delivery="queue")
    output = [
        event
        for source in _source_events(str(tmp_path))[:4]
        for event in projector.project(source)
    ]

    assert output[1]["type"] == "session.input.admitted"
    assert output[1]["data"]["input"]["delivery"] == "queue"


def test_tool_success_projects_exact_native_boundaries_after_adjacent_text(
    tmp_path: Any,
) -> None:
    projector = OpenCodeV2EventProjector()
    output = [
        event
        for source in _source_events(str(tmp_path))[:6]
        for event in projector.project(source)
    ]
    running = projector.project(
        _tool_part_event(
            "source-tool-running",
            "running",
            metadata={"title": "Read README"},
        )
    )
    succeeded = projector.project(
        _tool_part_event(
            "source-tool-completed",
            "completed",
            output="Penguin docs",
            metadata={"title": "Read README", "lines": 1},
            created=8,
        )
    )
    completed = projector.project(_source_events(str(tmp_path))[7])
    idle = projector.project(_source_events(str(tmp_path))[8])
    output.extend([*running, *succeeded, *completed, *idle])

    assert [event["type"] for event in running] == [
        "session.text.ended",
        "session.tool.input.started",
        "session.tool.input.ended",
        "session.tool.called",
        "session.tool.progress",
    ]
    assert running[0]["data"]["text"] == "Hel"
    assert running[1]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "id": "call_read",
        "name": "read",
    }
    assert running[2]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "id": "call_read",
        "text": '{"path":"README.md"}',
    }
    assert running[3]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "id": "call_read",
        "input": {"path": "README.md"},
        "executed": False,
    }
    assert running[4]["data"]["metadata"] == {"title": "Read README"}
    assert "durable" not in running[4]
    assert [event["type"] for event in succeeded] == ["session.tool.success"]
    assert succeeded[0]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "id": "call_read",
        "content": [{"type": "text", "text": "Penguin docs"}],
        "executed": False,
        "metadata": {"lines": 1, "title": "Read README"},
    }
    assert succeeded[0]["durable"]["version"] == 2
    assert [event["type"] for event in completed] == ["session.step.ended"]
    assert [event["type"] for event in idle] == ["session.execution.succeeded"]
    assert [event["durable"]["seq"] for event in output if "durable" in event] == list(
        range(13)
    )


def test_tool_error_is_terminal_without_fabricated_success(tmp_path: Any) -> None:
    projector = OpenCodeV2EventProjector()
    output = [
        event
        for source in _source_events(str(tmp_path))[:5]
        for event in projector.project(source)
    ]
    running_event = _tool_part_event("source-tool-error-running", "running")
    failed_event = _tool_part_event(
        "source-tool-error",
        "error",
        error="README.md is unavailable",
        metadata={"path": "README.md"},
        created=8,
    )
    late_success = _tool_part_event(
        "source-tool-late-success",
        "completed",
        output="should be ignored",
        created=9,
    )
    output.extend(projector.project(running_event))
    failed = projector.project(failed_event)
    output.extend(failed)

    assert [event["type"] for event in failed] == ["session.tool.failed"]
    assert failed[0]["data"] == {
        "sessionID": SESSION_ID,
        "assistantMessageID": ASSISTANT_ID,
        "id": "call_read",
        "error": {
            "type": "tool.execution",
            "message": "README.md is unavailable",
        },
        "executed": False,
        "metadata": {"path": "README.md"},
    }
    assert failed[0]["durable"]["version"] == 2
    assert projector.project({**failed_event, "id": "source-tool-error-again"}) == []
    assert projector.project(late_success) == []

    completed = projector.project(_source_events(str(tmp_path))[7])
    idle = projector.project(_source_events(str(tmp_path))[8])
    output.extend([*completed, *idle])
    assert [event["type"] for event in completed] == ["session.step.ended"]
    assert [event["type"] for event in idle] == ["session.execution.succeeded"]
    assert all(event["type"] != "session.tool.success" for event in output)
    assert all(event["type"] != "session.execution.failed" for event in output)


def test_multiple_tools_keep_call_identity_and_sequence_isolated(tmp_path: Any) -> None:
    projector = OpenCodeV2EventProjector()
    output = [
        event
        for source in _source_events(str(tmp_path))[:5]
        for event in projector.project(source)
    ]
    sources = [
        _tool_part_event("source-tool-one-running", "running"),
        _tool_part_event(
            "source-tool-two-running",
            "running",
            call_id="call_bash",
            part_id="part_tool_bash",
            name="bash",
            tool_input={"command": "pytest -q"},
        ),
        _tool_part_event(
            "source-tool-two-success",
            "completed",
            call_id="call_bash",
            part_id="part_tool_bash",
            name="bash",
            tool_input={"command": "pytest -q"},
            output="2 passed",
            created=8,
        ),
        _tool_part_event(
            "source-tool-one-failed",
            "error",
            error="missing file",
            created=9,
        ),
    ]
    output.extend(event for source in sources for event in projector.project(source))

    called = [event for event in output if event["type"] == "session.tool.called"]
    terminal = [
        event
        for event in output
        if event["type"] in {"session.tool.success", "session.tool.failed"}
    ]
    assert [event["data"]["id"] for event in called] == [
        "call_read",
        "call_bash",
    ]
    assert [(event["type"], event["data"]["id"]) for event in terminal] == [
        ("session.tool.success", "call_bash"),
        ("session.tool.failed", "call_read"),
    ]
    assert all(
        event["data"]["assistantMessageID"] == ASSISTANT_ID
        for event in [*called, *terminal]
    )
    assert [event["durable"]["seq"] for event in output if "durable" in event] == list(
        range(13)
    )


def test_late_tool_terminal_completes_a_prior_pending_idle(tmp_path: Any) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    output = [event for source in events[:5] for event in projector.project(source)]
    output.extend(
        projector.project(_tool_part_event("source-tool-late-running", "running"))
    )

    assert projector.project(events[7]) == []
    assert projector.project(events[8]) == []
    late_terminal_source = _tool_part_event(
        "source-tool-late-terminal",
        "completed",
        output="done after idle",
        created=10,
    )
    terminal = projector.project(late_terminal_source)
    output.extend(terminal)

    assert [event["type"] for event in terminal] == [
        "session.tool.success",
        "session.step.ended",
        "session.execution.succeeded",
    ]
    assert terminal[0]["data"]["content"] == [
        {"type": "text", "text": "done after idle"}
    ]
    assert terminal[2]["data"] == {"sessionID": SESSION_ID}
    assert all(event["created"] == 10 for event in terminal)
    assert [event["durable"]["seq"] for event in output if "durable" in event] == list(
        range(11)
    )
    assert (
        projector.project(
            {**late_terminal_source, "id": "source-tool-late-terminal-duplicate"}
        )
        == []
    )
    assert projector.project({**events[8], "id": "source-idle-after-terminal"}) == []


def test_unsettled_tool_blocks_success_and_provider_failure_wins(
    tmp_path: Any,
) -> None:
    events = _source_events(str(tmp_path))
    projector = OpenCodeV2EventProjector()
    output = [event for source in events[:5] for event in projector.project(source)]
    output.extend(
        projector.project(_tool_part_event("source-tool-provider-running", "running"))
    )

    assert projector.project(events[8]) == []
    provider_error = {
        **events[7],
        "id": "source-provider-error-with-tool",
        "properties": {
            **events[7]["properties"],
            "error": {
                "name": "APIError",
                "data": {
                    "message": "Provider unavailable",
                    "isRetryable": False,
                    "statusCode": 503,
                },
            },
        },
    }
    failed = projector.project(provider_error)
    output.extend(failed)

    assert [event["type"] for event in failed] == [
        "session.step.failed",
        "session.execution.failed",
    ]
    assert (
        projector.project(
            _tool_part_event(
                "source-tool-after-provider-failure",
                "completed",
                output="late",
                created=10,
            )
        )
        == []
    )
    assert projector.project({**events[8], "id": "source-idle-after-failure"}) == []
    assert all(event["type"] != "session.execution.succeeded" for event in output)
    assert all(event["type"] != "session.tool.success" for event in output)


def test_server_connected_handshake_is_exact_and_deterministic() -> None:
    connected = server_connected_event("connection-1")

    assert connected == server_connected_event("connection-1")
    assert connected["id"].startswith("evt_")
    assert connected["type"] == "server.connected"
    assert connected["data"] == {}
    assert set(connected) == {"id", "type", "data"}
    assert connected["id"] != server_connected_event("connection-2")["id"]
