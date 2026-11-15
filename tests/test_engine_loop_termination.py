"""``run_response`` and ``run_task`` end their turn loops by the same rules.

Both entry points run ``Engine._iteration_loop``. A run without an iteration
cap must still end when the model keeps producing output Penguin has to
recover from, and a cancelled run keeps what it already did.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from penguin.engine import (
    MAX_CONSECUTIVE_OUTPUT_CONTINUATIONS,
    MAX_MALFORMED_ACTION_REPAIRS,
    StopCondition,
)
from penguin.llm.contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMProviderError,
)
from penguin.utils.errors import LLMEmptyResponseError
from tests.test_engine_task_finish_contract import _ScriptedTaskEngine

MODES = ["task", "response"]
LIMIT_STATUS = {"task": "iterations_exceeded", "response": "max_iterations"}
MALFORMED = '-contract.md","show_line_numbers":true}</read_file>\n\n'


async def _run(engine: _ScriptedTaskEngine, mode: str) -> dict[str, Any]:
    if mode == "task":
        return await engine.run_task(task_prompt="Work", enable_events=False)
    return await engine.run_response("Work", streaming=False)


def _malformed_turn() -> dict[str, Any]:
    return {"assistant_response": MALFORMED, "action_results": []}


def _length_turn() -> dict[str, Any]:
    return {
        "assistant_response": "partial, ",
        "action_results": [],
        "finish_reason": FinishReason.LENGTH,
    }


class _AlwaysStop(StopCondition):
    async def should_stop(self, engine: Any) -> bool:
        del engine
        return True


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_stop_request_is_reported_as_stopped(mode: str) -> None:
    engine = _ScriptedTaskEngine([])
    engine.stop_conditions.append(_AlwaysStop())

    result = await _run(engine, mode)

    assert engine.provider_calls == 0
    assert result["status"] == "stopped"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_an_empty_provider_answer_is_reported_the_same_way(mode: str) -> None:
    engine = _ScriptedTaskEngine([])

    async def empty(**_kwargs: Any) -> dict[str, Any]:
        raise LLMEmptyResponseError("model returned no answer")

    engine._llm_step = empty  # type: ignore[method-assign]

    result = await _run(engine, mode)

    assert result["status"] == "llm_empty_response_error"
    if mode == "response":
        assert (
            result["assistant_response"] == "Error occurred: model returned no answer"
        )


@pytest.mark.asyncio
async def test_a_response_reports_a_provider_error_as_its_answer() -> None:
    engine = _ScriptedTaskEngine([])
    error = LLMError(message="denied", category=ErrorCategory.AUTH, retryable=False)

    async def failing(**_kwargs: Any) -> dict[str, Any]:
        raise LLMProviderError(error)

    engine._llm_step = failing  # type: ignore[method-assign]

    result = await _run(engine, "response")

    assert result["status"] == "provider_error"
    assert result["assistant_response"].startswith("Provider error occurred:")
    assert result["recoverable"] is False
    assert result["error"]["message"] == "denied"


@pytest.mark.asyncio
async def test_a_failed_finish_response_does_not_end_the_response() -> None:
    engine = _ScriptedTaskEngine(
        [
            {
                "assistant_response": "",
                "action_results": [
                    {"action": "finish_response", "status": "error", "result": "no"}
                ],
            },
            {"assistant_response": "Done", "action_results": []},
        ]
    )

    result = await _run(engine, "response")

    assert engine.provider_calls == 2
    assert result["status"] == "completed"
    assert result["assistant_response"] == "Done"


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_repeated_malformed_tool_syntax_ends_an_uncapped_run(mode: str) -> None:
    engine = _ScriptedTaskEngine([_malformed_turn() for _ in range(40)])

    result = await _run(engine, mode)

    assert engine.provider_calls == MAX_MALFORMED_ACTION_REPAIRS + 1
    assert result["status"] == LIMIT_STATUS[mode]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_alternating_recovery_turns_still_end_an_uncapped_run(mode: str) -> None:
    turns = [turn for _ in range(20) for turn in (_length_turn(), _malformed_turn())]
    engine = _ScriptedTaskEngine(turns)

    result = await _run(engine, mode)

    assert engine.provider_calls == 2 * (MAX_MALFORMED_ACTION_REPAIRS + 1)
    assert result["status"] == LIMIT_STATUS[mode]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_output_limit_stop_uses_the_iteration_limit_status(mode: str) -> None:
    engine = _ScriptedTaskEngine([_length_turn() for _ in range(40)])

    result = await _run(engine, mode)

    assert engine.provider_calls == MAX_CONSECUTIVE_OUTPUT_CONTINUATIONS + 1
    assert result["status"] == LIMIT_STATUS[mode]


@pytest.mark.asyncio
@pytest.mark.parametrize("mode", MODES)
async def test_a_cancelled_run_saves_what_it_already_did(mode: str) -> None:
    engine = _ScriptedTaskEngine([])
    conversation = engine.test_conversation_manager.conversation
    saved_lengths: list[int] = []
    engine.test_conversation_manager.save = (  # type: ignore[method-assign]
        lambda: saved_lengths.append(len(conversation.session.messages)) or True
    )

    async def cancelled_mid_turn(**_kwargs: Any) -> dict[str, Any]:
        conversation.add_assistant_message("Started the edit")
        raise asyncio.CancelledError

    engine._llm_step = cancelled_mid_turn  # type: ignore[method-assign]

    with pytest.raises(asyncio.CancelledError):
        await _run(engine, mode)

    assert saved_lengths, "a cancelled run did not save the conversation"
    assert saved_lengths[-1] == len(conversation.session.messages)
