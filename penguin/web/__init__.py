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

from typing import Optional

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


# Try to expose web components
try:
    from .app import create_app, PenguinAPI
    from .routes import router as api_router
    from .server import start_server, main
    
    __all__ = [
        "create_app",
        "PenguinAPI", 
        "api_router",
        "start_server",
        "main",
        "get_web_app",
        "PenguinWeb"
    ]
    
except ImportError:
    # Web dependencies not available (minimal install)
    __all__ = ["get_web_app"]


class PenguinWeb:
    """Main web interface class for programmatic access."""
    
    def __init__(self, host: str = "localhost", port: int = 8000):
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
                "Web dependencies not available. Install with: pip install penguin-ai[web]"
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
