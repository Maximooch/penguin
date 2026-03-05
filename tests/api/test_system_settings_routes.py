"""Tests for Penguin system settings route helpers."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

import pytest

from penguin.web.routes import get_system_settings


class _Runtime:
    def __init__(self, root: Path) -> None:
        resolved = str(root.resolve())
        self.project_root = resolved
        self.workspace_root = resolved
        self.execution_mode = "project"
        self.active_root = resolved

    def to_dict(self) -> dict[str, Any]:
        return {
            "project_root": self.project_root,
            "workspace_root": self.workspace_root,
            "execution_mode": self.execution_mode,
            "active_root": self.active_root,
        }


class _Core:
    def __init__(self, root: Path) -> None:
        resolved = str(root.resolve())
        self.runtime_config = _Runtime(root)
        self._opencode_session_directories: dict[str, str] = {}
        self.conversation_manager = SimpleNamespace(
            session_manager=SimpleNamespace(sessions={}, session_index={}),
            agent_session_managers={},
        )
        self.model_config = SimpleNamespace(model="openai/gpt-5", provider="openai")


@pytest.mark.asyncio
async def test_get_system_settings_returns_runtime_and_paths(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    payload = await get_system_settings(core=typed_core)

    assert payload["status"] == "success"
    settings = payload["settings"]
    runtime = settings["runtime"]
    assert runtime["execution_mode"] == "project"
    assert runtime["active_root"] == str(tmp_path.resolve())

    locations = settings["locations"]
    project = locations["project"]
    global_config = locations["global"]["config"]

    assert project["root"] == str(tmp_path.resolve())
    assert project["local"]["path"].endswith(".penguin/settings.local.yml")
    assert project["config"]["path"].endswith(".penguin/config.yml")
    assert global_config["path"].endswith("penguin/config.yml")


@pytest.mark.asyncio
async def test_get_system_settings_uses_session_directory_git_root(
    tmp_path: Path,
) -> None:
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / ".git").mkdir()
    session_dir = repo / "src"
    session_dir.mkdir()

    core = _Core(tmp_path)
    core._opencode_session_directories["session_1"] = str(session_dir.resolve())
    typed_core = cast(Any, core)

    payload = await get_system_settings(core=typed_core, session_id="session_1")

    project = payload["settings"]["locations"]["project"]
    assert project["root"] == str(repo.resolve())
    assert project["dir"] == str((repo / ".penguin").resolve())
