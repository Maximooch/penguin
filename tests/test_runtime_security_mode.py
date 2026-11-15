"""A runtime security change reaches permission enforcement.

Covers SM-77: ``RuntimeConfig.set_security_mode`` and ``set_security_enabled``
notified the tool manager, which ignored both, so the API reported a new mode
or YOLO state while enforcement kept the one it was built with.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

import pytest

from penguin.security.permission_engine import PermissionResult
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def manager(monkeypatch: pytest.MonkeyPatch) -> ToolManager:
    monkeypatch.delenv("PENGUIN_YOLO", raising=False)
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    # A root change rescans the active root's file map; permissions ignore it.
    monkeypatch.setattr(manager, "_refresh_file_map", lambda: None)
    return manager


def _write(manager: ToolManager) -> PermissionResult | None:
    target = os.path.join(manager.workspace_root, "notes.txt")
    result, _reason = manager.check_tool_permission(
        "write_file", {"path": target, "content": "x"}
    )
    return result


def test_switching_to_read_only_denies_writes(manager: ToolManager) -> None:
    assert _write(manager) is PermissionResult.ALLOW

    manager.on_runtime_config_change("security_mode", "read_only")

    assert _write(manager) is PermissionResult.DENY


def test_the_workspace_boundary_follows_a_root_change(
    manager: ToolManager, tmp_path: Path
) -> None:
    target = {"path": str(tmp_path / "notes.txt"), "content": "x"}
    assert manager.check_tool_permission("write_file", target)[0] is not (
        PermissionResult.ALLOW
    )

    manager.on_runtime_config_change("workspace_root", str(tmp_path))

    assert manager.check_tool_permission("write_file", target)[0] is (
        PermissionResult.ALLOW
    )


def test_turning_checks_off_and_on_takes_effect(manager: ToolManager) -> None:
    manager.on_runtime_config_change("security_mode", "read_only")

    manager.on_runtime_config_change("security_enabled", False)
    assert _write(manager) is None

    manager.on_runtime_config_change("security_enabled", True)
    assert _write(manager) is PermissionResult.DENY
