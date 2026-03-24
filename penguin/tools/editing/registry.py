from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List, Optional


_PATCH_OPERATION_SCHEMA: Dict[str, Any] = {
    "type": "object",
    "description": "Canonical nested patch operation object",
    "properties": {
        "type": {
            "type": "string",
            "enum": [
                "unified_diff",
                "replace_lines",
                "insert_lines",
                "delete_lines",
                "regex_replace",
            ],
        },
        "diff_content": {"type": "string"},
        "search_pattern": {"type": "string"},
        "replacement": {"type": "string"},
        "start_line": {"type": "integer"},
        "end_line": {"type": "integer"},
        "after_line": {"type": "integer"},
        "new_content": {"type": "string"},
        "verify": {"type": "boolean"},
    },
    "required": ["type"],
}


EDIT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "description": "Read file contents with optional line numbers and truncation. Always shows the exact path being read.",
        "aliases": ["enhanced_read"],
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the file to read",
                },
                "show_line_numbers": {
                    "type": "boolean",
                    "description": "Show line numbers in output (default: false)",
                },
                "max_lines": {
                    "type": "integer",
                    "description": "Maximum number of lines to read (optional)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Legacy alias for `path` during migration",
                },
            },
            "required": ["path"],
        },
    },
    {
        "name": "write_file",
        "description": "Write a file with optional backup support. Accepts full file content and uses the canonical edit contract.",
        "aliases": ["write_to_file", "enhanced_write"],
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "The path of the file to write to",
                },
                "content": {
                    "type": "string",
                    "description": "The full content to write to the file",
                },
                "backup": {
                    "type": "boolean",
                    "description": "Create backup of existing file (default: true)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Legacy alias for `path` during migration",
                },
            },
            "required": ["path", "content"],
        },
    },
    {
        "name": "patch_file",
        "description": "Patch a single file. Prefer the nested JSON operation object; flat legacy fields remain supported temporarily.",
        "aliases": [
            "apply_diff",
            "edit_with_pattern",
            "replace_lines",
            "insert_lines",
            "delete_lines",
        ],
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "operation": deepcopy(_PATCH_OPERATION_SCHEMA),
                "operation_type": {
                    "type": "string",
                    "description": "Legacy flat alias for operation.type during migration",
                },
                "diff_content": {
                    "type": "string",
                    "description": "Legacy flat alias for unified diffs during migration",
                },
                "search_pattern": {
                    "type": "string",
                    "description": "Legacy flat alias for regex replacements during migration",
                },
                "replacement": {
                    "type": "string",
                    "description": "Legacy flat alias for regex replacements during migration",
                },
                "start_line": {
                    "type": "integer",
                    "description": "Legacy flat alias for line-based operations during migration",
                },
                "end_line": {
                    "type": "integer",
                    "description": "Legacy flat alias for line-based operations during migration",
                },
                "after_line": {
                    "type": "integer",
                    "description": "Legacy flat alias for insert_lines during migration",
                },
                "new_content": {
                    "type": "string",
                    "description": "Legacy flat alias for line-based operations during migration",
                },
                "verify": {
                    "type": "boolean",
                    "description": "Legacy flat alias for replace_lines verification during migration",
                },
                "backup": {
                    "type": "boolean",
                    "description": "Create backup of original file (default: true)",
                },
                "file_path": {
                    "type": "string",
                    "description": "Legacy alias for `path` during migration",
                },
            },
            "required": ["path", "operation"],
        },
    },
    {
        "name": "patch_files",
        "description": "Patch multiple files atomically. Prefer a structured JSON operations array; legacy raw patch content remains supported temporarily.",
        "aliases": ["multiedit_apply", "multiedit"],
        "input_schema": {
            "type": "object",
            "properties": {
                "apply": {
                    "type": "boolean",
                    "description": "Apply changes now (default: false for dry-run)",
                },
                "backup": {
                    "type": "boolean",
                    "description": "Default backup behavior for structured operations (default: true)",
                },
                "operations": {
                    "type": "array",
                    "description": "Canonical structured edit operations for multi-file patching",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "Target file path",
                            },
                            "operation": deepcopy(_PATCH_OPERATION_SCHEMA),
                            "backup": {
                                "type": "boolean",
                                "description": "Optional per-operation backup override",
                            },
                        },
                        "required": ["path", "operation"],
                    },
                },
                "content": {
                    "type": "string",
                    "description": "Legacy multiedit/unified patch content kept temporarily for migration",
                },
            },
            "required": [],
        },
    },
]


def get_edit_tool_schemas() -> List[Dict[str, Any]]:
    """Return deep-copied canonical edit tool schemas."""
    return deepcopy(EDIT_TOOL_SCHEMAS)


def get_edit_tool_schema(name: str) -> Dict[str, Any]:
    """Return one canonical edit tool schema by name."""
    for schema in EDIT_TOOL_SCHEMAS:
        if schema["name"] == name:
            return deepcopy(schema)
    raise KeyError(f"Unknown edit tool schema: {name}")


def get_edit_tool_schema_map() -> Dict[str, Dict[str, Any]]:
    """Return canonical edit tool schemas keyed by name."""
    return {schema["name"]: deepcopy(schema) for schema in EDIT_TOOL_SCHEMAS}


def get_edit_tool_public_names() -> List[str]:
    """Return canonical public edit tool names in prompt order."""
    return [schema["name"] for schema in EDIT_TOOL_SCHEMAS]


def get_edit_tool_aliases(name: str) -> List[str]:
    """Return aliases for one canonical edit tool."""
    schema = get_edit_tool_schema(name)
    aliases = schema.get("aliases")
    if not isinstance(aliases, list):
        return []
    return [str(alias) for alias in aliases]


def get_patch_operation_types() -> List[str]:
    """Return supported canonical patch operation types."""
    schema = get_edit_tool_schema("patch_file")
    operation = (
        schema.get("input_schema", {}).get("properties", {}).get("operation", {})
    )
    return list(operation.get("properties", {}).get("type", {}).get("enum", []))


def get_patch_files_item_schema() -> Dict[str, Any]:
    """Return the schema for one `patch_files.operations[]` entry."""
    schema = get_edit_tool_schema("patch_files")
    return deepcopy(
        schema.get("input_schema", {})
        .get("properties", {})
        .get("operations", {})
        .get("items", {})
    )
