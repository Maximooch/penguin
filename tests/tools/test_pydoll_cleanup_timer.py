"""The PyDoll idle timer restarts after its previous task has ended (SM-58)."""

from __future__ import annotations

import asyncio

import pytest

from penguin.tools.pydoll_tools import PyDollBrowserManager


@pytest.mark.asyncio
async def test_idle_timer_restarts_after_the_old_task_finished() -> None:
    manager = PyDollBrowserManager.__new__(PyDollBrowserManager)
    manager.browser = object()
    manager.initialized = True
    manager._last_activity = None
    finished = asyncio.create_task(asyncio.sleep(0))
    await finished
    manager._cleanup_task = finished

    await manager._start_cleanup_timer()

    try:
        assert manager._cleanup_task is not finished
        assert not manager._cleanup_task.done()
    finally:
        manager._cleanup_task.cancel()


@pytest.mark.asyncio
async def test_running_idle_timer_is_left_alone() -> None:
    manager = PyDollBrowserManager.__new__(PyDollBrowserManager)
    manager.browser = object()
    manager.initialized = True
    manager._last_activity = None
    running = asyncio.create_task(asyncio.sleep(30))
    manager._cleanup_task = running

    await manager._start_cleanup_timer()

    try:
        assert manager._cleanup_task is running
    finally:
        running.cancel()
