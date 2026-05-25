"""Tests for small core state helper delegation."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core_runtime import core_state


def test_validate_path_creates_directory_and_checks_writable(tmp_path) -> None:
    created = tmp_path / "new" / "workspace"
    checked: list[Any] = []

    core_state.validate_path(
        created,
        access_check=lambda path, mode: checked.append((path, mode)) or True,
    )

    assert created.is_dir()
    assert checked == [(created, 2)]


def test_validate_path_rejects_non_writable_path(tmp_path) -> None:
    with pytest.raises(PermissionError, match="No write access"):
        core_state.validate_path(
            tmp_path,
            access_check=lambda _path, _mode: False,
        )


def test_progress_callbacks_run_in_registration_order() -> None:
    calls: list[tuple[str, int, int, str | None]] = []
    core = SimpleNamespace(progress_callbacks=[])

    core_state.register_progress_callback(
        core,
        lambda iteration, maximum, message: calls.append(
            ("first", iteration, maximum, message)
        ),
    )
    core_state.register_progress_callback(
        core,
        lambda iteration, maximum, message: calls.append(
            ("second", iteration, maximum, message)
        ),
    )

    core_state.notify_progress(core, 2, 5, "working")

    assert calls == [
        ("first", 2, 5, "working"),
        ("second", 2, 5, "working"),
    ]


def test_reset_context_resets_diagnostics_interrupt_and_conversation() -> None:
    calls: list[str] = []
    core = SimpleNamespace(
        _interrupted=True,
        conversation_manager=SimpleNamespace(
            reset=lambda: calls.append("conversation")
        ),
    )
    diagnostics = SimpleNamespace(reset=lambda: calls.append("diagnostics"))

    core_state.reset_context(core, diagnostics_manager=diagnostics)

    assert core._interrupted is False
    assert calls == ["diagnostics", "conversation"]


def test_reset_state_resets_context_and_schedules_external_cleanup() -> None:
    calls: list[str] = []
    core = SimpleNamespace(
        _interrupted=True,
        conversation_manager=SimpleNamespace(
            reset=lambda: calls.append("conversation")
        ),
    )
    diagnostics = SimpleNamespace(reset=lambda: calls.append("diagnostics"))

    core_state.reset_state(
        core,
        diagnostics_manager=diagnostics,
        schedule_browser_close=lambda: calls.append("browser"),
    )

    assert core._interrupted is False
    assert calls == ["diagnostics", "conversation", "browser"]


def test_context_file_and_snapshot_helpers_delegate_to_conversation_manager() -> None:
    calls: list[tuple[str, Any]] = []

    class _ConversationManager:
        def list_context_files(self) -> list[dict[str, str]]:
            calls.append(("list", None))
            return [{"path": "README.md"}]

        def create_snapshot(self, *, meta: dict[str, Any] | None = None) -> str:
            calls.append(("create", meta))
            return "snapshot_1"

        def restore_snapshot(self, snapshot_id: str) -> bool:
            calls.append(("restore", snapshot_id))
            return True

        def branch_from_snapshot(
            self,
            snapshot_id: str,
            *,
            meta: dict[str, Any] | None = None,
        ) -> str:
            calls.append(("branch", (snapshot_id, meta)))
            return "snapshot_branch"

    core = SimpleNamespace(conversation_manager=_ConversationManager())

    assert core_state.list_context_files(core) == [{"path": "README.md"}]
    assert core_state.create_snapshot(core, meta={"name": "save"}) == "snapshot_1"
    assert core_state.restore_snapshot(core, "snapshot_1") is True
    assert (
        core_state.branch_from_snapshot(core, "snapshot_1", meta={"name": "branch"})
        == "snapshot_branch"
    )
    assert calls == [
        ("list", None),
        ("create", {"name": "save"}),
        ("restore", "snapshot_1"),
        ("branch", ("snapshot_1", {"name": "branch"})),
    ]
