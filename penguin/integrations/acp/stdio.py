"""Keep the ACP protocol writer bound to stdout during diagnostic redirection."""

from __future__ import annotations

import asyncio
import json
from typing import Any, BinaryIO

__all__ = ["ProtocolTransport", "protocol_writer"]


class ProtocolTransport:
    """NDJSON transport preserving draft capability fields for negotiation.

    SDK 0.12 drops unknown ClientCapabilities fields. Observe the canonical
    draft subagents field before SDK validation; all RPC dispatch stays in SDK.
    """

    def __init__(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        self.reader, self.writer = reader, writer
        self.subagents = False
        self.lock = asyncio.Lock()

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
            return message
        return None

    async def close(self) -> None:
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
