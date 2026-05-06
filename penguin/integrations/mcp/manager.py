"""MCP client manager for consuming external MCP servers as Penguin tools."""

from __future__ import annotations

import asyncio
import json
import logging
import threading
from concurrent.futures import Future
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from penguin.integrations.mcp.config import MCPServerConfig
from penguin.integrations.mcp.names import make_tool_name

logger = logging.getLogger(__name__)

try:  # pragma: no cover - availability depends on optional extra
    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.sse import sse_client  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore
    from mcp.client.streamable_http import streamablehttp_client  # type: ignore

    HAS_MCP_SDK = True
except Exception:  # pragma: no cover - exercised when extra is absent
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    sse_client = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
    streamablehttp_client = None  # type: ignore[assignment]
    HAS_MCP_SDK = False


class MCPServerStatus(str, Enum):
    """Lifecycle status for a configured MCP server."""

    DISCONNECTED = "disconnected"
    CONNECTING = "connecting"
    CONNECTED = "connected"
    FAILED = "failed"


@dataclass
class MCPToolDefinition:
    """A discovered MCP tool mapped onto Penguin's public tool surface."""

    public_name: str
    server_name: str
    raw_name: str
    description: str
    input_schema: dict[str, Any]

    def to_penguin_schema(self) -> dict[str, Any]:
        """Return ToolManager-compatible schema."""
        return {
            "name": self.public_name,
            "description": self.description,
            "input_schema": self.input_schema,
            "metadata": {
                "provider": "mcp",
                "mcp_server": self.server_name,
                "mcp_tool": self.raw_name,
            },
        }


@dataclass
class MCPServerState:
    """Runtime state for one MCP server connection."""

    config: MCPServerConfig
    status: MCPServerStatus = MCPServerStatus.DISCONNECTED
    tools: dict[str, MCPToolDefinition] = field(default_factory=dict)
    error: str | None = None
    session: Any = None
    stack: AsyncExitStack | None = None


class MCPClientManager:
    """Manage MCP client sessions and tool discovery."""

    def __init__(self, servers: list[MCPServerConfig]) -> None:
        self._states = {
            server.name: MCPServerState(config=server) for server in servers
        }
        self._tool_index: dict[str, MCPToolDefinition] = {}
        self._discovered = False
        self._loop: asyncio.AbstractEventLoop | None = None
        self._loop_thread: threading.Thread | None = None
        self._actor_queue: asyncio.Queue[tuple[Any, Future[Any]]] | None = None

    @property
    def available(self) -> bool:
        """Return whether the optional MCP SDK is importable."""
        return HAS_MCP_SDK

    def status(self) -> dict[str, Any]:
        """Return serializable MCP manager status."""
        return {
            "available": self.available,
            "discovered": self._discovered,
            "server_count": len(self._states),
            "tool_count": len(self._tool_index),
            "servers": {
                name: {
                    "status": state.status.value,
                    "transport": state.config.transport,
                    "command": state.config.command,
                    "url": state.config.url,
                    "tool_count": len(state.tools),
                    "error": state.error,
                    "tools": sorted(state.tools),
                }
                for name, state in self._states.items()
            },
        }

    def list_tools_sync(self) -> list[MCPToolDefinition]:
        """Discover MCP tools synchronously for ToolManager integration."""
        if not self._discovered:
            self._run_async(self.discover())
        return list(self._tool_index.values())

    def call_tool_sync(self, public_name: str, arguments: dict[str, Any]) -> Any:
        """Call an MCP tool synchronously for ToolManager integration."""
        return self._run_async(self.call_tool(public_name, arguments))

    def refresh_sync(self) -> list[MCPToolDefinition]:
        """Force rediscovery synchronously."""
        return self._run_async(self.refresh())

    def reconnect_sync(self, server_name: str | None = None) -> dict[str, Any]:
        """Reconnect one or all MCP servers synchronously."""
        self._run_async(self.reconnect(server_name))
        return self.status()

    def close_sync(self) -> dict[str, Any]:
        """Close all MCP sessions synchronously."""
        self._run_async(self.close())
        status = self.status()
        self._stop_actor()
        return status

    async def discover(self) -> list[MCPToolDefinition]:
        """Connect to configured servers and discover tools."""
        if self._discovered:
            return list(self._tool_index.values())
        if not HAS_MCP_SDK:
            for state in self._states.values():
                state.status = MCPServerStatus.FAILED
                state.error = (
                    "MCP SDK is not installed. Install with `penguin-ai[mcp]`."
                )
            logger.info("MCP SDK is not installed; no MCP tools discovered")
            self._discovered = True
            return []

        existing: set[str] = set()
        for state in self._states.values():
            await self._connect_and_list_tools(state, existing)
        self._discovered = True
        return list(self._tool_index.values())

    async def refresh(self) -> list[MCPToolDefinition]:
        """Close sessions and force a fresh tool discovery pass."""
        await self.close()
        self._tool_index.clear()
        for state in self._states.values():
            state.tools.clear()
            state.error = None
        self._discovered = False
        return await self.discover()

    async def reconnect(self, server_name: str | None = None) -> None:
        """Reconnect one server or all servers and refresh their tool lists."""
        if server_name is None:
            await self.refresh()
            return
        state = self._states.get(server_name)
        if state is None:
            raise ValueError(f"Unknown MCP server: {server_name}")
        if state.stack is not None:
            await state.stack.aclose()
        for public_name in list(state.tools):
            self._tool_index.pop(public_name, None)
        state.tools.clear()
        state.stack = None
        state.session = None
        state.error = None
        state.status = MCPServerStatus.DISCONNECTED
        existing = set(self._tool_index)
        await self._connect_and_list_tools(state, existing)
        self._discovered = True

    async def call_tool(self, public_name: str, arguments: dict[str, Any]) -> Any:
        """Call a discovered MCP tool by Penguin public name."""
        if public_name not in self._tool_index:
            await self.discover()
        tool = self._tool_index.get(public_name)
        if tool is None:
            raise ValueError(f"Unknown MCP tool: {public_name}")

        state = self._states[tool.server_name]
        if state.session is None or state.status != MCPServerStatus.CONNECTED:
            await self._connect_and_list_tools(state, set(self._tool_index))
        if state.session is None:
            raise RuntimeError(f"MCP server '{tool.server_name}' is not connected")

        timeout = state.config.tool_timeout_sec
        result = await asyncio.wait_for(
            state.session.call_tool(tool.raw_name, arguments or {}),
            timeout=timeout,
        )
        return self._serialize_call_result(result)

    async def close(self) -> None:
        """Close cached MCP session handles from the actor task that opened them."""
        for state in self._states.values():
            if state.stack is not None:
                try:
                    await state.stack.aclose()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    logger.warning(
                        "Failed closing MCP server '%s': %s",
                        state.config.name,
                        exc,
                    )
            state.stack = None
            state.session = None
            state.status = MCPServerStatus.DISCONNECTED

    async def _connect_and_list_tools(
        self,
        state: MCPServerState,
        existing: set[str],
    ) -> None:
        state.status = MCPServerStatus.CONNECTING
        state.error = None
        try:
            session = await self._ensure_session(state)
            response = await asyncio.wait_for(
                session.list_tools(),
                timeout=state.config.startup_timeout_sec,
            )
            for raw_tool in getattr(response, "tools", []) or []:
                raw_name = str(getattr(raw_tool, "name", ""))
                if not raw_name or not state.config.allows_tool(raw_name):
                    continue
                public_name = make_tool_name(state.config.name, raw_name, existing)
                existing.add(public_name)
                input_schema = getattr(raw_tool, "inputSchema", None) or getattr(
                    raw_tool,
                    "input_schema",
                    None,
                )
                if not isinstance(input_schema, dict):
                    input_schema = {"type": "object", "properties": {}}
                description = str(getattr(raw_tool, "description", "") or "")
                definition = MCPToolDefinition(
                    public_name=public_name,
                    server_name=state.config.name,
                    raw_name=raw_name,
                    description=(
                        description or f"MCP tool {raw_name} from {state.config.name}"
                    ),
                    input_schema=input_schema,
                )
                state.tools[public_name] = definition
                self._tool_index[public_name] = definition
            state.status = MCPServerStatus.CONNECTED
        except Exception as exc:
            state.status = MCPServerStatus.FAILED
            state.error = str(exc)
            logger.warning(
                "MCP server '%s' discovery failed: %s",
                state.config.name,
                exc,
            )

    async def _ensure_session(self, state: MCPServerState) -> Any:
        """Open or return a persistent MCP stdio session."""
        if state.session is not None:
            return state.session
        if not HAS_MCP_SDK:
            raise RuntimeError(
                "MCP SDK is not installed. Install with `penguin-ai[mcp]`."
            )

        stack = AsyncExitStack()
        if state.config.transport == "stdio":
            params = StdioServerParameters(  # type: ignore[misc]
                command=state.config.command,
                args=state.config.args,
                env=state.config.env or None,
                cwd=state.config.cwd,
            )
            read_stream, write_stream = await stack.enter_async_context(
                stdio_client(params)
            )
        elif state.config.transport == "streamable_http":
            if streamablehttp_client is None:
                raise RuntimeError("MCP streamable HTTP client is unavailable")
            read_stream, write_stream, _session_id = await stack.enter_async_context(
                streamablehttp_client(
                    state.config.url or "",
                    headers=state.config.resolved_http_headers or None,
                    timeout=state.config.startup_timeout_sec,
                    sse_read_timeout=state.config.tool_timeout_sec,
                )
            )
        elif state.config.transport == "sse":
            if sse_client is None:
                raise RuntimeError("MCP SSE client is unavailable")
            read_stream, write_stream = await stack.enter_async_context(
                sse_client(
                    state.config.url or "",
                    headers=state.config.resolved_http_headers or None,
                    timeout=state.config.startup_timeout_sec,
                    sse_read_timeout=state.config.tool_timeout_sec,
                )
            )
        else:
            raise ValueError(f"Unsupported MCP transport: {state.config.transport}")
        session = await stack.enter_async_context(
            ClientSession(read_stream, write_stream)
        )
        await asyncio.wait_for(
            session.initialize(),
            timeout=state.config.startup_timeout_sec,
        )
        state.stack = stack
        state.session = session
        return session

    @staticmethod
    def _serialize_call_result(result: Any) -> Any:
        """Convert MCP SDK result objects into JSON-ish data."""
        if hasattr(result, "model_dump"):
            return result.model_dump()
        if hasattr(result, "dict"):
            return result.dict()
        if hasattr(result, "content"):
            content = getattr(result, "content")
            return [MCPClientManager._serialize_call_result(item) for item in content]
        if isinstance(result, (str, int, float, bool)) or result is None:
            return result
        if isinstance(result, list):
            return [MCPClientManager._serialize_call_result(item) for item in result]
        if isinstance(result, dict):
            return {
                key: MCPClientManager._serialize_call_result(value)
                for key, value in result.items()
            }
        try:
            return json.loads(
                json.dumps(
                    result,
                    default=lambda value: getattr(value, "__dict__", str(value)),
                )
            )
        except Exception:
            return str(result)

    def _run_async(self, coro: Any) -> Any:
        """Run manager coroutines on one actor task.

        The MCP SDK stdio transport uses AnyIO cancel scopes that must close in
        the same task that opened them. A single actor task preserves session
        state and closes transports cleanly.
        """
        loop, queue = self._ensure_actor()
        future: Future[Any] = Future()
        loop.call_soon_threadsafe(queue.put_nowait, (coro, future))
        return future.result()

    def _ensure_actor(
        self,
    ) -> tuple[asyncio.AbstractEventLoop, asyncio.Queue[tuple[Any, Future[Any]]]]:
        if (
            self._loop is not None
            and self._loop.is_running()
            and self._actor_queue is not None
        ):
            return self._loop, self._actor_queue

        ready = threading.Event()
        loop = asyncio.new_event_loop()

        def run_loop() -> None:
            asyncio.set_event_loop(loop)
            self._actor_queue = asyncio.Queue()
            ready.set()
            loop.run_until_complete(self._actor_worker())
            loop.close()

        thread = threading.Thread(
            target=run_loop,
            name="penguin-mcp-client-loop",
            daemon=True,
        )
        thread.start()
        ready.wait(timeout=5)
        if self._actor_queue is None:
            raise RuntimeError("MCP actor failed to start")
        self._loop = loop
        self._loop_thread = thread
        return loop, self._actor_queue

    async def _actor_worker(self) -> None:
        assert self._actor_queue is not None
        while True:
            coro, future = await self._actor_queue.get()
            if coro is None:
                future.set_result(None)
                return
            try:
                result = await coro
            except BaseException as exc:  # pragma: no cover - re-raised by caller
                future.set_exception(exc)
            else:
                future.set_result(result)

    def _stop_actor(self) -> None:
        if self._loop is None or self._actor_queue is None:
            return
        future: Future[Any] = Future()
        self._loop.call_soon_threadsafe(
            self._actor_queue.put_nowait,
            (None, future),
        )
        future.result(timeout=5)
        if self._loop_thread is not None:
            self._loop_thread.join(timeout=5)
        self._loop = None
        self._loop_thread = None
        self._actor_queue = None


__all__ = [
    "HAS_MCP_SDK",
    "MCPClientManager",
    "MCPServerStatus",
    "MCPToolDefinition",
]
