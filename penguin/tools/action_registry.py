"""Compatibility registry for ActionXML tool routing.

This registry centralizes the routes that can already be expressed as
ToolManager tool invocations. ActionExecutor remains the compatibility wrapper
for legacy, UI-heavy, or manager-specific handlers that have not moved yet.
"""

# Keep Optional annotations for Python 3.9 compatibility.
# ruff: noqa: UP007
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional

from penguin.utils.parser import (
    ActionType,
    parse_patch_file_payload,
    parse_patch_files_payload,
    parse_read_file_payload,
    parse_write_file_payload,
)

ToolInputBuilder = Callable[[Any], dict[str, Any]]


@dataclass(frozen=True)
class ActionToolRoute:
    """Registry entry mapping one ActionXML action to one ToolManager tool."""

    action_type: ActionType
    tool_name: str
    build_input: ToolInputBuilder
    canonical_action_type: Optional[ActionType] = None


class ActionToolRegistry:
    """Registry for ActionXML actions that can route through ToolManager."""

    def __init__(self, routes: list[ActionToolRoute]) -> None:
        self._routes = {route.action_type: route for route in routes}

    def get(self, action_type: ActionType) -> Optional[ActionToolRoute]:
        """Return the route for an action type, if registered."""

        return self._routes.get(action_type)

    def has(self, action_type: ActionType) -> bool:
        """Return whether an action type is registered."""

        return action_type in self._routes

    def action_types(self) -> tuple[ActionType, ...]:
        """Return registered action types."""

        return tuple(self._routes.keys())

    def execute(self, action_type: ActionType, params: Any, tool_manager: Any) -> Any:
        """Build tool input and execute the registered ToolManager tool."""

        route = self.get(action_type)
        if route is None:
            raise KeyError(action_type)

        tool_input = route.build_input(params)
        error = tool_input.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"
        return tool_manager.execute_tool(route.tool_name, tool_input)


def _read_file_input(params: Any) -> dict[str, Any]:
    parsed = parse_read_file_payload(params)
    if "error" in parsed:
        return parsed
    return {
        "path": parsed["path"],
        "show_line_numbers": parsed["show_line_numbers"],
        "max_lines": parsed["max_lines"],
    }


def _write_file_input(params: Any) -> dict[str, Any]:
    parsed = parse_write_file_payload(params)
    if "error" in parsed:
        return parsed
    return {
        "path": parsed["path"],
        "content": parsed["content"],
        "backup": parsed["backup"],
        "_warnings": parsed.get("warnings", []),
    }


def _patch_file_input(
    params: Any,
    *,
    default_operation_type: Optional[str] = None,
) -> dict[str, Any]:
    parsed = parse_patch_file_payload(
        params,
        default_operation_type=default_operation_type,
    )
    if "error" in parsed:
        return parsed
    return {
        "path": parsed["path"],
        "operation": parsed["operation"],
        "backup": parsed["backup"],
        "_warnings": parsed.get("warnings", []),
    }


def _patch_files_input(params: Any) -> dict[str, Any]:
    parsed = parse_patch_files_payload(params)
    if "error" in parsed:
        return parsed

    tool_input: dict[str, Any] = {
        "apply": parsed.get("apply", False),
        "backup": parsed.get("backup", True),
        "_warnings": parsed.get("warnings", []),
    }
    if isinstance(parsed.get("operations"), list):
        tool_input["operations"] = parsed["operations"]
    elif isinstance(parsed.get("content"), str):
        tool_input["content"] = parsed["content"]
    return tool_input


def create_default_action_tool_registry() -> ActionToolRegistry:
    """Create the default ActionXML-to-ToolManager registry."""

    routes = [
        ActionToolRoute(
            ActionType.EXECUTE,
            "code_execution",
            lambda params: {"code": params},
        ),
        ActionToolRoute(
            ActionType.EXECUTE_COMMAND,
            "execute_command",
            lambda params: {"command": params},
        ),
        ActionToolRoute(
            ActionType.SEARCH,
            "grep_search",
            lambda params: {"pattern": params},
        ),
        ActionToolRoute(ActionType.READ_FILE, "read_file", _read_file_input),
        ActionToolRoute(
            ActionType.ENHANCED_READ,
            "read_file",
            _read_file_input,
            canonical_action_type=ActionType.READ_FILE,
        ),
        ActionToolRoute(ActionType.WRITE_FILE, "write_file", _write_file_input),
        ActionToolRoute(
            ActionType.ENHANCED_WRITE,
            "write_file",
            _write_file_input,
            canonical_action_type=ActionType.WRITE_FILE,
        ),
        ActionToolRoute(ActionType.PATCH_FILE, "patch_file", _patch_file_input),
        ActionToolRoute(
            ActionType.APPLY_DIFF,
            "patch_file",
            lambda params: _patch_file_input(
                params,
                default_operation_type="unified_diff",
            ),
            canonical_action_type=ActionType.PATCH_FILE,
        ),
        ActionToolRoute(ActionType.PATCH_FILES, "patch_files", _patch_files_input),
        ActionToolRoute(
            ActionType.MULTIEDIT,
            "patch_files",
            _patch_files_input,
            canonical_action_type=ActionType.PATCH_FILES,
        ),
        ActionToolRoute(
            ActionType.EDIT_WITH_PATTERN,
            "patch_file",
            lambda params: _patch_file_input(
                params,
                default_operation_type="regex_replace",
            ),
            canonical_action_type=ActionType.PATCH_FILE,
        ),
        ActionToolRoute(
            ActionType.REPLACE_LINES,
            "patch_file",
            lambda params: _patch_file_input(
                params,
                default_operation_type="replace_lines",
            ),
            canonical_action_type=ActionType.PATCH_FILE,
        ),
        ActionToolRoute(
            ActionType.INSERT_LINES,
            "patch_file",
            lambda params: _patch_file_input(
                params,
                default_operation_type="insert_lines",
            ),
            canonical_action_type=ActionType.PATCH_FILE,
        ),
        ActionToolRoute(
            ActionType.DELETE_LINES,
            "patch_file",
            lambda params: _patch_file_input(
                params,
                default_operation_type="delete_lines",
            ),
            canonical_action_type=ActionType.PATCH_FILE,
        ),
    ]
    return ActionToolRegistry(routes)


__all__ = [
    "ActionToolRegistry",
    "ActionToolRoute",
    "ToolInputBuilder",
    "create_default_action_tool_registry",
]
