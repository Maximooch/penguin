"""Authentication middleware for Penguin web API.

Supports both API key and JWT token authentication for Link integration
and other external clients.
"""

import logging
import os
from typing import Any, Optional
from datetime import datetime, timedelta

from fastapi import HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
import jwt

logger = logging.getLogger(__name__)

# Security scheme for Bearer token
security = HTTPBearer(auto_error=False)


class AuthenticationError(Exception):
    """Raised when authentication fails."""
    pass


class AuthConfig:
    """Authentication configuration."""

    def __init__(self):
        # API Key authentication
        self.api_keys = self._load_api_keys()

        # JWT authentication
        self.jwt_secret = os.getenv("PENGUIN_JWT_SECRET")
        self.jwt_algorithm = os.getenv("PENGUIN_JWT_ALGORITHM", "HS256")
        self.jwt_expiration_hours = int(os.getenv("PENGUIN_JWT_EXPIRATION_HOURS", "24"))

        # Link-specific configuration
        self.link_api_key = os.getenv("LINK_API_KEY")
        self.link_auth_required = os.getenv("PENGUIN_LINK_AUTH_REQUIRED", "false").lower() == "true"

        # General auth settings
        self.auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
        self.public_endpoints = self._load_public_endpoints()

    def _load_api_keys(self) -> set:
        """Load valid API keys from environment."""
        keys = set()

        # Load from PENGUIN_API_KEYS (comma-separated)
        api_keys_str = os.getenv("PENGUIN_API_KEYS", "")
        if api_keys_str:
            keys.update(k.strip() for k in api_keys_str.split(",") if k.strip())

        # Load Link API key if present
        link_key = os.getenv("LINK_API_KEY")
        if link_key:
            keys.add(link_key.strip())

        return keys

    def _load_public_endpoints(self) -> set:
        """Load endpoints that don't require authentication."""
        public = {
            "/",
            "/api/docs",
            "/api/redoc",
            "/api/openapi.json",
            "/api/v1/health",
            "/static/",
        }

        # Load additional public endpoints from environment
        public_str = os.getenv("PENGUIN_PUBLIC_ENDPOINTS", "")
        if public_str:
            public.update(p.strip() for p in public_str.split(",") if p.strip())

        return public

    @property
    def public_endpoint_prefixes(self) -> set[str]:
        """Return public endpoints that should be treated as prefixes."""
        return {path for path in self.public_endpoints if path.endswith("/") and path != "/"}

    @property
    def public_endpoint_exact_matches(self) -> set[str]:
        """Return public endpoints that require exact path matches."""
        return self.public_endpoints - self.public_endpoint_prefixes

    def is_public_endpoint(self, path: str) -> bool:
        """Check if an endpoint is public (doesn't require auth)."""
        if path in self.public_endpoint_exact_matches:
            return True

        return any(path.startswith(prefix) for prefix in self.public_endpoint_prefixes)


class AuthenticationMiddleware(BaseHTTPMiddleware):
    """Middleware for authenticating API requests."""

    def __init__(self, app, config: Optional[AuthConfig] = None):
        super().__init__(app)
        self.config = config or AuthConfig()

    async def dispatch(self, request: Request, call_next):
        """Process request and validate authentication."""
        # Skip auth if disabled
        if not self.config.auth_enabled:
            return await call_next(request)

        # Skip auth for public endpoints
        if self.config.is_public_endpoint(request.url.path):
            return await call_next(request)

        try:
            auth_result = await self._authenticate_request(request)
        except AuthenticationError as e:
            logger.warning(f"Authentication failed for {request.url.path}: {str(e)}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={
                    "detail": {
                        "error": {
                            "code": "AUTHENTICATION_FAILED",
                            "message": str(e),
                            "recoverable": False,
                            "suggested_action": "check_credentials",
                        }
                    }
                },
                headers={"WWW-Authenticate": "Bearer"},
            )
        except Exception as e:
            logger.error(f"Unexpected error in authentication: {str(e)}")
            return JSONResponse(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                content={
                    "detail": {
                        "error": {
                            "code": "AUTHENTICATION_ERROR",
                            "message": "Internal authentication error",
                            "recoverable": True,
                            "suggested_action": "retry",
                        }
                    }
                },
            )

        # Add auth info to request state
        request.state.authenticated = True
        request.state.auth_method = auth_result["method"]
        request.state.auth_subject = auth_result.get("subject", "unknown")
        request.state.auth_metadata = auth_result.get("metadata", {})

        return await call_next(request)

    async def _authenticate_request(self, request: Request) -> dict:
        """Authenticate a request using available methods."""
        # Try API key authentication first (faster)
        api_key = self._extract_api_key(request)
        if api_key and self._validate_api_key(api_key):
            return {
                "method": "api_key",
                "subject": "api_client",
                "metadata": {"key_prefix": api_key[:8] + "..."}
            }

        # Try JWT authentication
        token = self._extract_bearer_token(request)
        if token:
            claims = self._validate_jwt(token)
            return {
                "method": "jwt",
                "subject": claims.get("sub", "unknown"),
                "metadata": claims
            }

        # No valid authentication found
        raise AuthenticationError("No valid authentication credentials provided")

    def _extract_api_key(self, connection: Any) -> Optional[str]:
        """Extract API key from request or websocket headers."""
        headers = connection.headers

        # Check X-API-Key header
        api_key = headers.get("X-API-Key")
        if api_key:
            return api_key

        # Check X-Link-API-Key header (Link-specific)
        link_key = headers.get("X-Link-API-Key")
        if link_key:
            return link_key

        return None

    def _extract_bearer_token(self, connection: Any) -> Optional[str]:
        """Extract Bearer token from Authorization header."""
        auth_header = connection.headers.get("Authorization")
        if not auth_header:
            return None

        parts = auth_header.split()
        if len(parts) != 2 or parts[0].lower() != "bearer":
            return None

        return parts[1]

    def _validate_api_key(self, api_key: str) -> bool:
        """Validate an API key."""
        if not api_key:
            return False

        # Check against configured keys
        return api_key in self.config.api_keys

    def _validate_jwt(self, token: str) -> dict:
        """Validate and decode a JWT token."""
        if not self.config.jwt_secret:
            raise AuthenticationError("JWT authentication not configured")

        try:
            # Decode and validate token
            claims = jwt.decode(
                token,
                self.config.jwt_secret,
                algorithms=[self.config.jwt_algorithm]
            )

            # Check expiration
            if "exp" in claims:
                exp_timestamp = claims["exp"]
                if datetime.utcfromtimestamp(exp_timestamp) < datetime.utcnow():
                    raise AuthenticationError("Token has expired")

            return claims

        except jwt.ExpiredSignatureError:
            raise AuthenticationError("Token has expired")
        except jwt.InvalidTokenError as e:
            raise AuthenticationError(f"Invalid token: {str(e)}")

    def create_jwt(self, subject: str, metadata: Optional[dict] = None) -> str:
        """Create a JWT token for a subject.

        Args:
            subject: Subject identifier (user ID, service name, etc.)
            metadata: Additional claims to include in the token

        Returns:
            Encoded JWT token
        """
        if not self.config.jwt_secret:
            raise ValueError("JWT secret not configured")

        # Build claims
        claims = {
            "sub": subject,
            "iat": datetime.utcnow(),
            "exp": datetime.utcnow() + timedelta(hours=self.config.jwt_expiration_hours)
        }

        # Add metadata
        if metadata:
            claims.update(metadata)

        # Encode token
        token = jwt.encode(
            claims,
            self.config.jwt_secret,
            algorithm=self.config.jwt_algorithm
        )

        return token


# Dependency for route-level auth
async def require_auth(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = None
) -> dict:
    """FastAPI dependency for requiring authentication.

    Usage:
        @router.get("/protected")
        async def protected_endpoint(auth: dict = Depends(require_auth)):
            return {"user": auth["subject"]}
    """
    if not hasattr(request.state, "authenticated") or not request.state.authenticated:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "AUTHENTICATION_REQUIRED",
                    "message": "Authentication required for this endpoint",
                    "recoverable": False,
                    "suggested_action": "provide_credentials"
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "method": request.state.auth_method,
        "subject": request.state.auth_subject,
        "metadata": request.state.auth_metadata
    }


def authenticate_connection(
    connection: Any,
    config: Optional[AuthConfig] = None,
) -> dict:
    """Authenticate an HTTP or WebSocket connection using shared auth rules."""
    auth_config = config or AuthConfig()
    middleware = AuthenticationMiddleware(app=lambda scope, receive, send: None, config=auth_config)

    api_key = middleware._extract_api_key(connection)
    if api_key and middleware._validate_api_key(api_key):
        return {
            "method": "api_key",
            "subject": "api_client",
            "metadata": {"key_prefix": api_key[:8] + "..."},
        }

    token = middleware._extract_bearer_token(connection)
    if token:
        claims = middleware._validate_jwt(token)
        return {
            "method": "jwt",
            "subject": claims.get("sub", "unknown"),
            "metadata": claims,
        }

    raise AuthenticationError("No valid authentication credentials provided")


async def require_websocket_auth(
    websocket: WebSocket,
    config: Optional[AuthConfig] = None,
) -> dict:
    """Authenticate a WebSocket connection before accept()."""
    auth_config = config or AuthConfig()
    if not auth_config.auth_enabled or auth_config.is_public_endpoint(websocket.url.path):
        return {"method": "anonymous", "subject": "public", "metadata": {}}

    try:
        auth_result = authenticate_connection(websocket, auth_config)
    except AuthenticationError as exc:
        logger.warning("WebSocket authentication failed for %s: %s", websocket.url.path, exc)
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc),
        ) from exc

    websocket.state.authenticated = True
    websocket.state.auth_method = auth_result["method"]
    websocket.state.auth_subject = auth_result.get("subject", "unknown")
    websocket.state.auth_metadata = auth_result.get("metadata", {})
    return auth_result
