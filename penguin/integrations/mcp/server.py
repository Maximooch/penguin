"""Expose selected Penguin tools through a real MCP server."""

from __future__ import annotations

import inspect
import json
import logging
import re
import sys
from dataclasses import dataclass, field
from typing import Any, Callable, Iterable, Optional

try:  # pragma: no cover - import availability depends on optional extra
    from mcp.server.fastmcp import FastMCP

    HAS_MCP_SERVER_SDK = True
except Exception:  # pragma: no cover - exercised when optional extra missing
    FastMCP = None  # type: ignore[assignment]
    HAS_MCP_SERVER_SDK = False

from penguin.integrations.mcp.server_tools import (
    MCPServerTool,
    build_blueprint_tools,
    RunModeJobRegistry,
    build_pm_tools,
    build_runmode_tools,
)
from penguin.tools.tool_manager import ToolManager

logger = logging.getLogger(__name__)

DEFAULT_EXPOSED_TOOLS = (
    "read_file",
    "list_files",
    "find_file",
    "grep_search",
    "analyze_project",
    "penguin_pm_*",
    "penguin_blueprint_*",
    "penguin_runmode_*",
)

DEFAULT_DENIED_PATTERNS = (
    "mcp__*",
    "execute*",
    "run_*",
    "process_*",
    "browser_*",
    "pydoll_*",
    "create_*",
    "write_*",
    "patch_*",
    "delete_*",
    "apply_*",
    "edit_*",
    "reindex_workspace",
    "spawn_sub_agent",
    "delegate*",
    "send_message",
)

_JSON_TYPE_TO_PYTHON: dict[str, Any] = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


@dataclass(frozen=True)
class PenguinMCPServerConfig:
    """Configuration for exposing Penguin as an MCP server."""

    name: str = "penguin"
    allow_tools: tuple[str, ...] = DEFAULT_EXPOSED_TOOLS
    deny_patterns: tuple[str, ...] = DEFAULT_DENIED_PATTERNS
    transport: str = "stdio"
    enabled: bool = True
    expose_pm_tools: bool = True
    expose_blueprint_tools: bool = True
    expose_runtime_tools: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


class MCPServerUnavailableError(RuntimeError):
    """Raised when the optional MCP SDK server extra is unavailable."""


class PenguinMCPServer:
    """SDK-backed MCP server exposing selected Penguin ToolManager tools."""

    def __init__(
        self,
        tool_manager: ToolManager,
        config: Optional[PenguinMCPServerConfig] = None,
        core: Any = None,
    ) -> None:
        self.tool_manager = tool_manager
        self.config = config or PenguinMCPServerConfig()
        self.core = core or getattr(tool_manager, "_core", None)
        self._runmode_job_registry = RunModeJobRegistry()
        self._runtime_tools = self._build_runtime_tools()
        self._runtime_tool_map = {tool.name: tool for tool in self._runtime_tools}
        self._tool_schemas = self._select_tool_schemas()

    def list_exposed_tools(self) -> list[dict[str, Any]]:
        """Return the selected ToolManager schemas exposed over MCP."""
        return list(self._tool_schemas)

    def create_fastmcp(self) -> Any:
        """Create and populate a FastMCP server instance."""
        if not HAS_MCP_SERVER_SDK or FastMCP is None:
            raise MCPServerUnavailableError(
                "MCP server SDK is not installed. Install with `penguin-ai[mcp]` "
                "on Python 3.10+."
            )

        mcp = FastMCP(self.config.name)
        for schema in self._tool_schemas:
            handler = self._build_tool_handler(schema)
            mcp.add_tool(
                handler,
                name=schema["name"],
                description=schema.get("description") or "Penguin tool",
                structured_output=False,
            )
        return mcp

    def run(self, transport: Optional[str] = None) -> None:
        """Run the FastMCP server."""
        selected_transport = transport or self.config.transport
        if selected_transport != "stdio":
            raise ValueError(
                "Phase 2A only supports stdio transport for Penguin MCP server."
            )
        self.create_fastmcp().run(transport="stdio")

    def call_tool(self, tool_name: str, arguments: dict[str, Any]) -> str:
        """Route an MCP call through ToolManager.execute_tool()."""
        if not self._is_allowed(tool_name):
            return json.dumps(
                {
                    "error": "tool_not_exposed",
                    "tool": tool_name,
                    "message": "This Penguin tool is not exposed over MCP.",
                },
                indent=2,
            )

        runtime_tool = self._runtime_tool_map.get(tool_name)
        if runtime_tool is not None:
            try:
                result = runtime_tool.handler(arguments or {})
            except Exception as exc:
                return json.dumps(
                    {
                        "error": "penguin_runtime_tool_failed",
                        "tool": tool_name,
                        "message": str(exc),
                    },
                    indent=2,
                    default=str,
                )
        else:
            result = self.tool_manager.execute_tool(tool_name, arguments or {})
        if isinstance(result, str):
            return result
        return json.dumps(result, indent=2, default=str)

    def _select_tool_schemas(self) -> list[dict[str, Any]]:
        schemas: list[dict[str, Any]] = []
        for schema in self.tool_manager.get_tools():
            name = schema.get("name")
            if not isinstance(name, str) or not self._is_allowed(name):
                continue
            schemas.append(
                {
                    "name": name,
                    "description": schema.get("description", ""),
                    "input_schema": _object_schema(schema.get("input_schema")),
                }
            )
        for tool in self._runtime_tools:
            if self._is_allowed(tool.name):
                schemas.append(
                    {
                        "name": tool.name,
                        "description": tool.description,
                        "input_schema": _object_schema(tool.input_schema),
                    }
                )
        return schemas

    def _build_runtime_tools(self) -> list[MCPServerTool]:
        if self.core is None:
            return []
        tools: list[MCPServerTool] = []
        if self.config.expose_pm_tools:
            tools.extend(build_pm_tools(self.core))
        if self.config.expose_blueprint_tools:
            tools.extend(build_blueprint_tools(self.core))
        if self.config.expose_runtime_tools:
            tools.extend(build_runmode_tools(self.core, self._runmode_job_registry))
        return tools

    def _is_allowed(self, tool_name: str) -> bool:
        if any(_glob_match(tool_name, pattern) for pattern in self.config.deny_patterns):
            return False
        return any(_glob_match(tool_name, pattern) for pattern in self.config.allow_tools)

    def _build_tool_handler(self, schema: dict[str, Any]) -> Callable[..., Any]:
        tool_name = schema["name"]
        input_schema = _object_schema(schema.get("input_schema"))
        properties = input_schema.get("properties", {})
        required = set(input_schema.get("required", []))
        param_to_property: dict[str, str] = {}

        async def handler(**kwargs: Any) -> str:
            arguments = {
                param_to_property.get(key, key): value for key, value in kwargs.items()
            }
            return self.call_tool(tool_name, arguments)

        handler.__name__ = _safe_identifier(tool_name)
        handler.__doc__ = schema.get("description") or f"Run Penguin tool {tool_name}."
        parameters: list[inspect.Parameter] = []

        for property_name, property_schema in properties.items():
            param_name = _safe_identifier(property_name)
            if param_name in param_to_property:
                param_name = f"{param_name}_{len(param_to_property)}"
            param_to_property[param_name] = property_name
            default = inspect.Parameter.empty if property_name in required else None
            annotation = _python_annotation_for_schema(property_schema)
            parameters.append(
                inspect.Parameter(
                    param_name,
                    inspect.Parameter.KEYWORD_ONLY,
                    default=default,
                    annotation=annotation,
                )
            )

        handler.__signature__ = inspect.Signature(  # type: ignore[attr-defined]
            parameters=parameters,
            return_annotation=str,
        )
        return handler


def build_penguin_mcp_server(
    tool_manager: ToolManager,
    *,
    allow_tools: Optional[Iterable[str]] = None,
    deny_patterns: Optional[Iterable[str]] = None,
    name: str = "penguin",
    core: Any = None,
    expose_pm_tools: bool = True,
    expose_blueprint_tools: bool = True,
    expose_runtime_tools: bool = False,
) -> PenguinMCPServer:
    """Build a configured Penguin MCP server wrapper."""
    return PenguinMCPServer(
        tool_manager,
        PenguinMCPServerConfig(
            name=name,
            allow_tools=tuple(allow_tools or DEFAULT_EXPOSED_TOOLS),
            deny_patterns=tuple(deny_patterns or DEFAULT_DENIED_PATTERNS),
            expose_pm_tools=expose_pm_tools,
            expose_blueprint_tools=expose_blueprint_tools,
            expose_runtime_tools=expose_runtime_tools,
        ),
        core=core,
    )


def _object_schema(schema: Any) -> dict[str, Any]:
    if not isinstance(schema, dict):
        return {"type": "object", "properties": {}}
    result = dict(schema)
    if result.get("type") != "object":
        result["type"] = "object"
    if not isinstance(result.get("properties"), dict):
        result["properties"] = {}
    return result


def _python_annotation_for_schema(schema: Any) -> Any:
    if not isinstance(schema, dict):
        return Any
    schema_type = schema.get("type")
    if isinstance(schema_type, list):
        schema_type = next((item for item in schema_type if item != "null"), None)
    return _JSON_TYPE_TO_PYTHON.get(str(schema_type), Any)


def _safe_identifier(value: str) -> str:
    cleaned = re.sub(r"\W+", "_", value).strip("_") or "tool"
    if cleaned[0].isdigit():
        cleaned = f"_{cleaned}"
    if not cleaned.isidentifier():
        cleaned = "tool"
    return cleaned


def _glob_match(value: str, pattern: str) -> bool:
    regex = "^" + re.escape(pattern).replace("\\*", ".*") + "$"
    return re.match(regex, value) is not None


def configure_stdio_logging() -> None:
    """Configure logging for stdio MCP mode without corrupting stdout."""
    logging.basicConfig(
        level=logging.INFO,
        stream=sys.stderr,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


__all__ = [
    "DEFAULT_DENIED_PATTERNS",
    "DEFAULT_EXPOSED_TOOLS",
    "HAS_MCP_SERVER_SDK",
    "MCPServerUnavailableError",
    "PenguinMCPServer",
    "PenguinMCPServerConfig",
    "build_penguin_mcp_server",
    "configure_stdio_logging",
]
