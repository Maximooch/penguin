from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from penguin.core import PenguinCore


@pytest.mark.asyncio
async def test_start_run_mode_cleans_up_when_runmode_construction_fails():
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

    with patch("penguin.core.RunMode", side_effect=RuntimeError("init failed")):
        with pytest.raises(RuntimeError, match="init failed"):
            await PenguinCore.start_run_mode(core, name="Task")

    assert core._runmode_active is False
    assert core._runmode_stream_callback is None
    assert core.run_mode is None
    assert core._ui_update_callback is None
    assert core._continuous_mode is False
    assert "Error starting RunMode" in core.current_runmode_status_summary
