"""Keep the ACP protocol writer bound to stdout during diagnostic redirection."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, BinaryIO

from acp import RequestError
from acp.schema import CancelRequestNotification
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ProtocolTransport", "protocol_writer"]


class ProtocolTransport:
    """NDJSON transport preserving draft capability fields for negotiation.

    SDK 0.12 drops unknown ClientCapabilities fields. Observe the canonical
    draft subagents field before SDK validation. Explicit schema-validated
    handlers cover deletion and cancellable prompts; other routes stay in SDK.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader, self.writer = reader, writer
        self.subagents = False
        self.lock = asyncio.Lock()
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.tasks: set[asyncio.Task[Any]] = set()
        self.pending: dict[Any, tuple[dict[str, Any], asyncio.Task[Any]]] = {}
        self.cancel_handlers: dict[str, Callable[..., Any]] = {}
        self.session_responses: set[Any] = set()
        self.after_session_response: Callable[..., Any] | None = None

    def register(
        self,
        method: str,
        handler: Callable[..., Any],
        cancel: Callable[..., Any] | None = None,
    ) -> None:
        """Add a validated method handler with optional exact-request cancellation."""
        self.handlers[method] = handler
        if cancel is not None:
            self.cancel_handlers[method] = cancel

    async def _dispatch(self, message: dict[str, Any]) -> None:
        response = {"jsonrpc": "2.0", "id": message["id"]}
        try:
            result = await self.handlers[message["method"]](message.get("params"))
            response["result"] = result.model_dump(by_alias=True, exclude_none=True)
        except ValidationError:
            response["error"] = RequestError.invalid_params().to_error_obj()
        except RequestError as exc:
            response["error"] = exc.to_error_obj()
        except Exception:
            response["error"] = RequestError.internal_error().to_error_obj()
        try:
            await self.send(response)
        finally:
            self.pending.pop(message["id"], None)

    async def _cancel(self, record: tuple[dict[str, Any], asyncio.Task[Any]]) -> None:
        message, task = record
        if self.pending.get(message["id"]) != record or task.done():
            return
        callback = self.cancel_handlers.get(message["method"])
        if callback is not None:
            await callback(message.get("params"), task)

    async def send(self, message: dict[str, Any]) -> None:
        async with self.lock:
            self.writer.write(
                (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await self.writer.drain()
        request_id = message.get("id")
        if type(request_id) in (str, int) and request_id in self.session_responses:
            self.session_responses.discard(request_id)
            result = message.get("result")
            if isinstance(result, dict) and self.after_session_response is not None:
                sid = result.get("sessionId")
                if isinstance(sid, str):
                    await self.after_session_response(sid)

    async def receive(self) -> dict[str, Any] | None:
        while line := await self.reader.readline():
            if not line.strip():
                continue
            try:
                message = json.loads(line)
            except ValueError:
                await self.send(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32700, "message": "Parse error"},
                    }
                )
                continue
            if not isinstance(message, dict):
                await self.send(
                    {
                        "jsonrpc": "2.0",
                        "id": None,
                        "error": {"code": -32600, "message": "Invalid request"},
                    }
                )
                continue
            if message.get("method") == "session/new" and type(message.get("id")) in (
                str,
                int,
            ):
                self.session_responses.add(message["id"])
            if message.get("method") == "initialize":
                params = message.get("params")
                capabilities = (
                    params.get("clientCapabilities", {})
                    if isinstance(params, dict)
                    else {}
                )
                self.subagents = isinstance(capabilities, dict) and isinstance(
                    capabilities.get("subagents"), dict
                )
            if message.get("method") == "$/cancel_request" and "id" not in message:
                try:
                    request = CancelRequestNotification.model_validate(
                        message.get("params")
                    )
                except ValidationError:
                    continue
                record = self.pending.get(request.request_id)
                if record is not None:
                    task = asyncio.create_task(self._cancel(record))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
                continue
            if message.get("method") in self.handlers:
                # A request-only method must not mutate state from a notification.
                if message.get("jsonrpc") == "2.0" and type(message.get("id")) in (
                    str,
                    int,
                ):
                    if message["id"] in self.pending:
                        await self.send(
                            {
                                "jsonrpc": "2.0",
                                "id": message["id"],
                                "error": RequestError.invalid_request().to_error_obj(),
                            }
                        )
                        continue
                    task = asyncio.create_task(self._dispatch(message))
                    self.pending[message["id"]] = (message, task)
                    self.tasks.add(task)

                    def done(
                        completed: asyncio.Task[Any], request_id=message["id"]
                    ) -> None:
                        self.tasks.discard(completed)
                        record = self.pending.get(request_id)
                        if record is not None and record[1] is completed:
                            self.pending.pop(request_id, None)

                    task.add_done_callback(done)
                    # Establish handler ownership before reading a back-to-back cancel.
                    await asyncio.sleep(0)
                elif "id" in message:
                    await self.send(
                        {
                            "jsonrpc": "2.0",
                            "id": message["id"],
                            "error": RequestError.invalid_request().to_error_obj(),
                        }
                    )
                continue
            return message
        return None

    async def close(self) -> None:
        self.session_responses.clear()
        for task in self.tasks.copy():
            task.cancel()
        if self.tasks:
            await asyncio.gather(*self.tasks, return_exceptions=True)
        self.writer.close()


class _ProtocolTransport(asyncio.WriteTransport):
    """Write only protocol bytes to the captured output stream on every OS."""

    def __init__(self, stream: BinaryIO) -> None:
        super().__init__()
        self.stream = stream
        self.closed = False

    def write(self, data: bytes) -> None:
        if self.closed:
            raise ConnectionError("ACP output is closed")
        self.stream.write(data)
        self.stream.flush()

    def is_closing(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True

    def get_extra_info(self, name: str, default: Any = None) -> Any:
        return default


def protocol_writer(stream: BinaryIO) -> asyncio.StreamWriter:
    """Create an SDK-compatible writer without consulting mutable sys.stdout."""
    loop = asyncio.get_running_loop()
    protocol = asyncio.StreamReaderProtocol(asyncio.StreamReader())
    return asyncio.StreamWriter(_ProtocolTransport(stream), protocol, None, loop)
