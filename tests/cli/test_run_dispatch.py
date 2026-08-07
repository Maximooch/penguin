"""Contract matrix for top-level CLI dispatch precedence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from penguin.cli.run_dispatch import (
    DispatchMode,
    DispatchRequest,
    execute_run_mode,
    select_dispatch_mode,
)


@pytest.mark.parametrize(
    ("dispatch_request", "expected"),
    [
        (
            DispatchRequest("task", True, "session", "prompt", True, None),
            DispatchMode.RUN_MODE,
        ),
        (DispatchRequest(None, True, None, "prompt", True, None), DispatchMode.SESSION),
        (
            DispatchRequest(None, False, "session", "prompt", True, None),
            DispatchMode.SESSION,
        ),
        (
            DispatchRequest(None, False, None, "prompt", True, None),
            DispatchMode.DIRECT_PROMPT,
        ),
        (DispatchRequest(None, False, None, None, True, None), DispatchMode.CONTINUOUS),
        (
            DispatchRequest(None, False, None, None, False, None),
            DispatchMode.INTERACTIVE,
        ),
        (
            DispatchRequest(None, False, None, None, False, "project"),
            DispatchMode.SUBCOMMAND,
        ),
    ],
)
def test_dispatch_precedence(
    dispatch_request: DispatchRequest, expected: DispatchMode
) -> None:
    assert select_dispatch_mode(dispatch_request) is expected


@pytest.mark.asyncio
async def test_execute_run_mode_preserves_stream_order_and_completion() -> None:
    console = SimpleNamespace(print=Mock(), file=SimpleNamespace(flush=Mock()))

    async def start_run_mode(**kwargs) -> None:
        callback = kwargs["stream_callback_for_cli"]
        await callback("reason", "reasoning")
        await callback("answer", "assistant")
        await callback("", "assistant")

    core = SimpleNamespace(
        start_run_mode=AsyncMock(side_effect=start_run_mode),
        current_runmode_status_summary="Completed successfully",
    )

    completion = await execute_run_mode(
        core,
        console,
        task_name="task",
        continuous=False,
        time_limit=None,
        description=None,
    )

    streamed = [
        call.args[0]
        for call in console.print.call_args_list
        if call.args and call.args[0] in {"reason", "answer"}
    ]
    assert streamed == ["reason", "answer"]
    assert completion.kind == "finished"


@pytest.mark.asyncio
async def test_execute_run_mode_rejects_missing_single_task_before_core_call() -> None:
    core = SimpleNamespace(start_run_mode=AsyncMock())
    console = SimpleNamespace(print=Mock())

    with pytest.raises(ValueError, match="task name"):
        await execute_run_mode(
            core,
            console,
            task_name=None,
            continuous=False,
            time_limit=None,
            description=None,
        )

    core.start_run_mode.assert_not_awaited()
