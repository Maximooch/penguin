"""Tests for checkpoint runtime helpers delegated to by PenguinCore."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from penguin.core_runtime.checkpoint_runtime import (
    get_checkpoint_stats,
    list_checkpoints,
)


class _ConversationManager:
    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []
        self.current_session = SimpleNamespace(id="session_current")
        self.checkpoint_manager = SimpleNamespace(
            config=SimpleNamespace(
                frequency=3,
                retention={"keep_all_hours": 12, "max_age_days": 7},
            )
        )
        self.checkpoints = [
            {"id": "cp_manual", "type": "manual", "auto": False},
            {"id": "cp_auto", "type": "auto", "auto": True},
            {"id": "cp_branch", "type": "branch", "auto": False},
        ]

    def get_current_session(self) -> SimpleNamespace:
        return self.current_session

    def list_checkpoints(
        self,
        *,
        session_id: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        self.calls.append({"session_id": session_id, "limit": limit})
        return self.checkpoints[:limit]


def test_list_checkpoints_defaults_to_current_session() -> None:
    manager = _ConversationManager()

    checkpoints = list_checkpoints(manager)

    assert [checkpoint["id"] for checkpoint in checkpoints] == [
        "cp_manual",
        "cp_auto",
        "cp_branch",
    ]
    assert manager.calls == [{"session_id": "session_current", "limit": 50}]


def test_list_checkpoints_preserves_explicit_session_and_limit() -> None:
    manager = _ConversationManager()

    checkpoints = list_checkpoints(manager, session_id="session_explicit", limit=2)

    assert [checkpoint["id"] for checkpoint in checkpoints] == [
        "cp_manual",
        "cp_auto",
    ]
    assert manager.calls == [{"session_id": "session_explicit", "limit": 2}]


def test_list_checkpoints_tolerates_current_session_without_id() -> None:
    manager = _ConversationManager()
    manager.current_session = SimpleNamespace()

    checkpoints = list_checkpoints(manager)

    assert [checkpoint["id"] for checkpoint in checkpoints] == [
        "cp_manual",
        "cp_auto",
        "cp_branch",
    ]
    assert manager.calls == [{"session_id": None, "limit": 50}]


def test_get_checkpoint_stats_counts_checkpoint_types() -> None:
    manager = _ConversationManager()

    stats = get_checkpoint_stats(manager)

    assert stats == {
        "enabled": True,
        "total_checkpoints": 3,
        "auto_checkpoints": 1,
        "manual_checkpoints": 1,
        "branch_checkpoints": 1,
        "config": {
            "frequency": 3,
            "retention_hours": 12,
            "max_age_days": 7,
        },
    }
    assert manager.calls == [{"session_id": None, "limit": 1000}]


def test_get_checkpoint_stats_tolerates_partial_retention_config() -> None:
    manager = _ConversationManager()
    manager.checkpoint_manager.config = SimpleNamespace(
        frequency=10,
        retention={"keep_all_hours": 6},
    )

    stats = get_checkpoint_stats(manager)

    assert stats["enabled"] is True
    assert stats["config"] == {
        "frequency": 10,
        "retention_hours": 6,
        "max_age_days": None,
    }


def test_get_checkpoint_stats_reports_disabled_without_checkpoint_manager() -> None:
    manager = _ConversationManager()
    manager.checkpoint_manager = None

    assert get_checkpoint_stats(manager) == {
        "enabled": False,
        "total_checkpoints": 0,
        "auto_checkpoints": 0,
        "manual_checkpoints": 0,
        "branch_checkpoints": 0,
    }
