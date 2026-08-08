"""Contract matrix for top-level CLI dispatch precedence."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from penguin.cli.run_dispatch import (
    DispatchMode,
    DispatchRequest,
    execute_direct_prompt,
    execute_run_mode,
    resolve_session,
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


@pytest.mark.asyncio
async def test_direct_prompt_validates_before_core_and_supports_stdin() -> None:
    core = SimpleNamespace(process=AsyncMock(return_value={"assistant_response": "ok"}))

    with pytest.raises(ValueError, match="Unknown output format"):
        await execute_direct_prompt(core, prompt_text="hello", output_format="xml")
    core.process.assert_not_awaited()

    outcome = await execute_direct_prompt(
        core,
        prompt_text="-",
        output_format="json",
        stdin_text=" piped prompt \n",
        stdin_is_tty=False,
    )
    assert outcome.response == {"assistant_response": "ok"}
    core.process.assert_awaited_once_with({"text": "piped prompt"}, streaming=False)


def test_session_resolution_preserves_resume_precedence_and_fresh_state() -> None:
    core = SimpleNamespace(
        load_conversation=Mock(),
        list_checkpoints=Mock(return_value={"checkpoints": [{"id": "last"}]}),
    )

    resumed = resolve_session(core, continue_last=True, resume_session="explicit")
    assert resumed.session_id == "explicit"
    core.load_conversation.assert_called_once_with("explicit")
    core.list_checkpoints.assert_not_called()

    core.load_conversation.reset_mock()
    continued = resolve_session(core, continue_last=True, resume_session=None)
    assert continued.session_id == "last"
    core.load_conversation.assert_called_once_with("last")

    core.list_checkpoints.return_value = {"checkpoints": []}
    assert (
        resolve_session(core, continue_last=True, resume_session=None).kind == "fresh"
    )
