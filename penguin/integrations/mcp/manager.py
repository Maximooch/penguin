"""MCP client manager for consuming external MCP servers as Penguin tools."""

from __future__ import annotations

import asyncio
import json
import logging
from contextlib import AsyncExitStack
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

from penguin.integrations.mcp.config import MCPServerConfig
from penguin.integrations.mcp.names import make_tool_name

logger = logging.getLogger(__name__)

try:  # pragma: no cover - availability depends on optional extra
    from mcp import ClientSession, StdioServerParameters  # type: ignore
    from mcp.client.stdio import stdio_client  # type: ignore

    HAS_MCP_SDK = True
except Exception:  # pragma: no cover - exercised when extra is absent
    ClientSession = None  # type: ignore[assignment]
    StdioServerParameters = None  # type: ignore[assignment]
    stdio_client = None  # type: ignore[assignment]
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
    error: Optional[str] = None
    session: Any = None
    stack: Optional[AsyncExitStack] = None


class MCPClientManager:
    """Manage MCP client sessions and tool discovery."""

    def __init__(self, servers: list[MCPServerConfig]) -> None:
        self._states = {
            server.name: MCPServerState(config=server) for server in servers
        }
        self._tool_index: dict[str, MCPToolDefinition] = {}
        self._discovered = False

    @property
    def available(self) -> bool:
        """Return whether the optional MCP SDK is importable."""
        return HAS_MCP_SDK

    def status(self) -> dict[str, Any]:
        """Return serializable MCP manager status."""
        return {
            "available": self.available,
            "discovered": self._discovered,
            "servers": {
                name: {
                    "status": state.status.value,
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

    async def discover(self) -> list[MCPToolDefinition]:
        """Connect to configured servers and discover tools."""
        if self._discovered:
            return list(self._tool_index.values())
        if not HAS_MCP_SDK:
            logger.info("MCP SDK is not installed; no MCP tools discovered")
            self._discovered = True
            return []

        existing: set[str] = set()
        for state in self._states.values():
            await self._connect_and_list_tools(state, existing)
        self._discovered = True
        return list(self._tool_index.values())

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
        """Close all open MCP sessions."""
        for state in self._states.values():
            if state.stack is not None:
                try:
                    await state.stack.aclose()
                except Exception as exc:  # pragma: no cover - defensive cleanup
                    logger.warning("Failed closing MCP server '%s': %s", state.config.name, exc)
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
                    description=description or f"MCP tool {raw_name} from {state.config.name}",
                    input_schema=input_schema,
                )
                state.tools[public_name] = definition
                self._tool_index[public_name] = definition
            state.status = MCPServerStatus.CONNECTED
        except Exception as exc:
            state.status = MCPServerStatus.FAILED
            state.error = str(exc)
            logger.warning("MCP server '%s' discovery failed: %s", state.config.name, exc)

    async def _ensure_session(self, state: MCPServerState) -> Any:
        if state.session is not None:
            return state.session
        if not HAS_MCP_SDK:
            raise RuntimeError("MCP SDK is not installed. Install with `penguin-ai[mcp]`.")

        stack = AsyncExitStack()
        params = StdioServerParameters(  # type: ignore[misc]
            command=state.config.command,
            args=state.config.args,
            env=state.config.env or None,
            cwd=state.config.cwd,
        )
        read_stream, write_stream = await stack.enter_async_context(stdio_client(params))
        session = await stack.enter_async_context(ClientSession(read_stream, write_stream))
        await asyncio.wait_for(session.initialize(), timeout=state.config.startup_timeout_sec)
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
            return {key: MCPClientManager._serialize_call_result(value) for key, value in result.items()}
        try:
            return json.loads(json.dumps(result, default=lambda value: getattr(value, "__dict__", str(value))))
        except Exception:
            return str(result)

    @staticmethod
    def _run_async(coro: Any) -> Any:
        try:
            asyncio.get_running_loop()
        except RuntimeError:
            return asyncio.run(coro)

        result: Any = None
        error: Optional[BaseException] = None

        def run() -> None:
            nonlocal result, error
            try:
                result = asyncio.run(coro)
            except BaseException as exc:  # pragma: no cover - re-raised below
                error = exc

        import threading

        thread = threading.Thread(target=run, daemon=True)
        thread.start()
        thread.join()
        if error is not None:
            raise error
        return result


__all__ = [
    "HAS_MCP_SDK",
    "MCPClientManager",
    "MCPServerStatus",
    "MCPToolDefinition",
]
