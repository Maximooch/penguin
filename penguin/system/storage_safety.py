"""Deterministic storage pressure policy for background Penguin writes."""

from __future__ import annotations

import os
import shutil
import time
from dataclasses import asdict, dataclass
from enum import Enum
from pathlib import Path
from typing import Callable, Mapping

__all__ = [
    "DiskUsage",
    "StorageSafetyLevel",
    "StorageSafetyMonitor",
    "StorageSafetyPolicy",
    "StorageSafetyStatus",
    "evaluate_storage_safety",
    "storage_safety_policy_from_env",
]

GIB = 1024 * 1024 * 1024
DEFAULT_WARNING_FREE_BYTES = 5 * GIB
DEFAULT_CRITICAL_FREE_BYTES = 2 * GIB
DEFAULT_WARNING_FREE_FRACTION = 0.10
DEFAULT_CRITICAL_FREE_FRACTION = 0.05
DEFAULT_MAX_CHECKPOINT_BYTES = 5 * GIB
DEFAULT_PROBE_INTERVAL_SECONDS = 30.0


class StorageSafetyLevel(str, Enum):
    """Storage health level used by runtime diagnostics."""

    HEALTHY = "healthy"
    WARNING = "warning"
    CRITICAL = "critical"


@dataclass(frozen=True)
class DiskUsage:
    """Portable disk usage values in bytes."""

    total: int
    used: int
    free: int


@dataclass(frozen=True)
class StorageSafetyPolicy:
    """Warning and critical floors for background persistence."""

    warning_free_bytes: int = DEFAULT_WARNING_FREE_BYTES
    critical_free_bytes: int = DEFAULT_CRITICAL_FREE_BYTES
    warning_free_fraction: float = DEFAULT_WARNING_FREE_FRACTION
    critical_free_fraction: float = DEFAULT_CRITICAL_FREE_FRACTION
    max_checkpoint_bytes: int | None = DEFAULT_MAX_CHECKPOINT_BYTES


@dataclass(frozen=True)
class StorageSafetyStatus:
    """One evidence-bearing storage safety evaluation."""

    root: Path
    level: StorageSafetyLevel
    allow_background_writes: bool
    total_bytes: int
    used_bytes: int
    free_bytes: int
    free_fraction: float
    checkpoint_bytes: int | None
    reasons: tuple[str, ...]
    policy: StorageSafetyPolicy

    def to_dict(self) -> dict[str, object]:
        """Return a JSON-serializable diagnostics payload."""

        return {
            "root": str(self.root),
            "level": self.level.value,
            "allow_background_writes": self.allow_background_writes,
            "total_bytes": self.total_bytes,
            "used_bytes": self.used_bytes,
            "free_bytes": self.free_bytes,
            "free_fraction": self.free_fraction,
            "checkpoint_bytes": self.checkpoint_bytes,
            "reasons": list(self.reasons),
            "policy": asdict(self.policy),
        }


def evaluate_storage_safety(
    root: str | Path,
    *,
    policy: StorageSafetyPolicy,
    disk_usage: DiskUsage,
    checkpoint_bytes: int | None = None,
) -> StorageSafetyStatus:
    """Evaluate storage evidence against deterministic warning/critical floors.

    Args:
        root: Filesystem root being evaluated.
        policy: Configured safety thresholds.
        disk_usage: Current total, used, and free bytes.
        checkpoint_bytes: Optional current checkpoint directory size.

    Returns:
        Evidence-bearing safety status. Critical status blocks only background
        writes; callers remain responsible for surfacing active user-write errors.
    """

    free_fraction = disk_usage.free / disk_usage.total if disk_usage.total > 0 else 0.0
    critical_reasons: list[str] = []
    if disk_usage.free < policy.critical_free_bytes:
        critical_reasons.append("free_bytes_below_critical")
    if free_fraction < policy.critical_free_fraction:
        critical_reasons.append("free_fraction_below_critical")
    if (
        checkpoint_bytes is not None
        and policy.max_checkpoint_bytes is not None
        and checkpoint_bytes > policy.max_checkpoint_bytes
    ):
        critical_reasons.append("checkpoint_bytes_above_limit")

    if critical_reasons:
        level = StorageSafetyLevel.CRITICAL
        reasons = tuple(critical_reasons)
    else:
        warning_reasons: list[str] = []
        if disk_usage.free < policy.warning_free_bytes:
            warning_reasons.append("free_bytes_below_warning")
        if free_fraction < policy.warning_free_fraction:
            warning_reasons.append("free_fraction_below_warning")
        if warning_reasons:
            level = StorageSafetyLevel.WARNING
            reasons = tuple(warning_reasons)
        else:
            level = StorageSafetyLevel.HEALTHY
            reasons = ()

    return StorageSafetyStatus(
        root=Path(root).expanduser().resolve(),
        level=level,
        allow_background_writes=level is not StorageSafetyLevel.CRITICAL,
        total_bytes=disk_usage.total,
        used_bytes=disk_usage.used,
        free_bytes=disk_usage.free,
        free_fraction=free_fraction,
        checkpoint_bytes=checkpoint_bytes,
        reasons=reasons,
        policy=policy,
    )


def storage_safety_policy_from_env(
    environ: Mapping[str, str] | None = None,
) -> StorageSafetyPolicy:
    """Build a storage safety policy from environment overrides."""

    env = os.environ if environ is None else environ
    return StorageSafetyPolicy(
        warning_free_bytes=_env_int(
            env,
            "PENGUIN_STORAGE_WARNING_FREE_BYTES",
            DEFAULT_WARNING_FREE_BYTES,
        ),
        critical_free_bytes=_env_int(
            env,
            "PENGUIN_STORAGE_CRITICAL_FREE_BYTES",
            DEFAULT_CRITICAL_FREE_BYTES,
        ),
        warning_free_fraction=_env_float(
            env,
            "PENGUIN_STORAGE_WARNING_FREE_FRACTION",
            DEFAULT_WARNING_FREE_FRACTION,
        ),
        critical_free_fraction=_env_float(
            env,
            "PENGUIN_STORAGE_CRITICAL_FREE_FRACTION",
            DEFAULT_CRITICAL_FREE_FRACTION,
        ),
        max_checkpoint_bytes=_env_optional_int(
            env,
            "PENGUIN_CHECKPOINT_MAX_BYTES",
            DEFAULT_MAX_CHECKPOINT_BYTES,
        ),
    )


class StorageSafetyMonitor:
    """Cached filesystem probe for background-write admission decisions."""

    def __init__(
        self,
        root: str | Path,
        *,
        checkpoint_path: str | Path | None = None,
        policy: StorageSafetyPolicy | None = None,
        probe_interval_seconds: float = DEFAULT_PROBE_INTERVAL_SECONDS,
        disk_usage_provider: Callable[[Path], DiskUsage] | None = None,
        monotonic: Callable[[], float] = time.monotonic,
    ) -> None:
        """Initialize a monitor without probing the filesystem."""

        self.root = Path(root).expanduser().resolve()
        self.checkpoint_path = (
            Path(checkpoint_path).expanduser().resolve()
            if checkpoint_path is not None
            else None
        )
        self.policy = policy or storage_safety_policy_from_env()
        self.probe_interval_seconds = max(0.0, probe_interval_seconds)
        self._disk_usage_provider = disk_usage_provider or _read_disk_usage
        self._monotonic = monotonic
        self._last_checked_at = float("-inf")
        self._last_status: StorageSafetyStatus | None = None

    @property
    def last_status(self) -> StorageSafetyStatus | None:
        """Return the most recent status without triggering a probe."""

        return self._last_status

    def check(
        self,
        *,
        force: bool = False,
        checkpoint_bytes: int | None = None,
    ) -> StorageSafetyStatus:
        """Return a cached or freshly measured storage status."""

        now = self._monotonic()
        if (
            not force
            and self._last_status is not None
            and now - self._last_checked_at < self.probe_interval_seconds
        ):
            return self._last_status

        measured_checkpoint_bytes = checkpoint_bytes
        if measured_checkpoint_bytes is None and self.checkpoint_path is not None:
            measured_checkpoint_bytes = _directory_size(self.checkpoint_path)
        status = evaluate_storage_safety(
            self.root,
            policy=self.policy,
            disk_usage=self._disk_usage_provider(self.root),
            checkpoint_bytes=measured_checkpoint_bytes,
        )
        self._last_checked_at = now
        self._last_status = status
        return status


def _read_disk_usage(root: Path) -> DiskUsage:
    """Read disk usage for ``root`` using the standard library."""

    usage = shutil.disk_usage(root)
    return DiskUsage(total=usage.total, used=usage.used, free=usage.free)


def _directory_size(path: Path) -> int:
    """Return total regular-file bytes below ``path``, tolerating races."""

    total = 0
    if not path.exists():
        return total
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def _env_int(environ: Mapping[str, str], name: str, default: int) -> int:
    """Read a positive integer environment value."""

    try:
        value = int(environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if value >= 0 else default


def _env_optional_int(
    environ: Mapping[str, str], name: str, default: int | None
) -> int | None:
    """Read a positive integer or disable a ceiling with a non-positive value."""

    raw = environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return default
    return value if value > 0 else None


def _env_float(environ: Mapping[str, str], name: str, default: float) -> float:
    """Read a fractional environment value between zero and one."""

    try:
        value = float(environ.get(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if 0.0 <= value <= 1.0 else default
