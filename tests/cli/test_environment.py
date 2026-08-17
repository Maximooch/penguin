"""Tests for isolated CLI path and environment normalization."""

from __future__ import annotations

import os
from pathlib import Path

from penguin.cli.environment import preconfigure_cli_environment


def test_preconfigure_environment_is_repeatable(tmp_path: Path, monkeypatch) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.chdir(tmp_path)

    first = preconfigure_cli_environment(
        workspace, None, "workspace", default_workspace=tmp_path / "unused"
    )
    second = preconfigure_cli_environment(
        workspace, None, "workspace", default_workspace=tmp_path / "unused"
    )

    assert first == second == (None, workspace.resolve())
    assert os.environ["PENGUIN_CWD"] == str(workspace.resolve())
    assert os.environ["PENGUIN_WRITE_ROOT"] == "workspace"


def test_preconfigure_environment_resolves_managed_project(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    project = workspace / "projects" / "demo"
    project.mkdir(parents=True)
    monkeypatch.chdir(tmp_path)

    resolved_project, resolved_workspace = preconfigure_cli_environment(
        workspace, "demo", "project", default_workspace=tmp_path / "unused"
    )

    assert resolved_project == project.resolve()
    assert resolved_workspace == workspace.resolve()
    assert os.environ["PENGUIN_PROJECT_ROOT"] == str(project.resolve())
    assert os.environ["PENGUIN_CWD"] == str(project.resolve())


def test_preconfigure_environment_clears_stale_project(
    tmp_path: Path, monkeypatch
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("PENGUIN_PROJECT_ROOT", str(tmp_path / "stale"))
    monkeypatch.chdir(tmp_path)

    resolved_project, _ = preconfigure_cli_environment(
        workspace, None, None, default_workspace=tmp_path / "unused"
    )

    assert resolved_project is None
    assert "PENGUIN_PROJECT_ROOT" not in os.environ
