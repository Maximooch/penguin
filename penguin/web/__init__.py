"""Penguin Web - Web Interface and API for Penguin AI Assistant.

This module provides web-based interfaces for Penguin, including:
- FastAPI-based REST API
- WebSocket support for real-time communication
- Static file serving for web UI
- Optional Streamlit integration

Example Usage:
    ```python
    from penguin.web import create_app, PenguinAPI

    # Create FastAPI application
    app = create_app()

    # Or use the API class directly
    api = PenguinAPI()
    await api.chat("Hello, how can you help me?")
    ```

Installation:
    The web interface requires additional dependencies:
    ```bash
    pip install penguin-ai[web]
    ```
"""

from importlib import import_module
from typing import Any, Optional

from penguin.constants import DEFAULT_WEB_PORT

# Web application - will be imported when FastAPI is available
_web_app: Optional[object] = None


def get_web_app():
    """Get the web application instance.

    Returns:
        The FastAPI application, or None if web dependencies not available
    """
    global _web_app
    if _web_app is None:
        try:
            from .app import create_app

            _web_app = create_app()
        except ImportError:
            # Web dependencies not available
            return None
    return _web_app


__all__ = [
    "PenguinAPI",
    "PenguinWeb",
    "api_router",
    "create_app",
    "get_web_app",
    "main",
    "start_server",
]


def __getattr__(name: str) -> Any:
    """Load optional web exports without importing config at package import time.

    Keeping ``penguin.web`` lazy is a correctness requirement for the isolated
    8080 launcher: its environment must be installed before application/config
    modules resolve or create mutable workspace paths.
    """

    if name in {"create_app", "PenguinAPI"}:
        value = getattr(import_module(".app", __name__), name)
    elif name == "api_router":
        value = getattr(import_module(".routes", __name__), "router")
    elif name in {"start_server", "main"}:
        value = getattr(import_module(".server", __name__), name)
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value


class PenguinWeb:
    """Main web interface class for programmatic access."""

    def __init__(self, host: str = "localhost", port: int = DEFAULT_WEB_PORT):
        """Initialize web interface.

        Args:
            host: Host to bind the server to
            port: Port to bind the server to
        """
        self.host = host
        self.port = port
        self.app = get_web_app()
        if not self.app:
            raise ImportError(
                "Web dependencies not available. Install with: "
                "pip install penguin-ai[web]"
            )

    def run(self, **kwargs):
        """Run the web server with uvicorn."""
        try:
            import uvicorn

            uvicorn.run(self.app, host=self.host, port=self.port, **kwargs)
        except ImportError:
            raise ImportError(
                "uvicorn not available. Install with: pip install penguin-ai[web]"
            )
