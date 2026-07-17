"""Production checkpoint admission safety tests."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import TYPE_CHECKING

import pytest

from penguin.system.checkpoint_manager import (
    CheckpointConfig,
    CheckpointManager,
    CheckpointMetadata,
    CheckpointType,
)
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.storage_safety import (
    DiskUsage,
    StorageSafetyMonitor,
    StorageSafetyPolicy,
)

if TYPE_CHECKING:
    from pathlib import Path


class _SessionManager:
    """Minimal session collaborator for checkpoint admission tests."""

    def __init__(self) -> None:
        self.session_index: dict[str, object] = {}
        self.current_session: Session | None = None


def _message() -> Message:
    """Return one eligible user message."""

    return Message(
        role="user",
        content="preserve this active conversation",
        category=MessageCategory.DIALOG,
    )


@pytest.mark.asyncio
async def test_auto_checkpoint_cap_blocks_new_write_after_maintenance(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The configured count ceiling is admission control, not cleanup advice."""

    monitor = StorageSafetyMonitor(
        tmp_path,
        policy=StorageSafetyPolicy(
            warning_free_bytes=10,
            critical_free_bytes=5,
            warning_free_fraction=0.01,
            critical_free_fraction=0.001,
            max_checkpoint_bytes=None,
        ),
        disk_usage_provider=lambda _path: DiskUsage(
            total=10_000,
            used=100,
            free=9_900,
        ),
    )
    session_manager = _SessionManager()
    manager = CheckpointManager(
        tmp_path,
        session_manager,
        CheckpointConfig(max_auto_checkpoints=1),
        storage_safety_monitor=monitor,
    )
    existing_path = manager.checkpoints_path / "existing.json.gz"
    existing_path.write_bytes(b"existing")
    manager.checkpoint_index["existing"] = CheckpointMetadata(
        id="existing",
        type=CheckpointType.AUTO,
        created_at="2026-07-10T00:00:00",
        session_id="session",
        message_id="message",
        message_count=1,
    )
    manager.refresh_admission_counters()
    session = Session(id="session")
    session_manager.current_session = session
    message = _message()
    session.add_message(message)

    with caplog.at_level(logging.WARNING, logger="penguin.system.checkpoint_manager"):
        checkpoint_id = await manager.create_checkpoint(session, message)

    assert checkpoint_id is None
    assert manager._workers_started is True
    assert manager.checkpoint_queue is not None
    assert manager.get_storage_safety_status()["block_reason"] == (
        "max_auto_checkpoints"
    )
    assert any(
        "Automatic checkpoint blocked" in record.message for record in caplog.records
    )
    await manager.stop_workers()


@pytest.mark.asyncio
async def test_critical_disk_floor_blocks_background_checkpoint_only(
    tmp_path: Path,
) -> None:
    """Disk pressure blocks auto work while leaving the in-memory session intact."""

    policy = StorageSafetyPolicy(
        warning_free_bytes=200,
        critical_free_bytes=100,
        warning_free_fraction=0.20,
        critical_free_fraction=0.10,
        max_checkpoint_bytes=None,
    )
    monitor = StorageSafetyMonitor(
        tmp_path,
        policy=policy,
        disk_usage_provider=lambda _path: DiskUsage(total=1_000, used=950, free=50),
    )
    manager = CheckpointManager(
        tmp_path,
        _SessionManager(),
        CheckpointConfig(max_auto_checkpoints=1000),
        storage_safety_monitor=monitor,
    )
    session = Session()
    message = _message()
    session.add_message(message)

    checkpoint_id = await manager.create_checkpoint(session, message)

    assert checkpoint_id is None
    assert session.messages[-1].content == "preserve this active conversation"
    status = manager.get_storage_safety_status()
    assert status["allow_background_writes"] is False
    assert status["block_reason"] == "storage_critical"
    assert status["reasons"] == [
        "free_bytes_below_critical",
        "free_fraction_below_critical",
    ]


@pytest.mark.asyncio
async def test_manager_cleanup_plan_defaults_to_read_only(tmp_path: Path) -> None:
    """Manager cleanup planning never deletes its source checkpoint."""

    manager = CheckpointManager(tmp_path, _SessionManager(), CheckpointConfig())
    checkpoint_id = "old-auto"
    checkpoint_file = manager.checkpoints_path / f"{checkpoint_id}.json.gz"
    checkpoint_file.write_bytes(b"checkpoint")
    manager.checkpoint_index[checkpoint_id] = CheckpointMetadata(
        id=checkpoint_id,
        type=CheckpointType.AUTO,
        created_at="2020-01-01T00:00:00",
        session_id="inactive",
        message_id="message",
        message_count=1,
    )
    manager.refresh_admission_counters()

    plan = manager.plan_checkpoint_cleanup(
        now=datetime(2026, 7, 10, tzinfo=timezone.utc)
    )

    assert plan["dry_run"] is True
    assert plan["candidate_count"] == 1
    assert checkpoint_file.read_bytes() == b"checkpoint"

    default_result = await manager.cleanup_old_checkpoints()
    assert default_result["status"] == "dry_run"
    assert checkpoint_file.read_bytes() == b"checkpoint"

    with pytest.raises(PermissionError, match="resolved workspace path"):
        await manager.cleanup_old_checkpoints(execute=True)
    assert checkpoint_file.read_bytes() == b"checkpoint"
