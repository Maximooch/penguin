"""Penguin Web Server - Entry point for running the web interface.

This module provides the main entry point for running the Penguin web server.
It uses the app factory from app.py to create and configure the FastAPI application.
"""

import argparse
import json
import logging
import os
import sys
from datetime import datetime, timezone
from ipaddress import ip_address
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Optional, Sequence
from urllib.parse import quote

from penguin.constants import DEFAULT_WEB_PORT
from penguin.local_auth import is_web_auth_enabled, write_local_auth_token
from penguin.web.runtime_storage import (
    RuntimeStorageLayout,
    RuntimeStorageLease,
    resolve_runtime_storage,
)

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
LOCAL_ONLY_HOSTS = {"127.0.0.1", "localhost", "::1"}
SERVER_LOG_DIRNAME = "server-logs"
SERVER_LOG_FILENAME_PREFIX = "penguin-web"
SERVER_LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
SERVER_LOG_HANDLER_FLAG = "_penguin_web_server_file_handler"


def _coerce_int_env(name: str, default: int) -> int:
    """Return a positive integer environment value or a safe default."""
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        value = int(raw)
    except ValueError:
        logger.warning("Invalid %s=%r; using default %s", name, raw, default)
        return default
    return value if value > 0 else default


def _web_server_file_logging_enabled() -> bool:
    """Return whether web server file logging should be configured."""
    value = os.environ.get("PENGUIN_WEB_LOG_ENABLED", "true").strip().lower()
    return value not in {"0", "false", "no", "off"}


def _new_server_log_filename() -> str:
    """Return a unique text filename for one web server process run."""
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    return f"{SERVER_LOG_FILENAME_PREFIX}-{timestamp}-{os.getpid()}.txt"


def _resolve_server_log_path() -> Path:
    """Resolve the managed web server log file path."""
    override = os.environ.get("PENGUIN_WEB_LOG_FILE", "").strip()
    if override:
        return Path(override).expanduser().resolve()

    directory_override = os.environ.get("PENGUIN_WEB_LOG_DIR", "").strip()
    if directory_override:
        return (
            Path(directory_override).expanduser().resolve() / _new_server_log_filename()
        )

    from penguin.config import get_workspace_root

    return (
        get_workspace_root().expanduser().resolve()
        / SERVER_LOG_DIRNAME
        / _new_server_log_filename()
    )


def _attach_startup_file_handler(log_path: Path, log_level: int) -> None:
    """Attach an idempotent startup file handler before uvicorn takes over."""
    root_logger = logging.getLogger()
    root_logger.setLevel(min(root_logger.level or log_level, log_level))

    for handler in list(root_logger.handlers):
        if not getattr(handler, SERVER_LOG_HANDLER_FLAG, False):
            continue
        if Path(getattr(handler, "baseFilename", "")) == log_path:
            handler.setLevel(log_level)
            return
        root_logger.removeHandler(handler)
        handler.close()

    handler = RotatingFileHandler(
        log_path,
        maxBytes=_coerce_int_env("PENGUIN_WEB_LOG_MAX_BYTES", 5 * 1024 * 1024),
        backupCount=_coerce_int_env("PENGUIN_WEB_LOG_BACKUP_COUNT", 3),
        encoding="utf-8",
    )
    handler.setLevel(log_level)
    handler.setFormatter(logging.Formatter(SERVER_LOG_FORMAT))
    setattr(handler, SERVER_LOG_HANDLER_FLAG, True)
    root_logger.addHandler(handler)


def _build_uvicorn_log_config(log_path: Path, log_level: str) -> dict[str, Any]:
    """Build uvicorn logging config that preserves console output and adds a file."""
    max_bytes = _coerce_int_env("PENGUIN_WEB_LOG_MAX_BYTES", 5 * 1024 * 1024)
    backup_count = _coerce_int_env("PENGUIN_WEB_LOG_BACKUP_COUNT", 3)
    return {
        "version": 1,
        "disable_existing_loggers": False,
        "formatters": {
            "default": {
                "()": "uvicorn.logging.DefaultFormatter",
                "fmt": "%(levelprefix)s %(message)s",
                "use_colors": None,
            },
            "access": {
                "()": "uvicorn.logging.AccessFormatter",
                "fmt": (
                    '%(levelprefix)s %(client_addr)s - "%(request_line)s" '
                    "%(status_code)s"
                ),
            },
            "file": {
                "format": SERVER_LOG_FORMAT,
            },
        },
        "handlers": {
            "default": {
                "formatter": "default",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stderr",
            },
            "access": {
                "formatter": "access",
                "class": "logging.StreamHandler",
                "stream": "ext://sys.stdout",
            },
            "file": {
                "formatter": "file",
                "class": "logging.handlers.RotatingFileHandler",
                "filename": str(log_path),
                "maxBytes": max_bytes,
                "backupCount": backup_count,
                "encoding": "utf-8",
            },
        },
        "loggers": {
            "uvicorn": {
                "handlers": ["default", "file"],
                "level": log_level.upper(),
                "propagate": False,
            },
            "uvicorn.error": {
                "level": log_level.upper(),
            },
            "uvicorn.access": {
                "handlers": ["access", "file"],
                "level": log_level.upper(),
                "propagate": False,
            },
        },
        "root": {
            "handlers": ["file"],
            "level": log_level.upper(),
        },
    }


def _configure_server_file_logging(log_level: str) -> Optional[dict[str, Any]]:
    """Configure managed web server file logging and return uvicorn config."""
    if not _web_server_file_logging_enabled():
        return None

    try:
        log_path = _resolve_server_log_path()
        log_path.parent.mkdir(parents=True, exist_ok=True)
        numeric_level = logging.getLevelName(log_level.upper())
        if not isinstance(numeric_level, int):
            numeric_level = logging.INFO
        _attach_startup_file_handler(log_path, numeric_level)
    except OSError as exc:
        logger.warning("Failed to configure Penguin web server file logging: %s", exc)
        return None

    logger.info("Penguin web server logs writing to %s", log_path)
    return _build_uvicorn_log_config(log_path, log_level)


def _is_local_host(host: str) -> bool:
    """Return whether the bind host is limited to local access."""
    normalized = (host or "").strip().lower()
    if normalized in LOCAL_ONLY_HOSTS:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def validate_startup_security(host: str) -> None:
    """Fail fast for insecure broad-bind deployments unless explicitly allowed."""
    if _is_local_host(host):
        return

    auth_enabled = is_web_auth_enabled()
    if auth_enabled:
        return

    allow_insecure = (
        os.environ.get("PENGUIN_ALLOW_INSECURE_NO_AUTH", "false").lower() == "true"
    )
    if allow_insecure:
        logger.warning(
            "Starting Penguin web server without auth on non-local host %s because "
            "PENGUIN_ALLOW_INSECURE_NO_AUTH=true",
            host,
        )
        return

    raise RuntimeError(
        "Refusing to bind Penguin web server to a non-local host with auth disabled. "
        "Remove PENGUIN_AUTH_ENABLED=false, switch to HOST=127.0.0.1 "
        "for local-only use, "
        "or explicitly override with PENGUIN_ALLOW_INSECURE_NO_AUTH=true."
    )


def create_app_factory():
    """Create the FastAPI application lazily for uvicorn."""
    try:
        from .app import create_app
    except ImportError as exc:
        raise ImportError(
            "Web dependencies not available. Install with: pip install penguin-ai[web]"
        ) from exc

    return create_app()


def _validate_app_factory_import() -> None:
    """Validate web dependencies without constructing a reload-parent app."""

    try:
        from .app import create_app
    except ImportError as exc:
        raise ImportError(
            "Web dependencies not available. Install with: pip install penguin-ai[web]"
        ) from exc
    if not callable(create_app):
        raise RuntimeError("Penguin web application factory is not callable")


def _display_host(host: str) -> str:
    """Return the user-facing host for startup messaging."""
    return "localhost" if host in {"0.0.0.0", "::", ""} else host


def _resolve_port() -> int:
    """Parse the configured web port with a controlled error path."""
    raw = os.environ.get("PORT", str(DEFAULT_WEB_PORT))
    try:
        return int(raw)
    except ValueError as exc:
        raise RuntimeError(
            f"Invalid PORT value {raw!r}. Set PORT to an integer port number."
        ) from exc


def _build_arg_parser() -> argparse.ArgumentParser:
    """Build CLI parser for the web server entrypoint."""
    parser = argparse.ArgumentParser(prog="penguin-web")
    parser.add_argument("--host", help="Bind host override")
    parser.add_argument("--port", type=int, help="Bind port override")
    parser.add_argument(
        "--debug",
        action="store_true",
        help="Enable debug mode with uvicorn reload",
    )
    return parser


def _resolve_runtime_settings(
    argv: Optional[Sequence[str]] = None,
) -> tuple[str, int, bool]:
    """Resolve host/port/debug from CLI args first, then env vars."""
    parser = _build_arg_parser()
    args = parser.parse_args(list(argv) if argv is not None else [])

    host = args.host or os.environ.get("HOST", DEFAULT_HOST)

    if args.port is not None:
        port = args.port
    else:
        port = _resolve_port()

    env_debug = os.environ.get("DEBUG", "false").lower() == "true"
    debug = args.debug or env_debug
    return host, port, debug


def _print_startup_banner(host: str, port: int) -> None:
    """Print startup information using the actual configured address."""
    display_host = _display_host(host)
    print("\n\033[96m=== Penguin Server ===\033[0m")
    print(f"\033[96mVisit http://{display_host}:{port} to start using Penguin!\033[0m")
    print(f"\033[96mAPI documentation: http://{display_host}:{port}/api/docs\033[0m\n")


def _log_runtime_storage(layout: RuntimeStorageLayout) -> None:
    """Log one privacy-safe storage ownership record at startup."""

    logger.info(
        "Penguin runtime storage: %s",
        json.dumps(layout.to_diagnostics(), sort_keys=True),
    )


def _print_no_auth_warning(host: str, port: int) -> None:
    """Print a clear warning when Penguin starts without authentication."""
    display_host = _display_host(host)
    if _is_local_host(host):
        print(
            "\033[93mWarning: Penguin local web auth is explicitly disabled "
            "for this session.\033[0m"
        )
        print(
            f"\033[93mThis instance is reachable at "
            f"http://{display_host}:{port} without authentication.\033[0m"
        )
        print(
            "\033[93mProtected local startup is the default: uv run penguin-web\033[0m"
        )
        print(
            "\033[93mTo keep auth disabled intentionally: "
            "PENGUIN_AUTH_ENABLED=false uv run penguin-web\033[0m\n"
        )
        return

    print(
        "\033[91mWarning: Penguin is exposed on a non-local host "
        "without authentication.\033[0m"
    )
    print(
        "\033[91mThis is only allowed because "
        "PENGUIN_ALLOW_INSECURE_NO_AUTH=true is set.\033[0m"
    )
    print(
        "\033[93mSafer options: remove PENGUIN_AUTH_ENABLED=false "
        "or switch back to HOST=127.0.0.1.\033[0m\n"
    )


def _print_local_auth_bootstrap_banner(host: str, port: int) -> None:
    """Print startup guidance when local web auth is enabled."""
    try:
        from .middleware.auth import AuthConfig, get_startup_auth_token
    except ImportError:
        return

    auth_config = AuthConfig()
    startup_token = get_startup_auth_token(auth_config)
    display_host = _display_host(host)
    print("\033[93mPenguin local web auth is enabled.\033[0m")
    if startup_token:
        try:
            write_local_auth_token(startup_token, host=host, port=port)
        except Exception as exc:
            logger.warning(
                "Failed to write local auth token cache for %s:%s: %s",
                host,
                port,
                exc,
            )
        encoded_token = quote(startup_token, safe="")
        bootstrap_url = (
            f"http://{display_host}:{port}/authorize#local_token={encoded_token}"
        )
        print(
            "\033[93mBrowser/dashboard only: open this local authorization "
            "URL once for this browser.\033[0m"
        )
        print(f"\033[93m  {bootstrap_url}\033[0m")
        print(f"\033[93mStartup token (debug fallback): {startup_token}\033[0m")
    else:
        print(
            "\033[93mBrowser/dashboard: authorize with a configured API key "
            "at /api/v1/auth/session if needed.\033[0m"
        )
    print("\033[93mTUI/CLI: local Penguin sessions authenticate automatically.\033[0m")
    print(
        "\033[93mCI/headless: use PENGUIN_API_KEYS with X-API-Key header auth.\033[0m"
    )
    print(
        "\033[93mTo explicitly run local-only without auth: "
        "PENGUIN_AUTH_ENABLED=false uv run penguin-web\033[0m\n"
    )


def main(argv: Optional[Sequence[str]] = None):
    """Entry point for the web server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: Web dependencies not available.")
        print("Install with: pip install penguin-ai[web]")
        return 1

    storage_lease: Optional[RuntimeStorageLease] = None
    try:
        host, port, debug = _resolve_runtime_settings(argv)
        storage_layout = resolve_runtime_storage(host=host, port=port)
        storage_lease = RuntimeStorageLease(storage_layout).acquire()
        log_level = "debug" if debug else "info"
        log_config = _configure_server_file_logging(log_level)
        _log_runtime_storage(storage_layout)
        app = None
        validate_startup_security(host)
        if debug:
            _validate_app_factory_import()
        else:
            app = create_app_factory()
    except Exception as e:
        if storage_lease is not None:
            storage_lease.release()
        print(f"Error: Failed to initialize Penguin web application: {e}")
        return 1

    try:
        _print_startup_banner(host, port)
        auth_enabled = is_web_auth_enabled()
        if auth_enabled:
            _print_local_auth_bootstrap_banner(host, port)
        else:
            _print_no_auth_warning(host, port)

        if debug:
            uvicorn.run(
                "penguin.web.server:create_app_factory",
                host=host,
                port=port,
                log_level=log_level,
                log_config=log_config,
                reload=True,
                factory=True,
            )
            return 0

        if app is None:
            return 1

        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level,
            log_config=log_config,
            reload=False,
        )

        return 0
    finally:
        if storage_lease is not None:
            storage_lease.release()


def start_server(
    host: str = DEFAULT_HOST, port: int = DEFAULT_WEB_PORT, debug: bool = False
):
    """Start the web server programmatically.

    Args:
        host: Host to bind the server to
        port: Port to bind the server to
        debug: Enable debug mode with auto-reload
    """
    try:
        import uvicorn
    except ImportError as exc:
        raise ImportError(
            "Web dependencies not available. Install with: pip install penguin-ai[web]"
        ) from exc

    storage_layout = resolve_runtime_storage(host=host, port=port)
    with RuntimeStorageLease(storage_layout):
        log_level = "debug" if debug else "info"
        log_config = _configure_server_file_logging(log_level)
        _log_runtime_storage(storage_layout)
        validate_startup_security(host)

        if debug:
            uvicorn.run(
                "penguin.web.server:create_app_factory",
                host=host,
                port=port,
                log_level=log_level,
                log_config=log_config,
                reload=True,
                factory=True,
            )
            return

        app = create_app_factory()
        uvicorn.run(
            app,
            host=host,
            port=port,
            log_level=log_level,
            log_config=log_config,
            reload=False,
        )


if __name__ == "__main__":
    exit(main(sys.argv[1:]))
