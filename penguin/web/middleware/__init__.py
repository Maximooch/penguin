"""Middleware components for Penguin web API."""

from .auth import (
    AuthenticationMiddleware,
    AuthConfig,
    AuthenticationError,
    require_auth,
)

__all__ = [
    "AuthenticationMiddleware",
    "AuthConfig",
    "AuthenticationError",
    "require_auth",
]
