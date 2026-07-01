"""Tests for RunMode lifecycle helpers."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock

import pytest

from penguin.core_runtime import runmode_lifecycle


class _FakeRunMode:
    def __init__(self, *, continuous_mode: bool = False) -> None:
        self.continuous_mode = continuous_mode
        self.start = AsyncMock()
        self.start_continuous = AsyncMock()


def _owner() -> SimpleNamespace:
    return SimpleNamespace(
        _ui_update_callback=None,
        _runmode_stream_callback=None,
        _runmode_active=False,
        _continuous_mode=False,
        current_runmode_status_summary="RunMode idle.",
        run_mode="stale",
        _prepare_runmode_stream_callback=lambda callback: ("prepared", callback),
        _handle_run_mode_event=AsyncMock(),
    )


@pytest.mark.asyncio
async def test_start_run_mode_runs_single_task_and_cleans_transient_state() -> None:
    owner = _owner()
    run_mode = _FakeRunMode()
    factory_calls: list[dict[str, Any]] = []

    def run_mode_factory(core: Any, **kwargs: Any) -> _FakeRunMode:
        factory_calls.append({"core": core, **kwargs})
        return run_mode

    await runmode_lifecycle.start_run_mode(
        owner,
        name="Task",
        description="Do work",
        context={"id": "task-1"},
        stream_callback_for_cli=AsyncMock(),
        run_mode_factory=run_mode_factory,
        log_error=lambda *_args, **_kwargs: None,
        logger=logging.getLogger(__name__),
    )

    assert factory_calls == [
        {
            "core": owner,
            "time_limit": None,
            "event_callback": owner._handle_run_mode_event,
        }
    ]
    run_mode.start.assert_awaited_once_with(
        name="Task",
        description="Do work",
        context={"id": "task-1"},
    )
    run_mode.start_continuous.assert_not_awaited()
    assert owner._runmode_active is False
    assert owner._runmode_stream_callback is None
    assert owner._ui_update_callback is None
    assert owner.run_mode is None
    assert owner._continuous_mode is False


@pytest.mark.asyncio
async def test_start_run_mode_uses_project_frontier_for_continuous_project() -> None:
    owner = _owner()
    run_mode = _FakeRunMode()

    await runmode_lifecycle.start_run_mode(
        owner,
        name="Project Name",
        description="Project description",
        context={"project_id": "project-123"},
        continuous=True,
        mode_type="project",
        run_mode_factory=lambda *_args, **_kwargs: run_mode,
        log_error=lambda *_args, **_kwargs: None,
        logger=logging.getLogger(__name__),
    )

    run_mode.start.assert_not_awaited()
    run_mode.start_continuous.assert_awaited_once_with(
        specified_task_name=None,
        task_description=None,
        project_id="project-123",
    )
    assert owner._continuous_mode is False


@pytest.mark.asyncio
async def test_start_run_mode_passes_task_details_for_continuous_task() -> None:
    owner = _owner()
    run_mode = _FakeRunMode(continuous_mode=True)

    await runmode_lifecycle.start_run_mode(
        owner,
        name="Task Name",
        description="Task description",
        continuous=True,
        mode_type="task",
        time_limit=5,
        run_mode_factory=lambda *_args, **_kwargs: run_mode,
        log_error=lambda *_args, **_kwargs: None,
        logger=logging.getLogger(__name__),
    )

    run_mode.start_continuous.assert_awaited_once_with(
        specified_task_name="Task Name",
        task_description="Task description",
        project_id=None,
    )
    assert owner._continuous_mode is True


@pytest.mark.asyncio
async def test_start_run_mode_reports_failure_and_invokes_ui_callback() -> None:
    owner = _owner()
    ui_callback = AsyncMock()
    logged_errors: list[dict[str, Any]] = []

    def failing_factory(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("init failed")

    def record_error(exc: BaseException, **kwargs: Any) -> None:
        logged_errors.append({"exc": exc, **kwargs})

    with pytest.raises(RuntimeError, match="init failed"):
        await runmode_lifecycle.start_run_mode(
            owner,
            name="Task",
            description="Do work",
            ui_update_callback_for_cli=ui_callback,
            run_mode_factory=failing_factory,
            log_error=record_error,
            logger=logging.getLogger(__name__),
        )

    ui_callback.assert_awaited_once_with()
    assert str(logged_errors[0]["exc"]) == "init failed"
    assert logged_errors[0]["context"] == {
        "component": "core",
        "method": "start_run_mode",
        "task_name": "Task",
        "description": "Do work",
    }
    assert owner.current_runmode_status_summary == "Error starting RunMode: init failed"
    assert owner._runmode_active is False
    assert owner._runmode_stream_callback is None
    assert owner._ui_update_callback is None
    assert owner.run_mode is None
    assert owner._continuous_mode is False


@pytest.mark.asyncio
async def test_start_run_mode_preserves_original_failure_when_ui_callback_fails(
    caplog: pytest.LogCaptureFixture,
) -> None:
    owner = _owner()

    async def failing_ui_callback() -> None:
        raise RuntimeError("ui failed")

    def failing_factory(*_args: Any, **_kwargs: Any) -> Any:
        raise RuntimeError("init failed")

    with caplog.at_level(logging.ERROR):
        with pytest.raises(RuntimeError, match="init failed"):
            await runmode_lifecycle.start_run_mode(
                owner,
                ui_update_callback_for_cli=failing_ui_callback,
                run_mode_factory=failing_factory,
                log_error=lambda *_args, **_kwargs: None,
                logger=logging.getLogger(__name__),
            )

    assert "Error in UI update callback: ui failed" in caplog.text
