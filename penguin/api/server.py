# Legacy API server - redirects to penguin.web for backwards compatibility
# This module is kept for backwards compatibility with existing imports
# The canonical server is now penguin.web.server

from penguin.web.server import main, start_server
from penguin.web.app import create_app

__all__ = ["main", "start_server", "create_app"]
