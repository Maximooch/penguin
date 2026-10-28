"""Keep the ACP protocol writer bound to stdout during diagnostic redirection."""

from __future__ import annotations

import asyncio
import json
from typing import TYPE_CHECKING, Any, BinaryIO

from acp import RequestError
from pydantic import ValidationError

if TYPE_CHECKING:
    from collections.abc import Callable

__all__ = ["ProtocolTransport", "protocol_writer"]


class ProtocolTransport:
    """NDJSON transport preserving draft capability fields for negotiation.

    SDK 0.12 drops unknown ClientCapabilities fields. Observe the canonical
    draft subagents field before SDK validation. Published methods missing from
    the SDK router have explicit schema-validated handlers; others stay in SDK.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader, self.writer = reader, writer
        self.subagents = False
        self.lock = asyncio.Lock()
        self.handlers: dict[str, Callable[..., Any]] = {}
        self.tasks: set[asyncio.Task[Any]] = set()

    def register(self, method: str, handler: Callable[..., Any]) -> None:
        """Add a published method absent from this SDK's router."""
        self.handlers[method] = handler

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
        await self.send(response)

    async def send(self, message: dict[str, Any]) -> None:
        async with self.lock:
            self.writer.write(
                (json.dumps(message, ensure_ascii=False) + "\n").encode("utf-8")
            )
            await self.writer.drain()

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
            if message.get("method") in self.handlers:
                # A request-only method must not mutate state from a notification.
                if message.get("jsonrpc") == "2.0" and type(message.get("id")) in (
                    str,
                    int,
                ):
                    task = asyncio.create_task(self._dispatch(message))
                    self.tasks.add(task)
                    task.add_done_callback(self.tasks.discard)
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
