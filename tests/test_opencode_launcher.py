"""Regression tests for Penguin TUI launcher bootstrap and startup flow."""

from __future__ import annotations

import io
import json
import subprocess
import tarfile
import zipfile
from types import SimpleNamespace
from typing import TYPE_CHECKING

import pytest

from penguin.cli import opencode_launcher

if TYPE_CHECKING:
    from pathlib import Path


@pytest.fixture(autouse=True)
def _default_to_v1(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep existing launcher tests on the default V1 path."""
    monkeypatch.delenv("PENGUIN_TUI_V2", raising=False)


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


class _FakeHTTPResponse:
    def __init__(self, payload: bytes, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status

    def __enter__(self) -> _FakeHTTPResponse:
        return self

    def __exit__(self, *args: object) -> None:
        del args

    def getcode(self) -> int:
        return self.status

    def read(self) -> bytes:
        return self.payload


def _build_archive_bytes(
    asset_name: str,
    binary_name: str,
    *,
    v2_bundle: bool = False,
) -> bytes:
    members = {binary_name: b"#!/bin/sh\necho sidecar\n"}
    if v2_bundle:
        members = {
            f"bin/{binary_name}": b"#!/bin/sh\necho sidecar\n",
            "plugins/tui/penguin.tsx": b"export const Penguin = true\n",
            "penguin-tui/LICENSE": b"Penguin TUI license\n",
        }

    if asset_name.endswith(".zip"):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member_name, payload in members.items():
                archive.writestr(member_name, payload)
        return buf.getvalue()

    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w:gz") as archive:
        for member_name, payload in members.items():
            info = tarfile.TarInfo(name=member_name)
            info.size = len(payload)
            archive.addfile(info, io.BytesIO(payload))
    return buf.getvalue()


@pytest.mark.parametrize("link_type", [tarfile.SYMTYPE, tarfile.LNKTYPE])
def test_extract_archive_rejects_tar_links(
    tmp_path: Path,
    link_type: bytes,
) -> None:
    archive_path = tmp_path / "sidecar.tar.gz"
    outside = tmp_path / "outside"
    outside.mkdir()
    link = tarfile.TarInfo("pivot")
    link.type = link_type
    link.linkname = str(outside / "target")
    payload = b"must stay contained"
    nested = tarfile.TarInfo("pivot/pwned.txt")
    nested.size = len(payload)
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.addfile(link)
        archive.addfile(nested, io.BytesIO(payload))

    with pytest.raises(RuntimeError, match="Unsafe member type"):
        opencode_launcher._extract_archive(archive_path, tmp_path / "extract")

    assert not (outside / "pwned.txt").exists()


def test_default_release_url_points_to_penguin_repo(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    assert (
        opencode_launcher._sidecar_release_url()
        == "https://api.github.com/repos/Maximooch/penguin/releases/latest"
    )


def test_server_health_probe_uses_generation_specific_contract(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def _open(url: str, timeout: float) -> _FakeHTTPResponse:
        del timeout
        requested.append(url)
        if url.endswith("/api/health"):
            return _FakeHTTPResponse(b'{"healthy":true,"version":"test","pid":1}')
        return _FakeHTTPResponse(b'{"status":"ok"}')

    monkeypatch.setattr(opencode_launcher, "urlopen", _open)

    assert opencode_launcher._is_server_running("http://127.0.0.1:9000") is True
    assert requested[-1].endswith("/api/v1/health")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    assert opencode_launcher._is_server_running("http://127.0.0.1:9000") is True
    assert requested[-1].endswith("/api/health")


def test_v2_health_probe_rejects_a_v1_only_backend(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    requested: list[str] = []

    def _open(url: str, timeout: float) -> _FakeHTTPResponse:
        del timeout
        requested.append(url)
        if url.endswith("/api/v1/health"):
            return _FakeHTTPResponse(b'{"status":"ok"}')
        raise opencode_launcher.URLError("V2 route is absent")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setattr(opencode_launcher, "urlopen", _open)

    assert opencode_launcher._is_server_running("http://127.0.0.1:9000") is False
    assert requested == ["http://127.0.0.1:9000/api/health"]


def test_v2_health_probe_rejects_an_unexpected_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setattr(
        opencode_launcher,
        "urlopen",
        lambda *_args, **_kwargs: _FakeHTTPResponse(b'{"status":"ok"}'),
    )

    assert opencode_launcher._is_server_running("http://127.0.0.1:9000") is False


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

    assert (
        opencode_launcher._installed_penguin_version()
        == opencode_launcher.PENGUIN_VERSION
    )


@pytest.mark.parametrize(
    ("system", "machine", "musl", "avx2", "expected"),
    [
        ("darwin", "arm64", False, False, ["opencode2-darwin-arm64.zip"]),
        (
            "darwin",
            "x86_64",
            False,
            True,
            [
                "opencode2-darwin-x64.zip",
                "opencode2-darwin-x64-baseline.zip",
            ],
        ),
        (
            "darwin",
            "x86_64",
            False,
            False,
            ["opencode2-darwin-x64-baseline.zip"],
        ),
        (
            "linux",
            "aarch64",
            False,
            False,
            ["opencode2-linux-arm64.tar.gz"],
        ),
        (
            "linux",
            "aarch64",
            True,
            False,
            ["opencode2-linux-arm64-musl.tar.gz"],
        ),
        (
            "linux",
            "x86_64",
            False,
            True,
            [
                "opencode2-linux-x64.tar.gz",
                "opencode2-linux-x64-baseline.tar.gz",
            ],
        ),
        (
            "linux",
            "x86_64",
            False,
            False,
            ["opencode2-linux-x64-baseline.tar.gz"],
        ),
        (
            "linux",
            "x86_64",
            True,
            True,
            [
                "opencode2-linux-x64-musl.tar.gz",
                "opencode2-linux-x64-baseline-musl.tar.gz",
            ],
        ),
        (
            "linux",
            "x86_64",
            True,
            False,
            ["opencode2-linux-x64-baseline-musl.tar.gz"],
        ),
        (
            "win32",
            "AMD64",
            False,
            True,
            [
                "opencode2-windows-x64.zip",
                "opencode2-windows-x64-baseline.zip",
            ],
        ),
        (
            "win32",
            "AMD64",
            False,
            False,
            ["opencode2-windows-x64-baseline.zip"],
        ),
    ],
)
def test_v2_sidecar_platform_candidates_choose_compatible_variant_first(
    monkeypatch: pytest.MonkeyPatch,
    system: str,
    machine: str,
    musl: bool,
    avx2: bool,
    expected: list[str],
) -> None:
    monkeypatch.setattr(opencode_launcher.sys, "platform", system)
    monkeypatch.setattr(opencode_launcher.platform, "machine", lambda: machine)
    monkeypatch.setattr(opencode_launcher, "_is_musl_linux", lambda: musl)
    monkeypatch.setattr(opencode_launcher, "_cpu_supports_avx2", lambda: avx2)

    assert opencode_launcher._v2_sidecar_platform_candidates() == expected
    expected_binary = "opencode2.exe" if system.startswith("win") else "opencode2"
    assert opencode_launcher._v2_sidecar_binary_name() == expected_binary


def test_musl_detection_requires_positive_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencode_launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        opencode_launcher.platform,
        "libc_ver",
        lambda: ("musl", "1.2.5"),
    )

    assert opencode_launcher._is_musl_linux() is True

    monkeypatch.setattr(opencode_launcher.platform, "libc_ver", lambda: ("", ""))
    monkeypatch.setattr(opencode_launcher.Path, "is_file", lambda _path: False)
    monkeypatch.setattr(
        opencode_launcher.Path,
        "glob",
        lambda _path, _pattern: iter(()),
    )
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda _name: None)

    assert opencode_launcher._is_musl_linux() is False


def test_avx2_detection_defaults_to_baseline_without_cpu_flag(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(opencode_launcher.sys, "platform", "linux")
    monkeypatch.setattr(
        opencode_launcher.platform,
        "machine",
        lambda: "x86_64",
    )
    monkeypatch.setattr(
        opencode_launcher.Path,
        "read_text",
        lambda _path, **_kwargs: "flags : sse4_2 avx avx2",
    )
    assert opencode_launcher._cpu_supports_avx2() is True

    monkeypatch.setattr(
        opencode_launcher.Path,
        "read_text",
        lambda _path, **_kwargs: "flags : sse4_2 avx",
    )
    assert opencode_launcher._cpu_supports_avx2() is False


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
        "http://127.0.0.1:9000",
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
            "http://127.0.0.1:9000",
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
        "http://127.0.0.1:9000",
        ["--session", "abc123"],
        use_global_opencode=True,
    )

    assert cwd is None
    assert cmd == [
        global_bin,
        "attach",
        "http://127.0.0.1:9000",
        "--dir",
        str(project_dir),
        "--session",
        "abc123",
    ]


def test_build_command_uses_global_before_local_source_when_requested(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    local_source = tmp_path / "opencode"
    global_bin = "/usr/local/bin/opencode"

    monkeypatch.setattr(
        opencode_launcher, "_find_local_opencode_dir", lambda: local_source
    )
    monkeypatch.setattr(
        opencode_launcher.shutil,
        "which",
        lambda name: {
            "bun": "/usr/local/bin/bun",
            "opencode": global_bin,
        }.get(name),
    )
    monkeypatch.setattr(
        opencode_launcher, "_binary_supports_url_mode", lambda binary: True
    )

    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        [],
        use_global_opencode=True,
    )

    assert cwd is None
    assert cmd == [global_bin, str(project_dir), "--url", "http://127.0.0.1:9000"]


def test_v2_build_command_prefers_explicit_binary_over_source(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    source_dir = tmp_path / "opencode-v2"
    (source_dir / "src").mkdir(parents=True)
    (source_dir / "src" / "index.ts").write_text("", encoding="utf-8")
    binary = tmp_path / "opencode2"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_BIN_PATH", str(binary))
    monkeypatch.setenv("PENGUIN_OPENCODE_DIR", str(source_dir))
    monkeypatch.setattr(
        opencode_launcher.shutil,
        "which",
        lambda name: "/usr/local/bin/bun" if name == "bun" else None,
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_binary_supports_url_mode",
        lambda _binary: pytest.fail("V2 must not probe the V1 --url interface"),
    )

    child_env: dict[str, str] = {}
    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        ["--session", "abc123"],
        use_global_opencode=False,
        child_env=child_env,
    )

    assert cwd is None
    assert cmd == [
        str(binary.resolve()),
        str(project_dir),
        "--server",
        "http://127.0.0.1:9000",
        "--session",
        "abc123",
    ]
    assert "OPENCODE_CONFIG_DIR" not in child_env


def test_v2_build_command_uses_explicit_source_with_server_flag(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    source_dir = tmp_path / "opencode-v2"
    (source_dir / "src").mkdir(parents=True)
    (source_dir / "src" / "index.ts").write_text("", encoding="utf-8")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_OPENCODE_DIR", str(source_dir))
    monkeypatch.delenv("PENGUIN_TUI_BIN_PATH", raising=False)
    monkeypatch.setattr(
        opencode_launcher.shutil,
        "which",
        lambda name: "/usr/local/bin/bun" if name == "bun" else None,
    )

    child_env: dict[str, str] = {}
    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        ["--session", "abc123"],
        use_global_opencode=False,
        child_env=child_env,
    )

    assert cwd == source_dir.resolve()
    assert cmd == [
        "/usr/local/bin/bun",
        "run",
        "--conditions=browser",
        "./src/index.ts",
        str(project_dir),
        "--server",
        "http://127.0.0.1:9000",
        "--session",
        "abc123",
    ]
    assert "OPENCODE_CONFIG_DIR" not in child_env


def test_v2_build_command_uses_global_opencode2_and_preserves_explicit_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    global_bin = "/usr/local/bin/opencode2"

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setattr(
        opencode_launcher.shutil,
        "which",
        lambda name: global_bin if name == "opencode2" else None,
    )

    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        ["--server=http://127.0.0.1:9010"],
        use_global_opencode=True,
    )

    assert cwd is None
    assert cmd == [
        global_bin,
        str(project_dir),
        "--server=http://127.0.0.1:9010",
    ]


def test_v2_global_fallback_keeps_explicit_binary_user_managed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    binary = tmp_path / "opencode2"
    binary.write_text("#!/bin/sh\n", encoding="utf-8")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_BIN_PATH", str(binary))
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda _name: None)

    child_env: dict[str, str] = {}
    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        [],
        use_global_opencode=True,
        child_env=child_env,
    )

    assert cwd is None
    assert cmd == [
        str(binary.resolve()),
        str(project_dir),
        "--server",
        "http://127.0.0.1:9000",
    ]
    assert "OPENCODE_CONFIG_DIR" not in child_env


def test_v2_build_command_sets_bundled_config_for_auto_sidecar(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "proj"
    project_dir.mkdir()
    cache_root = tmp_path / "cache"
    install_root = cache_root / "v2" / "v-test" / "asset"
    sidecar_bin = install_root / "bin" / "opencode2"
    sidecar_bin.parent.mkdir(parents=True)
    sidecar_bin.write_text("#!/bin/sh\n", encoding="utf-8")
    plugin_path = install_root / "plugins" / "tui" / "penguin.tsx"
    plugin_path.parent.mkdir(parents=True)
    plugin_path.write_text("export const Penguin = true\n", encoding="utf-8")

    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_BIN_PATH", raising=False)
    monkeypatch.delenv("PENGUIN_OPENCODE_DIR", raising=False)
    monkeypatch.setattr(opencode_launcher.shutil, "which", lambda _name: None)
    monkeypatch.setattr(
        opencode_launcher,
        "_resolve_sidecar_binary",
        lambda: sidecar_bin,
    )

    child_env = {"OPENCODE_CONFIG_DIR": "  "}
    cmd, cwd = opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        [],
        use_global_opencode=False,
        child_env=child_env,
    )

    assert cwd is None
    assert cmd == [
        str(sidecar_bin),
        str(project_dir),
        "--server",
        "http://127.0.0.1:9000",
    ]
    assert child_env["OPENCODE_CONFIG_DIR"] == str(install_root)

    explicit_env = {"OPENCODE_CONFIG_DIR": "/custom/opencode"}
    opencode_launcher._build_opencode_command(
        project_dir,
        "http://127.0.0.1:9000",
        [],
        use_global_opencode=False,
        child_env=explicit_env,
    )
    assert explicit_env["OPENCODE_CONFIG_DIR"] == "/custom/opencode"


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
            "http://127.0.0.1:9000",
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
    assert (cache_root / "current.json").is_file()
    assert not (cache_root / "v2").exists()
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


def test_v2_sidecar_bootstrap_isolates_and_pins_cache_identity(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.delenv("PENGUIN_TUI_RELEASE_URL", raising=False)
    monkeypatch.setattr(
        opencode_launcher,
        "_installed_penguin_version",
        lambda: "0.6.0",
    )
    asset_name = "opencode2-linux-x64-baseline.tar.gz"
    monkeypatch.setattr(
        opencode_launcher,
        "_v2_sidecar_platform_candidates",
        lambda: ["opencode2-linux-x64.tar.gz", asset_name],
    )
    archive_bytes = _build_archive_bytes(
        asset_name,
        "opencode2",
        v2_bundle=True,
    )
    digest = opencode_launcher.hashlib.sha256(archive_bytes).hexdigest()
    release_doc = {
        "tag_name": "v-test",
        "assets": [
            {
                "name": asset_name,
                "browser_download_url": "https://example.invalid/opencode2",
                "digest": f"sha256:{digest}",
            }
        ],
    }
    release_url = opencode_launcher._sidecar_release_url_for_version("0.6.0")

    v1_binary = cache_root / "v-test" / "asset" / "bin" / "opencode"
    v1_binary.parent.mkdir(parents=True)
    v1_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    opencode_launcher._write_cached_sidecar_marker(
        cache_root,
        binary_path=v1_binary,
        release_tag="v-test",
        asset_name="asset",
        release_url=release_url,
        requested_version="0.6.0",
    )
    outside_v2_binary = v1_binary.with_name("opencode2")
    outside_v2_binary.write_text("#!/bin/sh\n", encoding="utf-8")
    opencode_launcher._write_cached_sidecar_marker(
        cache_root / "v2",
        binary_path=outside_v2_binary,
        release_tag="v-test",
        asset_name="asset",
        release_url=release_url,
        requested_version="0.6.0",
        cache_identity=opencode_launcher._v2_sidecar_cache_identity(asset_name),
    )

    release_calls: list[str] = []
    download_calls: list[str] = []
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda url: release_calls.append(url) or release_doc,
    )

    def _download(url: str, destination: Path, timeout_seconds: float = 120.0) -> None:
        del timeout_seconds
        download_calls.append(url)
        destination.write_bytes(archive_bytes)

    monkeypatch.setattr(opencode_launcher, "_download_binary_asset", _download)

    first = opencode_launcher._resolve_sidecar_binary()

    expected = cache_root / "v2" / "v-test" / asset_name / "bin" / "opencode2"
    assert first == expected
    assert first.is_file()
    install_root = first.parent.parent
    plugin_path = install_root / "plugins" / "tui" / "penguin.tsx"
    license_path = install_root / "penguin-tui" / "LICENSE"
    assert plugin_path.read_text(encoding="utf-8") == "export const Penguin = true\n"
    assert license_path.read_text(encoding="utf-8") == "Penguin TUI license\n"
    assert release_calls == [release_url]
    assert download_calls == ["https://example.invalid/opencode2"]
    assert (cache_root / "current.json").is_file()

    marker_path = cache_root / "v2" / "current.json"
    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    assert marker["protocol_generation"] == "v2"
    assert marker["upstream_pin"] == "b35c5fc98577b77d8d67d298c6254e0cd138c9d5"
    assert marker["artifact_pin"] == "@opencode-ai/cli@0.0.0-next-17220"
    assert marker["platform_asset"] == asset_name

    plugin_path.unlink()
    second = opencode_launcher._resolve_sidecar_binary()
    assert second == first
    assert len(release_calls) == 2
    assert len(download_calls) == 2
    assert plugin_path.is_file()

    marker = json.loads(marker_path.read_text(encoding="utf-8"))
    marker["upstream_pin"] = "stale-pin"
    marker_path.write_text(json.dumps(marker), encoding="utf-8")
    third = opencode_launcher._resolve_sidecar_binary()
    assert third == first
    assert len(release_calls) == 3
    assert len(download_calls) == 3

    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda _url: pytest.fail("valid V2 marker should avoid release lookup"),
    )
    fourth = opencode_launcher._resolve_sidecar_binary()
    assert fourth == first
    assert len(download_calls) == 3


@pytest.mark.parametrize(
    "digest",
    [None, "", "sha512:" + ("0" * 128), "sha256:not-a-digest"],
)
def test_v2_sidecar_bootstrap_requires_valid_sha256_digest(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    digest: str | None,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        opencode_launcher,
        "_installed_penguin_version",
        lambda: "0.6.0",
    )
    asset_name = "opencode2-linux-x64-baseline.tar.gz"
    monkeypatch.setattr(
        opencode_launcher,
        "_v2_sidecar_platform_candidates",
        lambda: [asset_name],
    )
    asset = {
        "name": asset_name,
        "browser_download_url": "https://example.invalid/opencode2",
    }
    if digest is not None:
        asset["digest"] = digest
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda _url: {"tag_name": "v-test", "assets": [asset]},
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_download_binary_asset",
        lambda *_args, **_kwargs: pytest.fail("invalid digest must fail first"),
    )

    with pytest.raises(RuntimeError, match="SHA-256"):
        opencode_launcher._resolve_sidecar_binary()


def test_v2_sidecar_bootstrap_rejects_archive_without_penguin_plugin(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_TUI_CACHE_DIR", str(cache_root))
    monkeypatch.setattr(
        opencode_launcher,
        "_installed_penguin_version",
        lambda: "0.6.0",
    )
    asset_name = "opencode2-linux-x64-baseline.tar.gz"
    monkeypatch.setattr(
        opencode_launcher,
        "_v2_sidecar_platform_candidates",
        lambda: [asset_name],
    )
    archive_bytes = _build_archive_bytes(asset_name, "bin/opencode2")
    digest = opencode_launcher.hashlib.sha256(archive_bytes).hexdigest()
    monkeypatch.setattr(
        opencode_launcher,
        "_read_json_url",
        lambda _url: {
            "tag_name": "v-test",
            "assets": [
                {
                    "name": asset_name,
                    "browser_download_url": "https://example.invalid/opencode2",
                    "digest": f"sha256:{digest}",
                }
            ],
        },
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_download_binary_asset",
        lambda _url, destination, timeout_seconds=120.0: destination.write_bytes(
            archive_bytes
        ),
    )

    with pytest.raises(RuntimeError, match=r"plugins/tui/penguin\.tsx"):
        opencode_launcher._resolve_sidecar_binary()

    assert not (cache_root / "v2" / "current.json").exists()


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
        assert env_map["PENGUIN_WEB_URL"] == "http://127.0.0.1:9000"
    assert stop_calls == [fake_proc]


def test_parse_args_defaults_to_local_web_port_9000(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("PENGUIN_WEB_URL", raising=False)

    args, extra = opencode_launcher._parse_args([])

    assert args.url == "http://127.0.0.1:9000"
    assert extra == []


def test_prepare_local_auth_env_seeds_shared_startup_token(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env: dict[str, str] = {}
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path))

    opencode_launcher._prepare_local_auth_env(
        "http://127.0.0.1:9000", env, server_running=False
    )

    assert env["PENGUIN_AUTH_STARTUP_TOKEN"]
    assert env["PENGUIN_LOCAL_AUTH_TOKEN"] == env["PENGUIN_AUTH_STARTUP_TOKEN"]
    assert not (tmp_path / "127.0.0.1-9000.token").exists()


def test_prepare_local_auth_env_preserves_existing_api_keys() -> None:
    env = {
        "PENGUIN_AUTH_ENABLED": "true",
        "PENGUIN_API_KEYS": "configured-key",
    }

    opencode_launcher._prepare_local_auth_env(
        "http://127.0.0.1:9000", env, server_running=False
    )

    assert "PENGUIN_AUTH_STARTUP_TOKEN" not in env
    assert "PENGUIN_LOCAL_AUTH_TOKEN" not in env


def test_prepare_local_auth_env_respects_explicit_auth_disable() -> None:
    env = {"PENGUIN_AUTH_ENABLED": "false"}

    opencode_launcher._prepare_local_auth_env(
        "http://127.0.0.1:9000", env, server_running=False
    )

    assert "PENGUIN_AUTH_STARTUP_TOKEN" not in env
    assert "PENGUIN_LOCAL_AUTH_TOKEN" not in env


def test_prepare_local_auth_env_reads_existing_local_token_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env: dict[str, str] = {}
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path))
    token_file = tmp_path / "127.0.0.1-9000.token"
    token_file.write_text("existing-token", encoding="utf-8")

    opencode_launcher._prepare_local_auth_env(
        "http://127.0.0.1:9000", env, server_running=True
    )

    assert env["PENGUIN_LOCAL_AUTH_TOKEN"] == "existing-token"
    assert "PENGUIN_AUTH_STARTUP_TOKEN" not in env


def test_prepare_opencode_v2_env_bridges_auth_and_disables_updater(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    env = {"PENGUIN_LOCAL_AUTH_TOKEN": "startup-token"}

    opencode_launcher._prepare_opencode_v2_env(env)

    assert env["OPENCODE_PASSWORD"] == "startup-token"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"


def test_prepare_opencode_v2_env_preserves_explicit_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    env = {
        "PENGUIN_LOCAL_AUTH_TOKEN": "startup-token",
        "OPENCODE_PASSWORD": "explicit-password",
    }

    opencode_launcher._prepare_opencode_v2_env(env)

    assert env["OPENCODE_PASSWORD"] == "explicit-password"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"


def test_prepare_opencode_v2_env_bridges_configured_api_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    env = {
        "PENGUIN_API_KEYS": "primary-key, fallback-key",
        "PENGUIN_LOCAL_AUTH_TOKEN": "stale-startup-token",
    }

    opencode_launcher._prepare_opencode_v2_env(env)

    assert env["OPENCODE_PASSWORD"] == "primary-key"
    assert env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"


def test_prepare_opencode_v2_env_replaces_blank_password(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    env = {
        "PENGUIN_LOCAL_AUTH_TOKEN": "startup-token",
        "OPENCODE_PASSWORD": "  ",
    }

    opencode_launcher._prepare_opencode_v2_env(env)

    assert env["OPENCODE_PASSWORD"] == "startup-token"


def test_prepare_opencode_v2_env_is_noop_for_v1() -> None:
    env = {"PENGUIN_LOCAL_AUTH_TOKEN": "startup-token"}

    opencode_launcher._prepare_opencode_v2_env(env)

    assert env == {"PENGUIN_LOCAL_AUTH_TOKEN": "startup-token"}


def test_main_reuses_cached_local_auth_token_for_running_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sandbox"
    project_dir.mkdir()
    cache_dir = tmp_path / "auth-cache"
    cache_dir.mkdir()
    (cache_dir / "127.0.0.1-9000.token").write_text("cached-token", encoding="utf-8")
    captured_run_env: dict[str, str] = {}

    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(cache_dir))
    monkeypatch.delenv("PENGUIN_AUTH_ENABLED", raising=False)
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)
    monkeypatch.delenv("PENGUIN_LOCAL_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        opencode_launcher, "_is_server_running", lambda *args, **kwargs: True
    )
    monkeypatch.setattr(opencode_launcher, "_is_local_url", lambda base_url: True)
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

    exit_code = opencode_launcher.main([str(project_dir)])

    assert exit_code == 0
    assert captured_run_env["PENGUIN_LOCAL_AUTH_TOKEN"] == "cached-token"


def test_prepare_local_auth_env_does_not_invent_token_for_running_server(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    env: dict[str, str] = {"PENGUIN_AUTH_ENABLED": "true"}
    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path))

    opencode_launcher._prepare_local_auth_env(
        "http://127.0.0.1:9000", env, server_running=True
    )

    assert "PENGUIN_LOCAL_AUTH_TOKEN" not in env
    assert "PENGUIN_AUTH_STARTUP_TOKEN" not in env


def test_main_shares_startup_token_with_autostarted_local_auth_server(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sandbox"
    project_dir.mkdir()

    fake_proc = _FakeProcess(running=True)
    captured_start_env: dict[str, str] = {}
    captured_run_env: dict[str, str] = {}

    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(tmp_path / "auth-cache"))
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)
    monkeypatch.delenv("PENGUIN_LOCAL_AUTH_TOKEN", raising=False)
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
    monkeypatch.setattr(opencode_launcher, "_stop_process", lambda proc: None)

    exit_code = opencode_launcher.main([str(project_dir)])

    assert exit_code == 0
    assert captured_start_env["PENGUIN_AUTH_STARTUP_TOKEN"]
    assert (
        captured_start_env["PENGUIN_LOCAL_AUTH_TOKEN"]
        == captured_start_env["PENGUIN_AUTH_STARTUP_TOKEN"]
    )
    assert (
        captured_run_env["PENGUIN_LOCAL_AUTH_TOKEN"]
        == captured_start_env["PENGUIN_AUTH_STARTUP_TOKEN"]
    )


def test_main_refreshes_local_auth_token_from_running_server_cache(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    project_dir = tmp_path / "sandbox"
    project_dir.mkdir()
    cache_dir = tmp_path / "auth-cache"
    cache_dir.mkdir()
    captured_run_env: dict[str, str] = {}
    health_checks = iter([False, True])

    monkeypatch.setenv("PENGUIN_LOCAL_AUTH_CACHE_DIR", str(cache_dir))
    monkeypatch.setenv("PENGUIN_TUI_V2", "1")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")
    monkeypatch.delenv("PENGUIN_API_KEYS", raising=False)
    monkeypatch.delenv("PENGUIN_AUTH_STARTUP_TOKEN", raising=False)
    monkeypatch.delenv("PENGUIN_LOCAL_AUTH_TOKEN", raising=False)
    monkeypatch.setattr(
        opencode_launcher.atexit, "register", lambda *args, **kwargs: None
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_is_server_running",
        lambda *args, **kwargs: next(health_checks),
    )
    monkeypatch.setattr(opencode_launcher, "_is_local_url", lambda base_url: True)
    monkeypatch.setattr(
        opencode_launcher, "_ensure_web_runtime_available", lambda: None
    )
    monkeypatch.setattr(
        opencode_launcher,
        "_start_web_server",
        lambda *args, **kwargs: _FakeProcess(running=False),
    )

    def _wait_for_server(*args, **kwargs) -> bool:
        del args, kwargs
        (cache_dir / "127.0.0.1-9000.token").write_text(
            "running-server-token",
            encoding="utf-8",
        )
        return True

    monkeypatch.setattr(opencode_launcher, "_wait_for_server", _wait_for_server)
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
    monkeypatch.setattr(opencode_launcher, "_stop_process", lambda proc: None)

    exit_code = opencode_launcher.main([str(project_dir)])

    assert exit_code == 0
    assert captured_run_env["PENGUIN_LOCAL_AUTH_TOKEN"] == "running-server-token"
    assert captured_run_env["OPENCODE_PASSWORD"] == "running-server-token"
    assert captured_run_env["OPENCODE_DISABLE_AUTOUPDATE"] == "1"


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
