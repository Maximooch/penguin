from __future__ import annotations

import fnmatch
import json
from typing import Any, Dict, Iterable, List, Optional, Tuple

from penguin.tools.tool_manager import ToolManager


class MCPServer:
    """Thin adapter exposing a subset of ToolManager tools via MCP.

    - Filters tools using allow/deny patterns.
    - Normalizes input/output to structured JSON objects.
    - Provides discovery and invocation entrypoints.
    """

    def __init__(
        self,
        tool_manager: ToolManager,
        *,
        allow: Optional[Iterable[str]] = None,
        deny: Optional[Iterable[str]] = None,
        confirm_required_write: bool = True,
    ) -> None:
        self.tm = tool_manager
        self.allow = tuple(allow or ("*",))
        # Default denylists: browser/pydoll and embedding/vector tools
        self.deny = tuple(
            deny
            or (
                "browser_*",
                "pydoll_*",
                "reindex_workspace",
            )
        )
        self.confirm_required_write = confirm_required_write

    # -------------------------
    # Discovery
    # -------------------------
    def list_tools(self) -> List[Dict[str, Any]]:
        tools: List[Dict[str, Any]] = []
        for spec in getattr(self.tm, "tools", []) or []:
            name = spec.get("name")
            if not name or not self._is_allowed(name):
                continue
            tools.append(
                {
                    "name": name,
                    "description": spec.get("description", ""),
                    "input_schema": spec.get("input_schema") or {"type": "object", "properties": {}},
                }
            )
        return tools

    # -------------------------
    # Invocation
    # -------------------------
    async def call_tool(self, name: str, params: Dict[str, Any], *, confirm: bool = False) -> Dict[str, Any]:
        if not self._is_allowed(name):
            return self._error("forbidden", f"Tool '{name}' is not allowed")

        if self.confirm_required_write and self._is_write_tool(name) and not confirm:
            return self._error("confirmation_required", f"Tool '{name}' requires confirmation")

        # Resolve the callable using ToolManager's internal registry
        func = self._resolve_tool_callable(name)
        if func is None:
            return self._error("not_found", f"Tool '{name}' not found")
        try:
            result = func(**(params or {}))  # supports sync; ToolManager tools are sync
            # Some tools return coroutine (rare) – await if needed
            if hasattr(result, "__await__"):
                result = await result  # type: ignore[func-returns-value]
            return self._ok(result)
        except Exception as e:  # pragma: no cover - surface errors cleanly
            return self._error("execution_error", str(e))

    # -------------------------
    # Helpers
    # -------------------------
    def _is_allowed(self, name: str) -> bool:
        if any(fnmatch.fnmatch(name, pat) for pat in self.deny):
            return False
        return any(fnmatch.fnmatch(name, pat) for pat in self.allow)

    @staticmethod
    def _is_write_tool(name: str) -> bool:
        # Heuristic: known write/edit tools
        return name in {"apply_diff", "edit_with_pattern", "create_file", "write_to_file"}

    def _resolve_tool_callable(self, name: str):
        # ToolManager keeps a private registry mapping names to call paths
        registry: Dict[str, str] = getattr(self.tm, "_tool_registry", {})
        target = registry.get(name)
        if not target:
            return None
        # Resolve 'self.xxx' members directly on ToolManager
        if target.startswith("self."):
            attr_path = target.split(".")
            obj = self.tm
            for part in attr_path[1:]:
                obj = getattr(obj, part)
            return obj
        # Otherwise, import the function dynamically
        try:
            import importlib

            module_path, func_name = target.rsplit(".", 1)
            mod = importlib.import_module(module_path)
            return getattr(mod, func_name)
        except Exception:
            return None

    @staticmethod
    def _ok(data: Any) -> Dict[str, Any]:
        return {"status": "ok", "data": data}

    @staticmethod
    def _error(code: str, message: str) -> Dict[str, Any]:
        return {"status": "error", "error": {"code": code, "message": message}}


