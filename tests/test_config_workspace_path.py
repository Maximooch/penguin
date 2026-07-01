"""Tests for workspace path fallback behavior in config loading."""

from __future__ import annotations

import importlib
from pathlib import Path

config_module = importlib.import_module("penguin.config")


def test_workspace_path_from_config_data_falls_back_when_not_writable(
    tmp_path,
    monkeypatch,
) -> None:
    configured = tmp_path / "configured"
    configured.mkdir()
    fallback = tmp_path / "fallback"
    monkeypatch.delenv("PENGUIN_WORKSPACE", raising=False)
    monkeypatch.setattr(config_module, "WORKSPACE_PATH", fallback)

    def fake_access(path: object, _mode: int) -> bool:
        return Path(path) != configured

    monkeypatch.setattr(config_module.os, "access", fake_access)

    resolved = config_module._workspace_path_from_config_data(
        {"workspace": {"path": str(configured)}}
    )

    assert resolved == fallback
    assert fallback.exists()
