"""Authentication middleware and local session helpers for Penguin web API.

Supports API key and JWT authentication for external clients plus a
startup-token-to-cookie bootstrap flow for local browser sessions.
"""

import logging
import os
import secrets
from typing import Any, Optional
from datetime import datetime, timedelta
from ipaddress import ip_address
from threading import Lock

from fastapi import HTTPException, Request, WebSocket, WebSocketException, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from starlette.middleware.base import BaseHTTPMiddleware
import jwt

logger = logging.getLogger(__name__)

DEFAULT_SESSION_COOKIE_NAME = "penguin_session"
DEFAULT_SESSION_COOKIE_PATH = "/"
DEFAULT_SESSION_COOKIE_SAMESITE = "lax"
DEFAULT_SESSION_EXPIRATION_SECONDS = 12 * 60 * 60
STARTUP_TOKEN_ENV = "PENGUIN_AUTH_STARTUP_TOKEN"
SESSION_SECRET_ENV = "PENGUIN_SESSION_SECRET"
_AUTH_SECRET_LOCK = Lock()

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
        self.link_auth_required = (
            os.getenv("PENGUIN_LINK_AUTH_REQUIRED", "false").lower() == "true"
        )

        # General auth settings
        self.auth_enabled = os.getenv("PENGUIN_AUTH_ENABLED", "false").lower() == "true"
        self.public_endpoints = self._load_public_endpoints()
        self.session_cookie_name = os.getenv(
            "PENGUIN_SESSION_COOKIE_NAME", DEFAULT_SESSION_COOKIE_NAME
        )
        self.session_cookie_path = os.getenv(
            "PENGUIN_SESSION_COOKIE_PATH", DEFAULT_SESSION_COOKIE_PATH
        )
        self.session_cookie_samesite = _normalize_samesite(
            os.getenv(
                "PENGUIN_SESSION_COOKIE_SAMESITE", DEFAULT_SESSION_COOKIE_SAMESITE
            )
        )
        self.session_expiration_seconds = int(
            os.getenv(
                "PENGUIN_SESSION_EXPIRATION_SECONDS",
                str(DEFAULT_SESSION_EXPIRATION_SECONDS),
            )
        )

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
            "/api/v1/auth/session",
            "/api/v1/auth/logout",
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
        return {
            path for path in self.public_endpoints if path.endswith("/") and path != "/"
        }

    @property
    def public_endpoint_exact_matches(self) -> set[str]:
        """Return public endpoints that require exact path matches."""
        return self.public_endpoints - self.public_endpoint_prefixes

    def is_public_endpoint(self, path: str) -> bool:
        """Check if an endpoint is public (doesn't require auth)."""
        if path in self.public_endpoint_exact_matches:
            return True

        return any(path.startswith(prefix) for prefix in self.public_endpoint_prefixes)

    @property
    def requires_startup_token(self) -> bool:
        """Return whether local bootstrap token auth should be enabled."""
        return self.auth_enabled and not self.api_keys


# Public-endpoint matching convention:
# - entries ending with "/" (except "/" itself) are treated as prefix matches
# - all other entries require exact path equality
# `is_public_endpoint()` checks exact matches first, then falls back to prefix matching.


def _normalize_samesite(value: str) -> str:
    """Return a valid cookie SameSite value."""
    normalized = (value or "").strip().lower()
    if normalized in {"lax", "strict", "none"}:
        return normalized
    return DEFAULT_SESSION_COOKIE_SAMESITE


def _is_loopback_host(host: str) -> bool:
    """Return whether the provided host resolves to loopback."""
    normalized = (host or "").strip().lower()
    if normalized in {"127.0.0.1", "localhost", "::1"}:
        return True
    try:
        return ip_address(normalized).is_loopback
    except ValueError:
        return False


def _load_or_create_secret(env_name: str, *, bytes_length: int) -> str:
    """Load an auth secret from env or create one for this process tree."""
    value = os.getenv(env_name, "").strip()
    if value:
        return value

    with _AUTH_SECRET_LOCK:
        value = os.getenv(env_name, "").strip()
        if value:
            return value

        generated = secrets.token_urlsafe(bytes_length)
        os.environ[env_name] = generated
        return generated


def get_startup_auth_token(config: Optional[AuthConfig] = None) -> Optional[str]:
    """Return the loopback bootstrap token when auth needs local browser bootstrap."""
    auth_config = config or AuthConfig()
    if not auth_config.requires_startup_token:
        return None
    return _load_or_create_secret(STARTUP_TOKEN_ENV, bytes_length=24)


def get_session_secret(config: Optional[AuthConfig] = None) -> str:
    """Return the signing secret used for Penguin browser session cookies."""
    auth_config = config or AuthConfig()
    explicit_secret = os.getenv(SESSION_SECRET_ENV, "").strip()
    if explicit_secret:
        return explicit_secret
    if auth_config.jwt_secret:
        return auth_config.jwt_secret
    return _load_or_create_secret(SESSION_SECRET_ENV, bytes_length=32)


def authenticate_local_session_token(
    token: str,
    config: Optional[AuthConfig] = None,
) -> dict:
    """Authenticate a token exchanged for a local browser session."""
    auth_config = config or AuthConfig()
    candidate = (token or "").strip()
    if not candidate:
        raise AuthenticationError("Local authorization token is required")

    startup_token = get_startup_auth_token(auth_config)
    if startup_token and secrets.compare_digest(candidate, startup_token):
        return {
            "method": "startup_token",
            "subject": "local_bootstrap",
            "metadata": {"interactive": True},
        }

    if validate_api_key(candidate, auth_config):
        return {
            "method": "api_key",
            "subject": "api_client",
            "metadata": {"key_prefix": candidate[:8] + "..."},
        }

    raise AuthenticationError("Invalid local authorization token")


def create_session_token(
    subject: str,
    *,
    auth_method: str,
    config: Optional[AuthConfig] = None,
    metadata: Optional[dict] = None,
) -> str:
    """Create a signed browser session token for Penguin local auth."""
    auth_config = config or AuthConfig()
    issued_at = datetime.utcnow()
    claims = {
        "sub": subject,
        "type": "session",
        "auth_method": auth_method,
        "iat": issued_at,
        "exp": issued_at + timedelta(seconds=auth_config.session_expiration_seconds),
    }
    if metadata:
        claims["metadata"] = metadata

    return jwt.encode(
        claims,
        get_session_secret(auth_config),
        algorithm=auth_config.jwt_algorithm,
    )


def validate_session_token(token: str, config: Optional[AuthConfig] = None) -> dict:
    """Validate a signed Penguin browser session token."""
    auth_config = config or AuthConfig()
    try:
        claims = jwt.decode(
            token,
            get_session_secret(auth_config),
            algorithms=[auth_config.jwt_algorithm],
        )
    except jwt.ExpiredSignatureError as exc:
        raise AuthenticationError("Session has expired") from exc
    except jwt.InvalidTokenError as exc:
        raise AuthenticationError(f"Invalid session token: {exc}") from exc

    if claims.get("type") != "session":
        raise AuthenticationError("Invalid session token type")
    return claims


def build_session_cookie_settings(
    request: Request,
    config: Optional[AuthConfig] = None,
) -> dict[str, Any]:
    """Build safe cookie settings for Penguin local browser sessions."""
    auth_config = config or AuthConfig()
    host = (request.url.hostname or "").strip().lower()
    secure = request.url.scheme == "https"
    if not secure and not _is_loopback_host(host):
        raise AuthenticationError(
            "Browser session cookies are only issued for loopback hosts or HTTPS origins"
        )

    return {
        "expires": auth_config.session_expiration_seconds,
        "httponly": True,
        "max_age": auth_config.session_expiration_seconds,
        "path": auth_config.session_cookie_path,
        "samesite": auth_config.session_cookie_samesite,
        "secure": secure,
    }


def extract_api_key(connection: Any) -> Optional[str]:
    """Extract API key from request or websocket headers."""
    headers = connection.headers

    api_key = headers.get("X-API-Key")
    if api_key:
        return api_key

    link_key = headers.get("X-Link-API-Key")
    if link_key:
        return link_key

    return None


def extract_bearer_token(connection: Any) -> Optional[str]:
    """Extract Bearer token from Authorization header."""
    auth_header = connection.headers.get("Authorization")
    if not auth_header:
        return None

    parts = auth_header.split()
    if len(parts) != 2 or parts[0].lower() != "bearer":
        return None

    return parts[1]


def validate_api_key(api_key: str, config: AuthConfig) -> bool:
    """Validate an API key against configured keys."""
    if not api_key:
        return False
    return any(secrets.compare_digest(api_key, key) for key in config.api_keys)


def validate_jwt(token: str, config: AuthConfig) -> dict:
    """Validate and decode a JWT token using the provided config."""
    if not config.jwt_secret:
        raise AuthenticationError("JWT authentication not configured")

    try:
        claims = jwt.decode(token, config.jwt_secret, algorithms=[config.jwt_algorithm])

        if "exp" in claims:
            exp_timestamp = claims["exp"]
            if datetime.utcfromtimestamp(exp_timestamp) < datetime.utcnow():
                raise AuthenticationError("Token has expired")

        return claims

    except jwt.ExpiredSignatureError:
        raise AuthenticationError("Token has expired")
    except jwt.InvalidTokenError as e:
        raise AuthenticationError(f"Invalid token: {str(e)}")


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
        except Exception:
            logger.exception("Unexpected error in authentication")
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
        api_key = extract_api_key(request)
        if api_key and validate_api_key(api_key, self.config):
            return {
                "method": "api_key",
                "subject": "api_client",
                "metadata": {"key_prefix": api_key[:8] + "..."},
            }

        token = extract_bearer_token(request)
        if token:
            claims = validate_jwt(token, self.config)
            return {
                "method": "jwt",
                "subject": claims.get("sub", "unknown"),
                "metadata": claims,
            }

        raise AuthenticationError("No valid authentication credentials provided")

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
            "exp": datetime.utcnow()
            + timedelta(hours=self.config.jwt_expiration_hours),
        }

        # Add metadata
        if metadata:
            claims.update(metadata)

        # Encode token
        token = jwt.encode(
            claims, self.config.jwt_secret, algorithm=self.config.jwt_algorithm
        )

        return token


# Dependency for route-level auth
async def require_auth(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials] = None
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
                    "suggested_action": "provide_credentials",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    return {
        "method": request.state.auth_method,
        "subject": request.state.auth_subject,
        "metadata": request.state.auth_metadata,
    }


def authenticate_connection(
    connection: Any,
    config: Optional[AuthConfig] = None,
) -> dict:
    """Authenticate an HTTP or WebSocket connection using shared auth rules."""
    auth_config = config or AuthConfig()

    api_key = extract_api_key(connection)
    if api_key and validate_api_key(api_key, auth_config):
        return {
            "method": "api_key",
            "subject": "api_client",
            "metadata": {"key_prefix": api_key[:8] + "..."},
        }

    token = extract_bearer_token(connection)
    if token:
        claims = validate_jwt(token, auth_config)
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
    if not auth_config.auth_enabled or auth_config.is_public_endpoint(
        websocket.url.path
    ):
        return {"method": "anonymous", "subject": "public", "metadata": {}}

    try:
        auth_result = authenticate_connection(websocket, auth_config)
    except AuthenticationError as exc:
        logger.warning(
            "WebSocket authentication failed for %s: %s", websocket.url.path, exc
        )
        raise WebSocketException(
            code=status.WS_1008_POLICY_VIOLATION,
            reason=str(exc),
        ) from exc

    websocket.state.authenticated = True
    websocket.state.auth_method = auth_result["method"]
    websocket.state.auth_subject = auth_result.get("subject", "unknown")
    websocket.state.auth_metadata = auth_result.get("metadata", {})
    return auth_result
