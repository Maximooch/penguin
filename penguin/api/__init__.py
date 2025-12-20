# Legacy API module - routes have been migrated to penguin.web.routes
# This module is kept for backwards compatibility with existing imports
from .server import create_app

__all__ = ["create_app"]
