"""Regression tests for Penguin TUI launcher bootstrap and startup flow."""

from __future__ import annotations

import io
import subprocess
import tarfile
import zipfile
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from penguin.cli import opencode_launcher

if TYPE_CHECKING:
    from pathlib import Path


class _FakeProcess:
    def __init__(self, *, running: bool = True) -> None:
        self._running = running
        self.terminated = False
        self.killed = False

    def poll(self) -> int | None:
        return None if self._running else 1

    def terminate(self) -> None:
        self.terminated = True
        self._running = False

    def wait(self, timeout: float | None = None) -> int:
        del timeout
        self._running = False
        return 0

    def kill(self) -> None:
        self.killed = True
        self._running = False


def _build_archive_bytes(asset_name: str, binary_name: str) -> bytes:
    if asset_name.endswith(".zip"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(binary_name, "#!/bin/sh\necho sidecar\n")
        return buf.getvalue()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        payload = b"#!/bin/sh\necho sidecar\n"
        info = tarfile.TarInfo(name=binary_name)
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


def test_default_release_url_points_to_penguin_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    assert (
        opencode_launcher._sidecar_release_url()
        == "https://api.github.com/repos/Maximooch/penguin/releases/latest"
    )


def test_sidecar_release_url_for_version_uses_tag_endpoint() -> None:
    assert opencode_launcher._sidecar_release_url_for_version("0.6.0") == (
        "https://api.github.com/repos/Maximooch/penguin/releases/tags/v0.6.0"
    )


def test_installed_penguin_version_falls_back_to_package_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _missing(_name: str) -> str:
        raise opencode_launcher.importlib.metadata.PackageNotFoundError

    monkeypatch.setattr(opencode_launcher.importlib.metadata, "version", _missing)

    assert opencode_launcher._installed_penguin_version() == "0.6.2.2"


def test_binary_supports_url_mode_from_help_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = getattr(opencode_launcher, "_URL_MODE_CAP_CACHE")
    cache.clear()

    def _run(*args, **kwargs):  # type: ignore[no-untyped-def]
        del args, kwargs
        return subprocess.CompletedProcess(
            args=["opencode", "--help"],
            returncode=0,
            stdout="... --url penguin web server url ...",
            stderr="",
        )

    monkeypatch.setattr(opencode_launcher.subprocess, "run", _run)

    supports = getattr(opencode_launcher, "_binary_supports_url_mode")
    assert supports("/tmp/opencode") is True


def test_build_command_uses_sidecar_when_local_source_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    sidecar_bin = tmp_path / opencode_launcher._sidecar_binary_name()
    sidecar_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(opencode_launcher, "_find_local_opencode_dir", lambda: None)
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        opencode_launcher, "_resolve_sidecar_binary", lambda: sidecar_bin
    )
    monkeypatch.setattr(
        opencode_launcher, "_binary_supports_url_mode", lambda binary: True
    )

    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://localhost:8000",
        ["--foo", "bar"],
        use_global_opencode=False,
    )

    assert cwd is None
    assert cmd[0] == str(sidecar_bin)
    assert "--url" in cmd
    assert cmd[-2:] == ["--foo", "bar"]


def test_build_command_rejects_incompatible_sidecar_without_url_option(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    sidecar_bin = tmp_path / opencode_launcher._sidecar_binary_name()
    sidecar_bin.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setattr(opencode_launcher, "_find_local_opencode_dir", lambda: None)
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda name: None)
    monkeypatch.setattr(
        opencode_launcher, "_resolve_sidecar_binary", lambda: sidecar_bin
    )
    monkeypatch.setattr(
        opencode_launcher, "_binary_supports_url_mode", lambda binary: False
    )

    with pytest.raises(RuntimeError) as exc:
        opencode_launcher._build_opencode_command(
            project_dir,
            "http://localhost:8000",
            [],
            use_global_opencode=False,
        )

    assert "not compatible" in str(exc.value)


def test_build_command_uses_global_attach_mode_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    global_bin = "/usr/local/bin/opencode"

    monkeypatch.setattr(opencode_launcher, "_find_local_opencode_dir", lambda: None)
    monkeypatch.setattr(
        opencode_launcher,
        "_resolve_sidecar_binary",
        lambda: (_ for _ in ()).throw(RuntimeError("sidecar unavailable")),
    )
    monkeypatch.setattr(
        opencode_launcher.shutil,
        "which",
        lambda name: global_bin if name == "opencode" else None,
    )
    monkeypatch.setattr(
        opencode_launcher, "_binary_supports_url_mode", lambda binary: False
    )

    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://localhost:8000",
        ["--session", "abc123"],
        use_global_opencode=True,
    )

    assert cwd is None
    assert cmd == [
        global_bin,
        "attach",
        "http://localhost:8000",
        "--dir",
        str(project_dir),
        "--session",
        "abc123",
    ]


def test_build_command_error_surfaces_sidecar_bootstrap_detail(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()

    monkeypatch.setattr(opencode_launcher, "_find_local_opencode_dir", lambda: None)
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda name: None)

    def _fail_sidecar() -> Path:
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(opencode_launcher, "_resolve_sidecar_binary", _fail_sidecar)

    with pytest.raises(RuntimeError) as exc:
        opencode_launcher._build_opencode_command(
            project_dir,
            "http://localhost:8000",
            [],
            use_global_opencode=False,
        )

    message = str(exc.value)
    assert "pip install -U penguin-ai" in message
    assert "network unavailable" in message


def test_sidecar_bootstrap_downloads_verifies_and_caches(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    monkeypatch.setattr(
        opencode_launcher, "_installed_penguin_version", lambda: "0.6.0"
    )

    asset_name = opencode_launcher._sidecar_platform_candidates()[0]
    binary_name = opencode_launcher._sidecar_binary_name()
    archive_bytes = _build_archive_bytes(asset_name, binary_name)
    digest = opencode_launcher.hashlib.sha256(archive_bytes).hexdigest()

    release_doc = {
        "tag_name": "v-test",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": "https://example.invalid/opencode",
                "digest": f"sha256:{digest}",
            }
        ],
    }

    calls: list[str] = []
    release_calls: list[str] = []

    def _read_release(url: str):
        release_calls.append(url)
        return release_doc

    monkeypatch.setattr(opencode_launcher, "_read_json_url", _read_release)

    def _download(url: str, destination: Path, timeout_seconds: float = 120.0) -> None:
        del timeout_seconds
        calls.append(url)
        destination.write_bytes(archive_bytes)

    monkeypatch.setattr(opencode_launcher, "_download_binary_asset", _download)

    first = opencode_launcher._resolve_sidecar_binary()
    assert first.exists()
    assert first.is_file()
    assert len(calls) == 1
    assert release_calls == [
        opencode_launcher._sidecar_release_url_for_version("0.6.0")
    ]

    # Marker-based cache path should avoid release API/download on second call.
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda url: (_ for _ in ()).throw(RuntimeError("should not fetch release")),
    )
    second = opencode_launcher._resolve_sidecar_binary()
    assert second == first
    assert len(calls) == 1


def test_sidecar_bootstrap_rejects_checksum_mismatch(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    monkeypatch.setattr(
        opencode_launcher, "_installed_penguin_version", lambda: "0.6.0"
    )

    asset_name = opencode_launcher._sidecar_platform_candidates()[0]
    binary_name = opencode_launcher._sidecar_binary_name()
    archive_bytes = _build_archive_bytes(asset_name, binary_name)

    release_doc = {
        "tag_name": "v-test",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": "https://example.invalid/opencode",
                "digest": "sha256:" + ("0" * 64),
            }
        ],
    }

    monkeypatch.setattr(opencode_launcher, "_read_json_url", lambda url: release_doc)

    def _download(url: str, destination: Path, timeout_seconds: float = 120.0) -> None:
        del url, timeout_seconds
        destination.write_bytes(archive_bytes)

    monkeypatch.setattr(opencode_launcher, "_download_binary_asset", _download)

    with pytest.raises(RuntimeError) as exc:
        opencode_launcher._resolve_sidecar_binary()

    assert "checksum verification" in str(exc.value)


def test_sidecar_cache_invalidates_when_installed_version_changes(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    binary_path = (
        cache_root
        / "v0.6.0"
        / "asset"
        / "bin"
        / opencode_launcher._sidecar_binary_name()
    )
    binary_path.parent.mkdir(parents=True, exist_ok=True)
    binary_path.write_text("#!/bin/sh\n", encoding="utf-8")

    release_url = opencode_launcher._sidecar_release_url_for_version("0.6.0")
    opencode_launcher._write_cached_sidecar_marker(
        cache_root,
        binary_path=binary_path,
        release_tag="v0.6.0",
        asset_name="asset",
        release_url=release_url,
        requested_version="0.6.0",
    )

    cached = opencode_launcher._read_cached_sidecar_marker(
        cache_root,
        release_url=opencode_launcher._sidecar_release_url_for_version("0.6.1"),
        requested_version="0.6.1",
    )

    assert cached is None


def test_sidecar_release_override_bypasses_installed_version_lookup(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.setenv(
        "PENGUIN_TUI_RELEASE_URL",
        "https://example.invalid/releases/custom",
    )

    asset_name = opencode_launcher._sidecar_platform_candidates()[0]
    binary_name = opencode_launcher._sidecar_binary_name()
    archive_bytes = _build_archive_bytes(asset_name, binary_name)
    digest = opencode_launcher.hashlib.sha256(archive_bytes).hexdigest()
    release_doc = {
        "tag_name": "v-custom",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": "https://example.invalid/opencode",
                "digest": f"sha256:{digest}",
            }
        ],
    }

    def _unexpected_version() -> str:
        raise AssertionError("installed version lookup should be skipped")

    release_calls: list[str] = []

    monkeypatch.setattr(
        opencode_launcher,
        "_installed_penguin_version",
        _unexpected_version,
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda url: release_calls.append(url) or release_doc,
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_download_binary_asset",
        lambda _url, destination, timeout_seconds=120.0: destination.write_bytes(
            archive_bytes
        ),
    )

    resolved = opencode_launcher._resolve_sidecar_binary()

    assert resolved.exists()
    assert release_calls == ["https://example.invalid/releases/custom"]


def test_sidecar_bootstrap_errors_when_exact_version_release_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    monkeypatch.setattr(
        opencode_launcher, "_installed_penguin_version", lambda: "9.9.9"
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda _url: (_ for _ in ()).throw(RuntimeError("missing release")),
    )

    with pytest.raises(RuntimeError) as exc:
        opencode_launcher._resolve_sidecar_binary()

    assert "v9.9.9" in str(exc.value)


def test_sidecar_bootstrap_errors_when_exact_version_has_no_compatible_asset(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    monkeypatch.setattr(
        opencode_launcher, "_installed_penguin_version", lambda: "9.9.9"
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda _url: {
            "tag_name": "v9.9.9",
            "assets": [
                {
                    "name": "opencode-unsupported.zip",
                    "browser_download_url": "https://example.invalid/opencode",
                }
            ],
        },
    )

    with pytest.raises(RuntimeError) as exc:
        opencode_launcher._resolve_sidecar_binary()

    assert "v9.9.9" in str(exc.value)


def test_main_autostarts_web_and_preserves_project_directory_env(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sandbox"
    project_dir.mkdir()

    fake_proc = _FakeProcess(running=True)
    captured_start_env: dict[str, str] = {}
    captured_run_env: dict[str, str] = {}
    stop_calls: list[_FakeProcess | None] = []

    monkeypatch.setattr(
        opencode_launcher.atexit, "register", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        opencode_launcher, "_is_server_running", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(opencode_launcher, "_is_local_url", lambda base_url: True)
    monkeypatch.setattr(
        opencode_launcher, "_ensure_web_runtime_available", lambda: None
    )

    def _start(base_url: str, env: dict[str, str]) -> _FakeProcess:
        del base_url
        captured_start_env.update(env)
        return fake_proc

    monkeypatch.setattr(opencode_launcher, "_start_web_server", _start)
    monkeypatch.setattr(
        opencode_launcher, "_wait_for_server", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_build_opencode_command",
        lambda *args, **kwargs: (["opencode", str(project_dir)], None),
    )

    def _run(cmd: list[str], cwd: Path | None, env: dict[str, str]):
        del cmd, cwd
        captured_run_env.update(env)
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(opencode_launcher.subprocess, "run", _run)

    def _stop(proc: _FakeProcess | None) -> None:
        stop_calls.append(proc)

    monkeypatch.setattr(opencode_launcher, "_stop_process", _stop)

    exit_code = opencode_launcher.main([str(project_dir)])

    assert exit_code == 0
    for env_map in (captured_start_env, captured_run_env):
        assert env_map["PENGUIN_CWD"] == str(project_dir)
        assert env_map["PENGUIN_PROJECT_ROOT"] == str(project_dir)
        assert env_map["PENGUIN_WRITE_ROOT"] == "project"
        assert env_map["PWD"] == str(project_dir)
        assert env_map["PENGUIN_WEB_URL"] == "http://localhost:8000"
    assert stop_calls == [fake_proc]


def test_main_returns_error_when_autostart_health_never_recovers(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sandbox"
    project_dir.mkdir()

    fake_proc = _FakeProcess(running=True)
    stop_calls: list[_FakeProcess | None] = []

    monkeypatch.setattr(
        opencode_launcher.atexit, "register", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        opencode_launcher, "_is_server_running", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(opencode_launcher, "_is_local_url", lambda base_url: True)
    monkeypatch.setattr(
        opencode_launcher, "_ensure_web_runtime_available", lambda: None
    )
    monkeypatch.setattr(
        opencode_launcher, "_start_web_server", lambda *args, **kwargs: fake_proc
    )
    monkeypatch.setattr(
        opencode_launcher, "_wait_for_server", lambda *args, **kwargs: False
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_build_opencode_command",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("build command should not execute when health fails")
        ),
    )

    def _stop(proc: _FakeProcess | None) -> None:
        stop_calls.append(proc)

    monkeypatch.setattr(opencode_launcher, "_stop_process", _stop)

    exit_code = opencode_launcher.main([str(project_dir)])

    assert exit_code == 1
    assert stop_calls == [fake_proc]
