"""Penguin Web Server - Entry point for running the web interface.

This module provides the main entry point for running the Penguin web server.
It uses the app factory from app.py to create and configure the FastAPI application.
"""

import logging
import os
from ipaddress import ip_address

logger = logging.getLogger(__name__)

DEFAULT_HOST = "127.0.0.1"
LOCAL_ONLY_HOSTS = {"127.0.0.1", "localhost", "::1"}


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

    auth_enabled = os.environ.get("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
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
        "Refusing to bind Penguin web server to a non-local host without authentication. "
        "Set PENGUIN_AUTH_ENABLED=true or explicitly override with "
        "PENGUIN_ALLOW_INSECURE_NO_AUTH=true."
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


def _display_host(host: str) -> str:
    """Return the user-facing host for startup messaging."""
    return "localhost" if host in {"0.0.0.0", "::", ""} else host


def _print_startup_banner(host: str, port: int) -> None:
    """Print startup information using the actual configured address."""
    display_host = _display_host(host)
    print("\n\033[96m=== Penguin AI Server ===\033[0m")
    print(f"\033[96mVisit http://{display_host}:{port} to start using Penguin!\033[0m")
    print(f"\033[96mAPI documentation: http://{display_host}:{port}/api/docs\033[0m\n")


def _print_local_auth_bootstrap_banner(host: str, port: int) -> None:
    """Print one-time local authorization instructions when bootstrap auth is enabled."""
    try:
        from .middleware.auth import AuthConfig, get_startup_auth_token
    except ImportError:
        return

    auth_config = AuthConfig()
    startup_token = get_startup_auth_token(auth_config)
    if not startup_token:
        return

    display_host = _display_host(host)
    print("\033[93mLocal Penguin authorization is enabled.\033[0m")
    print(
        f"\033[93mRedeem the startup token at http://{display_host}:{port}/api/v1/auth/session\033[0m"
    )
    print(f"\033[93mStartup token: {startup_token}\033[0m\n")


def main():
    """Entry point for the web server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: Web dependencies not available.")
        print("Install with: pip install penguin-ai[web]")
        return 1

    host = os.environ.get("HOST", DEFAULT_HOST)
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    app = None

    try:
        validate_startup_security(host)
        if debug:
            create_app_factory()
        else:
            app = create_app_factory()
    except Exception as e:
        print(f"Error: Failed to initialize Penguin web application: {e}")
        return 1

    _print_startup_banner(host, port)
    _print_local_auth_bootstrap_banner(host, port)

    if debug:
        uvicorn.run(
            "penguin.web.server:create_app_factory",
            host=host,
            port=port,
            log_level="debug",
            reload=True,
            factory=True,
        )
        return 0

    if app is None:
        return 1

    uvicorn.run(app, host=host, port=port, log_level="info", reload=False)

    return 0


def start_server(host: str = DEFAULT_HOST, port: int = 8000, debug: bool = False):
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

    validate_startup_security(host)
    if debug:
        uvicorn.run(
            "penguin.web.server:create_app_factory",
            host=host,
            port=port,
            log_level="debug",
            reload=True,
            factory=True,
        )
        return

    app = create_app_factory()
    uvicorn.run(app, host=host, port=port, log_level="info", reload=False)


if __name__ == "__main__":
    exit(main())
