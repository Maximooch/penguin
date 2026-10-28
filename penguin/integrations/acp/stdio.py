"""Keep the ACP protocol writer bound to stdout during diagnostic redirection."""

from __future__ import annotations

import asyncio
from typing import Any, BinaryIO

__all__ = ["protocol_writer"]


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
