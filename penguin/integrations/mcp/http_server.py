from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, Header, HTTPException  # type: ignore
from fastapi.responses import StreamingResponse  # type: ignore

from penguin.integrations.mcp.server import MCPServer
from penguin.integrations.mcp.auth import OAuth2Validator, fetch_openid_configuration


class _AuthDeps:
    def __init__(self, issuer: Optional[str], jwks_url: Optional[str], audience: Optional[str]):
        self._validator: Optional[OAuth2Validator] = None
        if issuer and jwks_url:
            self._validator = OAuth2Validator(issuer=issuer, jwks_url=jwks_url, audience=audience)

    def require(self, authorization: Optional[str] = Header(None)) -> Dict[str, Any]:
        if not self._validator:
            return {}
        if not authorization or not authorization.lower().startswith("bearer "):
            raise HTTPException(status_code=401, detail="missing bearer token")
        token = authorization.split(" ", 1)[1]
        try:
            return self._validator.validate(token)
        except Exception as e:  # pragma: no cover
            raise HTTPException(status_code=401, detail=str(e))


def get_router(server: MCPServer, *, oauth2: Optional[Dict[str, Any]] = None) -> APIRouter:
    router = APIRouter(prefix="/api/v1/mcp", tags=["mcp"])

    validator = None
    if oauth2 and oauth2.get("issuer"):
        issuer = str(oauth2.get("issuer"))
        jwks_url = str(oauth2.get("jwks_url") or fetch_openid_configuration(issuer).get("jwks_uri"))
        audience = oauth2.get("audience")
        validator = _AuthDeps(issuer, jwks_url, audience if isinstance(audience, str) else None)

    def _auth():
        if validator:
            return Depends(validator.require)
        # no-op dependency
        def _noop():
            return {}
        return Depends(_noop)

    @router.get("/tools")
    async def list_tools(_claims: Dict[str, Any] = _auth()):  # noqa: B008
        return {"tools": server.list_tools()}

    @router.post("/tools/{name}:call")
    async def call_tool(name: str, params: Dict[str, Any], confirm: Optional[bool] = None, _claims: Dict[str, Any] = _auth()):  # noqa: B008
        result = await server.call_tool(name, params or {}, confirm=bool(confirm))
        return result

    return router


