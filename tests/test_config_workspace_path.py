"""Tests for workspace path fallback behavior in config loading."""

from __future__ import annotations

import importlib
from pathlib import Path

import yaml

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


def test_explicit_skipped_model_config_does_not_inherit_default_model(
    monkeypatch, tmp_path: Path
) -> None:
    config_path = tmp_path / "config.yml"
    workspace = tmp_path / "workspace"
    config_path.write_text(
        yaml.safe_dump({"workspace": {"path": str(workspace)}, "model": None}),
        encoding="utf-8",
    )
    monkeypatch.setenv("PENGUIN_CONFIG_PATH", str(config_path))
    monkeypatch.delenv("PENGUIN_DEFAULT_MODEL", raising=False)
    monkeypatch.delenv("PENGUIN_DEFAULT_PROVIDER", raising=False)
    monkeypatch.delenv("PENGUIN_WORKSPACE", raising=False)

    cfg = config_module.Config.load_config()

    assert cfg.workspace_path == workspace
    assert cfg.model_config.model == ""
    assert cfg.model_config.provider == ""
