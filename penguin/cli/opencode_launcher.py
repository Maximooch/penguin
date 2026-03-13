"""Launch the Penguin TUI against Penguin web with sane local defaults.

This launcher is intended for local workflows where Penguin web and the
Penguin TUI are run together from a terminal.
"""

from __future__ import annotations

import argparse
import atexit
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile
from pathlib import Path
from typing import Any, Sequence
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import Request, urlopen

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}
DEFAULT_TUI_RELEASE_URL = (
    "https://api.github.com/repos/Maximooch/penguin/releases/latest"
)
_URL_MODE_CAP_CACHE: dict[str, bool] = {}


def _normalize_base_url(raw_url: str) -> str:
    """Normalize a base URL for web health checks and TUI connectivity.

    Args:
        raw_url: Raw URL string from CLI args or environment.

    Returns:
        A normalized URL with scheme and netloc.

    Raises:
        ValueError: If the input does not include a host.
    """
    parsed = urlparse(raw_url)
    scheme = parsed.scheme or "http"
    netloc = parsed.netloc or parsed.path
    path = parsed.path if parsed.netloc else ""
    normalized = urlunparse((scheme, netloc, path.rstrip("/"), "", "", ""))
    if not urlparse(normalized).netloc:
        raise ValueError(f"Invalid URL '{raw_url}' (missing host)")
    return normalized


def _health_url(base_url: str) -> str:
    """Build the Penguin health endpoint URL.

    Args:
        base_url: Normalized Penguin web base URL.

    Returns:
        Health endpoint URL.
    """
    return f"{base_url.rstrip('/')}/api/v1/health"


def _is_server_running(base_url: str, timeout_seconds: float = 1.0) -> bool:
    """Check whether Penguin web appears reachable.

    Args:
        base_url: Normalized Penguin web base URL.
        timeout_seconds: HTTP timeout for the health check request.

    Returns:
        True if `/api/v1/health` responds with HTTP 200, otherwise False.
    """
    try:
        with urlopen(_health_url(base_url), timeout=timeout_seconds) as response:
            status = getattr(response, "status", response.getcode())
            return status == 200
    except (URLError, OSError):
        return False


def _is_local_url(base_url: str) -> bool:
    """Return whether URL points to the local machine.

    Args:
        base_url: Normalized Penguin web base URL.

    Returns:
        True for localhost-like hostnames, otherwise False.
    """
    host = (urlparse(base_url).hostname or "").strip().lower()
    return host in LOCAL_HOSTS


def _find_penguin_project_root() -> Path | None:
    """Resolve the Penguin project root when available.

    Returns:
        Path to a Penguin source checkout root, or None.
    """
    env_root = os.getenv("PENGUIN_SOURCE_ROOT", "").strip()
    if env_root:
        candidate = Path(env_root).expanduser().resolve()
        if (candidate / "pyproject.toml").exists():
            return candidate

    opencode_dir = os.getenv("PENGUIN_OPENCODE_DIR", "").strip()
    if opencode_dir:
        start = Path(opencode_dir).expanduser().resolve()
        for candidate in (start, *start.parents):
            if (candidate / "pyproject.toml").exists() and (
                candidate / "penguin-tui"
            ).exists():
                return candidate

    start = Path(__file__).resolve()
    for candidate in (start.parent, *start.parents):
        if (candidate / "pyproject.toml").exists() and (candidate / "penguin").exists():
            return candidate

    return None


def _start_web_server(base_url: str, env: dict[str, str]) -> subprocess.Popen[str]:
    """Start `penguin.web.server` as a detached child process.

    Args:
        base_url: Normalized Penguin web base URL.
        env: Process environment used for the spawned server.

    Returns:
        A running subprocess handle.
    """
    parsed = urlparse(base_url)
    host = parsed.hostname or "127.0.0.1"
    port = parsed.port
    if port is None:
        port = 443 if parsed.scheme == "https" else 80

    server_env = dict(env)
    server_env["HOST"] = host
    server_env["PORT"] = str(port)

    uv_bin = shutil.which("uv")
    launch_commands: list[list[str]] = []
    if uv_bin:
        project_root = _find_penguin_project_root()
        if project_root is not None:
            launch_commands.append(
                [
                    uv_bin,
                    "run",
                    "--project",
                    str(project_root),
                    "--extra",
                    "web",
                    "penguin-web",
                ]
            )
        launch_commands.append(
            [
                uv_bin,
                "run",
                "--no-project",
                "--python",
                sys.executable,
                "penguin-web",
            ]
        )
    launch_commands.append([sys.executable, "-m", "penguin.web.server"])

    last_proc: subprocess.Popen[str] | None = None
    for command in launch_commands:
        proc = subprocess.Popen(
            command,
            env=server_env,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            text=True,
        )
        time.sleep(0.25)
        if proc.poll() is None:
            return proc
        last_proc = proc

    if last_proc is not None:
        return last_proc

    raise RuntimeError("Unable to spawn Penguin web server process")


def _wait_for_server(
    base_url: str, proc: subprocess.Popen[str], timeout_seconds: float
) -> bool:
    """Wait for Penguin web to become healthy.

    Args:
        base_url: Normalized Penguin web base URL.
        proc: Child process handle.
        timeout_seconds: Max wait time.

    Returns:
        True when server is healthy; False if timeout or child exits.
    """
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_server_running(base_url, timeout_seconds=0.5):
            return True
        if proc.poll() is not None:
            return False
        time.sleep(0.2)
    return False


def _stop_process(proc: subprocess.Popen[str] | None) -> None:
    """Terminate a child process if still alive.

    Args:
        proc: Child process handle.
    """
    if proc is None:
        return
    if proc.poll() is not None:
        return

    proc.terminate()
    try:
        proc.wait(timeout=5)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait(timeout=5)


def _find_local_opencode_dir() -> Path | None:
    """Find local `penguin-tui/packages/opencode` if present.

    Returns:
        Path to local OpenCode package directory, or None.
    """
    env_path = os.getenv("PENGUIN_OPENCODE_DIR", "").strip()
    if env_path:
        candidate = Path(env_path).expanduser().resolve()
        if (candidate / "src" / "index.ts").exists():
            return candidate

    repo_root = Path(__file__).resolve().parents[2]
    candidate = repo_root / "penguin-tui" / "packages" / "opencode"
    if (candidate / "src" / "index.ts").exists():
        return candidate
    return None


def _sidecar_binary_name() -> str:
    return "opencode.exe" if sys.platform.startswith("win") else "opencode"


def _sidecar_cache_root() -> Path:
    raw = os.getenv("PENGUIN_TUI_CACHE_DIR", "").strip()
    if raw:
        return Path(raw).expanduser().resolve()
    return Path.home() / ".cache" / "penguin" / "tui"


def _sidecar_release_url() -> str:
    raw = os.getenv("PENGUIN_TUI_RELEASE_URL", "").strip()
    return raw or DEFAULT_TUI_RELEASE_URL


def _sidecar_platform_candidates() -> list[str]:
    machine = platform.machine().strip().lower()
    if machine in {"amd64", "x86_64", "x64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine

    if sys.platform == "darwin":
        if arch == "arm64":
            return ["opencode-darwin-arm64.zip"]
        if arch == "x64":
            return ["opencode-darwin-x64.zip", "opencode-darwin-x64-baseline.zip"]

    if sys.platform.startswith("linux"):
        if arch == "arm64":
            return ["opencode-linux-arm64.tar.gz", "opencode-linux-arm64-musl.tar.gz"]
        if arch == "x64":
            return [
                "opencode-linux-x64.tar.gz",
                "opencode-linux-x64-musl.tar.gz",
                "opencode-linux-x64-baseline.tar.gz",
                "opencode-linux-x64-baseline-musl.tar.gz",
            ]

    if sys.platform.startswith("win"):
        if arch == "x64":
            return ["opencode-windows-x64.zip", "opencode-windows-x64-baseline.zip"]

    raise RuntimeError(
        "Unsupported platform for Penguin TUI sidecar bootstrap: "
        f"{sys.platform}/{machine}"
    )


def _read_json_url(url: str, timeout_seconds: float = 20.0) -> dict[str, Any]:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "User-Agent": "penguin-tui-launcher",
        },
    )
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read().decode("utf-8")
    data = json.loads(payload)
    if isinstance(data, dict):
        return data
    raise RuntimeError(f"Invalid JSON payload from sidecar release URL: {url}")


def _download_binary_asset(
    url: str,
    destination: Path,
    timeout_seconds: float = 120.0,
) -> None:
    request = Request(url, headers={"User-Agent": "penguin-tui-launcher"})
    with urlopen(request, timeout=timeout_seconds) as response:
        payload = response.read()
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(payload)


def _sha256_file(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as handle:
        while True:
            chunk = handle.read(1024 * 1024)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest()


def _verify_asset_digest(archive_path: Path, digest: str | None) -> None:
    if not digest:
        return

    value = str(digest).strip()
    if not value:
        return

    expected = value.split(":", 1)[1] if ":" in value else value
    actual = _sha256_file(archive_path)
    if actual.lower() != expected.lower():
        raise RuntimeError(
            "Downloaded Penguin TUI sidecar failed checksum verification "
            f"(expected={expected}, actual={actual})"
        )


def _extract_archive(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    lower_name = archive_path.name.lower()
    if lower_name.endswith(".zip"):
        with zipfile.ZipFile(archive_path, "r") as archive:
            for member in archive.namelist():
                target = (destination / member).resolve()
                if (
                    destination.resolve() not in target.parents
                    and target != destination.resolve()
                ):
                    raise RuntimeError(f"Unsafe path in sidecar zip archive: {member}")
            archive.extractall(destination)
        return

    if lower_name.endswith(".tar.gz") or lower_name.endswith(".tgz"):
        with tarfile.open(archive_path, "r:gz") as archive:
            base = destination.resolve()
            for member in archive.getmembers():
                target = (destination / member.name).resolve()
                if base not in target.parents and target != base:
                    raise RuntimeError(
                        f"Unsafe path in sidecar tar archive: {member.name}"
                    )
            archive.extractall(destination)
        return

    raise RuntimeError(f"Unsupported sidecar archive format: {archive_path.name}")


def _locate_extracted_binary(search_root: Path) -> Path | None:
    binary_name = _sidecar_binary_name()
    exact = search_root / binary_name
    if exact.exists() and exact.is_file():
        return exact

    for candidate in search_root.rglob(binary_name):
        if candidate.is_file():
            return candidate
    return None


def _read_cached_sidecar_marker(cache_root: Path) -> Path | None:
    marker = cache_root / "current.json"
    if not marker.exists():
        return None

    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except Exception:
        return None

    if not isinstance(data, dict):
        return None
    raw_path = data.get("binary_path")
    if not isinstance(raw_path, str) or not raw_path.strip():
        return None
    binary_path = Path(raw_path).expanduser().resolve()
    if not binary_path.exists() or not binary_path.is_file():
        return None
    return binary_path


def _write_cached_sidecar_marker(
    cache_root: Path,
    *,
    binary_path: Path,
    release_tag: str,
    asset_name: str,
) -> None:
    marker = cache_root / "current.json"
    payload = {
        "binary_path": str(binary_path),
        "release_tag": release_tag,
        "asset_name": asset_name,
    }
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")


def _select_release_asset(release: dict[str, Any]) -> dict[str, Any]:
    assets_raw = release.get("assets")
    assets = assets_raw if isinstance(assets_raw, list) else []
    candidates = _sidecar_platform_candidates()

    for wanted in candidates:
        for asset in assets:
            if not isinstance(asset, dict):
                continue
            if str(asset.get("name", "")).strip() == wanted:
                return asset

    available = [
        str(asset.get("name", "")).strip()
        for asset in assets
        if isinstance(asset, dict) and asset.get("name")
    ]
    raise RuntimeError(
        "No compatible Penguin TUI sidecar asset found for platform "
        f"{sys.platform}/{platform.machine()}. Available assets: {available}"
    )


def _resolve_sidecar_binary() -> Path:
    explicit_path = os.getenv("PENGUIN_TUI_BIN_PATH", "").strip()
    if explicit_path:
        candidate = Path(explicit_path).expanduser().resolve()
        if candidate.exists() and candidate.is_file():
            return candidate
        raise RuntimeError(
            f"Configured PENGUIN_TUI_BIN_PATH does not exist: {candidate}"
        )

    cache_root = _sidecar_cache_root()
    cached = _read_cached_sidecar_marker(cache_root)
    if cached is not None:
        return cached

    release_url = _sidecar_release_url()
    release = _read_json_url(release_url)
    asset = _select_release_asset(release)

    asset_name = str(asset.get("name", "")).strip()
    asset_url = str(asset.get("browser_download_url", "")).strip()
    if not asset_name or not asset_url:
        raise RuntimeError("Sidecar release metadata is missing asset download fields")

    release_tag = str(release.get("tag_name", "latest")).strip() or "latest"
    install_root = cache_root / release_tag / asset_name
    binary_path = install_root / "bin" / _sidecar_binary_name()
    if binary_path.exists() and binary_path.is_file():
        _write_cached_sidecar_marker(
            cache_root,
            binary_path=binary_path,
            release_tag=release_tag,
            asset_name=asset_name,
        )
        return binary_path

    tmp_root = cache_root / ".tmp"
    tmp_root.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="sidecar-", dir=str(tmp_root)) as tmp_dir:
        tmp_dir_path = Path(tmp_dir)
        archive_path = tmp_dir_path / asset_name
        _download_binary_asset(asset_url, archive_path)
        _verify_asset_digest(
            archive_path, asset.get("digest") if isinstance(asset, dict) else None
        )

        extracted_dir = tmp_dir_path / "extract"
        _extract_archive(archive_path, extracted_dir)
        extracted_binary = _locate_extracted_binary(extracted_dir)
        if extracted_binary is None:
            raise RuntimeError(
                "Downloaded Penguin TUI sidecar archive did not contain an executable"
            )

        binary_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(extracted_binary, binary_path)

    if not sys.platform.startswith("win"):
        mode = binary_path.stat().st_mode
        binary_path.chmod(mode | 0o755)

    _write_cached_sidecar_marker(
        cache_root,
        binary_path=binary_path,
        release_tag=release_tag,
        asset_name=asset_name,
    )
    return binary_path


def _binary_supports_url_mode(binary: str) -> bool:
    cache_key = str(Path(binary).expanduser())
    cached = _URL_MODE_CAP_CACHE.get(cache_key)
    if cached is not None:
        return cached

    forced = os.getenv("PENGUIN_TUI_LAUNCH_MODE", "").strip().lower()
    if forced == "url":
        _URL_MODE_CAP_CACHE[cache_key] = True
        return True
    if forced == "attach":
        _URL_MODE_CAP_CACHE[cache_key] = False
        return False

    supports_url = False
    try:
        result = subprocess.run(
            [binary, "--help"],
            stdin=subprocess.DEVNULL,
            capture_output=True,
            text=True,
            timeout=5,
        )
        combined = f"{result.stdout}\n{result.stderr}".lower()
        supports_url = "--url" in combined
    except Exception:
        supports_url = False

    _URL_MODE_CAP_CACHE[cache_key] = supports_url
    return supports_url


def _build_binary_tui_command(
    *,
    binary: str,
    project_dir: Path,
    base_url: str,
    extra_args: list[str],
    has_url_arg: bool,
    require_url_mode: bool,
) -> list[str]:
    supports_url_mode = _binary_supports_url_mode(binary)
    if supports_url_mode:
        cmd = [binary, str(project_dir)]
        if not has_url_arg:
            cmd.extend(["--url", base_url])
        cmd.extend(extra_args)
        return cmd

    if require_url_mode:
        raise RuntimeError(
            "Downloaded Penguin TUI sidecar is not compatible with Penguin "
            "(missing '--url' support). Clear your sidecar cache or set "
            "PENGUIN_TUI_RELEASE_URL to a Penguin TUI release endpoint."
        )

    cmd = [binary, "attach", base_url, "--dir", str(project_dir)]
    cmd.extend(extra_args)
    return cmd


def _build_opencode_command(
    project_dir: Path,
    base_url: str,
    extra_args: Sequence[str],
    use_global_opencode: bool,
) -> tuple[list[str], Path | None]:
    """Resolve the best OpenCode command invocation.

    Args:
        project_dir: Target project directory for the TUI session.
        base_url: Penguin web base URL.
        extra_args: Additional args passed through to OpenCode CLI.

    Returns:
        Tuple of command argv and optional cwd for the child process.

    Raises:
        RuntimeError: If no executable strategy is available.
    """
    extra = list(extra_args)
    has_url_arg = "--url" in extra

    bun_bin = shutil.which("bun")
    local_dir = _find_local_opencode_dir()
    if bun_bin and local_dir is not None:
        cmd = [
            bun_bin,
            "run",
            "--conditions=browser",
            "./src/index.ts",
            str(project_dir),
        ]
        if not has_url_arg:
            cmd.extend(["--url", base_url])
        cmd.extend(extra)
        return cmd, local_dir

    try:
        sidecar_bin = _resolve_sidecar_binary()
        cmd = _build_binary_tui_command(
            binary=str(sidecar_bin),
            project_dir=project_dir,
            base_url=base_url,
            extra_args=extra,
            has_url_arg=has_url_arg,
            require_url_mode=True,
        )
        return cmd, None
    except RuntimeError as exc:
        sidecar_error = str(exc)

    if use_global_opencode:
        opencode_bin = shutil.which("opencode")
        if opencode_bin:
            cmd = _build_binary_tui_command(
                binary=opencode_bin,
                project_dir=project_dir,
                base_url=base_url,
                extra_args=extra,
                has_url_arg=has_url_arg,
                require_url_mode=False,
            )
            return cmd, None

    raise RuntimeError(
        "Penguin TUI runtime is not available. Install TUI support with "
        "'pip install \"penguin-ai[tui]\"'. For development, set "
        "PENGUIN_OPENCODE_DIR to your local 'penguin-tui/packages/opencode' "
        "path, or use --use-global-opencode with an installed 'opencode' binary. "
        f"Sidecar bootstrap error: {sidecar_error}"
    )


def _launcher_prog_name() -> str:
    """Return the active executable name for argparse help output."""
    script_name = Path(sys.argv[0]).name.strip()
    return script_name or "penguin"


def _ensure_web_runtime_available() -> None:
    """Fail fast when local web autostart prerequisites are missing."""
    try:
        import fastapi  # noqa: F401
        import uvicorn  # noqa: F401
    except Exception as exc:
        raise RuntimeError(
            "Penguin web autostart requires web dependencies. "
            "Install with 'pip install \"penguin-ai[tui]\"' (or [web]) and retry."
        ) from exc


def _parse_args(
    argv: Sequence[str] | None = None,
) -> tuple[argparse.Namespace, list[str]]:
    """Parse launcher arguments while preserving unknown OpenCode args.

    Args:
        argv: Optional raw argv list.

    Returns:
        Parsed known args and unknown pass-through args.
    """
    parser = argparse.ArgumentParser(
        prog=_launcher_prog_name(),
        description="Launch Penguin TUI with Penguin web auto-start.",
    )
    parser.add_argument(
        "project",
        nargs="?",
        default=".",
        help="Project directory (defaults to current working directory).",
    )
    parser.add_argument(
        "--url",
        default=os.getenv("PENGUIN_WEB_URL", "http://localhost:8000"),
        help="Penguin web base URL (default: %(default)s).",
    )
    parser.add_argument(
        "--no-web-autostart",
        action="store_true",
        help="Do not auto-start Penguin web when it is not reachable.",
    )
    parser.add_argument(
        "--web-timeout",
        type=float,
        default=60.0,
        help="Seconds to wait for auto-started web server health.",
    )
    parser.add_argument(
        "--use-global-opencode",
        action="store_true",
        help="Use global 'opencode' binary instead of local penguin-tui sources.",
    )
    return parser.parse_known_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    """Entry point for the OpenCode launcher command.

    Args:
        argv: Optional argument vector.

    Returns:
        Process exit code.
    """
    args, extra_args = _parse_args(argv)

    try:
        base_url = _normalize_base_url(args.url)
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    project_dir = Path(args.project).expanduser().resolve()
    if not project_dir.exists() or not project_dir.is_dir():
        print(
            f"Error: project directory does not exist: {project_dir}", file=sys.stderr
        )
        return 2

    env = dict(os.environ)
    env["PENGUIN_CWD"] = str(project_dir)
    env["PENGUIN_PROJECT_ROOT"] = str(project_dir)
    env["PENGUIN_WRITE_ROOT"] = "project"
    env["PENGUIN_WEB_URL"] = base_url
    # OpenCode thread bootstrap prefers process.env.PWD for base directory.
    # Force it to the requested target project when launched via uvx/tool shims.
    env["PWD"] = str(project_dir)

    server_proc: subprocess.Popen[str] | None = None
    cleanup_registered = False

    should_try_web_start = _is_local_url(base_url) and not args.no_web_autostart
    if not _is_server_running(base_url):
        if should_try_web_start:
            try:
                _ensure_web_runtime_available()
            except RuntimeError as exc:
                print(f"Error: {exc}", file=sys.stderr)
                return 1
            print(f"Starting Penguin web server at {base_url}...", file=sys.stderr)
            server_proc = _start_web_server(base_url, env)
            atexit.register(_stop_process, server_proc)
            cleanup_registered = True
            if not _wait_for_server(
                base_url, server_proc, timeout_seconds=args.web_timeout
            ):
                _stop_process(server_proc)
                print(
                    (
                        "Error: Penguin web did not become healthy at "
                        f"{_health_url(base_url)}"
                    ),
                    file=sys.stderr,
                )
                return 1
        elif args.no_web_autostart:
            print(
                (
                    "Warning: Penguin web is not reachable at "
                    f"{base_url}; continuing without auto-start."
                ),
                file=sys.stderr,
            )
        else:
            print(
                "Warning: URL is non-local and not reachable; skipping auto-start.",
                file=sys.stderr,
            )

    try:
        opencode_cmd, opencode_cwd = _build_opencode_command(
            project_dir,
            base_url,
            extra_args,
            use_global_opencode=args.use_global_opencode,
        )
    except RuntimeError as exc:
        if cleanup_registered:
            _stop_process(server_proc)
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    try:
        result = subprocess.run(opencode_cmd, cwd=opencode_cwd, env=env)
        return result.returncode
    except KeyboardInterrupt:
        return 130
    finally:
        if cleanup_registered:
            _stop_process(server_proc)


if __name__ == "__main__":
    raise SystemExit(main())
