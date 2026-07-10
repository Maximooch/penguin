"""Read-only checkpoint cleanup planning tests."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import TYPE_CHECKING

from penguin.system.checkpoint_cleanup import build_checkpoint_cleanup_plan
from penguin.system.checkpoint_manager import CheckpointMetadata, CheckpointType

if TYPE_CHECKING:
    from pathlib import Path


def _metadata(
    checkpoint_id: str,
    *,
    checkpoint_type: CheckpointType,
    created_at: datetime,
    session_id: str,
) -> CheckpointMetadata:
    """Build deterministic metadata for one cleanup fixture."""

    return CheckpointMetadata(
        id=checkpoint_id,
        type=checkpoint_type,
        created_at=created_at.isoformat(),
        session_id=session_id,
        message_id=f"message-{checkpoint_id}",
        message_count=1,
        auto=checkpoint_type == CheckpointType.AUTO,
    )


def test_cleanup_plan_is_read_only_and_explains_every_decision(
    tmp_path: Path,
) -> None:
    """Planning reports bytes, ownership, age, protection, and recovery."""

    now = datetime(2026, 7, 10, 12, 0, 0)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    index = {
        "expired": _metadata(
            "expired",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=45),
            session_id="inactive",
        ),
        "active-expired": _metadata(
            "active-expired",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=45),
            session_id="active",
        ),
        "recent": _metadata(
            "recent",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(hours=1),
            session_id="inactive",
        ),
        "manual": _metadata(
            "manual",
            checkpoint_type=CheckpointType.MANUAL,
            created_at=now - timedelta(days=90),
            session_id="inactive",
        ),
    }
    for number, checkpoint_id in enumerate(index, start=1):
        (checkpoints / f"{checkpoint_id}.json.gz").write_bytes(b"x" * number)
    orphan = checkpoints / "orphan.json.gz"
    orphan.write_bytes(b"orphan")
    before = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in checkpoints.iterdir()
    }

    plan = build_checkpoint_cleanup_plan(
        checkpoints,
        index,
        keep_all_hours=24,
        keep_every_nth=10,
        max_age_days=30,
        max_auto_checkpoints=1000,
        active_session_ids={"active"},
        now=now,
    )

    assert plan.dry_run is True
    assert plan.total_count == 5
    assert plan.total_bytes == sum(len(value[0]) for value in before.values())
    assert [item.checkpoint_id for item in plan.candidates] == ["expired"]
    reasons = {item.checkpoint_id: item.reason for item in plan.retained}
    assert reasons["active-expired"] == "active_session"
    assert reasons["recent"] == "recent"
    assert reasons["manual"] == "protected_manual"
    assert reasons["orphan"] == "unindexed_requires_review"
    assert plan.session_ownership["active"]["retained_count"] == 1
    assert plan.age_buckets["over_30_days"]["count"] == 3
    assert plan.recovery_plan["archive_before_delete"] is True
    assert "restore" in plan.recovery_plan

    after = {
        path.name: (path.read_bytes(), path.stat().st_mtime_ns)
        for path in checkpoints.iterdir()
    }
    assert after == before


def test_cleanup_plan_enforces_auto_count_without_deleting_protected_items(
    tmp_path: Path,
) -> None:
    """The count cap selects oldest unprotected autos and preserves branch state."""

    now = datetime(2026, 7, 10, 12, 0, 0)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    index: dict[str, CheckpointMetadata] = {}
    for offset in range(5):
        checkpoint_id = f"auto-{offset}"
        index[checkpoint_id] = _metadata(
            checkpoint_id,
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(hours=offset + 2),
            session_id="session",
        )
        (checkpoints / f"{checkpoint_id}.json.gz").write_bytes(b"auto")
    index["branch"] = _metadata(
        "branch",
        checkpoint_type=CheckpointType.BRANCH,
        created_at=now - timedelta(days=100),
        session_id="session",
    )
    (checkpoints / "branch.json.gz").write_bytes(b"branch")

    plan = build_checkpoint_cleanup_plan(
        checkpoints,
        index,
        keep_all_hours=24,
        keep_every_nth=1,
        max_age_days=365,
        max_auto_checkpoints=2,
        now=now,
    )

    assert {item.checkpoint_id for item in plan.candidates} == {
        "auto-2",
        "auto-3",
        "auto-4",
    }
    assert all(item.reason == "max_auto_checkpoints" for item in plan.candidates)
    assert any(
        item.checkpoint_id == "branch" and item.reason == "protected_branch"
        for item in plan.retained
    )


def test_cleanup_plan_enforces_size_and_protects_newest_active_checkpoint(
    tmp_path: Path,
) -> None:
    """Size pressure removes old autos but not manual or newest active state."""

    now = datetime(2026, 7, 10, 12, 0, 0)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    index = {
        "active-new": _metadata(
            "active-new",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=1),
            session_id="active",
        ),
        "active-old": _metadata(
            "active-old",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=3),
            session_id="active",
        ),
        "inactive": _metadata(
            "inactive",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=2),
            session_id="inactive",
        ),
        "manual": _metadata(
            "manual",
            checkpoint_type=CheckpointType.MANUAL,
            created_at=now - timedelta(days=30),
            session_id="active",
        ),
    }
    for checkpoint_id in index:
        (checkpoints / f"{checkpoint_id}.json.gz").write_bytes(b"x" * 100)

    plan = build_checkpoint_cleanup_plan(
        checkpoints,
        index,
        keep_all_hours=0,
        keep_every_nth=1,
        max_age_days=365,
        max_auto_checkpoints=100,
        max_checkpoint_bytes=250,
        active_session_keep=1,
        active_session_ids={"active"},
        now=now,
    )

    candidates = {item.checkpoint_id: item.reason for item in plan.candidates}
    retained = {item.checkpoint_id: item.reason for item in plan.retained}
    assert candidates == {
        "active-old": "max_checkpoint_bytes",
        "inactive": "max_checkpoint_bytes",
    }
    assert retained["active-new"] == "active_session"
    assert retained["manual"] == "protected_manual"


def test_cleanup_plan_missing_auto_does_not_displace_active_checkpoint(
    tmp_path: Path,
) -> None:
    """Active protection selects the newest checkpoint that can be restored."""

    now = datetime(2026, 7, 10, 12, 0, 0)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    index = {
        "active-missing": _metadata(
            "active-missing",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now,
            session_id="active",
        ),
        "active-usable": _metadata(
            "active-usable",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(hours=1),
            session_id="active",
        ),
        "active-expired": _metadata(
            "active-expired",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=45),
            session_id="active",
        ),
    }
    (checkpoints / "active-usable.json.gz").write_bytes(b"usable")
    (checkpoints / "active-expired.json.gz").write_bytes(b"expired")

    plan = build_checkpoint_cleanup_plan(
        checkpoints,
        index,
        keep_all_hours=0,
        keep_every_nth=1,
        max_age_days=30,
        max_auto_checkpoints=100,
        active_session_keep=1,
        active_session_ids={"active"},
        now=now,
    )

    retained = {item.checkpoint_id: item.reason for item in plan.retained}
    candidates = {item.checkpoint_id: item.reason for item in plan.candidates}
    assert retained["active-missing"] == "missing_file_requires_review"
    assert retained["active-usable"] == "active_session"
    assert candidates["active-expired"] == "max_age_days"


def test_cleanup_plan_missing_auto_does_not_shift_sampling_candidates(
    tmp_path: Path,
) -> None:
    """Sampling positions are based only on checkpoint files that exist."""

    now = datetime(2026, 7, 10, 12, 0, 0)
    checkpoints = tmp_path / "checkpoints"
    checkpoints.mkdir()
    index = {
        "missing-newest": _metadata(
            "missing-newest",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=2),
            session_id="session",
        ),
        "usable-newest": _metadata(
            "usable-newest",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=3),
            session_id="session",
        ),
        "usable-oldest": _metadata(
            "usable-oldest",
            checkpoint_type=CheckpointType.AUTO,
            created_at=now - timedelta(days=4),
            session_id="session",
        ),
    }
    (checkpoints / "usable-newest.json.gz").write_bytes(b"newest")
    (checkpoints / "usable-oldest.json.gz").write_bytes(b"oldest")

    plan = build_checkpoint_cleanup_plan(
        checkpoints,
        index,
        keep_all_hours=0,
        keep_every_nth=2,
        max_age_days=30,
        max_auto_checkpoints=100,
        now=now,
    )

    retained = {item.checkpoint_id: item.reason for item in plan.retained}
    candidates = {item.checkpoint_id: item.reason for item in plan.candidates}
    assert retained["missing-newest"] == "missing_file_requires_review"
    assert retained["usable-newest"] == "sampled_retention"
    assert candidates["usable-oldest"] == "sampled_out"
