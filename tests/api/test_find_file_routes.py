"""Tests for OpenCode-compatible find.file routes."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from typing import Any, cast

from fastapi import FastAPI
from fastapi.testclient import TestClient

from penguin.web import routes as routes_module


class _Core:
    def __init__(self, workspace: Path) -> None:
        root = str(workspace)
        self.runtime_config = SimpleNamespace(
            workspace_root=root,
            project_root=root,
            active_root=root,
        )
        self._opencode_session_directories: dict[str, str] = {}


def _clear_find_cache() -> None:
    with routes_module._FIND_FILE_INDEX_CACHE_LOCK:
        routes_module._FIND_FILE_INDEX_CACHE.clear()


def _build_client(core: _Core) -> TestClient:
    cast(Any, routes_module.router).core = cast(Any, core)
    app = FastAPI()
    app.include_router(routes_module.router)
    return TestClient(app)


def test_find_file_routes_resolve_files_and_alias_without_404(tmp_path: Path) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_routes"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    core = _Core(repo)
    with _build_client(core) as client:
        first = client.get(
            "/find/file",
            params={"directory": str(repo), "query": "readme"},
        )
        assert first.status_code == 200
        assert "README.md" in first.json()

        alias = client.get("/api/v1/find/file", params={"query": "readme"})
        assert alias.status_code == 200
        assert "README.md" in alias.json()


def test_find_file_empty_query_defaults_to_directories(tmp_path: Path) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_default_dirs"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "cmux").mkdir()
    (repo / "src").mkdir()

    core = _Core(repo)
    with _build_client(core) as client:
        response = client.get(
            "/find/file",
            params={"directory": str(repo), "query": ""},
        )
        assert response.status_code == 200
        data = response.json()
        assert "cmux/" in data
        assert "src/" in data
        assert "README.md" not in data
        assert all(isinstance(item, str) and item.endswith("/") for item in data)


def test_find_file_query_returns_files_and_dirs_and_type_filters(
    tmp_path: Path,
) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_filters"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")
    (repo / "src").mkdir()
    (repo / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")

    core = _Core(repo)
    with _build_client(core) as client:
        mixed = client.get(
            "/find/file",
            params={"directory": str(repo), "query": "src"},
        )
        assert mixed.status_code == 200
        mixed_data = mixed.json()
        assert "src/" in mixed_data
        assert "src/main.py" in mixed_data

        only_dirs = client.get(
            "/find/file",
            params={"directory": str(repo), "query": "src", "type": "directory"},
        )
        assert only_dirs.status_code == 200
        only_dirs_data = only_dirs.json()
        assert only_dirs_data
        assert "src/" in only_dirs_data
        assert "src/main.py" not in only_dirs_data
        assert all(item.endswith("/") for item in only_dirs_data)

        only_files = client.get(
            "/find/file",
            params={"directory": str(repo), "query": "src", "dirs": "false"},
        )
        assert only_files.status_code == 200
        only_files_data = only_files.json()
        assert only_files_data
        assert "src/main.py" in only_files_data
        assert "src/" not in only_files_data
        assert all(not item.endswith("/") for item in only_files_data)


def test_find_file_sorts_hidden_last_unless_query_targets_hidden(
    tmp_path: Path,
) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_hidden"
    repo.mkdir()
    (repo / "visible").mkdir()
    (repo / ".hidden").mkdir()
    (repo / ".hidden" / "secret.txt").write_text("x", encoding="utf-8")

    core = _Core(repo)
    with _build_client(core) as client:
        default_response = client.get(
            "/find/file",
            params={"directory": str(repo), "query": ""},
        )
        assert default_response.status_code == 200
        default_data = default_response.json()
        assert "visible/" in default_data
        assert ".hidden/" in default_data
        assert default_data.index("visible/") < default_data.index(".hidden/")

        hidden_response = client.get(
            "/find/file",
            params={"directory": str(repo), "query": ".hid"},
        )
        assert hidden_response.status_code == 200
        hidden_data = hidden_response.json()
        assert hidden_data
        assert hidden_data[0] == ".hidden/"


def test_find_file_uses_last_scoped_directory_fallback(tmp_path: Path) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_scope"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")

    core = _Core(repo)
    with _build_client(core) as client:
        scoped = client.get("/path", params={"directory": str(repo)})
        assert scoped.status_code == 200

        fallback = client.get("/find/file", params={"query": "readme"})
        assert fallback.status_code == 200
        assert "README.md" in fallback.json()


def test_find_file_uses_session_directory_request_for_fallback(tmp_path: Path) -> None:
    _clear_find_cache()
    repo = tmp_path / "repo_find_session_scope"
    repo.mkdir()
    (repo / "README.md").write_text("hello", encoding="utf-8")

    core = _Core(repo)
    with _build_client(core) as client:
        session_list = client.get(
            "/session",
            params={"directory": str(repo), "limit": 50},
        )
        assert session_list.status_code == 200

        fallback = client.get("/find/file", params={"query": "readme"})
        assert fallback.status_code == 200
        assert "README.md" in fallback.json()
