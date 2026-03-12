"""Launch the Penguin TUI against Penguin web with sane local defaults.

This launcher is intended for local workflows where Penguin web and the
Penguin TUI are run together from a terminal.
"""

from __future__ import annotations

import argparse
import atexit
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Sequence
from urllib.error import URLError
from urllib.parse import urlparse, urlunparse
from urllib.request import urlopen

LOCAL_HOSTS = {"", "localhost", "127.0.0.1", "0.0.0.0", "::1"}


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

    if use_global_opencode:
        opencode_bin = shutil.which("opencode")
        if opencode_bin:
            cmd = [opencode_bin, str(project_dir)]
            # Global OpenCode builds may not expose --url. Prefer env-based routing.
            cmd.extend(extra)
            return cmd, None

    raise RuntimeError(
        "Penguin TUI runtime is not available. Install TUI support with "
        "'pip install \"penguin-ai[tui]\"'. For development, set "
        "PENGUIN_OPENCODE_DIR to your local 'penguin-tui/packages/opencode' "
        "path, or use --use-global-opencode with an installed 'opencode' binary."
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
