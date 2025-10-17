from __future__ import annotations

import json
import time
from typing import Any, Dict, Optional

import httpx  # type: ignore

try:
    import jwt  # type: ignore
    from jwt import PyJWKClient  # type: ignore
except Exception:  # pragma: no cover
    jwt = None  # type: ignore
    PyJWKClient = None  # type: ignore


class OAuth2Validator:
    """Minimal OAuth 2.1/JWT validator using JWKS.

    This class is intentionally lightweight and only activated when the
    `pyjwt` dependency is available and HTTP transport is enabled.
    """

    def __init__(self, issuer: str, jwks_url: str, audience: Optional[str] = None):
        self.issuer = issuer.rstrip("/")
        self.jwks_url = jwks_url
        self.audience = audience
        self._jwks_client = PyJWKClient(jwks_url) if PyJWKClient else None

    def enabled(self) -> bool:
        return bool(self._jwks_client and jwt)

    def validate(self, token: str) -> Dict[str, Any]:
        if not self.enabled():
            raise RuntimeError("OAuth2/JWT validation not available (pyjwt not installed)")

        signing_key = self._jwks_client.get_signing_key_from_jwt(token)  # type: ignore[attr-defined]
        options = {"verify_aud": self.audience is not None}
        payload = jwt.decode(  # type: ignore[call-arg]
            token,
            signing_key.key,  # type: ignore[arg-type]
            algorithms=["RS256", "ES256", "PS256"],
            audience=self.audience,
            issuer=self.issuer,
            options=options,
        )
        # Basic sanity timing checks
        now = int(time.time())
        if payload.get("exp") and now > int(payload["exp"]):
            raise ValueError("Token expired")
        if payload.get("nbf") and now < int(payload["nbf"]):
            raise ValueError("Token not yet valid")
        return payload


def fetch_openid_configuration(issuer: str) -> Dict[str, Any]:
    
    url = issuer.rstrip("/") + "/.well-known/openid-configuration"
    with httpx.Client(timeout=5.0) as client:
        resp = client.get(url)
        resp.raise_for_status()
        return resp.json()


