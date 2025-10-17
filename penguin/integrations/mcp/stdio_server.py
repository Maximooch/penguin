from __future__ import annotations

import asyncio
import json
import sys
from typing import Any, Dict

from penguin.integrations.mcp.server import MCPServer


async def _handle_stdin(server: MCPServer) -> None:
    loop = asyncio.get_running_loop()
    reader = asyncio.StreamReader()
    protocol = asyncio.StreamReaderProtocol(reader)
    await loop.connect_read_pipe(lambda: protocol, sys.stdin)
    writer_transport, writer_protocol = await loop.connect_write_pipe(asyncio.streams.FlowControlMixin, sys.stdout)
    writer = asyncio.StreamWriter(writer_transport, writer_protocol, None, loop)

    while True:
        line = await reader.readline()
        if not line:
            break
        try:
            req = json.loads(line.decode("utf-8"))
            method = req.get("method")
            if method == "list_tools":
                resp = {"status": "ok", "tools": server.list_tools()}
            elif method == "call_tool":
                name = req.get("name")
                params = req.get("params") or {}
                confirm = bool(req.get("confirm", False))
                resp = await server.call_tool(str(name), dict(params), confirm=confirm)
            else:
                resp = {"status": "error", "error": {"code": "bad_request", "message": "Unknown method"}}
        except Exception as e:  # pragma: no cover
            resp = {"status": "error", "error": {"code": "bad_request", "message": str(e)}}

        writer.write((json.dumps(resp) + "\n").encode("utf-8"))
        await writer.drain()


def run_stdio(server: MCPServer) -> None:
    asyncio.run(_handle_stdin(server))


