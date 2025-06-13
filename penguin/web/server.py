"""Penguin Web Server - Entry point for running the web interface.

This module provides the main entry point for running the Penguin web server.
It uses the app factory from app.py to create and configure the FastAPI application.
"""

import os
import logging

logger = logging.getLogger(__name__)

def main():
    """Entry point for the web server."""
    try:
        import uvicorn
        from .app import create_app
    except ImportError:
        print("Error: Web dependencies not available.")
        print("Install with: pip install penguin-ai[web]")
        return 1
    
    # Create the application
    try:
        app = create_app()
    except Exception as e:
        print(f"Error: Failed to initialize Penguin web application: {e}")
        return 1
    
    # Display startup information
    print("\n\033[96m=== Penguin AI Server ===\033[0m")
    print("\033[96mVisit http://localhost:8000 to start using Penguin!\033[0m")
    print("\033[96mAPI documentation: http://localhost:8000/api/docs\033[0m\n")
    
    # Get configuration from environment
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    debug = os.environ.get("DEBUG", "false").lower() == "true"
    
    # Start the server
    uvicorn.run(
        app, 
        host=host, 
        port=port,
        log_level="debug" if debug else "info",
        reload=debug  # Enable auto-reload in debug mode
    )
    
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
        from .app import create_app
    except ImportError:
        raise ImportError(
            "Web dependencies not available. Install with: pip install penguin-ai[web]"
        )
    
    app = create_app()
    
    uvicorn.run(
        app,
        host=host,
        port=port,
        log_level="debug" if debug else "info",
        reload=debug
    )


if __name__ == "__main__":
    exit(main())
