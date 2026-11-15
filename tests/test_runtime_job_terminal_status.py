"""A finished runtime job keeps its terminal status.

Covers SM-75 (runtime job upsert): ``upsert_runtime_job`` replaced every
column, so a late write such as a cancel request read before the job finished
could turn a completed job back into ``cancel_requested``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from penguin.project.runtime_jobs import RuntimeJobRecord
from penguin.project.storage import ProjectStorage

if TYPE_CHECKING:
    from pathlib import Path


def _record(status: str, **fields: Any) -> RuntimeJobRecord:
    return RuntimeJobRecord(
        job_id="job_1",
        kind="runmode",
        status=status,
        started_at="2026-11-15T00:00:00+00:00",
        **fields,
    )


def test_a_late_update_cannot_reopen_a_finished_job(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path / "projects.db")
    storage.upsert_runtime_job(_record("running"))
    storage.upsert_runtime_job(_record("completed", result_summary="done"))

    storage.upsert_runtime_job(_record("cancel_requested", cancel_requested=True))

    stored = storage.get_runtime_job("job_1")
    assert stored is not None
    assert stored.status == "completed"
    assert stored.result_summary == "done"


def test_a_running_job_still_takes_updates(tmp_path: Path) -> None:
    storage = ProjectStorage(tmp_path / "projects.db")
    storage.upsert_runtime_job(_record("running"))

    storage.upsert_runtime_job(_record("cancel_requested", cancel_requested=True))

    stored = storage.get_runtime_job("job_1")
    assert stored is not None
    assert stored.status == "cancel_requested"
