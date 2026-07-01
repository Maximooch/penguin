from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from penguin.core import PenguinCore


@pytest.mark.asyncio
async def test_start_run_mode_cleans_up_when_runmode_construction_fails(monkeypatch):
    core = SimpleNamespace(
        _ui_update_callback=None,
        _runmode_stream_callback=None,
        _runmode_active=False,
        _continuous_mode=False,
        current_runmode_status_summary="",
        run_mode="stale",
        _prepare_runmode_stream_callback=lambda cb: cb,
        _handle_run_mode_event=AsyncMock(),
    )
    facade_globals = PenguinCore.start_run_mode.__globals__

    def fail_runmode(*_args, **_kwargs):
        raise RuntimeError("init failed")

    monkeypatch.setitem(facade_globals, "RunMode", fail_runmode)

    with pytest.raises(RuntimeError, match="init failed"):
        await PenguinCore.start_run_mode(core, name="Task")

    assert core._runmode_active is False
    assert core._runmode_stream_callback is None
    assert core.run_mode is None
    assert core._ui_update_callback is None
    assert core._continuous_mode is False
    assert "Error starting RunMode" in core.current_runmode_status_summary


@pytest.mark.asyncio
async def test_start_run_mode_continuous_project_uses_ready_frontier(
    monkeypatch,
):
    core = SimpleNamespace(
        _ui_update_callback=None,
        _runmode_stream_callback=None,
        _runmode_active=False,
        _continuous_mode=False,
        current_runmode_status_summary="",
        run_mode=None,
        _prepare_runmode_stream_callback=lambda cb: cb,
        _handle_run_mode_event=AsyncMock(),
    )
    run_mode = SimpleNamespace(start_continuous=AsyncMock(), continuous_mode=False)
    facade_globals = PenguinCore.start_run_mode.__globals__

    monkeypatch.setitem(facade_globals, "RunMode", lambda *_args, **_kwargs: run_mode)
    await PenguinCore.start_run_mode(
        core,
        name="Example Project",
        description="Project description",
        context={"project_id": "project-123"},
        continuous=True,
        mode_type="project",
    )

    run_mode.start_continuous.assert_awaited_once_with(
        specified_task_name=None,
        task_description=None,
        project_id="project-123",
    )
