"""Guard against historical checkpoint queue/worker event-loop mismatches."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock

import pytest

from penguin.system.checkpoint_manager import CheckpointManager

if TYPE_CHECKING:
    from pathlib import Path


def test_checkpoint_workers_restart_on_a_new_event_loop(tmp_path: Path) -> None:
    """Clean shutdown must allow the same manager to use a fresh event loop."""
    manager = CheckpointManager(tmp_path, SimpleNamespace())
    create = AsyncMock()
    manager._create_checkpoint_file = create
    queues = []
    tasks = []

    async def cycle() -> None:
        await manager.start_workers()
        queues.append(manager.checkpoint_queue)
        tasks.extend(manager._worker_tasks)
        try:
            await manager.checkpoint_queue.put(("create", "synthetic", "metadata"))
            await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=1)
        finally:
            await manager.stop_workers()

    asyncio.run(cycle())
    asyncio.run(cycle())
    assert queues[0] is not queues[1]
    assert create.await_count == 2
    assert all(task.done() for task in tasks)
    assert not manager._workers_started


@pytest.mark.asyncio
@pytest.mark.xfail(
    strict=True,
    reason="Checkpoint worker omits task_done when checkpoint creation raises",
)
async def test_failed_checkpoint_does_not_strand_queue_join(tmp_path: Path) -> None:
    """Disk errors must not leave the queue's unfinished-work count stuck."""
    manager = CheckpointManager(tmp_path, SimpleNamespace())
    manager._create_checkpoint_file = AsyncMock(side_effect=OSError(28, "disk full"))
    await manager.start_workers()
    try:
        await manager.checkpoint_queue.put(("create", "synthetic", "metadata"))
        await asyncio.wait_for(manager.checkpoint_queue.join(), timeout=0.1)
    finally:
        await manager.stop_workers()
