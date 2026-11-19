"""A finished workflow keeps its outcome when it is signalled later (SM-21)."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

import pytest

from penguin.orchestration.backend import WorkflowStatus
from penguin.orchestration.config import OrchestrationConfig
from penguin.orchestration.native import NativeBackend
from penguin.orchestration.state import WorkflowState

if TYPE_CHECKING:
    from pathlib import Path


def _backend_with(tmp_path: Path, status: WorkflowStatus) -> NativeBackend:
    backend = NativeBackend(OrchestrationConfig(), tmp_path / "workflows.db")
    backend.storage.save_state(
        WorkflowState(
            workflow_id="wf-1",
            task_id="task-1",
            status=status,
            started_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    return backend


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "status",
    [WorkflowStatus.COMPLETED, WorkflowStatus.FAILED, WorkflowStatus.CANCELLED],
)
@pytest.mark.parametrize("signal", ["pause", "cancel"])
async def test_signal_does_not_rewrite_a_finished_workflow(
    tmp_path: Path, status: WorkflowStatus, signal: str
) -> None:
    backend = _backend_with(tmp_path, status)

    assert await backend.signal_workflow("wf-1", signal) is False

    assert backend.storage.get_state("wf-1").status == status
    assert "wf-1" not in backend._paused_workflows
    assert "wf-1" not in backend._cancelled_workflows


@pytest.mark.asyncio
async def test_running_workflow_can_still_be_cancelled(tmp_path: Path) -> None:
    backend = _backend_with(tmp_path, WorkflowStatus.RUNNING)

    assert await backend.signal_workflow("wf-1", "cancel") is True

    assert backend.storage.get_state("wf-1").status == WorkflowStatus.CANCELLED
