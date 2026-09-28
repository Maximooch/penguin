"""Regressions for context/bugs/process-poll-empty-loop.md."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    from collections.abc import Iterator

from penguin.engine import LoopState
from penguin.tools.process_runtime import ProcessRuntime
from penguin.tools.runtime import (
    ToolCall,
    execute_tool_calls_serially,
    hash_tool_output,
    tool_results_loop_identity,
)


@pytest.fixture
def runtime() -> Iterator[ProcessRuntime]:
    instance = ProcessRuntime()
    try:
        yield instance
    finally:
        instance.cleanup()


def _wait_for_stdout(
    runtime: ProcessRuntime, process_id: str, sequence: int = 1
) -> None:
    """Synchronize with the child without consuming its output."""
    record = runtime._processes[process_id]
    with record.changed:
        assert record.changed.wait_for(lambda: record.next_sequence > sequence, 3)


def test_first_default_poll_recovers_ready_output(runtime: ProcessRuntime) -> None:
    started = runtime.start("printf 'hello\\n'; read line")
    process_id = started["process_id"]
    _wait_for_stdout(runtime, process_id)

    polled = runtime.poll(process_id)

    assert polled["process_status"] == "running"
    assert "hello" in polled["output"]
    assert runtime.poll(process_id, since_sequence=0)["output"] == polled["output"]


@pytest.mark.parametrize("after_output", [False, True])
def test_returned_cursor_does_not_skip_output(
    runtime: ProcessRuntime, after_output: bool
) -> None:
    started = runtime.start(
        "read first; printf 'first\\n'; read second; printf 'second\\n'; read done"
    )
    process_id = started["process_id"]
    cursor = started["next_sequence"]
    if after_output:
        runtime.write_stdin(process_id, "go\n")
        _wait_for_stdout(runtime, process_id)
        first = runtime.poll(process_id)
        assert "first" in first["output"]
        cursor = first["next_sequence"]

    runtime.write_stdin(process_id, "go\n")
    _wait_for_stdout(runtime, process_id, 2 if after_output else 1)
    polled = runtime.poll(process_id, since_sequence=cursor)
    expected = "second" if after_output else "first"

    # Prove the bytes were captured before asserting cursor-based delivery.
    assert expected in runtime.poll(process_id, since_sequence=0)["output"]
    assert expected in polled["output"]


def test_running_process_can_wait_through_three_empty_polls(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("read done")["process_id"]
    state = LoopState()
    for _ in range(3):
        polled = runtime.poll(process_id)
        assert polled["process_status"] == "running"
        assert polled["output"] == ""
        should_stop, reason = state.check_empty_tool_only("", [polled])
        assert (should_stop, reason) == (False, None)


@pytest.mark.asyncio
async def test_scheduler_preserves_running_process_metadata_and_nonempty_hash(
    runtime: ProcessRuntime,
) -> None:
    process_id = runtime.start("read done")["process_id"]

    def execute_call(call: ToolCall) -> dict[str, Any]:
        return runtime.poll(call.arguments["process_id"])

    results = await execute_tool_calls_serially(
        [
            ToolCall(
                id="poll",
                name="process_poll",
                arguments={"process_id": process_id},
                source="responses",
            )
        ],
        execute_call,
    )

    result = results[0]
    assert "status=running" in result.output
    assert result.structured_output["process_status"] == "running"
    assert result.output_hash != hash_tool_output("")
    assert "e3b0c44298fc" not in tool_results_loop_identity(results).summary
