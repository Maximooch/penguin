"""Every holder of the active file root agrees after any root or mode change.

Covers SM-57: RuntimeConfig set PENGUIN_CWD to the project root even in
workspace mode and never updated it for a workspace change, and the tool
manager left its notebook executor in the old directory when a root changed.
"""

from __future__ import annotations

import os
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from penguin.config import RuntimeConfig
from penguin.tools.tool_manager import ToolManager

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture
def roots(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    paths = {name: tmp_path / name for name in ("project", "workspace", "other")}
    for path in paths.values():
        path.mkdir()
    monkeypatch.setenv("PENGUIN_PROJECT_ROOT", str(paths["project"]))
    monkeypatch.setenv("PENGUIN_CWD", str(paths["project"]))
    monkeypatch.setenv("PENGUIN_WRITE_ROOT", "project")
    return {name: path.resolve() for name, path in paths.items()}


def _runtime(roots: dict[str, Path]) -> RuntimeConfig:
    runtime = RuntimeConfig({"workspace_path": str(roots["workspace"])})
    runtime.set_workspace_root(str(roots["workspace"]))
    runtime.set_execution_mode("workspace")
    return runtime


def test_a_project_root_change_in_workspace_mode_keeps_the_workspace_active(
    roots: dict[str, Path],
) -> None:
    runtime = _runtime(roots)

    runtime.set_project_root(str(roots["other"]))

    assert os.environ["PENGUIN_CWD"] == runtime.active_root == str(roots["workspace"])


def test_a_workspace_root_change_moves_the_active_root(
    roots: dict[str, Path],
) -> None:
    runtime = _runtime(roots)

    runtime.set_workspace_root(str(roots["other"]))

    assert os.environ["PENGUIN_CWD"] == runtime.active_root == str(roots["other"])


def test_the_notebook_follows_a_project_root_change(
    roots: dict[str, Path], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("PENGUIN_YOLO", "1")
    manager = ToolManager({}, lambda *_args: None, fast_startup=True)
    manager.set_execution_root("project")
    manager._notebook_executor = SimpleNamespace(active_directory=manager._file_root)
    manager._lazy_initialized["notebook_executor"] = True

    manager.on_runtime_config_change("project_root", str(roots["other"]))

    assert manager._file_root == str(roots["other"])
    assert manager._notebook_executor.active_directory == str(roots["other"])
