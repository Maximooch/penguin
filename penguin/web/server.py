"""Penguin Web Server - Entry point for running the web interface.

This module provides the main entry point for running the Penguin web server.
It uses the app factory from app.py to create and configure the FastAPI application.
"""

import logging
import os

logger = logging.getLogger(__name__)


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
    print(
        f"\033[96mVisit http://{display_host}:{port} to start using Penguin!\033[0m"
    )
    print(
        f"\033[96mAPI documentation: http://{display_host}:{port}/api/docs\033[0m\n"
    )


def main():
    """Entry point for the web server."""
    try:
        import uvicorn
    except ImportError:
        print("Error: Web dependencies not available.")
        print("Install with: pip install penguin-ai[web]")
        return 1

    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"

    try:
        if debug:
            create_app_factory()
            app = None
        else:
            app = create_app_factory()
    except Exception as e:
        print(f"Error: Failed to initialize Penguin web application: {e}")
        return 1

    _print_startup_banner(host, port)

    if debug:
        uvicorn.run(
            "penguin.web.server:create_app_factory",
            host=host,
            port=port,
            log_level="debug",
            reload=True,
            factory=True,
        )
    else:
        uvicorn.run(app, host=host, port=port, log_level="info", reload=False)

    return 0


def start_server(host: str = "0.0.0.0", port: int = 8000, debug: bool = False):
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
