"""Durable checkpoint retention and recoverable cleanup transactions.

The checkpoint manager owns worker admission and lifecycle state.  This module
owns the filesystem transaction that removes checkpoint data, including the
crash-recovery manifest used by automatic retention and the explicit archive
cleanup workflow.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import shutil
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Protocol

from penguin.system.runtime_diagnostics import record_runtime_duration

__all__ = [
    "archive_cleanup_candidates",
    "enforce_automatic_retention",
    "fsync_directory",
    "recover_automatic_retention_transactions",
    "recover_confirmed_cleanup_archives",
    "sha256_file",
    "write_json_atomic",
]


logger = logging.getLogger(__name__)


class _RetentionManager(Protocol):
    """The small manager interface needed by retention transactions."""

    checkpoints_path: Path
    checkpoint_index: dict[str, Any]
    config: Any
    _checkpoint_bytes: int

    def _assert_checkpoint_generation_current(self) -> None:
        """Verify that the worker generation can still commit."""

    def _save_checkpoint_index_or_raise(self) -> None:
        """Durably publish the current checkpoint index."""

    def _reconcile_checkpoint_storage(self) -> None:
        """Refresh storage/accounting state after a transaction."""

    def refresh_admission_counters(self) -> None:
        """Refresh auto-checkpoint counts after an index mutation."""

    def plan_checkpoint_cleanup(self, **kwargs: Any) -> dict[str, Any]:
        """Build the read-only retention plan used by this transaction."""


def recover_automatic_retention_transactions(
    manager: _RetentionManager,
    *,
    metadata_from_manifest: Callable[[dict[str, Any]], Any],
) -> None:
    """Restore or finish automatic-retention transactions after a crash.

    A ``planned`` manifest is rolled back to its original source files; a
    ``committed`` manifest finishes deleting quarantined files.  The caller
    supplies metadata reconstruction so this module does not depend on the
    checkpoint manager's enum/dataclass definitions.
    """

    transaction_root = manager.checkpoints_path / ".automatic-retention"
    if not transaction_root.exists():
        return
    checkpoint_root = manager.checkpoints_path.resolve()
    for transaction_path in sorted(transaction_root.glob("txn-*")):
        manifest_path = transaction_path / "manifest.json"
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                manifest = json.load(handle)
            entries = manifest.get("entries", [])
            if not isinstance(entries, list):
                raise ValueError("retention manifest entries must be a list")
            state = manifest.get("state")
            if state not in {"planned", "committed"}:
                raise ValueError("invalid retention transaction state")
            index_changed = False
            for entry in entries:
                if not isinstance(entry, dict):
                    raise ValueError("invalid retention manifest entry")
                checkpoint_id = entry.get("checkpoint_id")
                source_value = entry.get("source")
                quarantine_value = entry.get("quarantine")
                if not all(
                    isinstance(value, str)
                    for value in (
                        checkpoint_id,
                        source_value,
                        quarantine_value,
                    )
                ):
                    raise ValueError("incomplete retention manifest entry")
                source = Path(source_value).expanduser().resolve()
                quarantine = Path(quarantine_value).expanduser().resolve()
                if source.parent != checkpoint_root:
                    raise RuntimeError(f"Unsafe retention recovery source: {source}")
                if transaction_path.resolve() not in quarantine.parents:
                    raise RuntimeError(
                        f"Unsafe retention recovery quarantine: {quarantine}"
                    )
                if state == "planned":
                    if quarantine.exists() and not source.exists():
                        quarantine.replace(source)
                    elif quarantine.exists() and source.exists():
                        quarantine.unlink()
                    metadata_payload = entry.get("metadata")
                    if (
                        source.exists()
                        and checkpoint_id not in manager.checkpoint_index
                    ):
                        if not isinstance(metadata_payload, dict):
                            raise ValueError("planned retention entry has no metadata")
                        manager.checkpoint_index[checkpoint_id] = (
                            metadata_from_manifest(dict(metadata_payload))
                        )
                        index_changed = True
                else:
                    if quarantine.exists():
                        quarantine.unlink()
                    if checkpoint_id in manager.checkpoint_index:
                        manager.checkpoint_index.pop(checkpoint_id, None)
                        index_changed = True
            if index_changed:
                manager._save_checkpoint_index_or_raise()
            shutil.rmtree(transaction_path)
        except Exception:
            logger.error(
                "Unable to recover automatic retention transaction path=%s",
                transaction_path,
                exc_info=True,
            )
    try:
        transaction_root.rmdir()
    except OSError:
        pass
    fsync_directory(manager.checkpoints_path)


def recover_confirmed_cleanup_archives(
    manager: _RetentionManager,
    *,
    metadata_from_manifest: Callable[[dict[str, Any]], Any],
) -> None:
    """Reconcile an interrupted confirmed-cleanup archive transaction.

    Confirmed cleanup retains its archive instead of deleting it.  A manifest
    whose terminal state was not durably written is therefore resolved from the
    persisted checkpoint index: an unchanged index means restore the archive;
    an index with every candidate removed means the archive commit succeeded.
    """

    archive_root = manager.checkpoints_path / "archive"
    if not archive_root.exists():
        return
    checkpoint_root = manager.checkpoints_path.expanduser().resolve()
    for archive_path in sorted(
        path for path in archive_root.iterdir() if path.is_dir()
    ):
        manifest_path = archive_path / "manifest.json"
        try:
            with manifest_path.open(encoding="utf-8") as handle:
                manifest = json.load(handle)
            state = manifest.get("state")
            if state in {"completed", "rolled_back"}:
                continue
            candidates = manifest.get("candidates", [])
            if not isinstance(candidates, list):
                raise ValueError("cleanup archive candidates must be a list")
            entries = [
                _validated_archive_entry(entry, archive_path, checkpoint_root)
                for entry in candidates
            ]
            candidate_ids = {entry["checkpoint_id"] for entry in entries}
            if candidate_ids and candidate_ids.isdisjoint(manager.checkpoint_index):
                # The reduced index was saved before the process stopped. Keep
                # the recoverable archive and record its completed terminal state.
                manifest["state"] = "completed"
                write_json_atomic(manifest_path, manifest)
                continue

            restored = False
            for entry in entries:
                checkpoint_id = entry["checkpoint_id"]
                source = entry["source"]
                archive_file = entry["archive_file"]
                if archive_file.exists() and not source.exists():
                    archive_file.replace(source)
                    restored = True
                elif archive_file.exists() and source.exists():
                    raise RuntimeError(
                        f"Both archive and checkpoint source exist for {checkpoint_id}"
                    )
                if checkpoint_id not in manager.checkpoint_index:
                    metadata_payload = entry.get("metadata")
                    if not isinstance(metadata_payload, dict):
                        raise ValueError(
                            f"Cleanup archive entry has no metadata: {checkpoint_id}"
                        )
                    manager.checkpoint_index[checkpoint_id] = metadata_from_manifest(
                        dict(metadata_payload)
                    )
                    restored = True
            if restored:
                manager._save_checkpoint_index_or_raise()
            manifest["state"] = "rolled_back"
            write_json_atomic(manifest_path, manifest)
        except Exception:
            logger.error(
                "Unable to recover confirmed checkpoint cleanup archive path=%s",
                archive_path,
                exc_info=True,
            )
    fsync_directory(manager.checkpoints_path)


def _validated_archive_entry(
    entry: Any,
    archive_path: Path,
    checkpoint_root: Path,
) -> dict[str, Any]:
    """Validate one archive-manifest candidate before any recovery mutation."""

    if not isinstance(entry, dict):
        raise ValueError("cleanup archive entry must be an object")
    checkpoint_id = entry.get("checkpoint_id")
    source_value = entry.get("source")
    if not isinstance(checkpoint_id, str) or not checkpoint_id:
        raise ValueError("cleanup archive entry is missing checkpoint_id")
    if not isinstance(source_value, str) or not source_value:
        raise ValueError("cleanup archive entry is missing source")
    source = Path(source_value).expanduser().resolve()
    if source.parent != checkpoint_root:
        raise RuntimeError(f"Unsafe cleanup archive source: {source}")
    archive_file = (archive_path / source.name).resolve()
    if archive_file.parent != archive_path.resolve():
        raise RuntimeError(f"Unsafe cleanup archive target: {archive_file}")
    declared_archive_value = entry.get("archive_path")
    if isinstance(declared_archive_value, str) and declared_archive_value:
        declared_archive = Path(declared_archive_value).expanduser().resolve()
        if declared_archive != archive_file:
            raise RuntimeError(
                f"Cleanup archive target does not match manifest: {declared_archive}"
            )
    return {
        "checkpoint_id": checkpoint_id,
        "source": source,
        "archive_file": archive_file,
        "metadata": entry.get("metadata"),
    }


def archive_cleanup_candidates(
    manager: _RetentionManager,
    plan: dict[str, Any],
    *,
    metadata_to_manifest: Callable[[Any], dict[str, Any]],
) -> int:
    """Move reviewed candidates into a recoverable archive and update the index.

    The caller must hold the manager's checkpoint mutation lock.
    """

    manager._assert_checkpoint_generation_current()
    recovery_plan = plan.get("recovery_plan", {})
    archive_value = recovery_plan.get("archive_destination")
    if not isinstance(archive_value, str) or not archive_value:
        raise RuntimeError("Cleanup plan has no archive destination")
    archive_path = Path(archive_value).expanduser().resolve()
    checkpoint_root = manager.checkpoints_path.expanduser().resolve()
    if checkpoint_root not in archive_path.parents:
        raise RuntimeError("Checkpoint archive must remain below checkpoint storage")
    archive_path.mkdir(parents=True, exist_ok=False)

    manifest: dict[str, Any] = {
        "state": "planned",
        "generated_at": plan.get("generated_at"),
        "source": str(checkpoint_root),
        "archive": str(archive_path),
        "candidates": [],
        "moved": [],
    }
    for candidate in plan.get("candidates", []):
        source_value = candidate.get("path")
        checkpoint_id = candidate.get("checkpoint_id")
        if not isinstance(source_value, str) or not isinstance(checkpoint_id, str):
            continue
        source = Path(source_value).expanduser().resolve()
        if source.parent != checkpoint_root:
            raise RuntimeError(f"Unsafe checkpoint cleanup source: {source}")
        metadata = manager.checkpoint_index.get(checkpoint_id)
        if metadata is None:
            raise RuntimeError(
                f"Checkpoint cleanup index entry is missing: {checkpoint_id}"
            )
        manifest["candidates"].append(
            {
                "checkpoint_id": checkpoint_id,
                "source": str(source),
                "size_bytes": candidate.get("size_bytes", 0),
                "sha256": sha256_file(source),
                "metadata": metadata_to_manifest(metadata),
            }
        )

    manifest_path = archive_path / "manifest.json"
    write_json_atomic(manifest_path, manifest)
    original_index = dict(manager.checkpoint_index)
    index_committed = False
    try:
        for candidate in manifest["candidates"]:
            manager._assert_checkpoint_generation_current()
            source = Path(candidate["source"])
            target = archive_path / source.name
            if target.exists():
                raise FileExistsError(f"Archive target already exists: {target}")
            source.replace(target)
            manifest["moved"].append(
                {
                    **candidate,
                    "archive_path": str(target),
                }
            )
            manager.checkpoint_index.pop(candidate["checkpoint_id"], None)
        manager._assert_checkpoint_generation_current()
        manager._save_checkpoint_index_or_raise()
        index_committed = True
        manager.refresh_admission_counters()
        manifest["state"] = "completed"
        write_json_atomic(manifest_path, manifest)
    except Exception:
        if index_committed:
            # The file moves and reduced index are already durable. Do not put
            # data back merely because recording the terminal manifest failed.
            manifest["state"] = "completed"
            try:
                write_json_atomic(manifest_path, manifest)
            except Exception:
                logger.error(
                    "Unable to finalize committed checkpoint cleanup archive path=%s",
                    archive_path,
                    exc_info=True,
                )
        else:
            manager.checkpoint_index = original_index
            rollback_failed = False
            for moved in reversed(manifest["moved"]):
                source = Path(moved["source"])
                archive_file = Path(moved["archive_path"])
                try:
                    if archive_file.exists() and not source.exists():
                        archive_file.replace(source)
                    elif archive_file.exists() and source.exists():
                        raise RuntimeError(
                            "Both archive and checkpoint source exist for "
                            f"{source.name}"
                        )
                except Exception:
                    rollback_failed = True
                    logger.error(
                        "Unable to restore checkpoint cleanup archive source=%s",
                        source,
                        exc_info=True,
                    )
            manager.refresh_admission_counters()
            manifest["state"] = "partial" if rollback_failed else "rolled_back"
            try:
                write_json_atomic(manifest_path, manifest)
            except Exception:
                logger.error(
                    "Unable to record checkpoint cleanup rollback path=%s",
                    archive_path,
                    exc_info=True,
                )
        raise
    return len(manifest["moved"])


def enforce_automatic_retention(
    manager: _RetentionManager,
    *,
    reserve_auto_slots: int,
    is_auto_checkpoint: Callable[[Any], bool],
    metadata_to_manifest: Callable[[Any], dict[str, Any]],
) -> int:
    """Apply one atomic automatic-retention transaction under the mutation lock."""

    retention_started = time.perf_counter()
    plan = manager.plan_checkpoint_cleanup(
        max_auto_checkpoints=max(
            0,
            manager.config.max_auto_checkpoints - max(0, reserve_auto_slots),
        )
    )
    manager._assert_checkpoint_generation_current()
    checkpoint_root = manager.checkpoints_path.resolve()
    candidates: list[dict[str, Any]] = []
    for candidate in plan.get("candidates", []):
        checkpoint_id = candidate.get("checkpoint_id")
        source_value = candidate.get("path")
        if not isinstance(checkpoint_id, str) or not isinstance(source_value, str):
            continue
        metadata = manager.checkpoint_index.get(checkpoint_id)
        if metadata is None or not is_auto_checkpoint(metadata):
            continue
        source = Path(source_value).expanduser().resolve()
        if source.parent != checkpoint_root:
            raise RuntimeError(f"Unsafe automatic retention source: {source}")
        if not source.exists():
            continue
        candidates.append(
            {
                "checkpoint_id": checkpoint_id,
                "source": source,
                "metadata": metadata,
            }
        )

    if not candidates:
        manager._reconcile_checkpoint_storage()
        record_runtime_duration(
            "checkpoint.retention",
            (time.perf_counter() - retention_started) * 1000,
        )
        return 0

    transaction_root = manager.checkpoints_path / ".automatic-retention"
    transaction_root.mkdir(exist_ok=True)
    transaction_path = transaction_root / (
        f"txn-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex}"
    )
    transaction_path.mkdir()
    manifest_path = transaction_path / "manifest.json"
    manifest: dict[str, Any] = {
        "state": "planned",
        "created_at": datetime.now().isoformat(),
        "entries": [
            {
                "checkpoint_id": candidate["checkpoint_id"],
                "source": str(candidate["source"]),
                "quarantine": str(transaction_path / candidate["source"].name),
                "metadata": metadata_to_manifest(candidate["metadata"]),
            }
            for candidate in candidates
        ],
    }
    write_json_atomic(manifest_path, manifest)
    fsync_directory(transaction_root)

    original_index = dict(manager.checkpoint_index)
    moved: list[dict[str, Any]] = []
    index_committed = False
    try:
        for candidate, entry in zip(candidates, manifest["entries"]):
            manager._assert_checkpoint_generation_current()
            source = candidate["source"]
            quarantine = Path(entry["quarantine"])
            source.replace(quarantine)
            moved.append(entry)
        fsync_directory(manager.checkpoints_path)
        fsync_directory(transaction_path)

        for candidate in candidates:
            manager.checkpoint_index.pop(candidate["checkpoint_id"], None)
        manager._assert_checkpoint_generation_current()
        manager._save_checkpoint_index_or_raise()
        index_committed = True

        manifest["state"] = "committed"
        write_json_atomic(manifest_path, manifest)
        fsync_directory(transaction_path)
    except Exception:
        if not index_committed:
            manager.checkpoint_index = original_index
            for entry in reversed(moved):
                source = Path(entry["source"])
                quarantine = Path(entry["quarantine"])
                if quarantine.exists() and not source.exists():
                    quarantine.replace(source)
            fsync_directory(manager.checkpoints_path)
            try:
                manager._save_checkpoint_index_or_raise()
                shutil.rmtree(transaction_path)
            except Exception:
                # The planned manifest contains enough metadata for startup
                # recovery if the original index cannot be restored now.
                pass
        manager._reconcile_checkpoint_storage()
        raise

    # The reduced index is durable before quarantined data is removed. A crash
    # before this cleanup is recovered on the next manager startup.
    try:
        shutil.rmtree(transaction_path)
    except OSError:
        logger.warning(
            "Committed checkpoint retention awaits startup cleanup path=%s",
            transaction_path,
            exc_info=True,
        )
    try:
        transaction_root.rmdir()
    except OSError:
        pass
    fsync_directory(manager.checkpoints_path)
    manager._reconcile_checkpoint_storage()
    removed = len(candidates)
    if removed:
        logger.info(
            "Automatic checkpoint retention removed=%s remaining=%s bytes=%s",
            removed,
            len(manager.checkpoint_index),
            manager._checkpoint_bytes,
        )
    record_runtime_duration(
        "checkpoint.retention",
        (time.perf_counter() - retention_started) * 1000,
    )
    return removed


def sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for an archive manifest entry."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    """Write one JSON payload through a unique same-directory temporary file."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
        fsync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


def fsync_directory(path: Path) -> None:
    """Best-effort fsync of a directory after atomic rename/unlink operations."""

    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    except OSError:
        # Some filesystems do not expose directory fsync. The data files remain
        # atomically renamed; this only weakens crash durability on that platform.
        pass
    finally:
        os.close(descriptor)
