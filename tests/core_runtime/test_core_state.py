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
