from __future__ import annotations

from copy import deepcopy
from typing import Any, Dict, List

EDIT_TOOL_SCHEMAS: List[Dict[str, Any]] = [
    {
        "name": "read_file",
        "description": (
            "Read file contents with optional line numbers and truncation. "
            "Always shows the exact path being read."
        ),
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
        "description": (
            "Write full file content. This preflights in memory and never "
            "creates .bak files; prefer edit_file or apply_patch for partial edits."
        ),
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
                    "description": (
                        "Deprecated compatibility flag; ignored because Penguin "
                        "no longer creates in-repo .bak files"
                    ),
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
        "name": "edit_file",
        "description": (
            "Safely edit one file by replacing exact old_string text with "
            "new_string. Fails without writing if the old string is missing "
            "or ambiguous."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to the file to edit",
                },
                "old_string": {
                    "type": "string",
                    "description": (
                        "Exact current file text to replace. Must be non-empty."
                    ),
                },
                "new_string": {
                    "type": "string",
                    "description": "Replacement text",
                },
                "replace_all": {
                    "type": "boolean",
                    "description": (
                        "Replace every occurrence. Default false requires exactly "
                        "one match."
                    ),
                },
            },
            "required": ["path", "old_string", "new_string"],
        },
    },
    {
        "name": "apply_patch",
        "description": (
            "Apply a Codex-style contextual patch. Penguin validates all hunks "
            "against current file contents before writing any file."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "patch": {
                    "type": "string",
                    "description": (
                        "Patch text beginning with *** Begin Patch and ending "
                        "with *** End Patch"
                    ),
                },
            },
            "required": ["patch"],
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
    """Return supported legacy patch operation types."""
    return []


def get_patch_files_item_schema() -> Dict[str, Any]:
    """Return the deprecated `patch_files.operations[]` schema."""
    return {"type": "object", "properties": {}, "required": []}
