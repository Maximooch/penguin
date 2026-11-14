"""Continuous run mode stops on a stop signal and on repeated empty responses."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin import run_mode as run_mode_module
from penguin.run_mode import RunMode
from tests.test_runmode_continuous_drift import DummyCore


def _run_mode(results: list[dict[str, str]]) -> RunMode:
    project_manager = MagicMock()
    project_manager.get_task_by_title = MagicMock(return_value=None)
    project_manager.get_next_task_async = AsyncMock(return_value=None)
    run_mode = RunMode(core=DummyCore(project_manager=project_manager))
    remaining = list(results)

    async def execute(*_args, **_kwargs):
        return remaining.pop(0) if len(remaining) > 1 else remaining[0]

    run_mode._execute_task = AsyncMock(side_effect=execute)
    run_mode._graceful_shutdown = AsyncMock()
    run_mode._health_check = AsyncMock()
    return run_mode


@pytest.fixture(autouse=True)
def _fast_sleep(monkeypatch: pytest.MonkeyPatch) -> None:
    real_sleep = asyncio.sleep

    async def short_sleep(_seconds: float) -> None:
        await real_sleep(0)

    monkeypatch.setattr(run_mode_module.asyncio, "sleep", short_sleep)


@pytest.mark.asyncio
async def test_repeated_empty_responses_end_continuous_mode() -> None:
    empty = {
        "status": "llm_empty_response_error",
        "completion_type": "llm_empty_response_error",
    }
    run_mode = _run_mode([empty])

    await asyncio.wait_for(run_mode.start_continuous(project_id=None), timeout=5)

    assert (
        run_mode._execute_task.await_count
        == RunMode.MAX_CONSECUTIVE_EMPTY_RESPONSES
    )


@pytest.mark.asyncio
async def test_emergency_stop_ends_continuous_mode() -> None:
    run_mode = _run_mode(
        [
            {"status": "completed", "completion_type": "emergency_stop"},
            {"status": "completed", "completion_type": "user_specified"},
        ]
    )

    await asyncio.wait_for(run_mode.start_continuous(project_id=None), timeout=5)

    assert run_mode._execute_task.await_count == 1
