"""Thin HTTP surfaces for Telegram webhooks and operator controls."""

from __future__ import annotations

import asyncio
import json
import secrets
from typing import TYPE_CHECKING, Any, Literal, Optional

from fastapi import APIRouter, HTTPException, Query, Request, Response
from pydantic import BaseModel, Field

from penguin.integrations.telegram.manager import TelegramManager

if TYPE_CHECKING:
    from penguin.integrations.telegram.config import TelegramConfig

__all__ = ["build_telegram_router"]


class PairingCreateRequest(BaseModel):
    """Operator request for a short-lived pairing code."""

    expected_user_id: Optional[str] = None
    ttl_seconds: int = Field(default=3600, ge=60, le=3600)


class DeadLetterActionRequest(BaseModel):
    """Explicit retry or discard of one terminal record."""

    kind: Literal["ingress", "delivery"]
    record_id: str = Field(min_length=1, max_length=512)


def build_telegram_router(config: TelegramConfig) -> APIRouter:
    """Create routes using the configured webhook path."""

    router = APIRouter()

    @router.post(config.webhook_path, include_in_schema=False)
    async def telegram_webhook(request: Request) -> dict[str, Any]:
        manager = _manager(request)
        if not config.enabled or config.transport != "webhook":
            raise HTTPException(status_code=404, detail="Telegram webhook is disabled")
        candidate = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
        expected = config.webhook_secret or ""
        if not expected or not secrets.compare_digest(candidate, expected):
            raise HTTPException(
                status_code=401, detail="Invalid Telegram webhook secret"
            )
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > config.webhook_body_limit_bytes:
                    raise HTTPException(
                        status_code=413, detail="Telegram webhook body is too large"
                    )
            except ValueError:
                raise HTTPException(status_code=400, detail="Invalid Content-Length")
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > config.webhook_body_limit_bytes:
                raise HTTPException(
                    status_code=413, detail="Telegram webhook body is too large"
                )
            body.extend(chunk)
        try:
            update = json.loads(bytes(body))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HTTPException(
                status_code=400, detail="Invalid Telegram update"
            ) from exc
        if not isinstance(update, dict):
            raise HTTPException(status_code=400, detail="Invalid Telegram update")
        try:
            admitted = await asyncio.wait_for(
                manager.admit_webhook_update(update),
                timeout=config.webhook_timeout_seconds,
            )
        except asyncio.TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Telegram update was not durably adopted"
            ) from exc
        return {"ok": True, "admitted": admitted}

    @router.get("/api/v1/integrations/telegram/status")
    async def telegram_status(request: Request) -> dict[str, Any]:
        return _manager(request).status()

    @router.post("/api/v1/integrations/telegram/pairings")
    async def create_pairing(
        payload: PairingCreateRequest,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        manager = _manager(request)
        if manager.config.dm_policy != "pairing":
            raise HTTPException(status_code=409, detail="DM pairing policy is disabled")
        expected_user_id = payload.expected_user_id
        if expected_user_id is not None and (
            not expected_user_id.isdigit() or int(expected_user_id) <= 0
        ):
            raise HTTPException(
                status_code=422, detail="expected_user_id must be a positive numeric ID"
            )
        code = await manager.create_pairing(
            expected_user_id=expected_user_id,
            ttl_seconds=payload.ttl_seconds,
        )
        response.headers["Cache-Control"] = "no-store"
        return {"code": code, "expires_in_seconds": payload.ttl_seconds}

    @router.delete("/api/v1/integrations/telegram/pairings/{user_id}")
    async def revoke_pairing(user_id: str, request: Request) -> dict[str, Any]:
        if not user_id.isdigit() or int(user_id) <= 0:
            raise HTTPException(status_code=422, detail="user_id must be numeric")
        return {"revoked": await _manager(request).revoke_dm(user_id)}

    @router.get("/api/v1/integrations/telegram/dead-letters")
    async def list_dead_letters(
        request: Request,
        kind: Literal["ingress", "delivery"] = Query(...),
        limit: int = Query(default=50, ge=1, le=100),
    ) -> dict[str, Any]:
        records = await _manager(request).list_dead_letters(kind=kind, limit=limit)
        return {"kind": kind, "records": records}

    @router.post("/api/v1/integrations/telegram/dead-letters/retry")
    async def retry_dead_letter(
        payload: DeadLetterActionRequest, request: Request
    ) -> dict[str, Any]:
        retried = await _manager(request).retry_dead_letter(
            kind=payload.kind, record_id=payload.record_id
        )
        if not retried:
            raise HTTPException(status_code=404, detail="Dead letter was not found")
        return {"retried": True}

    @router.post("/api/v1/integrations/telegram/dead-letters/discard")
    async def discard_dead_letter(
        payload: DeadLetterActionRequest, request: Request
    ) -> dict[str, Any]:
        discarded = await _manager(request).discard_dead_letter(
            kind=payload.kind, record_id=payload.record_id
        )
        if not discarded:
            raise HTTPException(
                status_code=404,
                detail="Dead letter was not found or remains referenced",
            )
        return {"discarded": True}

    return router


def _manager(request: Request) -> TelegramManager:
    manager = getattr(request.app.state, "telegram_manager", None)
    if not isinstance(manager, TelegramManager):
        raise HTTPException(
            status_code=503, detail="Telegram integration is not initialized"
        )
    return manager
