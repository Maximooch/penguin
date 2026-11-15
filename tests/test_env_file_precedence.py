"""Keys exported in the shell win over .env files; the project file beats the user's.

Covers SM-71: the project .env was loaded with ``override=True``, so it
replaced keys the user had exported in the shell for that run.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING

from penguin import config as config_module

if TYPE_CHECKING:
    from pathlib import Path

    import pytest


def test_shell_then_project_then_user_env(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    project_env = tmp_path / "project" / ".env"
    project_env.parent.mkdir()
    project_env.write_text("SM71_FOO=project\nSM71_BAR=project\n")
    user_env = tmp_path / "xdg" / "penguin" / ".env"
    user_env.parent.mkdir(parents=True)
    user_env.write_text("SM71_BAR=user\nSM71_BAZ=user\n")

    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "xdg"))
    monkeypatch.setenv("SM71_FOO", "shell")
    for name in ("SM71_BAR", "SM71_BAZ"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setattr(config_module, "_env_loaded", False)
    monkeypatch.setattr(
        config_module, "find_dotenv", lambda *_a, **_k: str(project_env), raising=False
    )
    monkeypatch.setattr("dotenv.main.find_dotenv", lambda *_a, **_k: str(project_env))

    try:
        config_module._ensure_env_loaded()

        assert os.environ["SM71_FOO"] == "shell"
        assert os.environ["SM71_BAR"] == "project"
        assert os.environ["SM71_BAZ"] == "user"
    finally:
        for name in ("SM71_BAR", "SM71_BAZ"):
            os.environ.pop(name, None)
