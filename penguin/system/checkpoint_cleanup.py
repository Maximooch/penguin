"""Read-only checkpoint inventory and retention planning.

The planner is intentionally separated from deletion. It can inspect a damaged or
oversized checkpoint tree and explain what policy would retain or remove without
changing source data.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Collection, Mapping

__all__ = [
    "CheckpointCleanupPlan",
    "CheckpointInventoryItem",
    "build_checkpoint_cleanup_plan",
]


@dataclass(frozen=True)
class CheckpointInventoryItem:
    """One checkpoint file and its retention decision."""

    checkpoint_id: str
    checkpoint_type: str
    created_at: str
    session_id: str
    path: Path
    size_bytes: int
    age_seconds: float
    decision: str
    reason: str
    indexed: bool

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable inventory record."""

        payload = asdict(self)
        payload["path"] = str(self.path)
        return payload


@dataclass(frozen=True)
class CheckpointCleanupPlan:
    """Complete read-only inventory and proposed retention result."""

    generated_at: str
    checkpoint_path: Path
    dry_run: bool
    total_count: int
    total_bytes: int
    candidate_count: int
    candidate_bytes: int
    retained_count: int
    retained_bytes: int
    candidates: tuple[CheckpointInventoryItem, ...]
    retained: tuple[CheckpointInventoryItem, ...]
    age_buckets: dict[str, dict[str, int]]
    session_ownership: dict[str, dict[str, int]]
    retention_policy: dict[str, int | None]
    recovery_plan: dict[str, object]

    def to_dict(self) -> dict[str, object]:
        """Return the full plan as a JSON-serializable payload."""

        return {
            "generated_at": self.generated_at,
            "checkpoint_path": str(self.checkpoint_path),
            "dry_run": self.dry_run,
            "total_count": self.total_count,
            "total_bytes": self.total_bytes,
            "candidate_count": self.candidate_count,
            "candidate_bytes": self.candidate_bytes,
            "retained_count": self.retained_count,
            "retained_bytes": self.retained_bytes,
            "candidates": [item.to_dict() for item in self.candidates],
            "retained": [item.to_dict() for item in self.retained],
            "age_buckets": self.age_buckets,
            "session_ownership": self.session_ownership,
            "retention_policy": self.retention_policy,
            "recovery_plan": self.recovery_plan,
        }


def build_checkpoint_cleanup_plan(
    checkpoint_path: str | Path,
    checkpoint_index: Mapping[str, Any],
    *,
    keep_all_hours: int,
    keep_every_nth: int,
    max_age_days: int,
    max_auto_checkpoints: int,
    max_checkpoint_bytes: int | None = None,
    active_session_keep: int = 1,
    active_session_ids: Collection[str] = (),
    now: datetime | None = None,
) -> CheckpointCleanupPlan:
    """Inventory checkpoints and calculate a non-destructive cleanup plan.

    Args:
        checkpoint_path: Directory containing ``*.json.gz`` checkpoints.
        checkpoint_index: Mapping of checkpoint IDs to metadata objects or dicts.
        keep_all_hours: Age window in which every auto checkpoint is retained.
        keep_every_nth: Sampling interval for older, non-expired auto checkpoints.
        max_age_days: Maximum age for unprotected automatic checkpoints.
        max_auto_checkpoints: Maximum number of retained unprotected autos.
        max_checkpoint_bytes: Maximum retained checkpoint bytes when configured.
        active_session_keep: Newest automatic checkpoints protected per active
            session. Older automatic checkpoints remain eligible for retention.
        active_session_ids: Sessions whose newest checkpoints are protected.
        now: Deterministic evaluation time. Defaults to current UTC time.

    Returns:
        A dry-run plan containing every file, byte count, decision, and recovery
        instruction. No file is created, modified, moved, or deleted.
    """

    root = Path(checkpoint_path).expanduser().resolve()
    evaluated_at = _normalize_datetime(now or datetime.now(timezone.utc))
    active_sessions = {str(value) for value in active_session_ids}
    keep_every = max(1, keep_every_nth)
    indexed_items: list[_MutableInventoryItem] = []

    for checkpoint_id, raw_metadata in checkpoint_index.items():
        metadata = _normalize_metadata(str(checkpoint_id), raw_metadata)
        file_path = root / f"{checkpoint_id}.json.gz"
        created_at = metadata["created_at"]
        size_bytes = _file_size(file_path)
        age_seconds = max(0.0, (evaluated_at - created_at).total_seconds())
        indexed_items.append(
            _MutableInventoryItem(
                checkpoint_id=str(checkpoint_id),
                checkpoint_type=metadata["checkpoint_type"],
                created_at=created_at,
                session_id=metadata["session_id"],
                path=file_path,
                size_bytes=size_bytes,
                age_seconds=age_seconds,
                indexed=True,
            )
        )

    indexed_ids = {item.checkpoint_id for item in indexed_items}
    orphan_items: list[_MutableInventoryItem] = []
    if root.exists():
        for file_path in sorted(root.glob("*.json.gz")):
            checkpoint_id = file_path.name[: -len(".json.gz")]
            if checkpoint_id in indexed_ids:
                continue
            try:
                created_at = datetime.fromtimestamp(
                    file_path.stat().st_mtime,
                    tz=timezone.utc,
                )
            except OSError:
                created_at = evaluated_at
            orphan_items.append(
                _MutableInventoryItem(
                    checkpoint_id=checkpoint_id,
                    checkpoint_type="unknown",
                    created_at=created_at,
                    session_id="unknown",
                    path=file_path,
                    size_bytes=_file_size(file_path),
                    age_seconds=max(
                        0.0,
                        (evaluated_at - created_at).total_seconds(),
                    ),
                    indexed=False,
                    decision="retain",
                    reason="unindexed_requires_review",
                )
            )

    missing_ids = {
        item.checkpoint_id for item in indexed_items if not item.path.exists()
    }
    auto_items = [item for item in indexed_items if item.checkpoint_type == "auto"]
    usable_auto_items = [
        item for item in auto_items if item.checkpoint_id not in missing_ids
    ]
    active_auto_ids: set[str] = set()
    for active_session_id in active_sessions:
        active_items = sorted(
            (
                item
                for item in usable_auto_items
                if item.session_id == active_session_id
            ),
            key=lambda item: item.created_at,
            reverse=True,
        )
        active_auto_ids.update(
            item.checkpoint_id for item in active_items[: max(1, active_session_keep)]
        )
    sampled_items = sorted(
        usable_auto_items,
        key=lambda item: item.created_at,
        reverse=True,
    )
    sample_positions = {
        item.checkpoint_id: position for position, item in enumerate(sampled_items)
    }
    recent_seconds = max(0, keep_all_hours) * 60 * 60
    maximum_age_seconds = max(0, max_age_days) * 24 * 60 * 60

    for item in indexed_items:
        if item.checkpoint_id in missing_ids:
            item.decision = "retain"
            item.reason = "missing_file_requires_review"
        elif item.checkpoint_id in active_auto_ids:
            item.decision = "retain"
            item.reason = "active_session"
        elif item.checkpoint_type != "auto":
            item.decision = "retain"
            item.reason = f"protected_{item.checkpoint_type}"
        elif item.age_seconds <= recent_seconds:
            item.decision = "retain"
            item.reason = "recent"
        elif item.age_seconds > maximum_age_seconds:
            item.decision = "delete"
            item.reason = "max_age_days"
        elif sample_positions[item.checkpoint_id] % keep_every == 0:
            item.decision = "retain"
            item.reason = "sampled_retention"
        else:
            item.decision = "delete"
            item.reason = "sampled_out"

    protected_auto_count = sum(
        1
        for item in usable_auto_items
        if item.decision == "retain" and item.reason == "active_session"
    )
    available_auto_slots = max(0, max_auto_checkpoints - protected_auto_count)
    unprotected_retained_autos = sorted(
        (
            item
            for item in usable_auto_items
            if item.decision == "retain"
            and item.reason not in {"active_session", "missing_file_requires_review"}
        ),
        key=lambda item: item.created_at,
        reverse=True,
    )
    for item in unprotected_retained_autos[available_auto_slots:]:
        item.decision = "delete"
        item.reason = "max_auto_checkpoints"

    if max_checkpoint_bytes is not None and max_checkpoint_bytes >= 0:
        retained_bytes = sum(
            item.size_bytes
            for item in [*indexed_items, *orphan_items]
            if item.decision != "delete"
        )
        size_candidates = sorted(
            (
                item
                for item in usable_auto_items
                if item.decision == "retain"
                and item.reason
                not in {"active_session", "missing_file_requires_review"}
            ),
            key=lambda item: (item.created_at, item.checkpoint_id),
        )
        for item in size_candidates:
            if retained_bytes <= max_checkpoint_bytes:
                break
            item.decision = "delete"
            item.reason = "max_checkpoint_bytes"
            retained_bytes -= item.size_bytes

    all_items = [*indexed_items, *orphan_items]
    candidates = tuple(
        _freeze_item(item)
        for item in sorted(
            (entry for entry in all_items if entry.decision == "delete"),
            key=lambda entry: (entry.created_at, entry.checkpoint_id),
        )
    )
    retained = tuple(
        _freeze_item(item)
        for item in sorted(
            (entry for entry in all_items if entry.decision != "delete"),
            key=lambda entry: (entry.created_at, entry.checkpoint_id),
        )
    )
    total_bytes = sum(item.size_bytes for item in all_items)
    candidate_bytes = sum(item.size_bytes for item in candidates)
    retained_bytes = sum(item.size_bytes for item in retained)

    return CheckpointCleanupPlan(
        generated_at=evaluated_at.isoformat(),
        checkpoint_path=root,
        dry_run=True,
        total_count=len(all_items),
        total_bytes=total_bytes,
        candidate_count=len(candidates),
        candidate_bytes=candidate_bytes,
        retained_count=len(retained),
        retained_bytes=retained_bytes,
        candidates=candidates,
        retained=retained,
        age_buckets=_build_age_buckets(all_items),
        session_ownership=_build_session_ownership(all_items),
        retention_policy={
            "keep_all_hours": keep_all_hours,
            "keep_every_nth": keep_every,
            "max_age_days": max_age_days,
            "max_auto_checkpoints": max_auto_checkpoints,
            "max_checkpoint_bytes": max_checkpoint_bytes,
            "active_session_keep": max(1, active_session_keep),
        },
        recovery_plan={
            "archive_before_delete": True,
            "archive_destination": str(
                root / "archive" / evaluated_at.strftime("%Y%m%dT%H%M%SZ")
            ),
            "manifest": (
                "Record checkpoint id, source path, size, and sha256 before move."
            ),
            "restore": (
                "Restore archived *.json.gz files to the checkpoint directory and "
                "rebuild checkpoint_index.json before rollback/branch operations."
            ),
            "approval_required": True,
        },
    )


@dataclass
class _MutableInventoryItem:
    """Internal mutable item while retention decisions are calculated."""

    checkpoint_id: str
    checkpoint_type: str
    created_at: datetime
    session_id: str
    path: Path
    size_bytes: int
    age_seconds: float
    indexed: bool
    decision: str = "retain"
    reason: str = "policy_retained"


def _freeze_item(item: _MutableInventoryItem) -> CheckpointInventoryItem:
    """Convert an internal item to its immutable public representation."""

    return CheckpointInventoryItem(
        checkpoint_id=item.checkpoint_id,
        checkpoint_type=item.checkpoint_type,
        created_at=item.created_at.isoformat(),
        session_id=item.session_id,
        path=item.path,
        size_bytes=item.size_bytes,
        age_seconds=item.age_seconds,
        decision=item.decision,
        reason=item.reason,
        indexed=item.indexed,
    )


def _normalize_metadata(checkpoint_id: str, raw_metadata: Any) -> dict[str, Any]:
    """Normalize dataclass/dict metadata without mutating the source."""

    if isinstance(raw_metadata, Mapping):
        getter = raw_metadata.get
    else:

        def getter(name: str, default: Any = None) -> Any:
            return getattr(raw_metadata, name, default)

    raw_type = getter("type", "unknown")
    checkpoint_type = str(getattr(raw_type, "value", raw_type) or "unknown")
    raw_created_at = getter("created_at", None)
    try:
        created_at = _normalize_datetime(datetime.fromisoformat(str(raw_created_at)))
    except (TypeError, ValueError):
        created_at = datetime.fromtimestamp(0, tz=timezone.utc)
    return {
        "checkpoint_id": checkpoint_id,
        "checkpoint_type": checkpoint_type,
        "created_at": created_at,
        "session_id": str(getter("session_id", "unknown") or "unknown"),
    }


def _normalize_datetime(value: datetime) -> datetime:
    """Return a timezone-aware UTC datetime."""

    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _file_size(path: Path) -> int:
    """Return a file's current size or zero if it races/disappears."""

    try:
        return path.stat().st_size
    except OSError:
        return 0


def _build_age_buckets(
    items: Collection[_MutableInventoryItem],
) -> dict[str, dict[str, int]]:
    """Aggregate count/bytes into stable age buckets."""

    buckets = {
        "under_24_hours": {"count": 0, "bytes": 0},
        "one_to_seven_days": {"count": 0, "bytes": 0},
        "eight_to_30_days": {"count": 0, "bytes": 0},
        "over_30_days": {"count": 0, "bytes": 0},
    }
    for item in items:
        age_days = item.age_seconds / (24 * 60 * 60)
        if age_days < 1:
            label = "under_24_hours"
        elif age_days <= 7:
            label = "one_to_seven_days"
        elif age_days <= 30:
            label = "eight_to_30_days"
        else:
            label = "over_30_days"
        buckets[label]["count"] += 1
        buckets[label]["bytes"] += item.size_bytes
    return buckets


def _build_session_ownership(
    items: Collection[_MutableInventoryItem],
) -> dict[str, dict[str, int]]:
    """Aggregate retained/candidate evidence by owning session."""

    ownership: dict[str, dict[str, int]] = {}
    for item in items:
        summary = ownership.setdefault(
            item.session_id,
            {
                "total_count": 0,
                "total_bytes": 0,
                "candidate_count": 0,
                "candidate_bytes": 0,
                "retained_count": 0,
                "retained_bytes": 0,
            },
        )
        summary["total_count"] += 1
        summary["total_bytes"] += item.size_bytes
        if item.decision == "delete":
            summary["candidate_count"] += 1
            summary["candidate_bytes"] += item.size_bytes
        else:
            summary["retained_count"] += 1
            summary["retained_bytes"] += item.size_bytes
    return ownership
