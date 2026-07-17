"""Deterministic storage safety-floor tests."""

from __future__ import annotations

from typing import TYPE_CHECKING

from penguin.system.storage_safety import (
    DiskUsage,
    StorageSafetyLevel,
    StorageSafetyPolicy,
    evaluate_storage_safety,
)

if TYPE_CHECKING:
    from pathlib import Path

POLICY = StorageSafetyPolicy(
    warning_free_bytes=200,
    critical_free_bytes=100,
    warning_free_fraction=0.20,
    critical_free_fraction=0.10,
    max_checkpoint_bytes=500,
)


def test_storage_safety_is_critical_before_enospc(tmp_path: Path) -> None:
    """Crossing either critical free-space floor blocks background writes."""

    status = evaluate_storage_safety(
        tmp_path,
        policy=POLICY,
        disk_usage=DiskUsage(total=1_000, used=950, free=50),
        checkpoint_bytes=100,
    )

    assert status.level is StorageSafetyLevel.CRITICAL
    assert status.allow_background_writes is False
    assert "free_bytes_below_critical" in status.reasons
    assert "free_fraction_below_critical" in status.reasons


def test_checkpoint_growth_limit_blocks_even_with_free_disk(tmp_path: Path) -> None:
    """Checkpoint growth has its own deterministic safety ceiling."""

    status = evaluate_storage_safety(
        tmp_path,
        policy=POLICY,
        disk_usage=DiskUsage(total=10_000, used=1_000, free=9_000),
        checkpoint_bytes=501,
    )

    assert status.level is StorageSafetyLevel.CRITICAL
    assert status.allow_background_writes is False
    assert status.reasons == ("checkpoint_bytes_above_limit",)


def test_storage_warning_is_visible_but_does_not_block(tmp_path: Path) -> None:
    """Warning thresholds surface pressure before the critical floor."""

    status = evaluate_storage_safety(
        tmp_path,
        policy=POLICY,
        disk_usage=DiskUsage(total=1_000, used=850, free=150),
        checkpoint_bytes=100,
    )

    assert status.level is StorageSafetyLevel.WARNING
    assert status.allow_background_writes is True
    assert status.reasons == (
        "free_bytes_below_warning",
        "free_fraction_below_warning",
    )


def test_healthy_storage_reports_capacity_and_checkpoint_usage(
    tmp_path: Path,
) -> None:
    """Healthy status retains exact evidence for diagnostics."""

    status = evaluate_storage_safety(
        tmp_path,
        policy=POLICY,
        disk_usage=DiskUsage(total=1_000, used=100, free=900),
        checkpoint_bytes=123,
    )

    assert status.level is StorageSafetyLevel.HEALTHY
    assert status.allow_background_writes is True
    assert status.free_fraction == 0.9
    assert status.checkpoint_bytes == 123
    assert status.to_dict()["policy"]["critical_free_bytes"] == 100
