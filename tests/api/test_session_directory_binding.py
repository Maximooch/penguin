"""Tests for immutable session-to-directory binding."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from penguin.web.routes import _bind_session_directory


def test_session_directory_binding_is_immutable(tmp_path: Path):
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()

    core = SimpleNamespace(_opencode_session_directories={})
    sid = "session_immutable"

    bound = _bind_session_directory(core, sid, str(first))
    assert bound is not None
    assert Path(bound).resolve() == first.resolve()

    same = _bind_session_directory(core, sid, str(first))
    assert same is not None
    assert Path(same).resolve() == first.resolve()

    with pytest.raises(HTTPException) as exc:
        _bind_session_directory(core, sid, str(second))
    assert exc.value.status_code == 409


def test_session_directory_binding_uses_existing_when_directory_missing(tmp_path: Path):
    directory = tmp_path / "project"
    directory.mkdir()

    core = SimpleNamespace(_opencode_session_directories={})
    sid = "session_existing"

    _bind_session_directory(core, sid, str(directory))
    reused = _bind_session_directory(core, sid, None)
    assert reused is not None

    assert Path(reused).resolve() == directory.resolve()


def test_session_directory_binding_rejects_invalid_directory(tmp_path: Path):
    core = SimpleNamespace(_opencode_session_directories={})
    sid = "session_invalid"

    with pytest.raises(HTTPException) as exc:
        _bind_session_directory(core, sid, str(tmp_path / "missing"))
    assert exc.value.status_code == 400


def test_session_directory_binding_allows_equivalent_paths(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    target = tmp_path / "target"
    alias = tmp_path / "alias"
    target.mkdir()
    alias.symlink_to(target, target_is_directory=True)

    core = SimpleNamespace(_opencode_session_directories={})
    sid = "session_equivalent"

    # Simulate non-canonicalized inputs while still treating paths as the same inode.
    from penguin.web import routes as routes_module

    monkeypatch.setattr(routes_module, "normalize_directory", lambda value: value)

    first = _bind_session_directory(core, sid, str(alias))
    second = _bind_session_directory(core, sid, str(target))

    assert first == str(alias)
    assert second == str(alias)
