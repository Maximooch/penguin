"""Bound the multipart request before it can fill temporary storage."""

import os

from starlette.exceptions import HTTPException
from starlette.requests import HTTPConnection
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

__all__ = ["UploadBodyLimitMiddleware", "max_upload_bytes"]

DEFAULT_MAX_UPLOAD_BYTES = 25 * 1024 * 1024
# Allow ordinary multipart headers and boundaries above the per-file limit.
MULTIPART_OVERHEAD_BYTES = 64 * 1024


def max_upload_bytes() -> int:
    """Return the positive per-file limit shared by middleware and route."""
    limit = int(os.getenv("PENGUIN_MAX_UPLOAD_BYTES", str(DEFAULT_MAX_UPLOAD_BYTES)))
    if limit <= 0:
        raise ValueError("PENGUIN_MAX_UPLOAD_BYTES must be positive")
    return limit


class UploadBodyLimitMiddleware:
    """Cap the body only on the image upload endpoint, without buffering it."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        path = scope["path"]
        root = scope.get("root_path", "").rstrip("/")
        if root and path.startswith(root + "/"):
            path = path[len(root):]
        if path != "/api/v1/upload":
            await self.app(scope, receive, send)
            return

        limit = max_upload_bytes() + MULTIPART_OVERHEAD_BYTES
        detail = f"Upload request exceeds {limit} bytes"
        length = HTTPConnection(scope).headers.get("content-length")
        if length is not None and length.isascii() and length.isdecimal():
            digits = length.lstrip("0") or "0"
            if (len(digits), digits) > (len(str(limit)), str(limit)):
                await JSONResponse({"detail": detail}, status_code=413)(
                    scope, receive, send
                )
                return

        received = 0

        async def receive_limited() -> Message:
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail=detail)
            return message

        await self.app(scope, receive_limited, send)
