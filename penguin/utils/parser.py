# Implementing a parser for the actions that the AI returns in its response.
# This is a simple parser that can be extended to support more complex actions.
# The parser is based on the idea of "action types" and "parameters" that are returned in the AI response.

# Inspired by the CodeAct paper: https://arxiv.org/abs/2402.01030
# CodeAct Github: https://github.com/xingyaoww/code-act

import asyncio
import json
import logging
import re
import time
from datetime import datetime
from enum import Enum
from html import unescape
from pathlib import Path
from typing import List, Dict, Any, Optional, Callable, Awaitable
import base64
from penguin.local_task.manager import ProjectManager
from penguin.tools import ToolManager
from penguin.utils.process_manager import ProcessManager
from penguin.system.conversation import MessageCategory
from penguin.system.execution_context import get_current_execution_context
from penguin.tools.browser_tools import BrowserScreenshotTool, browser_manager
from penguin.constants import (
    DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP,
    get_engine_max_iterations_default,
    DEFAULT_LARGE_FILE_THRESHOLD_BYTES,
)
import os

logger = logging.getLogger(__name__)


class ActionType(Enum):
    # READ = "read"
    # WRITE = "write"
    EXECUTE = "execute"
    EXECUTE_COMMAND = "execute_command"
    SEARCH = "search"
    # CREATE_FILE = "create_file"
    # CREATE_FOLDER = "create_folder"
    # LIST_FILES = "list_files"
    # LIST_FOLDERS = "list_folders"
    # GET_FILE_MAP = "get_file_map"
    # LINT = "lint"
    MEMORY_SEARCH = "memory_search"
    ADD_DECLARATIVE_NOTE = "add_declarative_note"
    # Enhanced file operations
    LIST_FILES_FILTERED = "list_files_filtered"
    FIND_FILES_ENHANCED = "find_files_enhanced"
    ENHANCED_DIFF = "enhanced_diff"
    ANALYZE_PROJECT = "analyze_project"
    READ_FILE = "read_file"
    ENHANCED_READ = "enhanced_read"
    ENHANCED_WRITE = "enhanced_write"
    WRITE_FILE = "write_file"
    APPLY_DIFF = "apply_diff"
    PATCH_FILE = "patch_file"
    MULTIEDIT = "multiedit"
    PATCH_FILES = "patch_files"
    EDIT_WITH_PATTERN = "edit_with_pattern"
    REPLACE_LINES = "replace_lines"
    INSERT_LINES = "insert_lines"
    DELETE_LINES = "delete_lines"
    # TASK_CREATE = "task_create"
    # TASK_UPDATE = "task_update"
    # TASK_COMPLETE = "task_complete"
    # TASK_LIST = "task_list"
    # PROJECT_CREATE = "project_create"
    # PROJECT_UPDATE = "project_update"
    # PROJECT_COMPLETE = "project_complete"
    # PROJECT_LIST = "project_list"
    # SUBTASK_ADD = "subtask_add"
    # TODO: add subtask_update, subtask_complete, subtask_list
    # TASK_DETAILS = "task_details"
    # PROJECT_DETAILS = "project_details"
    # WORKFLOW_ANALYZE = "workflow_analyze"
    ADD_SUMMARY_NOTE = "add_summary_note"
    PERPLEXITY_SEARCH = "perplexity_search"
    # REPL, iPython, shell, bash, zsh, networking, file_management, task management, etc.
    # TODO: Add more actions as needed
    PROCESS_START = "process_start"
    PROCESS_STOP = "process_stop"
    PROCESS_STATUS = "process_status"
    PROCESS_LIST = "process_list"
    PROCESS_ENTER = "process_enter"
    PROCESS_SEND = "process_send"
    PROCESS_EXIT = "process_exit"
    WORKSPACE_SEARCH = "workspace_search"
    TODOWRITE = "todowrite"
    TODOREAD = "todoread"
    QUESTION = "question"
    # Task Management Actions
    TASK_CREATE = "task_create"
    TASK_UPDATE = "task_update"
    TASK_COMPLETE = "task_complete"
    TASK_DELETE = "task_delete"
    TASK_LIST = "task_list"
    TASK_DISPLAY = "task_display"
    # Response/Task completion signals (explicit termination)
    FINISH_RESPONSE = "finish_response"
    FINISH_TASK = "finish_task"
    # Legacy alias - kept for backward compatibility
    TASK_COMPLETED = "task_completed"  # Deprecated: use FINISH_TASK
    PROJECT_CREATE = "project_create"
    PROJECT_UPDATE = "project_update"
    PROJECT_DELETE = "project_delete"
    PROJECT_LIST = "project_list"
    PROJECT_DISPLAY = "project_display"
    DEPENDENCY_DISPLAY = "dependency_display"
    ANALYZE_CODEBASE = "analyze_codebase"
    REINDEX_WORKSPACE = "reindex_workspace"
    SEND_MESSAGE = "send_message"
    # Browser actions
    BROWSER_NAVIGATE = "browser_navigate"
    BROWSER_INTERACT = "browser_interact"
    BROWSER_SCREENSHOT = "browser_screenshot"
    # PyDoll browser actions
    PYDOLL_BROWSER_NAVIGATE = "pydoll_browser_navigate"
    PYDOLL_BROWSER_INTERACT = "pydoll_browser_interact"
    PYDOLL_BROWSER_SCREENSHOT = "pydoll_browser_screenshot"
    PYDOLL_BROWSER_SCROLL = "pydoll_browser_scroll"
    # PyDoll debug toggle
    PYDOLL_DEBUG_TOGGLE = "pydoll_debug_toggle"

    # Sub-agent tools (agents-as-tools)
    SPAWN_SUB_AGENT = "spawn_sub_agent"
    STOP_SUB_AGENT = "stop_sub_agent"
    RESUME_SUB_AGENT = "resume_sub_agent"
    GET_AGENT_STATUS = "get_agent_status"
    WAIT_FOR_AGENTS = "wait_for_agents"
    GET_CONTEXT_INFO = "get_context_info"
    SYNC_CONTEXT = "sync_context"
    DELEGATE = "delegate"
    DELEGATE_EXPLORE_TASK = "delegate_explore_task"

    # Repository management actions
    GET_REPOSITORY_STATUS = "get_repository_status"
    CREATE_AND_SWITCH_BRANCH = "create_and_switch_branch"
    COMMIT_AND_PUSH_CHANGES = "commit_and_push_changes"
    CREATE_IMPROVEMENT_PR = "create_improvement_pr"
    CREATE_FEATURE_PR = "create_feature_pr"
    CREATE_BUGFIX_PR = "create_bugfix_pr"


class CodeActAction:
    def __init__(self, action_type, params):
        self.action_type = action_type
        self.params = params


def _split_unescaped(
    value: str,
    separator: str = ":",
    *,
    maxsplit: int = -1,
) -> List[str]:
    """Split on unescaped separators while preserving regex backslashes."""
    if not value:
        return [""]

    parts: List[str] = []
    current: List[str] = []
    splits = 0
    escape_next = False

    for char in value:
        if escape_next:
            if char in {separator, "\\"}:
                current.append(char)
            else:
                current.append("\\")
                current.append(char)
            escape_next = False
            continue

        if char == "\\":
            escape_next = True
            continue

        if char == separator and (maxsplit < 0 or splits < maxsplit):
            parts.append("".join(current))
            current = []
            splits += 1
            continue

        current.append(char)

    if escape_next:
        current.append("\\")

    parts.append("".join(current))
    return parts


def _find_unescaped_separator(
    value: str,
    separator: str = ":",
    *,
    reverse: bool = False,
) -> int:
    """Return the index of the next unescaped separator, or -1."""
    if not value:
        return -1

    indices = range(len(value) - 1, -1, -1) if reverse else range(len(value))
    for index in indices:
        if value[index] != separator:
            continue

        backslash_count = 0
        probe = index - 1
        while probe >= 0 and value[probe] == "\\":
            backslash_count += 1
            probe -= 1

        if backslash_count % 2 == 0:
            return index

    return -1


def _decode_escaped_edit_field(value: str, separator: str = ":") -> str:
    """Decode escaped separators/backslashes while preserving regex escapes."""
    if not value:
        return value

    decoded: List[str] = []
    index = 0
    while index < len(value):
        char = value[index]
        if char == "\\" and index + 1 < len(value):
            next_char = value[index + 1]
            if next_char in {separator, "\\"}:
                decoded.append(next_char)
                index += 2
                continue
        decoded.append(char)
        index += 1
    return "".join(decoded)


def parse_edit_with_pattern_payload(params: Any) -> Dict[str, Any]:
    """Parse regex edit payloads from JSON or escaped colon-delimited strings."""
    if isinstance(params, dict):
        payload = dict(params)
        file_path = payload.get("file_path") or payload.get("path") or ""
        search_pattern = payload.get("search_pattern") or payload.get("pattern")
        replacement = payload.get("replacement")
        if not isinstance(file_path, str) or not file_path.strip():
            return {"error": "Need file_path for edit_with_pattern"}
        if not isinstance(search_pattern, str):
            return {"error": "Need search_pattern for edit_with_pattern"}
        if not isinstance(replacement, str):
            return {"error": "Need replacement for edit_with_pattern"}
        backup = payload.get("backup", True)
        return {
            "file_path": file_path.strip(),
            "search_pattern": search_pattern,
            "replacement": replacement,
            "backup": bool(backup),
        }

    if not isinstance(params, str) or not params.strip():
        return {"error": "Need file_path:search_pattern:replacement format"}

    text = params.strip()
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
        except json.JSONDecodeError as exc:
            return {"error": f"edit_with_pattern expects valid JSON payload: {exc}"}
        return parse_edit_with_pattern_payload(parsed)

    backup = True
    body = text
    backup_index = _find_unescaped_separator(text, reverse=True)
    if backup_index >= 0:
        maybe_flag = text[backup_index + 1 :].strip().lower()
        if maybe_flag in {"true", "false"}:
            body = text[:backup_index]
            backup = maybe_flag == "true"

    path_index = _find_unescaped_separator(body)
    if path_index < 0:
        return {"error": "Need file_path:search_pattern:replacement format"}

    file_path = body[:path_index].strip()
    if not file_path:
        return {"error": "Need file_path:search_pattern:replacement format"}

    remainder = body[path_index + 1 :]
    pattern_index = _find_unescaped_separator(remainder)
    if pattern_index < 0:
        return {
            "error": (
                "Need file_path:search_pattern:replacement format. "
                "Escape literal colons in search patterns as \\: or use JSON payloads."
            )
        }

    search_pattern = _decode_escaped_edit_field(remainder[:pattern_index])
    replacement = _decode_escaped_edit_field(remainder[pattern_index + 1 :])
    if not search_pattern:
        return {"error": "Need search_pattern for edit_with_pattern"}

    return {
        "file_path": file_path,
        "search_pattern": search_pattern,
        "replacement": replacement,
        "backup": backup,
    }


def _parse_json_payload(params: Any) -> Optional[Dict[str, Any]]:
    """Parse JSON object payloads from dicts or JSON strings."""
    if isinstance(params, dict):
        return dict(params)
    if not isinstance(params, str):
        return None
    text = params.strip()
    if not text.startswith("{"):
        return None
    try:
        parsed = json.loads(text)
    except Exception:
        return None
    return parsed if isinstance(parsed, dict) else None


def _deprecated_payload_warning(tool_name: str, detail: str) -> str:
    """Build a consistent warning string for migration payloads."""
    return f"Deprecated {tool_name} payload: {detail}"


def _legacy_bool_suffix_payload(
    params: str,
    *,
    label: str,
) -> Dict[str, Any]:
    """Parse `path:content[:true|false]` legacy payloads."""
    first_sep = params.find(":")
    if first_sep == -1:
        return {"error": f"Need {label} format"}

    path = params[:first_sep].strip()
    remainder = params[first_sep + 1 :]
    if not path or not remainder:
        return {"error": f"Need {label} format"}

    backup = True
    content = remainder
    if ":" in remainder:
        content_part, flag = remainder.rsplit(":", 1)
        flag_stripped = flag.strip().lower()
        if flag_stripped in {"true", "false"} and "\n" not in flag and "\r" not in flag:
            backup = flag_stripped == "true"
            content = content_part

    return {"path": path, "content": content, "backup": backup}


def parse_write_file_payload(params: Any) -> Dict[str, Any]:
    """Parse canonical or legacy write-file payloads."""
    payload = _parse_json_payload(params)
    warnings: List[str] = []
    if payload is not None:
        path = payload.get("path") or payload.get("file_path") or ""
        content = payload.get("content")
        if not isinstance(path, str) or not path.strip():
            return {"error": "write_file requires 'path'"}
        if not isinstance(content, str):
            return {"error": "write_file requires 'content'"}
        if "file_path" in payload and "path" not in payload:
            warnings.append(
                _deprecated_payload_warning(
                    "write_file",
                    "use 'path' instead of legacy 'file_path'",
                )
            )
        return {
            "path": path.strip(),
            "content": content,
            "backup": bool(payload.get("backup", True)),
            "warnings": warnings,
        }

    if not isinstance(params, str) or not params.strip():
        return {
            "error": "write_file requires JSON payload or legacy path:content format"
        }

    parsed = _legacy_bool_suffix_payload(params, label="path:content[:backup]")
    error = parsed.get("error")
    if isinstance(error, str):
        return {"error": error}
    parsed["warnings"] = [
        _deprecated_payload_warning(
            "write_file",
            "use JSON object payloads instead of colon-delimited strings",
        )
    ]
    return parsed


def parse_read_file_payload(params: Any) -> Dict[str, Any]:
    """Parse canonical or legacy read-file payloads."""
    payload = _parse_json_payload(params)
    warnings: List[str] = []
    if payload is not None:
        path = payload.get("path") or payload.get("file_path") or ""
        if not isinstance(path, str) or not path.strip():
            return {"error": "read_file requires 'path'"}
        if "file_path" in payload and "path" not in payload:
            warnings.append(
                _deprecated_payload_warning(
                    "read_file",
                    "use 'path' instead of legacy 'file_path'",
                )
            )
        max_lines = payload.get("max_lines")
        if max_lines is not None:
            try:
                max_lines = int(max_lines)
            except Exception:
                return {"error": "read_file max_lines must be an integer"}
        return {
            "path": path.strip(),
            "show_line_numbers": bool(payload.get("show_line_numbers", False)),
            "max_lines": max_lines,
            "warnings": warnings,
        }

    if not isinstance(params, str) or not params.strip():
        return {
            "error": "read_file requires JSON payload or legacy path[:show_line_numbers[:max_lines]] format"
        }

    parts = params.split(":")
    if not parts or not parts[0].strip():
        return {"error": "File path is required"}
    path = parts[0].strip()
    show_line_numbers = parts[1].strip().lower() == "true" if len(parts) > 1 else False
    max_lines = None
    if len(parts) > 2 and parts[2].strip():
        if not parts[2].strip().isdigit():
            return {"error": "read_file max_lines must be an integer"}
        max_lines = int(parts[2].strip())

    return {
        "path": path,
        "show_line_numbers": show_line_numbers,
        "max_lines": max_lines,
        "warnings": [
            _deprecated_payload_warning(
                "read_file",
                "use JSON object payloads instead of colon-delimited strings",
            )
        ],
    }


def _infer_patch_operation_type(payload: Dict[str, Any]) -> Optional[str]:
    """Infer a patch operation type from flat payload keys."""
    if "diff_content" in payload or "diff" in payload:
        return "unified_diff"
    if (
        "search_pattern" in payload or "pattern" in payload
    ) and "replacement" in payload:
        return "regex_replace"
    if "after_line" in payload:
        return "insert_lines"
    if {"start_line", "end_line", "new_content"}.issubset(payload):
        return "replace_lines"
    if {"start_line", "end_line"}.issubset(payload):
        return "delete_lines"
    return None


def _build_patch_operation_payload(
    operation_type: str,
    payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Normalize flat patch payload fields into a canonical operation object."""
    if operation_type == "unified_diff":
        return {
            "type": "unified_diff",
            "diff_content": payload.get("diff_content") or payload.get("diff") or "",
        }
    if operation_type == "regex_replace":
        return {
            "type": "regex_replace",
            "search_pattern": payload.get("search_pattern")
            or payload.get("pattern")
            or "",
            "replacement": payload.get("replacement") or "",
        }
    if operation_type == "replace_lines":
        return {
            "type": "replace_lines",
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
            "new_content": payload.get("new_content", ""),
            "verify": payload.get("verify", True),
        }
    if operation_type == "insert_lines":
        return {
            "type": "insert_lines",
            "after_line": payload.get("after_line"),
            "new_content": payload.get("new_content", ""),
        }
    if operation_type == "delete_lines":
        return {
            "type": "delete_lines",
            "start_line": payload.get("start_line"),
            "end_line": payload.get("end_line"),
        }
    return {"type": operation_type}


def parse_patch_file_payload(
    params: Any,
    *,
    default_operation_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse canonical or legacy patch-file payloads into nested JSON shape."""
    payload = _parse_json_payload(params)
    warnings: List[str] = []
    if payload is not None:
        operation_payload = payload.get("operation")
        path = payload.get("path") or payload.get("file_path") or ""
        backup = payload.get("backup", True)

        if isinstance(operation_payload, dict):
            operation = dict(operation_payload)
            operation_type = operation.get("type") or payload.get("operation_type")
            if not operation_type:
                operation_type = _infer_patch_operation_type(operation)
            if not operation_type:
                return {"error": "patch_file requires operation.type"}
            operation["type"] = operation_type
            path = path or operation.get("path") or operation.get("file_path") or ""
            operation.pop("path", None)
            operation.pop("file_path", None)
            if "file_path" in payload and "path" not in payload:
                warnings.append(
                    _deprecated_payload_warning(
                        "patch_file",
                        "use top-level 'path' instead of legacy 'file_path'",
                    )
                )
            if not isinstance(path, str) or not path.strip():
                return {"error": "patch_file requires 'path'"}
            return {
                "path": path.strip(),
                "operation": operation,
                "backup": bool(backup),
                "warnings": warnings,
            }

        operation_type = (
            payload.get("operation_type")
            or payload.get("type")
            or default_operation_type
            or _infer_patch_operation_type(payload)
        )
        if not operation_type:
            return {
                "error": "patch_file requires an operation object or operation_type"
            }
        if not isinstance(path, str) or not path.strip():
            return {"error": "patch_file requires 'path'"}
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "flat JSON payloads are deprecated; use a nested operation object",
            )
        )
        if "file_path" in payload and "path" not in payload:
            warnings.append(
                _deprecated_payload_warning(
                    "patch_file",
                    "use 'path' instead of legacy 'file_path'",
                )
            )
        return {
            "path": path.strip(),
            "operation": _build_patch_operation_payload(operation_type, payload),
            "backup": bool(backup),
            "warnings": warnings,
        }

    if default_operation_type is None:
        return {
            "error": (
                "patch_file requires JSON payloads. Use {'path': ..., 'operation': {...}} "
                "or a legacy action tag during migration."
            )
        }

    if not isinstance(params, str) or not params.strip():
        return {"error": "patch_file legacy payload is empty"}

    if default_operation_type == "unified_diff":
        parsed = _legacy_bool_suffix_payload(
            params, label="file_path:diff_content[:backup]"
        )
        error = parsed.get("error")
        if isinstance(error, str):
            return {"error": error}
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "legacy diff strings are deprecated; use JSON payloads",
            )
        )
        return {
            "path": parsed["path"],
            "operation": {
                "type": "unified_diff",
                "diff_content": parsed["content"],
            },
            "backup": parsed["backup"],
            "warnings": warnings,
        }

    if default_operation_type == "regex_replace":
        parsed = parse_edit_with_pattern_payload(params)
        error = parsed.get("error")
        if isinstance(error, str):
            return {"error": error}
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "legacy edit_with_pattern strings are deprecated; use JSON payloads",
            )
        )
        return {
            "path": parsed["file_path"],
            "operation": {
                "type": "regex_replace",
                "search_pattern": parsed["search_pattern"],
                "replacement": parsed["replacement"],
            },
            "backup": parsed["backup"],
            "warnings": warnings,
        }

    if default_operation_type == "replace_lines":
        parts = str(params).split(":", 3)
        if len(parts) < 4:
            return {"error": "Need path:start_line:end_line:new_content format"}
        path = parts[0].strip()
        if not path:
            return {"error": "Need path for replace_lines"}
        try:
            start_line = int(parts[1].strip())
            end_line = int(parts[2].strip())
        except ValueError:
            return {"error": "start_line and end_line must be integers"}
        verify = True
        new_content = parts[3]
        if ":" in new_content:
            content_part, flag = new_content.rsplit(":", 1)
            flag_stripped = flag.strip().lower()
            if (
                flag_stripped in {"true", "false"}
                and "\n" not in flag
                and "\r" not in flag
            ):
                verify = flag_stripped == "true"
                new_content = content_part
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "legacy replace_lines strings are deprecated; use JSON payloads",
            )
        )
        return {
            "path": path,
            "operation": {
                "type": "replace_lines",
                "start_line": start_line,
                "end_line": end_line,
                "new_content": new_content,
                "verify": verify,
            },
            "backup": True,
            "warnings": warnings,
        }

    if default_operation_type == "insert_lines":
        parts = str(params).split(":", 2)
        if len(parts) < 3:
            return {"error": "Need path:after_line:new_content format"}
        path = parts[0].strip()
        if not path:
            return {"error": "Need path for insert_lines"}
        try:
            after_line = int(parts[1].strip())
        except ValueError:
            return {"error": "after_line must be an integer"}
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "legacy insert_lines strings are deprecated; use JSON payloads",
            )
        )
        return {
            "path": path,
            "operation": {
                "type": "insert_lines",
                "after_line": after_line,
                "new_content": parts[2],
            },
            "backup": True,
            "warnings": warnings,
        }

    if default_operation_type == "delete_lines":
        parts = str(params).split(":", 2)
        if len(parts) < 3:
            return {"error": "Need path:start_line:end_line format"}
        path = parts[0].strip()
        if not path:
            return {"error": "Need path for delete_lines"}
        try:
            start_line = int(parts[1].strip())
            end_line = int(parts[2].strip())
        except ValueError:
            return {"error": "start_line and end_line must be integers"}
        warnings.append(
            _deprecated_payload_warning(
                "patch_file",
                "legacy delete_lines strings are deprecated; use JSON payloads",
            )
        )
        return {
            "path": path,
            "operation": {
                "type": "delete_lines",
                "start_line": start_line,
                "end_line": end_line,
            },
            "backup": True,
            "warnings": warnings,
        }

    return {
        "error": f"Unsupported patch_file legacy operation type: {default_operation_type}"
    }


def parse_patch_files_payload(params: Any) -> Dict[str, Any]:
    """Parse canonical or legacy patch-files payloads."""
    payload = _parse_json_payload(params)
    warnings: List[str] = []
    if payload is not None:
        apply = bool(payload.get("apply", False))
        backup = bool(payload.get("backup", True))
        operations_payload = payload.get("operations")
        if isinstance(operations_payload, list):
            operations: List[Dict[str, Any]] = []
            for item in operations_payload:
                parsed = parse_patch_file_payload(item)
                error = parsed.get("error")
                if isinstance(error, str):
                    return {"error": error}
                operations.append(
                    {
                        "path": parsed["path"],
                        "operation": parsed["operation"],
                        "backup": parsed["backup"],
                        "_warnings": parsed.get("warnings", []),
                    }
                )
            return {
                "operations": operations,
                "apply": apply,
                "backup": backup,
                "warnings": warnings,
            }

        content = payload.get("content")
        if isinstance(content, str):
            warnings.append(
                _deprecated_payload_warning(
                    "patch_files",
                    "raw content payloads are deprecated; use a structured operations array",
                )
            )
            return {
                "content": content,
                "apply": apply,
                "backup": backup,
                "warnings": warnings,
            }

        return {"error": "patch_files requires 'operations' or legacy 'content'"}

    if not isinstance(params, str) or not params.strip():
        return {"error": "patch_files requires JSON payloads or legacy patch content"}

    content = params
    do_apply = False
    match = re.match(r"^apply\s*[:=]\s*(true|false)\s*\n", content, flags=re.IGNORECASE)
    if match:
        do_apply = match.group(1).lower() == "true"
        content = content[match.end() :]
    warnings.append(
        _deprecated_payload_warning(
            "patch_files",
            "raw patch text is deprecated; use a structured operations array",
        )
    )
    return {
        "content": content,
        "apply": do_apply,
        "backup": True,
        "warnings": warnings,
    }


def parse_action(content: str) -> List[CodeActAction]:
    """Parse actions from content using regex pattern matching.

    Args:
        content: The string content to parse for actions

    Returns:
        A list of CodeActAction objects, empty if no actions found
    """
    # Remove string-based validation
    if not content.strip():
        return []

    # Check for common action tag patterns - using the enum values directly to ensure only valid actions are detected
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    action_tag_regex = (
        f"<({action_tag_pattern})>.*?</\\1>"  # Match complete tag pairs only
    )

    if not re.search(action_tag_regex, content, re.DOTALL | re.IGNORECASE):
        # No properly formed action tags found
        logger.debug("No properly formed action tags found in content")
        return []

    # Extract only the AI's response part
    try:
        # Use more specific pattern matching to only extract valid action types
        pattern = f"<({action_tag_pattern})>(.*?)</\\1>"
        matches = re.finditer(pattern, content, re.DOTALL)

        actions = []  # Initialize the actions list

        match_found = False
        for match in matches:
            match_found = True
            action_type = match.group(1).lower()
            params = unescape(match.group(2).strip())

            # Verify this is a valid action type
            try:
                action_type_enum = ActionType[action_type.upper()]
                action = CodeActAction(action_type_enum, params)
                actions.append(action)
                logger.debug(f"Found valid action: {action_type}")
            except KeyError:
                # This shouldn't happen with our updated regex, but just in case
                logger.warning(f"Unrecognized action type: {action_type}")
                pass

        if not match_found:
            logger.debug("No actions matched in content despite initial regex check")

        return actions
    except Exception as e:
        logger.error(f"Error parsing actions: {str(e)}", exc_info=True)
        return []


def strip_action_tags(content: str) -> str:
    """Strip action tags from content, returning clean text for conversation history.

    This removes all valid action tags (e.g., <execute_command>...</execute_command>,
    <finish_response>...</finish_response>) from the content, leaving only the
    narrative/conversational text.

    Args:
        content: The string content containing action tags

    Returns:
        Content with action tags removed and whitespace cleaned up
    """
    if not content:
        return content

    # Build pattern for all valid action types
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])
    # Match complete tag pairs: <action_type>...</action_type>
    pattern = f"<({action_tag_pattern})>.*?</\\1>"

    # Remove all action tags
    cleaned = re.sub(pattern, "", content, flags=re.DOTALL | re.IGNORECASE)

    # Clean up excessive whitespace left behind
    # Replace multiple newlines with at most two
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
    # Strip leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned


def strip_incomplete_action_tags(content: str) -> str:
    """Strip incomplete/unclosed action tags from the end of content.

    When streaming is interrupted after detecting a complete action tag,
    there may be additional incomplete tags in the buffer (e.g., `<finish_response>`
    without its closing tag). This function removes such trailing fragments.

    Args:
        content: The string content that may have trailing incomplete tags

    Returns:
        Content with trailing incomplete tags removed
    """
    if not content:
        return content

    # Build pattern for valid action types
    action_tag_pattern = "|".join([action_type.value for action_type in ActionType])

    # Match incomplete opening tags at the end: <action_type> without </action_type>
    # This pattern finds <tag> or <tag>content... at the end without closing tag
    incomplete_pattern = f"<({action_tag_pattern})>(?:(?!</\\1>).)*$"

    # Remove trailing incomplete tags
    cleaned = re.sub(incomplete_pattern, "", content, flags=re.DOTALL | re.IGNORECASE)

    # Also remove partially-started opening tags at the end (e.g., <finish_ or <execute)
    # This handles cases where streaming was interrupted mid-tag
    partial_tag_pattern = f"<(?:{action_tag_pattern})?[^>]*$"
    cleaned = re.sub(partial_tag_pattern, "", cleaned, flags=re.IGNORECASE)

    # Also remove orphaned closing tags at the start (from previous incomplete)
    orphan_close_pattern = f"^\\s*</({action_tag_pattern})>"
    cleaned = re.sub(orphan_close_pattern, "", cleaned, flags=re.IGNORECASE)

    return cleaned.strip()


class ActionExecutor:
    def __init__(
        self,
        tool_manager: ToolManager,
        task_manager: ProjectManager,
        conversation_system=None,
        ui_event_callback: Optional[
            Callable[[str, Dict[str, Any]], Awaitable[None]]
        ] = None,
    ):
        """Execute parsed actions and (optionally) emit UI events.

        Args:
            tool_manager: The ToolManager instance
            task_manager: The Project/Task manager
            conversation_system: Conversation manager (optional)
            ui_event_callback: Async callback to emit UI events (e.g. PenguinCore.emit_ui_event)
        """
        self.tool_manager = tool_manager
        self.task_manager = task_manager
        self.process_manager = ProcessManager()
        self.current_process = None
        self.conversation_system = conversation_system
        try:
            logger.info(
                "ActionExecutor initialized with ToolManager id=%s file_root=%s mode=%s",
                hex(id(tool_manager)) if tool_manager else None,
                getattr(tool_manager, "_file_root", None) if tool_manager else None,
                getattr(tool_manager, "file_root_mode", None) if tool_manager else None,
            )
        except Exception:
            pass
        self._ui_event_cb = ui_event_callback
        self._ui_action_metadata: Dict[str, Dict[str, Any]] = {}
        # No direct initialization of expensive tools, we'll use tool_manager's properties

    def _inject_tool_call_id(self, params: str, action_id: str) -> str:
        """Inject an internal tool_call_id into JSON action payloads."""
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception:
            return params

        if not isinstance(payload, dict):
            return params
        if (
            isinstance(payload.get("tool_call_id"), str)
            and payload["tool_call_id"].strip()
        ):
            return params
        payload["tool_call_id"] = action_id
        try:
            return json.dumps(payload)
        except Exception:
            return params

    def _prepare_action_params(self, action: CodeActAction, action_id: str) -> Any:
        """Prepare handler params without mutating the original parsed action."""
        if action.action_type == ActionType.SPAWN_SUB_AGENT and isinstance(
            action.params, str
        ):
            return self._inject_tool_call_id(action.params, action_id)
        return action.params

    def _record_ui_action_metadata(
        self, action_id: str, metadata: Optional[Dict[str, Any]]
    ) -> None:
        """Persist transient UI metadata for the matching action_result event."""
        if not isinstance(action_id, str) or not action_id or action_id == "-":
            return
        if not isinstance(metadata, dict) or not metadata:
            return
        self._ui_action_metadata[action_id] = dict(metadata)

    def _consume_ui_action_metadata(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Return and remove transient UI metadata for an action."""
        if not isinstance(action_id, str) or not action_id:
            return None
        metadata = self._ui_action_metadata.pop(action_id, None)
        if isinstance(metadata, dict) and metadata:
            return metadata
        return None

    def _resolve_subagent_tool_call_id(
        self,
        payload: Optional[Dict[str, Any]] = None,
    ) -> str:
        """Resolve best-effort tool call identifier for sub-agent logs."""
        payload = payload or {}
        explicit = payload.get("tool_call_id") or payload.get("call_id")
        if isinstance(explicit, str) and explicit.strip():
            return explicit.strip()

        context = get_current_execution_context()
        if context and isinstance(context.request_id, str) and context.request_id:
            return context.request_id
        return "-"

    def _log_subagent_event(
        self,
        event: str,
        *,
        status: str,
        elapsed_ms: Optional[float] = None,
        target_agent: Optional[str] = None,
        parent_agent: Optional[str] = None,
        tool_call_id: Optional[str] = None,
        level: int = logging.INFO,
        **fields: Any,
    ) -> None:
        """Emit sub-agent logs to both module and uvicorn loggers."""
        context = get_current_execution_context()
        session_id = context.session_id if context and context.session_id else "-"
        agent_id = context.agent_id if context and context.agent_id else "default"
        call_id = tool_call_id or "-"

        parts = [
            f"subagent.{event}",
            f"status={status}",
            f"session={session_id}",
            f"agent={agent_id}",
            f"tool_call_id={call_id}",
            f"elapsed_ms={0.0 if elapsed_ms is None else round(float(elapsed_ms), 1)}",
        ]
        if target_agent:
            parts.append(f"target_agent={target_agent}")
        if parent_agent:
            parts.append(f"parent_agent={parent_agent}")

        for key, value in fields.items():
            if value is None:
                continue
            parts.append(f"{key}={value}")

        message = " ".join(parts)
        logger.log(level, message)
        logging.getLogger("uvicorn.error").log(level, message)

    def _is_lsp_refresh_action(self, action_type: ActionType) -> bool:
        """Return True if action can modify files and should refresh LSP state."""
        return action_type in {
            ActionType.APPLY_DIFF,
            ActionType.PATCH_FILE,
            ActionType.MULTIEDIT,
            ActionType.PATCH_FILES,
            ActionType.EDIT_WITH_PATTERN,
            ActionType.REPLACE_LINES,
            ActionType.INSERT_LINES,
            ActionType.DELETE_LINES,
            ActionType.ENHANCED_WRITE,
            ActionType.WRITE_FILE,
        }

    def _extract_changed_files(self, action: CodeActAction) -> List[str]:
        """Best-effort extraction of changed file paths from action parameters."""
        params = action.params or ""
        if action.action_type == ActionType.APPLY_DIFF:
            first_sep = params.find(":")
            if first_sep > 0:
                return [self._normalize_lsp_path(params[:first_sep].strip())]
            return []

        if action.action_type in {ActionType.ENHANCED_WRITE, ActionType.WRITE_FILE}:
            payload = _parse_json_payload(action.params)
            if isinstance(payload, dict):
                path = payload.get("path") or payload.get("file_path")
                if isinstance(path, str) and path.strip():
                    return [self._normalize_lsp_path(path.strip())]
            first_sep = params.find(":")
            if first_sep > 0:
                return [self._normalize_lsp_path(params[:first_sep].strip())]
            return []

        if action.action_type == ActionType.PATCH_FILE:
            payload = _parse_json_payload(action.params)
            if isinstance(payload, dict):
                path = payload.get("path") or payload.get("file_path")
                if isinstance(path, str) and path.strip():
                    return [self._normalize_lsp_path(path.strip())]
            return []

        if action.action_type in {
            ActionType.REPLACE_LINES,
            ActionType.INSERT_LINES,
            ActionType.DELETE_LINES,
        }:
            first_sep = params.find(":")
            if first_sep > 0:
                return [self._normalize_lsp_path(params[:first_sep].strip())]
            return []

        if action.action_type == ActionType.PATCH_FILES:
            payload = _parse_json_payload(action.params)
            if isinstance(payload, dict):
                operations = payload.get("operations")
                if isinstance(operations, list):
                    files = []
                    for item in operations:
                        if not isinstance(item, dict):
                            continue
                        path = item.get("path") or item.get("file_path")
                        if isinstance(path, str) and path.strip():
                            files.append(self._normalize_lsp_path(path.strip()))
                    return files
            return []

        if action.action_type == ActionType.EDIT_WITH_PATTERN:
            parts = params.split(":", 1)
            if parts and parts[0].strip():
                return [self._normalize_lsp_path(parts[0].strip())]
            return []

        return []

    def _lsp_base_directory(self) -> Optional[Path]:
        """Resolve the best base directory for UI/LSP path normalization."""
        context = get_current_execution_context()
        candidates = []
        if context is not None:
            candidates.extend(
                [context.directory, context.project_root, context.workspace_root]
            )
        candidates.append(getattr(self.tool_manager, "_file_root", None))

        for candidate in candidates:
            if not isinstance(candidate, str) or not candidate.strip():
                continue
            try:
                resolved = Path(candidate).expanduser().resolve()
            except Exception:
                continue
            if resolved.exists() and resolved.is_dir():
                return resolved
        return None

    def _normalize_lsp_path(self, path_value: str) -> str:
        """Normalize file paths for LSP/UI payloads."""
        text = str(path_value or "").strip()
        if not text:
            return ""

        candidate = Path(text).expanduser()
        if not candidate.is_absolute():
            return text.replace("\\", "/")

        try:
            resolved = candidate.resolve()
        except Exception:
            return text.replace("\\", "/")

        base_directory = self._lsp_base_directory()
        if base_directory is not None:
            try:
                return str(resolved.relative_to(base_directory)).replace("\\", "/")
            except Exception:
                pass
        return str(resolved).replace("\\", "/")

    def _parse_action_result_payload(self, result: Any) -> Dict[str, Any]:
        """Parse structured tool output when available."""
        if isinstance(result, dict):
            return result
        if not isinstance(result, str):
            return {}

        text = result.strip()
        if not text.startswith("{"):
            return {}

        try:
            payload = json.loads(text)
        except Exception:
            return {}
        return payload if isinstance(payload, dict) else {}

    def _extract_result_changed_files(self, result: Any) -> List[str]:
        """Prefer changed files returned by the tool over raw param parsing."""
        payload = self._parse_action_result_payload(result)
        if not payload:
            return []

        paths: List[str] = []

        single_file = payload.get("file")
        if isinstance(single_file, str) and single_file.strip():
            paths.append(single_file.strip())

        for key in ("files", "files_edited", "created"):
            value = payload.get(key)
            if isinstance(value, list):
                paths.extend(
                    str(item).strip()
                    for item in value
                    if isinstance(item, str) and str(item).strip()
                )

        diagnostics_payload = payload.get("diagnostics")
        if not paths and isinstance(diagnostics_payload, dict):
            paths.extend(
                str(raw_path).strip()
                for raw_path in diagnostics_payload.keys()
                if str(raw_path).strip()
            )

        deduped: List[str] = []
        seen: set[str] = set()
        for path in paths:
            normalized_path = self._normalize_lsp_path(path)
            if not normalized_path or normalized_path in seen:
                continue
            seen.add(normalized_path)
            deduped.append(normalized_path)
        return deduped

    def _build_lsp_diagnostics(
        self, files: List[str], result: Any
    ) -> Dict[str, List[Dict[str, Any]]]:
        """Build diagnostics payload for UI refresh events."""

        def _message_line_char(text: str) -> tuple[int, int]:
            line_match = re.search(
                r"(?:line|ln)\s*(\d+)(?:\D+(?:column|col|character|char)\s*(\d+))?",
                text,
                re.IGNORECASE,
            )
            if line_match:
                line = max(int(line_match.group(1)) - 1, 0)
                character = (
                    max(int(line_match.group(2)) - 1, 0) if line_match.group(2) else 0
                )
                return line, character

            colon_match = re.search(r":(\d+):(\d+)", text)
            if colon_match:
                return max(int(colon_match.group(1)) - 1, 0), max(
                    int(colon_match.group(2)) - 1, 0
                )

            return 0, 0

        def _normalize_entry(raw_entry: Any, fallback_message: str) -> Dict[str, Any]:
            if not isinstance(raw_entry, dict):
                line, character = _message_line_char(fallback_message)
                return {
                    "severity": 1,
                    "source": "penguin",
                    "message": fallback_message,
                    "range": {
                        "start": {"line": line, "character": character},
                        "end": {"line": line, "character": character + 1},
                    },
                }

            message = str(raw_entry.get("message") or fallback_message)[:500]
            severity = raw_entry.get("severity", 1)
            source = raw_entry.get("source") or "penguin"
            code = raw_entry.get("code")
            existing_range = raw_entry.get("range")

            if isinstance(existing_range, dict):
                start = existing_range.get("start") or {}
                end = existing_range.get("end") or {}
                line = int(start.get("line", 0))
                character = int(start.get("character", 0))
                end_line = int(end.get("line", line))
                end_character = int(end.get("character", character + 1))
            else:
                line, character = _message_line_char(message)
                end_line = line
                end_character = character + 1

            entry: Dict[str, Any] = {
                "severity": severity,
                "source": source,
                "message": message,
                "range": {
                    "start": {"line": line, "character": character},
                    "end": {"line": end_line, "character": end_character},
                },
            }
            if code is not None:
                entry["code"] = code
            return entry

        text = "" if result is None else str(result)
        text = text.strip()
        if not text:
            return {}

        payload: Dict[str, Any] = {}
        if isinstance(result, dict):
            payload = result
        elif isinstance(result, str):
            try:
                parsed = json.loads(result)
                if isinstance(parsed, dict):
                    payload = parsed
            except Exception:
                payload = {}

        diagnostics_payload = payload.get("diagnostics") if payload else None
        if isinstance(diagnostics_payload, dict):
            normalized: Dict[str, List[Dict[str, Any]]] = {}
            normalized_files = {
                self._normalize_lsp_path(path) for path in files if path
            }
            for raw_path, entries in diagnostics_payload.items():
                path = self._normalize_lsp_path(str(raw_path))
                if normalized_files and path and path not in normalized_files:
                    continue
                if not isinstance(entries, list):
                    continue
                normalized[path] = [
                    _normalize_entry(entry, "LSP diagnostic") for entry in entries
                ]

            if normalized:
                return normalized

        error_parts: List[str] = []
        return_code = payload.get("returncode") if payload else None
        if isinstance(return_code, int) and return_code != 0:
            error_parts.append(f"Command failed (exit {return_code})")

        for key in ("error", "stderr", "message", "details"):
            value = payload.get(key) if payload else None
            if isinstance(value, str) and value.strip():
                error_parts.append(value.strip())

        if not error_parts:
            lowered = text.lower()
            is_error = lowered.startswith("error") or "traceback" in lowered
            if not is_error:
                return {}
            error_parts.append(text)

        message = " - ".join(error_parts).splitlines()[0][:500]
        line, character = _message_line_char(message)
        targets = files or [""]
        diagnostics: Dict[str, List[Dict[str, Any]]] = {}
        for path in targets:
            diagnostics[path] = [
                {
                    "severity": 1,
                    "source": "penguin",
                    "code": "tool_action_error",
                    "message": message,
                    "range": {
                        "start": {"line": line, "character": character},
                        "end": {"line": line, "character": character + 1},
                    },
                }
            ]
        return diagnostics

    async def execute_action(self, action: CodeActAction) -> str:
        """Execute an action and emit UI events if a callback is provided."""
        logger.debug(f"Attempting to execute action: {action.action_type.value}")
        try:
            logger.info(
                "ActionExecutor executing %s using ToolManager id=%s file_root=%s mode=%s",
                action.action_type.value,
                hex(id(self.tool_manager)) if self.tool_manager else None,
                (
                    getattr(self.tool_manager, "_file_root", None)
                    if self.tool_manager
                    else None
                ),
                (
                    getattr(self.tool_manager, "file_root_mode", None)
                    if self.tool_manager
                    else None
                ),
            )
        except Exception:
            pass
        import uuid

        action_id = str(uuid.uuid4())[:8]
        handler_params = self._prepare_action_params(action, action_id)

        # --------------------------------------------------
        # Emit *start* UI event
        # --------------------------------------------------
        if self._ui_event_cb:
            try:
                logger.debug(
                    f"UI-emit start action id={action_id} type={action.action_type.value}"
                )
                await self._ui_event_cb(
                    "action",
                    {
                        "id": action_id,
                        "type": action.action_type.value,
                        "params": action.params,
                    },
                )
            except Exception as e:
                logger.debug(f"UI event emit failed (action start): {e}")

        action_map = {
            # ActionType.READ: lambda params: self.tool_manager.execute_tool("read_file", {"path": params}),
            # ActionType.WRITE: self._write_file,
            ActionType.EXECUTE: self._execute_code,
            ActionType.EXECUTE_COMMAND: self._execute_command,  # TODO: FULLY IMPLEMENT THIS
            ActionType.SEARCH: lambda params: self.tool_manager.execute_tool(
                "grep_search", {"pattern": params}
            ),
            # ActionType.CREATE_FILE: self._create_file,
            # ActionType.CREATE_FOLDER: lambda params: self.tool_manager.execute_tool("create_folder", {"path": params}),
            # ActionType.LIST_FILES: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.LIST_FOLDERS: lambda params: self.tool_manager.execute_tool("list_files", {"directory": params}),
            # ActionType.GET_FILE_MAP: lambda params: self.tool_manager.execute_tool("get_file_map", {"directory": params}),
            # ActionType.LINT: self._lint_python,
            ActionType.MEMORY_SEARCH: self._memory_search,
            ActionType.ADD_DECLARATIVE_NOTE: self._add_declarative_note,
            # ActionType.TASK_CREATE: self._execute_task_create,
            # ActionType.TASK_UPDATE: self._execute_task_update,
            # ActionType.TASK_COMPLETE: self._execute_task_complete,
            # ActionType.TASK_LIST: lambda params: list_tasks(self.task_manager),
            # ActionType.PROJECT_CREATE: self._execute_project_create,
            # ActionType.PROJECT_UPDATE: lambda params: update_task(self.task_manager, *params.split(':', 1)),
            # ActionType.PROJECT_COMPLETE: self._execute_project_complete,
            # ActionType.PROJECT_LIST: lambda params: list_tasks(self.task_manager),
            # ActionType.SUBTASK_ADD: self._execute_subtask_add,
            # ActionType.TASK_DETAILS: lambda params: get_task_details(self.task_manager, params),
            # ActionType.PROJECT_DETAILS: lambda params: self.task_manager.get_project_details(params),
            # ActionType.WORKFLOW_ANALYZE: lambda params: self.task_manager.analyze_workflow(),
            ActionType.ADD_SUMMARY_NOTE: self._add_summary_note,
            ActionType.PERPLEXITY_SEARCH: self._perplexity_search,
            ActionType.PROCESS_START: self._process_start,
            ActionType.PROCESS_STOP: self._process_stop,
            ActionType.PROCESS_STATUS: self._process_status,
            ActionType.PROCESS_LIST: self._process_list,
            ActionType.PROCESS_ENTER: self._process_enter,
            ActionType.PROCESS_SEND: self._process_send,
            ActionType.PROCESS_EXIT: self._process_exit,
            ActionType.WORKSPACE_SEARCH: self._workspace_search,
            ActionType.TODOWRITE: self._todo_write,
            ActionType.TODOREAD: self._todo_read,
            ActionType.QUESTION: self._question,
            ActionType.MULTIEDIT: self._multiedit,
            # Project management handlers
            ActionType.PROJECT_CREATE: self._project_create,
            ActionType.PROJECT_LIST: self._project_list,
            ActionType.PROJECT_UPDATE: self._project_update,
            ActionType.PROJECT_DELETE: self._project_delete,
            ActionType.PROJECT_DISPLAY: self._project_display,
            # Task management handlers
            ActionType.TASK_CREATE: self._task_create,
            ActionType.TASK_UPDATE: self._task_update,
            ActionType.TASK_COMPLETE: self._task_complete,
            ActionType.TASK_DELETE: self._task_delete,
            ActionType.TASK_LIST: self._task_list,
            ActionType.TASK_DISPLAY: self._task_display,
            # Response/Task completion signals
            ActionType.FINISH_RESPONSE: self._finish_response,
            ActionType.FINISH_TASK: self._finish_task,
            ActionType.TASK_COMPLETED: self._finish_task,  # Deprecated alias
            ActionType.DEPENDENCY_DISPLAY: self._dependency_display,
            ActionType.ANALYZE_CODEBASE: self._analyze_codebase,
            ActionType.REINDEX_WORKSPACE: self._reindex_workspace,
            ActionType.SEND_MESSAGE: self._send_message,
            # Browser actions
            ActionType.BROWSER_NAVIGATE: self._browser_navigate,
            ActionType.BROWSER_INTERACT: self._browser_interact,
            ActionType.BROWSER_SCREENSHOT: self._browser_screenshot,
            # PyDoll browser actions
            ActionType.PYDOLL_BROWSER_NAVIGATE: self._pydoll_browser_navigate,
            ActionType.PYDOLL_BROWSER_INTERACT: self._pydoll_browser_interact,
            ActionType.PYDOLL_BROWSER_SCREENSHOT: self._pydoll_browser_screenshot,
            ActionType.PYDOLL_BROWSER_SCROLL: self._pydoll_browser_scroll,
            # PyDoll debug toggle
            ActionType.PYDOLL_DEBUG_TOGGLE: self._pydoll_debug_toggle,
            # Sub-agent tools
            ActionType.SPAWN_SUB_AGENT: self._spawn_sub_agent,
            ActionType.STOP_SUB_AGENT: self._stop_sub_agent,
            ActionType.RESUME_SUB_AGENT: self._resume_sub_agent,
            ActionType.GET_AGENT_STATUS: self._get_agent_status,
            ActionType.WAIT_FOR_AGENTS: self._wait_for_agents,
            ActionType.GET_CONTEXT_INFO: self._get_context_info,
            ActionType.SYNC_CONTEXT: self._sync_context,
            ActionType.DELEGATE: self._delegate,
            ActionType.DELEGATE_EXPLORE_TASK: self._delegate_explore_task,
            # Enhanced file operations
            ActionType.LIST_FILES_FILTERED: self._list_files_filtered,
            ActionType.FIND_FILES_ENHANCED: self._find_files_enhanced,
            ActionType.ENHANCED_DIFF: self._enhanced_diff,
            ActionType.ANALYZE_PROJECT: self._analyze_project,
            ActionType.READ_FILE: self._read_file,
            ActionType.ENHANCED_READ: self._enhanced_read,
            ActionType.WRITE_FILE: self._write_file,
            ActionType.ENHANCED_WRITE: self._enhanced_write,
            ActionType.PATCH_FILE: self._patch_file,
            ActionType.APPLY_DIFF: self._apply_diff,
            ActionType.PATCH_FILES: self._patch_files,
            ActionType.EDIT_WITH_PATTERN: self._edit_with_pattern,
            ActionType.REPLACE_LINES: self._replace_lines,
            ActionType.INSERT_LINES: self._insert_lines,
            ActionType.DELETE_LINES: self._delete_lines,
            # Repository management actions
            ActionType.GET_REPOSITORY_STATUS: self._get_repository_status,
            ActionType.CREATE_AND_SWITCH_BRANCH: self._create_and_switch_branch,
            ActionType.COMMIT_AND_PUSH_CHANGES: self._commit_and_push_changes,
            ActionType.CREATE_IMPROVEMENT_PR: self._create_improvement_pr,
            ActionType.CREATE_FEATURE_PR: self._create_feature_pr,
            ActionType.CREATE_BUGFIX_PR: self._create_bugfix_pr,
        }

        try:
            if action.action_type not in action_map:
                logger.warning(f"Unknown action type: {action.action_type.value}")
                return f"Unknown action type: {action.action_type.value}"

            handler = action_map[action.action_type]
            logger.debug(f"Handler for action {action.action_type.value}: {handler}")

            if asyncio.iscoroutinefunction(handler):
                logger.debug(f"Executing async handler for {action.action_type.value}")
                result = await handler(handler_params)
            else:
                logger.debug(
                    f"Executing sync handler for {action.action_type.value} in thread pool"
                )
                # Offload synchronous tools to thread pool to avoid blocking the event loop.
                # asyncio.to_thread preserves contextvars for per-request execution context.
                result = await asyncio.to_thread(handler, handler_params)

                if asyncio.iscoroutine(result):
                    result = await result

            logger.info(f"Action {action.action_type.value} executed successfully")
            # --------------------------------------------------
            # Emit success UI event
            # --------------------------------------------------
            if self._ui_event_cb:
                try:
                    logger.debug(f"UI-emit success action_result id={action_id}")
                    event_payload: Dict[str, Any] = {
                        "id": action_id,
                        "status": "completed",
                        "result": result if isinstance(result, str) else str(result),
                        "action": action.action_type.value,
                    }
                    metadata = self._consume_ui_action_metadata(action_id)
                    if metadata:
                        event_payload["metadata"] = metadata
                    await self._ui_event_cb(
                        "action_result",
                        event_payload,
                    )
                except Exception as e:
                    logger.debug(f"UI event emit failed (action result): {e}")

            if self._ui_event_cb and self._is_lsp_refresh_action(action.action_type):
                files = self._extract_result_changed_files(result)
                if not files:
                    files = self._extract_changed_files(action)
                diagnostics_map = self._build_lsp_diagnostics(files, result)
                if not files and diagnostics_map:
                    files = [path for path in diagnostics_map.keys() if path]
                try:
                    await self._ui_event_cb(
                        "lsp.updated",
                        {
                            "action": action.action_type.value,
                            "files": files,
                        },
                    )
                    await self._ui_event_cb(
                        "lsp.client.diagnostics",
                        {
                            "action": action.action_type.value,
                            "files": files,
                            "serverID": "penguin",
                            "path": files[0] if files else "",
                            "count": sum(
                                len(entries)
                                for entries in diagnostics_map.values()
                                if isinstance(entries, list)
                            ),
                            "diagnostics": diagnostics_map,
                        },
                    )
                except Exception as e:
                    logger.debug(f"UI event emit failed (lsp refresh): {e}")
            return result
        except Exception as e:
            error_message = (
                f"Error executing action {action.action_type.value}: {str(e)}"
            )
            logger.error(error_message, exc_info=True)
            if self._ui_event_cb:
                try:
                    logger.debug(f"UI-emit error action_result id={action_id}")
                    event_payload: Dict[str, Any] = {
                        "id": action_id,
                        "status": "error",
                        "result": error_message,
                        "action": action.action_type.value,
                    }
                    metadata = self._consume_ui_action_metadata(action_id)
                    if metadata:
                        event_payload["metadata"] = metadata
                    await self._ui_event_cb(
                        "action_result",
                        event_payload,
                    )
                except Exception as ee:
                    logger.debug(f"UI event emit failed (action error): {ee}")
            return error_message

    # def _write_file(self, params: str) -> str:
    #     path, content = params.split(':', 1)
    #     return self.tool_manager.execute_tool("write_to_file", {"path": path.strip(), "content": content.strip()})

    # def _create_file(self, params: str) -> str:
    #     path, content = params.split(':', 1)
    #     return self.tool_manager.execute_tool("create_file", {"path": path.strip(), "content": content.strip()})

    def _execute_code(self, params: str) -> str:
        logger.debug(f"Executing code: {params}")
        return self.tool_manager.execute_tool("code_execution", {"code": params})

    def _execute_command(self, params: str) -> str:
        """Execute a shell command using the tool manager."""
        logger.debug(f"Executing command: {params}")
        return self.tool_manager.execute_tool("execute_command", {"command": params})

    # def _lint_python(self, params: str) -> str:
    #     parts = params.split(':', 1)
    #     if len(parts) == 2:
    #         target, is_file = parts[0].strip(), parts[1].strip().lower() == 'true'
    #     else:
    #         target, is_file = params.strip(), False

    #     # Use the current working directory to resolve the file path
    #     if is_file:
    #         target = str(Path.cwd() / target)

    # return self.tool_manager.execute_tool("lint_python", {"target": target, "is_file": is_file})

    # def _memory_search(self, params: str) -> str:
    #     query, k = params.split(":", 1) if ":" in params else (params, "5")
    #     return self.tool_manager.execute_tool(
    #         "memory_search", {"query": query.strip(), "k": int(k.strip())}
    #     )

    def _add_declarative_note(self, params: str) -> str:
        category, content = params.split(":", 1)
        return self.tool_manager.execute_tool(
            "add_declarative_note",
            {"category": category.strip(), "content": content.strip()},
        )

    def _create_folder(self, params: str) -> str:
        return self.tool_manager.execute_tool("create_folder", {"path": params})

    def _add_summary_note(self, params: str) -> str:
        # If there's no explicit category, use a default one
        if ":" not in params:
            category = "general"
            content = params.strip()
        else:
            category, content = params.split(":", 1)
            category = category.strip()
            content = content.strip()

        return self.tool_manager.add_summary_note(category, content)

    def _perplexity_search(self, params: str) -> str:
        parts = params.split(":", 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        results = self.tool_manager.execute_tool(
            "perplexity_search", {"query": query, "max_results": max_results}
        )

        # The results are already formatted as a string by the PerplexityProvider
        return results

    async def _process_start(self, params: str) -> str:
        logger.debug(f"Starting process with params: {params}")
        name, command = params.split(":", 1)
        return await self.process_manager.start_process(name.strip(), command.strip())

    async def _process_stop(self, params: str) -> str:
        return await self.process_manager.stop_process(params.strip())

    async def _process_status(self, params: str) -> str:
        return await self.process_manager.get_process_status(params.strip())

    async def _process_list(self, params: str) -> str:
        processes = await self.process_manager.list_processes()
        return "\n".join([f"{name}: {status}" for name, status in processes.items()])

    async def _process_enter(self, params: str) -> str:
        name = params.strip()
        reader = await self.process_manager.enter_process(name)
        if reader:
            self.current_process = name
            initial_output = await reader.read(1024)
            return (
                f"Entered process '{name}'. Initial output:\n{initial_output.decode()}"
            )
        return f"Failed to enter process '{name}'"

    async def _process_send(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        return await self.process_manager.send_command(
            self.current_process, params.strip()
        )

    async def _process_exit(self, params: str) -> str:
        if not self.current_process:
            return "Not currently in any process"
        result = await self.process_manager.exit_process(self.current_process)
        self.current_process = None
        return result

    async def _send_message(self, params: str) -> str:
        try:
            payload = (
                json.loads(params)
                if params.strip().startswith("{")
                else {"content": params}
            )
        except json.JSONDecodeError as exc:
            raise ValueError(f"send_message expects JSON payload: {exc}")

        content = payload.get("content") or payload.get("message")
        if not content:
            raise ValueError("send_message requires 'content'")

        channel = payload.get("channel")
        message_type = payload.get("message_type", "message")
        metadata = payload.get("metadata") or {}
        sender = payload.get("sender")
        raw_targets = (
            payload.get("targets") or payload.get("target") or payload.get("recipient")
        )

        if raw_targets is None:
            targets = ["human"]
        elif isinstance(raw_targets, (list, tuple, set)):
            targets = list(raw_targets)
        else:
            targets = [str(raw_targets)]

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)

        add_message_fn = None
        save_fn = None
        if callable(getattr(conversation, "add_message", None)):
            add_message_fn = conversation.add_message
            save_fn = getattr(conversation, "save", None)
        elif hasattr(conversation, "conversation") and callable(
            getattr(conversation.conversation, "add_message", None)
        ):
            add_message_fn = conversation.conversation.add_message
            save_fn = getattr(conversation, "save", None)

        if add_message_fn is None and core is None:
            raise RuntimeError("Penguin core unavailable for send_message action")

        results = []
        for target in targets:
            normalized = (target or "").strip()
            if normalized in ("", "human", "user"):
                delivered = False
                if core is not None:
                    try:
                        delivered = await core.send_to_human(
                            content,
                            message_type=message_type,
                            metadata=metadata,
                            channel=channel,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning(
                            "send_message core send_to_human failed: %s", exc
                        )
                        delivered = False
                if not delivered and add_message_fn is not None:
                    add_message_fn(
                        role="assistant",
                        content=content,
                        category=MessageCategory.DIALOG,
                        metadata={
                            **metadata,
                            "via": "send_message_fallback",
                            "target": "human",
                            "channel": channel,
                            "message_type": message_type,
                            "sender": sender,
                        },
                        message_type=message_type,
                        agent_id=sender,
                        recipient_id="human",
                    )
                    if callable(save_fn):
                        try:
                            save_fn()
                        except Exception:  # pragma: no cover - best effort
                            logger.debug(
                                "send_message fallback save failed", exc_info=True
                            )
                    results.append("human (logged)")
                else:
                    results.append("human")
            else:
                delivered = False
                if core is not None:
                    try:
                        delivered = await core.route_message(
                            normalized,
                            content,
                            message_type=message_type,
                            metadata=metadata,
                            agent_id=sender,
                            channel=channel,
                        )
                    except Exception as exc:  # pragma: no cover - defensive logging
                        logger.warning(
                            "send_message core route_message failed: %s", exc
                        )
                        delivered = False
                if not delivered and add_message_fn is not None:
                    add_message_fn(
                        role="assistant",
                        content=content,
                        category=MessageCategory.DIALOG,
                        metadata={
                            **metadata,
                            "via": "send_message_fallback",
                            "target": normalized,
                            "channel": channel,
                            "message_type": message_type,
                            "sender": sender,
                        },
                        message_type=message_type,
                        agent_id=sender,
                        recipient_id=normalized,
                    )
                    if callable(save_fn):
                        try:
                            save_fn()
                        except Exception:  # pragma: no cover - best effort
                            logger.debug(
                                "send_message fallback save failed", exc_info=True
                            )
                    results.append(f"{normalized} (logged)")
                elif delivered:
                    results.append(normalized)
                else:
                    results.append(f"{normalized} (failed)")

        return f"Sent message to {', '.join(results)}"

    # --------------------------------------------------
    # Sub-agent tools (agents-as-tools)
    # --------------------------------------------------

    async def _spawn_sub_agent(self, params: str) -> str:
        """Spawn a sub-agent; defaults to isolated session and context-window.

        JSON body:
          - id (required), parent (optional, default current), persona/system_prompt (optional)
          - share_session (bool, default False), share_context_window (bool, default False)
          - shared_context_window_max_tokens (int, optional), model_* overrides (optional), default_tools (optional)
          - initial_prompt (optional)
          - background (bool, default False): Run agent in background with initial_prompt
        """
        spawn_started_at = time.monotonic()

        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            self._log_subagent_event(
                "spawn.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                tool_call_id=self._resolve_subagent_tool_call_id(),
                error="invalid_json",
            )
            return f"Invalid JSON for spawn_sub_agent: {e}"

        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            self._log_subagent_event(
                "spawn.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                tool_call_id=self._resolve_subagent_tool_call_id(payload),
                error="missing_id",
            )
            return "spawn_sub_agent requires 'id'"

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            self._log_subagent_event(
                "spawn.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                target_agent=agent_id,
                tool_call_id=self._resolve_subagent_tool_call_id(payload),
                error="core_unavailable",
            )
            return "Core unavailable for spawn_sub_agent"

        parent_id = str(
            payload.get("parent")
            or getattr(conversation, "current_agent_id", None)
            or "default"
        ).strip()
        share_session = bool(payload.get("share_session", False))
        share_cw = bool(payload.get("share_context_window", False))
        background = bool(payload.get("background", False))
        tool_call_id = self._resolve_subagent_tool_call_id(payload)
        self._log_subagent_event(
            "spawn.request",
            status="started",
            elapsed_ms=0.0,
            target_agent=agent_id,
            parent_agent=parent_id,
            tool_call_id=tool_call_id,
            share_session=share_session,
            share_context_window=share_cw,
            background=background,
        )
        shared_context_window_max_tokens = payload.get(
            "shared_context_window_max_tokens", payload.get("shared_cw_max_tokens")
        )  # Accept both keys
        try:
            shared_context_window_max_tokens = (
                int(shared_context_window_max_tokens)
                if shared_context_window_max_tokens is not None
                else None
            )
        except Exception:
            shared_context_window_max_tokens = None

        kwargs: Dict[str, Any] = {}
        for key in (
            "persona",
            "system_prompt",
            "model_config_id",
            "model_output_max_tokens",
            "default_tools",
        ):
            if key in payload:
                kwargs[key] = payload[key]
        if isinstance(payload.get("model_overrides"), dict):
            kwargs["model_overrides"] = payload["model_overrides"]

        try:
            core.create_sub_agent(
                agent_id,
                parent_agent_id=parent_id,
                share_session=share_session,
                share_context_window=share_cw,
                shared_context_window_max_tokens=shared_context_window_max_tokens,
                **kwargs,
            )
            self._log_subagent_event(
                "spawn.created",
                status="completed",
                elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                target_agent=agent_id,
                parent_agent=parent_id,
                tool_call_id=tool_call_id,
                share_session=share_session,
                share_context_window=share_cw,
            )
        except Exception as e:
            self._log_subagent_event(
                "spawn.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                target_agent=agent_id,
                parent_agent=parent_id,
                tool_call_id=tool_call_id,
                error=str(e),
            )
            return f"Failed to spawn sub-agent '{agent_id}': {e}"

        session_info: Dict[str, Any] = {}
        try:
            publish = getattr(core, "publish_sub_agent_session_created", None)
            if callable(publish):
                info = await publish(
                    agent_id,
                    parent_agent_id=parent_id,
                    share_session=share_session,
                )
                if isinstance(info, dict):
                    session_info = dict(info)
                    ui_metadata: Dict[str, Any] = {
                        "summary": [
                            {
                                "id": str(info.get("id") or tool_call_id or agent_id),
                                "tool": "subagent",
                                "state": {
                                    "status": "completed",
                                    "title": str(info.get("title") or "").strip()
                                    or "Subagent session ready",
                                },
                            }
                        ],
                        "sessionId": info.get("id"),
                        "title": info.get("title") or f"Subagent session ({agent_id})",
                    }
                    self._record_ui_action_metadata(tool_call_id, ui_metadata)
                    self._log_subagent_event(
                        "spawn.session_event",
                        status="completed",
                        elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                        target_agent=agent_id,
                        parent_agent=parent_id,
                        tool_call_id=tool_call_id,
                        event_type="session.created",
                        child_session=info.get("id"),
                    )
        except Exception:
            logger.debug(
                "Failed to emit session.created for spawned sub-agent '%s'",
                agent_id,
                exc_info=True,
            )

        initial_prompt = payload.get("initial_prompt")
        if initial_prompt:
            if background:
                # Run agent in background using AgentExecutor
                try:
                    from penguin.multi.executor import (
                        get_executor,
                        set_executor,
                        AgentExecutor,
                    )

                    executor = get_executor()
                    if executor is None:
                        executor = AgentExecutor(core)
                        set_executor(executor)

                    await executor.spawn_agent(
                        agent_id,
                        initial_prompt,
                        metadata={
                            "parent": parent_id,
                            "share_session": share_session,
                            "share_context_window": share_cw,
                            "session_id": session_info.get("id"),
                            "directory": session_info.get("directory"),
                            "agent_mode": session_info.get("agent_mode"),
                        },
                    )
                    self._log_subagent_event(
                        "spawn.summary",
                        status="started",
                        elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                        target_agent=agent_id,
                        parent_agent=parent_id,
                        tool_call_id=tool_call_id,
                        background=True,
                    )
                    return f"Spawned sub-agent '{agent_id}' running in background (parent='{parent_id}')"
                except Exception as e:
                    self._log_subagent_event(
                        "spawn.summary",
                        status="failed",
                        elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
                        target_agent=agent_id,
                        parent_agent=parent_id,
                        tool_call_id=tool_call_id,
                        background=True,
                        error=str(e),
                    )
                    return f"Failed to spawn background agent '{agent_id}': {e}"
            else:
                # Synchronous: run the child prompt in the child session and block
                try:
                    if hasattr(core, "run_agent_prompt_in_session"):
                        await core.run_agent_prompt_in_session(
                            agent_id,
                            initial_prompt,
                            session_id=session_info.get("id"),
                            directory=session_info.get("directory"),
                            agent_mode=session_info.get("agent_mode"),
                        )
                    else:
                        await core.send_to_agent(agent_id, initial_prompt)
                except Exception as e:
                    logger.warning(f"Failed to send initial_prompt to {agent_id}: {e}")

        self._log_subagent_event(
            "spawn.summary",
            status="completed",
            elapsed_ms=(time.monotonic() - spawn_started_at) * 1000,
            target_agent=agent_id,
            parent_agent=parent_id,
            tool_call_id=tool_call_id,
            background=background,
            share_session=share_session,
            share_context_window=share_cw,
        )

        return f"Spawned sub-agent '{agent_id}' (parent='{parent_id}', share_session={share_session}, share_context_window={share_cw})"

    async def _delegate_explore_task(self, params: str) -> str:
        """Delegate an autonomous exploration task to haiku (later general sub agent) with tool access.

        The sub-agent can list directories, read files, and search.
        It runs a mini action loop until it has enough info to respond.

        JSON body:
          - task (required): What to explore/analyze
          - directory (optional): Starting directory (default: current)
          - max_iterations (optional): Max tool rounds (default: 10)

        Example: <delegate_explore_task>{"task": "Explore this codebase and summarize the architecture"}</delegate_explore_task>
        """
        import logging
        import os
        import re
        from pathlib import Path

        _logger = logging.getLogger(__name__)

        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON: {e}"

        task = payload.get("task", "").strip()
        if not task:
            return "delegate_explore_task requires 'task'"

        start_dir = payload.get("directory", ".")
        requested_max_iterations = payload.get("max_iterations", None)
        if requested_max_iterations is None:
            requested_max_iterations = get_engine_max_iterations_default()
        try:
            requested_max_iterations = int(requested_max_iterations)
        except Exception:
            requested_max_iterations = get_engine_max_iterations_default()

        max_iterations = min(
            requested_max_iterations,
            int(DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP),
        )

        # Get request-scoped working directory for context
        execution_context = get_current_execution_context()
        cwd = (
            execution_context.directory
            if execution_context and execution_context.directory
            else os.getcwd()
        )

        def _resolve_explore_path(raw_path: str) -> Path:
            candidate = Path(raw_path)
            if candidate.is_absolute():
                return candidate
            return (Path(cwd) / candidate).resolve()

        # Tool execution functions
        def execute_list_files(path: str) -> str:
            try:
                p = _resolve_explore_path(path)
                if not p.exists():
                    return f"Directory not found: {path}"
                if not p.is_dir():
                    return f"Not a directory: {path}"

                items = []
                for item in sorted(p.iterdir())[:50]:  # Limit to 50 items
                    if item.name.startswith("."):
                        continue  # Skip hidden
                    prefix = "📁 " if item.is_dir() else "📄 "
                    size = f" ({item.stat().st_size} bytes)" if item.is_file() else ""
                    items.append(f"{prefix}{item.name}{size}")

                return (
                    f"Contents of {path}:\n" + "\n".join(items)
                    if items
                    else f"{path} is empty"
                )
            except Exception as e:
                return f"Error listing {path}: {e}"

        def execute_read_file(path: str, max_lines: int = 200) -> str:
            try:
                p = _resolve_explore_path(path)
                if not p.exists():
                    return f"File not found: {path}"
                if not p.is_file():
                    return f"Not a file: {path}"
                if p.stat().st_size > DEFAULT_LARGE_FILE_THRESHOLD_BYTES:
                    return f"File too large: {path} ({p.stat().st_size} bytes)"

                content = p.read_text(errors="replace")
                lines = content.splitlines()[:max_lines]
                if len(content.splitlines()) > max_lines:
                    lines.append(
                        f"... (truncated, {len(content.splitlines())} total lines)"
                    )

                return f"=== {path} ===\n" + "\n".join(lines)
            except Exception as e:
                return f"Error reading {path}: {e}"

        def execute_search(pattern: str, path: str = ".") -> str:
            try:
                import subprocess

                result = subprocess.run(
                    [
                        "grep",
                        "-rn",
                        "--include=*.py",
                        "--include=*.js",
                        "--include=*.ts",
                        "--include=*.md",
                        "--include=*.json",
                        "--include=*.yaml",
                        "--include=*.yml",
                        pattern,
                        str(_resolve_explore_path(path)),
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                matches = result.stdout.strip().splitlines()[:20]  # Limit results
                if matches:
                    return f"Search results for '{pattern}':\n" + "\n".join(matches)
                return f"No matches found for '{pattern}'"
            except Exception as e:
                return f"Search error: {e}"

        def execute_tool(name: str, args: dict) -> str:
            if name == "list_files":
                return execute_list_files(args.get("path", "."))
            elif name == "read_file":
                return execute_read_file(
                    args.get("path", ""), args.get("max_lines", 200)
                )
            elif name == "search":
                return execute_search(args.get("pattern", ""), args.get("path", "."))
            return f"Unknown tool: {name}"

        # System prompt for the explorer
        system_prompt = f"""You are a codebase exploration assistant. Your job is to explore and understand codebases.

You have these tools:
- list_files: List directory contents
- read_file: Read a file (max 200 lines)
- search: Search for patterns in files

Current directory: {cwd}
Starting directory: {start_dir}

IMPORTANT:
1. Start by listing the root directory to understand the structure
2. Read key files like README.md, package.json, pyproject.toml, etc.
3. Identify the main technology stack and architecture
4. Be systematic but efficient - don't read every file
5. When you have enough information, provide a clear summary

To use a tool, respond with a JSON block:
```json
{{"tool": "tool_name", "args": {{"param": "value"}}}}
```

When done exploring, provide your final summary WITHOUT any tool calls."""

        try:
            from penguin.llm.openrouter_gateway import OpenRouterGateway
            from penguin.llm.model_config import ModelConfig

            model_config = ModelConfig(
                model="anthropic/claude-haiku-4.5",
                provider="openrouter",
                max_output_tokens=2000,
            )
            gateway = OpenRouterGateway(model_config)

            messages = [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": task},
            ]

            final_content = ""

            # Mini action loop
            for iteration in range(max_iterations):
                _logger.info(f"[DELEGATE] Iteration {iteration + 1}/{max_iterations}")

                response = await gateway.get_response(messages=messages)

                # Extract content from response
                content = ""
                if isinstance(response, dict):
                    content = response.get("content", "")
                    if not content and "choices" in response:
                        choices = response.get("choices", [])
                        if choices:
                            content = choices[0].get("message", {}).get("content", "")
                elif hasattr(response, "content"):
                    content = response.content
                else:
                    content = str(response)

                final_content = content

                # Check for tool calls (look for JSON blocks)
                tool_match = re.search(r"```json\s*({[^`]+})\s*```", content, re.DOTALL)
                if not tool_match:
                    # Also try without code fence
                    tool_match = re.search(r'\{"tool":\s*"(\w+)"', content)

                if tool_match:
                    try:
                        # Parse tool call
                        if "```" in content:
                            tool_json = json.loads(tool_match.group(1))
                        else:
                            # Extract full JSON object
                            start = content.find('{"tool"')
                            depth = 0
                            end = start
                            for i, c in enumerate(content[start:]):
                                if c == "{":
                                    depth += 1
                                elif c == "}":
                                    depth -= 1
                                if depth == 0:
                                    end = start + i + 1
                                    break
                            tool_json = json.loads(content[start:end])

                        tool_name = tool_json.get("tool")
                        tool_args = tool_json.get("args", {})

                        _logger.info(f"[DELEGATE] Tool call: {tool_name}({tool_args})")

                        # Execute tool
                        result = execute_tool(tool_name, tool_args)

                        # Add to conversation
                        messages.append({"role": "assistant", "content": content})
                        messages.append(
                            {"role": "user", "content": f"Tool result:\n{result}"}
                        )

                    except json.JSONDecodeError as e:
                        _logger.warning(f"[DELEGATE] Failed to parse tool call: {e}")
                        # Treat as final response
                        return f"[Haiku Explorer]:\n{content}"
                else:
                    # No tool call - this is the final response
                    return f"[Haiku Explorer]:\n{content}"

            # Max iterations reached
            return f"[Haiku Explorer] (max iterations reached):\n{final_content}"

        except Exception as e:
            _logger.error(f"delegate_explore_task failed: {e}", exc_info=True)
            return f"delegate_explore_task failed: {e}"

    async def _stop_sub_agent(self, params: str) -> str:
        """Stop/pause a sub-agent. Also cancels background tasks if running."""
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for stop_sub_agent: {e}"
        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            return "stop_sub_agent requires 'id'"
        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for stop_sub_agent"

        cancelled_background = False
        try:
            # Try to cancel background task if running in executor
            from penguin.multi.executor import get_executor

            executor = get_executor()
            if executor:
                status = executor.get_status(agent_id)
                if status and status.get("state") in ("pending", "running"):
                    cancelled_background = await executor.cancel(agent_id)
        except Exception as e:
            logger.debug(f"Failed to cancel background task for '{agent_id}': {e}")

        try:
            # Also pause in conversation manager
            if hasattr(core, "set_agent_paused"):
                core.set_agent_paused(agent_id, True)

            if cancelled_background:
                return f"Stopped sub-agent '{agent_id}' (background task cancelled)"
            return f"Paused sub-agent '{agent_id}'"
        except Exception as e:
            return f"Failed to pause sub-agent '{agent_id}': {e}"

    async def _resume_sub_agent(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for resume_sub_agent: {e}"
        agent_id = str(payload.get("id") or "").strip()
        if not agent_id:
            return "resume_sub_agent requires 'id'"
        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            return "Core unavailable for resume_sub_agent"
        try:
            if hasattr(core, "set_agent_paused"):
                core.set_agent_paused(agent_id, False)
            return f"Resumed sub-agent '{agent_id}'"
        except Exception as e:
            return f"Failed to resume sub-agent '{agent_id}': {e}"

    async def _get_agent_status(self, params: str) -> str:
        status_started_at = time.monotonic()
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            self._log_subagent_event(
                "status.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - status_started_at) * 1000,
                tool_call_id=self._resolve_subagent_tool_call_id(),
                error="invalid_json",
            )
            return f"Invalid JSON for get_agent_status: {e}"

        agent_id = str(payload.get("id") or payload.get("agent_id") or "").strip()
        include_result = bool(payload.get("include_result", False))

        tool_input: Dict[str, Any] = {"include_result": include_result}
        if agent_id:
            tool_input["id"] = agent_id

        tool_call_id = self._resolve_subagent_tool_call_id(payload)

        self._log_subagent_event(
            "status.request",
            status="started",
            elapsed_ms=0.0,
            target_agent=agent_id or "all",
            tool_call_id=tool_call_id,
            include_result=include_result,
        )
        result = self.tool_manager.execute_tool("get_agent_status", tool_input)

        summary_status = "completed"
        try:
            payload_result = json.loads(result) if isinstance(result, str) else {}
            if isinstance(payload_result, dict) and payload_result.get("error"):
                summary_status = "failed"
        except Exception:
            pass

        self._log_subagent_event(
            "status.summary",
            status=summary_status,
            elapsed_ms=(time.monotonic() - status_started_at) * 1000,
            target_agent=agent_id or "all",
            tool_call_id=tool_call_id,
            include_result=include_result,
        )
        return result

    async def _wait_for_agents(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for wait_for_agents: {e}"

        raw_ids = payload.get("ids", payload.get("agent_ids"))
        normalized_ids: Optional[List[str]] = None
        if raw_ids is None:
            normalized_ids = None
        elif isinstance(raw_ids, list):
            normalized_ids = [
                str(item).strip() for item in raw_ids if str(item).strip()
            ]
        elif isinstance(raw_ids, str):
            cleaned = raw_ids.strip()
            normalized_ids = [cleaned] if cleaned else []
        else:
            return "wait_for_agents 'ids' must be a list of strings"

        timeout = payload.get("timeout")
        if timeout is not None:
            try:
                timeout = float(timeout)
            except (TypeError, ValueError):
                return "wait_for_agents 'timeout' must be numeric"

        tool_input: Dict[str, Any] = {}
        if normalized_ids is not None:
            tool_input["ids"] = normalized_ids
        if timeout is not None:
            tool_input["timeout"] = timeout

        logger.info(
            "subagent.wait.request ids=%s timeout=%s",
            normalized_ids if normalized_ids is not None else "all",
            timeout,
        )

        async_wait_handler = getattr(
            self.tool_manager,
            "_execute_wait_for_agents",
            None,
        )
        if callable(async_wait_handler) and asyncio.iscoroutinefunction(
            async_wait_handler
        ):
            raw_result = await async_wait_handler(tool_input)
            try:
                parsed = json.loads(raw_result) if isinstance(raw_result, str) else {}
                if isinstance(parsed, dict):
                    logger.info(
                        "subagent.wait.result status=%s elapsed=%s polls=%s ids=%s",
                        parsed.get("status"),
                        parsed.get("elapsed_seconds"),
                        parsed.get("poll_count"),
                        parsed.get("waited_agent_ids"),
                    )
            except Exception:
                pass
            return raw_result

        return self.tool_manager.execute_tool("wait_for_agents", tool_input)

    async def _get_context_info(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for get_context_info: {e}"

        agent_id = str(payload.get("id") or payload.get("agent_id") or "").strip()
        include_stats = bool(payload.get("include_stats", False))

        tool_input: Dict[str, Any] = {"include_stats": include_stats}
        if agent_id:
            tool_input["id"] = agent_id

        logger.info(
            "subagent.context_info.request agent=%s include_stats=%s",
            agent_id or "default",
            include_stats,
        )
        return self.tool_manager.execute_tool("get_context_info", tool_input)

    async def _sync_context(self, params: str) -> str:
        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            return f"Invalid JSON for sync_context: {e}"

        parent = str(
            payload.get("parent") or payload.get("parent_agent_id") or ""
        ).strip()
        child = str(payload.get("child") or payload.get("child_agent_id") or "").strip()
        replace = bool(payload.get("replace", False))

        if not parent or not child:
            return "sync_context requires 'parent' and 'child'"

        logger.info(
            "subagent.context_sync.request parent=%s child=%s replace=%s",
            parent,
            child,
            replace,
        )
        return self.tool_manager.execute_tool(
            "sync_context",
            {
                "parent": parent,
                "child": child,
                "replace": replace,
            },
        )

    async def _delegate(self, params: str) -> str:
        """Delegate a task to a sub-agent.

        JSON body:
          - child (required): Target sub-agent ID
          - content (required): Task content
          - parent (optional): Parent agent ID
          - channel (optional): Logical channel
          - metadata (optional): Additional metadata
          - background (bool, default False): Run in background
          - wait (bool, default False): Wait for result when background=true
          - timeout (float, optional): Timeout in seconds when wait=true
        """
        delegate_started_at = time.monotonic()

        try:
            payload = json.loads(params) if params.strip() else {}
        except Exception as e:
            self._log_subagent_event(
                "delegate.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                tool_call_id=self._resolve_subagent_tool_call_id(),
                error="invalid_json",
            )
            return f"Invalid JSON for delegate: {e}"

        child = str(payload.get("child") or "").strip()
        content = payload.get("content")
        if not child or content is None:
            self._log_subagent_event(
                "delegate.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                tool_call_id=self._resolve_subagent_tool_call_id(payload),
                error="missing_child_or_content",
            )
            return "delegate requires 'child' and 'content'"

        conversation = self.conversation_system
        core = getattr(conversation, "core", None)
        if core is None:
            self._log_subagent_event(
                "delegate.summary",
                status="failed",
                elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                target_agent=child,
                tool_call_id=self._resolve_subagent_tool_call_id(payload),
                error="core_unavailable",
            )
            return "Core unavailable for delegate"

        parent = str(
            payload.get("parent")
            or getattr(conversation, "current_agent_id", None)
            or "default"
        ).strip()
        channel = payload.get("channel")
        metadata = payload.get("metadata") or {}
        background = bool(payload.get("background", False))
        wait = bool(payload.get("wait", False))
        timeout = payload.get("timeout")
        tool_call_id = self._resolve_subagent_tool_call_id(payload)

        self._log_subagent_event(
            "delegate.request",
            status="started",
            elapsed_ms=0.0,
            target_agent=child,
            parent_agent=parent,
            tool_call_id=tool_call_id,
            background=background,
            wait=wait,
            timeout=timeout,
            channel=channel,
        )

        # Record delegation event in both parent and child logs (best-effort)
        try:
            cm = getattr(core, "conversation_manager", None)
            if cm and hasattr(cm, "log_delegation_event"):
                import uuid as _uuid

                delegation_id = _uuid.uuid4().hex[:8]
                cm.log_delegation_event(
                    delegation_id=delegation_id,
                    parent_agent_id=parent,
                    child_agent_id=child,
                    event="request_sent",
                    message=str(content)[:140],
                    metadata={**metadata, **({"channel": channel} if channel else {})},
                )
                metadata = {**metadata, "delegation_id": delegation_id}
        except Exception as e:
            logger.debug(f"Failed to add delegation_id to metadata: {e}")

        if background:
            # Run delegated task in background using AgentExecutor
            try:
                from penguin.multi.executor import (
                    get_executor,
                    set_executor,
                    AgentExecutor,
                )
                import asyncio

                executor = get_executor()
                if executor is None:
                    executor = AgentExecutor(core)
                    set_executor(executor)

                # Check if agent is already running
                status = executor.get_status(child)
                if status and status.get("state") in ("pending", "running"):
                    self._log_subagent_event(
                        "delegate.summary",
                        status="failed",
                        elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                        target_agent=child,
                        parent_agent=parent,
                        tool_call_id=tool_call_id,
                        background=True,
                        error="already_running",
                    )
                    return f"Agent '{child}' is already running a background task"

                await executor.spawn_agent(
                    child,
                    str(content),
                    metadata={
                        "parent": parent,
                        "channel": channel,
                        **(metadata or {}),
                    },
                )

                if wait:
                    try:
                        result = await executor.wait_for(child, timeout=timeout)
                        self._log_subagent_event(
                            "delegate.summary",
                            status="completed",
                            elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                            target_agent=child,
                            parent_agent=parent,
                            tool_call_id=tool_call_id,
                            background=True,
                            wait=True,
                        )
                        return f"Delegated to '{child}' (background, waited): {result}"
                    except asyncio.TimeoutError:
                        self._log_subagent_event(
                            "delegate.summary",
                            status="timeout",
                            elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                            target_agent=child,
                            parent_agent=parent,
                            tool_call_id=tool_call_id,
                            background=True,
                            timeout=timeout,
                        )
                        return f"Delegated to '{child}' (background, timed out after {timeout}s)"
                else:
                    self._log_subagent_event(
                        "delegate.summary",
                        status="started",
                        elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                        target_agent=child,
                        parent_agent=parent,
                        tool_call_id=tool_call_id,
                        background=True,
                        wait=False,
                    )
                    return f"Delegated to '{child}' running in background"
            except Exception as e:
                self._log_subagent_event(
                    "delegate.summary",
                    status="failed",
                    elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                    target_agent=child,
                    parent_agent=parent,
                    tool_call_id=tool_call_id,
                    background=True,
                    error=str(e),
                )
                return f"Failed to delegate background task to '{child}': {e}"
        else:
            # Synchronous delegation via message passing
            try:
                await core.send_to_agent(
                    child,
                    content,
                    message_type="message",
                    metadata=metadata,
                    channel=channel,
                )
                self._log_subagent_event(
                    "delegate.summary",
                    status="completed",
                    elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                    target_agent=child,
                    parent_agent=parent,
                    tool_call_id=tool_call_id,
                    background=False,
                )
                return f"Delegated to '{child}' from '{parent}'"
            except Exception as e:
                self._log_subagent_event(
                    "delegate.summary",
                    status="failed",
                    elapsed_ms=(time.monotonic() - delegate_started_at) * 1000,
                    target_agent=child,
                    parent_agent=parent,
                    tool_call_id=tool_call_id,
                    background=False,
                    error=str(e),
                )
                return f"Failed to delegate to '{child}': {e}"

    def _workspace_search(self, params: str) -> str:
        parts = params.split(":", 1)
        if len(parts) == 2:
            query, max_results = parts[0].strip(), int(parts[1].strip())
        else:
            query, max_results = params.strip(), 5

        return self.tool_manager.execute_tool(
            "workspace_search", {"query": query, "max_results": max_results}
        )

    async def _memory_search(self, params: str) -> str:
        """
        Parse and execute memory search command
        Format: query:max_results:memory_type:categories:date_after:date_before
        Example: "project planning:5:logs:planning,projects:2024-01-01:2024-03-01"
        """
        try:
            parts = params.split(":")
            query = parts[0].strip()

            # Parse optional parameters
            max_results = int(parts[1]) if len(parts) > 1 and parts[1].strip() else 5
            memory_type = (
                parts[2].strip() if len(parts) > 2 and parts[2].strip() else None
            )
            categories = (
                parts[3].strip().split(",")
                if len(parts) > 3 and parts[3].strip()
                else None
            )

            # Use the tool_manager's memory_search method which will access the lazily loaded memory_searcher
            json_results = await self.tool_manager.perform_memory_search(
                query=query,
                k=max_results,
                memory_type=memory_type,
                categories=categories,
            )

            # Parse the JSON string returned by perform_memory_search
            try:
                import json

                parsed_results = json.loads(json_results)

                # Handle error responses
                if isinstance(parsed_results, dict) and "error" in parsed_results:
                    return f"Memory search error: {parsed_results['error']}"

                # Handle "no results" response
                if isinstance(parsed_results, dict) and "result" in parsed_results:
                    return parsed_results["result"]

                # Handle actual search results
                if isinstance(parsed_results, list):
                    results = parsed_results
                else:
                    return "Unexpected response format from memory search."

            except json.JSONDecodeError:
                return f"Error parsing memory search results: {json_results}"

            # Format results for display
            if not results:
                return "No results found."

            formatted_results = []
            for i, result in enumerate(results, 1):
                # Fix metadata field names to match actual result structure
                metadata = result.get("metadata", {})
                file_path = metadata.get("path", metadata.get("file_path", "Unknown"))
                file_type = metadata.get(
                    "file_type", metadata.get("memory_type", "Unknown")
                )
                categories = result.get(
                    "categories", metadata.get("categories", "None")
                )

                formatted_results.append(f"\n{i}. From: {file_path}")
                formatted_results.append(f"   Type: {file_type}")
                formatted_results.append(f"   Categories: {categories}")
                formatted_results.append(
                    f"   Score: {result.get('score', result.get('relevance', 0)):.2f}"
                )

                # Enhanced preview for conversation messages
                if file_type == "conversation_message":
                    role = metadata.get("message_role", "unknown")
                    timestamp = metadata.get("timestamp", "")
                    session_id = metadata.get("session_id", "unknown")

                    formatted_results.append(f"   Role: {role}")
                    if timestamp:
                        formatted_results.append(
                            f"   Time: {timestamp[:19]}"
                        )  # YYYY-MM-DDTHH:MM:SS
                    formatted_results.append(f"   Session: {session_id}")
                    formatted_results.append("   Message:")

                    # Get content preview with conversation context
                    content = result.get(
                        "content", result.get("preview", "No preview available")
                    )
                    # For conversation messages, show more content (up to 300 characters)
                    preview = content[:300] + "..." if len(content) > 300 else content
                    # Indent the content for better readability
                    indented_preview = "\n".join(
                        f"   > {line}" for line in preview.split("\n")
                    )
                    formatted_results.append(indented_preview)
                else:
                    formatted_results.append("   Preview:")
                    # Get content preview, limiting to 200 characters
                    content = result.get(
                        "content", result.get("preview", "No preview available")
                    )
                    preview = content[:200] + "..." if len(content) > 200 else content
                    formatted_results.append(f"   {preview}")

                formatted_results.append("")

            return "\n".join(formatted_results)

        except Exception as e:
            return f"Error executing memory search: {str(e)}"

    async def _memory_index(self, params: str) -> str:
        """Index all memory files"""
        try:
            return self.tool_manager.index_memory()
        except Exception as e:
            return f"Error indexing memory: {str(e)}"

    def _project_create(self, params: str) -> str:
        """Create a new project. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            project = self.task_manager.create(name.strip(), description.strip())
            return f"Project created: {project.name}"
        except Exception as e:
            return f"Error creating project: {str(e)}"

    def _project_list(self, params: str) -> str:
        """List all projects"""
        try:
            projects = (
                self.task_manager.projects.values()
            )  # Access the projects dict directly
            if not projects:
                return "No projects found."
            return "\n".join([f"- {p.name}: {p.description}" for p in projects])
        except Exception as e:
            return f"Error listing projects: {str(e)}"

    def _project_update(self, params: str) -> str:
        """Update project status. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            self.task_manager.update_status(name.strip(), description.strip())
            return f"Project '{name}' updated successfully"
        except Exception as e:
            return f"Error updating project: {str(e)}"

    def _project_delete(self, params: str) -> str:
        """Delete a project. Format: name"""
        try:
            self.task_manager.delete(params.strip())
            return f"Project '{params}' deleted successfully"
        except Exception as e:
            return f"Error deleting project: {str(e)}"

    def _project_display(self, params: str) -> str:
        """Display project details. Format: name"""
        try:
            output = self.task_manager.display(params.strip())
            return output
        except Exception as e:
            return f"Error displaying project: {str(e)}"

    def _normalize_todo_items(self, raw_items: Any) -> List[Dict[str, str]]:
        """Normalize todo payloads to OpenCode-compatible Todo[] shape."""
        if not isinstance(raw_items, list):
            return []

        normalized: List[Dict[str, str]] = []
        statuses = {"pending", "in_progress", "completed", "cancelled"}
        priorities = {"high", "medium", "low"}
        seen_ids = set()

        for item in raw_items:
            if not isinstance(item, dict):
                continue

            content_raw = item.get("content")
            if isinstance(content_raw, str):
                content = content_raw.strip()
            elif content_raw is None:
                content = ""
            else:
                content = str(content_raw).strip()
            if not content:
                continue

            status_raw = item.get("status", "pending")
            status = (
                status_raw.strip().lower()
                if isinstance(status_raw, str)
                else str(status_raw).strip().lower()
            )
            if status not in statuses:
                status = "pending"

            priority_raw = item.get("priority", "medium")
            priority = (
                priority_raw.strip().lower()
                if isinstance(priority_raw, str)
                else str(priority_raw).strip().lower()
            )
            if priority not in priorities:
                priority = "medium"

            todo_id_raw = item.get("id")
            if isinstance(todo_id_raw, str) and todo_id_raw.strip():
                todo_id = todo_id_raw.strip()
            else:
                todo_id = f"todo_{base64.urlsafe_b64encode(os.urandom(6)).decode('ascii').rstrip('=')}"

            if todo_id in seen_ids:
                suffix = 2
                candidate = f"{todo_id}_{suffix}"
                while candidate in seen_ids:
                    suffix += 1
                    candidate = f"{todo_id}_{suffix}"
                todo_id = candidate

            seen_ids.add(todo_id)
            normalized.append(
                {
                    "id": todo_id,
                    "content": content,
                    "status": status,
                    "priority": priority,
                }
            )

        return normalized

    def _parse_todo_params(self, params: str) -> List[Dict[str, str]]:
        """Parse todowrite payload from JSON object or JSON array."""
        content = (params or "").strip()
        if not content:
            return []

        payload = json.loads(content)
        if isinstance(payload, dict):
            maybe_items = payload.get("todos")
            if isinstance(maybe_items, list):
                return self._normalize_todo_items(maybe_items)
            if {"content", "status", "priority", "id"} & set(payload.keys()):
                return self._normalize_todo_items([payload])
            raise ValueError("todowrite expects JSON array or object with 'todos'")

        if isinstance(payload, list):
            return self._normalize_todo_items(payload)

        raise ValueError("todowrite expects JSON array or object with 'todos'")

    def _normalize_question_options(self, raw_items: Any) -> List[Dict[str, str]]:
        """Normalize question options to OpenCode-compatible shape."""
        if not isinstance(raw_items, list):
            return []

        normalized: List[Dict[str, str]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            label_raw = item.get("label")
            description_raw = item.get("description")

            label = (
                label_raw.strip()
                if isinstance(label_raw, str)
                else str(label_raw).strip()
                if label_raw is not None
                else ""
            )
            description = (
                description_raw.strip()
                if isinstance(description_raw, str)
                else str(description_raw).strip()
                if description_raw is not None
                else ""
            )

            if not label or not description:
                continue

            normalized.append(
                {
                    "label": label,
                    "description": description,
                }
            )

        return normalized

    def _normalize_question_items(self, raw_items: Any) -> List[Dict[str, Any]]:
        """Normalize question payload to OpenCode-compatible Question[] shape."""
        if not isinstance(raw_items, list):
            return []

        normalized: List[Dict[str, Any]] = []
        for item in raw_items:
            if not isinstance(item, dict):
                continue

            question_raw = item.get("question")
            header_raw = item.get("header")

            question_text = (
                question_raw.strip()
                if isinstance(question_raw, str)
                else str(question_raw).strip()
                if question_raw is not None
                else ""
            )
            header_text = (
                header_raw.strip()
                if isinstance(header_raw, str)
                else str(header_raw).strip()
                if header_raw is not None
                else ""
            )

            options = self._normalize_question_options(item.get("options"))
            if not question_text or not header_text or not options:
                continue

            question_payload: Dict[str, Any] = {
                "question": question_text,
                "header": header_text[:30],
                "options": options,
            }

            multiple = item.get("multiple")
            if isinstance(multiple, bool):
                question_payload["multiple"] = multiple

            custom = item.get("custom")
            if isinstance(custom, bool):
                question_payload["custom"] = custom

            normalized.append(question_payload)

        return normalized

    def _parse_question_params(self, params: str) -> List[Dict[str, Any]]:
        """Parse question payload from JSON object or JSON array."""
        content = (params or "").strip()
        if not content:
            raise ValueError("question expects JSON array or object with 'questions'")

        payload = json.loads(content)
        if isinstance(payload, dict):
            maybe_items = payload.get("questions")
            if isinstance(maybe_items, list):
                questions = self._normalize_question_items(maybe_items)
                if questions:
                    return questions
                raise ValueError("question payload contains no valid questions")
            if {"question", "header", "options"} <= set(payload.keys()):
                questions = self._normalize_question_items([payload])
                if questions:
                    return questions
                raise ValueError("question payload contains no valid questions")
            raise ValueError("question expects JSON array or object with 'questions'")

        if isinstance(payload, list):
            questions = self._normalize_question_items(payload)
            if questions:
                return questions
            raise ValueError("question payload contains no valid questions")

        raise ValueError("question expects JSON array or object with 'questions'")

    def _resolve_question_session_id(self) -> Optional[str]:
        """Resolve active session ID for question operations."""
        context = get_current_execution_context()
        if context is not None:
            session_id = context.session_id or context.conversation_id
            if isinstance(session_id, str) and session_id:
                return session_id

        session_id, _session, _manager = self._resolve_todo_session()
        if isinstance(session_id, str) and session_id:
            return session_id

        return None

    async def _question(self, params: str) -> str:
        """Ask structured user questions and wait for answers."""
        try:
            questions = self._parse_question_params(params)
        except Exception as e:
            return f"Error: Invalid question payload: {e}"

        session_id = self._resolve_question_session_id()
        if not session_id:
            return "Error: Unable to resolve session for question"

        try:
            from penguin.security.question import QuestionStatus, get_question_manager

            context = get_current_execution_context()
            request_context: Dict[str, Any] = {}
            if context is not None and isinstance(context.agent_id, str):
                request_context["agent_id"] = context.agent_id
            if context is not None and isinstance(context.directory, str):
                request_context["directory"] = context.directory

            manager = get_question_manager()
            request = manager.create_request(
                session_id=session_id,
                questions=questions,
                context=request_context,
            )
            resolved = await manager.wait_for_resolution(request.id)
            if resolved is None:
                return "Error: Question request was not resolved"
            if resolved.status == QuestionStatus.REJECTED:
                return "Error: The user rejected this question request"

            answers = resolved.answers or []
            formatted_pairs: List[str] = []
            for index, question in enumerate(questions):
                answer = answers[index] if index < len(answers) else []
                value = ", ".join(answer) if answer else "Unanswered"
                formatted_pairs.append(f'"{question["question"]}"="{value}"')

            formatted = ", ".join(formatted_pairs)
            return (
                "User has answered your questions: "
                f"{formatted}. "
                "You can now continue with the user's answers in mind."
            )
        except Exception as e:
            return f"Error: Failed to ask question: {e}"

    def _resolve_todo_session(self) -> tuple[Optional[str], Any, Any]:
        """Resolve the active session and manager for todo operations."""
        context = get_current_execution_context()
        context_session_id = None
        if context is not None:
            context_session_id = context.session_id or context.conversation_id

        conversation = self.conversation_system
        if conversation is None:
            return None, None, None

        core = getattr(conversation, "core", None)
        if core is not None and context_session_id:
            finder = getattr(core, "_find_session_store", None)
            if callable(finder):
                session, manager = finder(str(context_session_id))
                if session is not None and manager is not None:
                    return str(context_session_id), session, manager

        manager = getattr(conversation, "session_manager", None)
        if context_session_id and manager is not None:
            loader = getattr(manager, "load_session", None)
            if callable(loader):
                session = loader(str(context_session_id))
                if session is not None:
                    return str(context_session_id), session, manager

        getter = getattr(conversation, "get_current_session", None)
        if callable(getter):
            session = getter()
            if session is not None and manager is not None:
                resolved_id = str(
                    context_session_id or getattr(session, "id", "") or ""
                )
                if resolved_id:
                    return resolved_id, session, manager

        return None, None, None

    async def _todo_write(self, params: str) -> str:
        """Persist session-scoped todos. Format: JSON array or {"todos": [...]}"""
        try:
            todos = self._parse_todo_params(params)
        except Exception as e:
            return f"Error: Invalid todowrite payload: {e}"

        session_id, session, manager = self._resolve_todo_session()
        if not session_id or session is None or manager is None:
            return "Error: Unable to resolve session for todowrite"

        metadata = getattr(session, "metadata", None)
        if not isinstance(metadata, dict):
            metadata = {}
            session.metadata = metadata
        metadata["_opencode_todo_v1"] = todos

        mark_modified = getattr(manager, "mark_session_modified", None)
        if callable(mark_modified):
            mark_modified(session.id)
        saver = getattr(manager, "save_session", None)
        if callable(saver):
            saver(session)

        if self._ui_event_cb:
            try:
                event_payload: Dict[str, Any] = {
                    "sessionID": session_id,
                    "conversation_id": session_id,
                    "todos": todos,
                }
                context = get_current_execution_context()
                if context is not None and context.directory:
                    event_payload["directory"] = context.directory
                await self._ui_event_cb("todo.updated", event_payload)
            except Exception as e:
                logger.debug(f"UI event emit failed (todo.updated): {e}")

        return json.dumps(todos, indent=2)

    def _todo_read(self, params: str) -> str:
        """Read session-scoped todos as JSON."""
        _ = params
        session_id, session, _manager = self._resolve_todo_session()
        if not session_id or session is None:
            return "Error: Unable to resolve session for todoread"

        metadata = getattr(session, "metadata", None)
        if not isinstance(metadata, dict):
            return "[]"

        todos = self._normalize_todo_items(metadata.get("_opencode_todo_v1"))
        return json.dumps(todos, indent=2)

    def _task_create(self, params: str) -> str:
        """Create a new task. Format: name:description[:project_name]"""
        try:
            parts = params.split(":", 2)
            if len(parts) < 2:
                return "Error: Invalid task format. Use name:description[:project_name]"
            name, description = parts[0:2]
            project_name = parts[2].strip() if len(parts) > 2 else None
            response = self.task_manager.create_task(
                name.strip(), description.strip(), project_name
            )

            if isinstance(response, dict) and "result" in response:
                return response["result"]
            return f"Task created: {name}"
        except Exception as e:
            return f"Error creating task: {str(e)}"

    def _task_update(self, params: str) -> str:
        """Update task status. Format: name:description"""
        try:
            name, description = params.split(":", 1)
            self.task_manager.update_status(name.strip(), description.strip())
            return f"Task '{name}' updated successfully"
        except Exception as e:
            return f"Error updating task: {str(e)}"

    def _task_complete(self, params: str) -> str:
        """Complete a task. Format: name"""
        try:
            self.task_manager.complete(params.strip())
            return f"Task '{params}' completed successfully"
        except Exception as e:
            return f"Error completing task: {str(e)}"

    def _finish_response(self, params: str) -> str:
        """Signal that the conversational response is complete.

        Called by the LLM when it has finished responding and has no more
        actions to take. This stops the run_response loop.

        Format: optional summary
        """
        try:
            return self.tool_manager.task_tools.finish_response(
                params.strip() if params else None
            )
        except Exception as e:
            return f"Error signaling response completion: {str(e)}"

    def _finish_task(self, params: str) -> str:
        """Signal that the LLM believes the task objective is achieved.

        This transitions the task to PENDING_REVIEW status for human approval.
        The summary becomes the review note.

        Format: summary (optional) or JSON {"summary": "...", "status": "done|partial|blocked"}
        """
        try:
            return self.tool_manager.task_tools.finish_task(
                params.strip() if params else None
            )
        except Exception as e:
            return f"Error signaling task completion: {str(e)}"

    # Deprecated: kept for backward compatibility
    def _task_completed(self, params: str) -> str:
        """Deprecated: Use _finish_task instead."""
        return self._finish_task(params)

    def _task_delete(self, params: str) -> str:
        """Delete a task. Format: name"""
        try:
            self.task_manager.delete(params.strip())
            return f"Task '{params}' deleted successfully"
        except Exception as e:
            return f"Error deleting task: {str(e)}"

    def _task_list(self, params: str) -> str:
        """List tasks. Format: project_name(optional)"""
        try:
            tasks = []
            if params.strip():
                # List tasks for specific project
                project = self.task_manager._find_project_by_name(params.strip())
                if not project:
                    return f"Project '{params}' not found."
                tasks = list(project.tasks.values())
            else:
                # List ALL tasks (both project and independent)
                tasks = list(self.task_manager.independent_tasks.values())
                # Also get project tasks
                for project in self.task_manager.projects.values():
                    tasks.extend(project.tasks.values())

            if not tasks:
                return "No tasks found."

            # Format tasks into a readable table-like string
            formatted_tasks = []
            for task in tasks:
                status_icon = {"active": "🔵", "completed": "✅", "archived": "📦"}.get(
                    task.status, "❓"
                )

                priority_icon = {1: "🔴", 2: "🟡", 3: "🟢"}.get(task.priority, "⚪")

                task_line = [
                    f"{priority_icon} {status_icon} {task.title}",
                    f"    Status: {task.status}",
                    f"    Progress: {task.progress}%",
                    f"    Description: {task.description}",
                ]

                if task.tags:
                    task_line.append(
                        f"    Tags: {', '.join(f'#{tag}' for tag in task.tags)}"
                    )
                if task.due_date:
                    task_line.append(f"    Due: {task.due_date}")

                formatted_tasks.append("\n".join(task_line))

            return "\n\n".join(formatted_tasks)

        except Exception as e:
            logger.error(f"Error in _task_list: {str(e)}", exc_info=True)
            return f"Error listing tasks: {str(e)}"

    def _task_display(self, params: str) -> str:
        """Display task details. Format: name"""
        try:
            output = self.task_manager.display(params.strip())
            return output
        except Exception as e:
            return f"Error displaying task: {str(e)}"

    def _dependency_display(self, params: str) -> str:
        """Display dependencies for a task or project"""
        try:
            return self.task_manager.display_dependencies(params.strip())
        except Exception as e:
            return f"Error displaying dependencies: {str(e)}"

    def _context_get(self, params: str) -> str:
        """Get context for a project or task. Format: project_name/task_name"""
        try:
            # First try to find project
            project = self.task_manager._find_project_by_name(params)
            if project:
                # List all context files in project's context directory
                context_files = list(project.context_path.glob("*.md"))
                if not context_files:
                    return "No context files found for project."

                results = [f"Context for project '{params}':"]
                for cf in context_files:
                    with cf.open("r") as f:
                        content = f.read()
                    results.append(f"\n--- {cf.name} ---\n{content}")
                return "\n".join(results)

            # If not found, try to find task
            task = self.task_manager._find_task_by_name(params)
            if task:
                if not task.metadata.get("context"):
                    return f"No context found for task '{params}'"
                return f"Context for task '{params}':\n{task.metadata['context']}"

            return f"No project or task found with name: {params}"

        except Exception as e:
            return f"Error getting context: {str(e)}"

    def _context_add(self, params: str) -> str:
        """Add context to project/task. Format: name:content[:type]"""
        try:
            parts = params.split(":", 2)
            if len(parts) < 2:
                return "Error: Invalid format. Use name:content[:type]"

            name, content = parts[0:2]
            context_type = parts[2] if len(parts) > 2 else "notes"

            # Try project first
            project = self.task_manager._find_project_by_name(name)
            if project:
                context_file = self.task_manager.add_context(
                    project.id, content, context_type
                )
                return f"Added context to project '{name}': {context_file}"

            # Try task
            task = self.task_manager._find_task_by_name(name)
            if task:
                if "context" not in task.metadata:
                    task.metadata["context"] = []
                task.metadata["context"].append(
                    {
                        "type": context_type,
                        "content": content,
                        "added_at": datetime.now().isoformat(),
                    }
                )
                return f"Added context to task '{name}'"

            return f"No project or task found with name: {name}"

        except Exception as e:
            return f"Error adding context: {str(e)}"

    async def _browser_interact(self, params: str) -> str:
        """Interact with browser elements. Format: action:selector:text"""
        parts = params.split(":", 2)
        if len(parts) < 2:
            return "Error: Invalid format. Use action:selector[:text]"

        action = parts[0].strip()
        selector = parts[1].strip()
        text = parts[2].strip() if len(parts) > 2 else None

        if action not in ["click", "input", "submit"]:
            return f"Error: Invalid action '{action}'. Use click, input, or submit."

        return await self.tool_manager.execute_browser_interact(action, selector, text)

    async def _browser_screenshot(self, params: str) -> str:
        try:
            tool = BrowserScreenshotTool()
            result = await tool.execute()

            if "filepath" in result:
                # Extract description from params or use default
                description = (
                    params.strip() if params else "What can you see in this screenshot?"
                )

                # Create multimodal content in the same format as the /image command result
                multimodal_content = [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_path": result["filepath"]},
                ]

                # Add as a user message (matching how /image adds to conversation)
                self.conversation_system.add_message(
                    role="user",
                    content=multimodal_content,
                    category=MessageCategory.DIALOG,
                )

                return f"Screenshot saved to {result['filepath']} and added to conversation"
            else:
                return result.get("error", "Failed to capture screenshot")
        except Exception as e:
            return f"Error taking screenshot: {str(e)}"

    async def _browser_navigate(self, params: str) -> str:
        if not await browser_manager.initialize():
            return "Failed to initialize browser"
        return await browser_manager.navigate_to(params)

    async def _pydoll_browser_navigate(self, params: str) -> str:
        """Navigate to a URL using PyDoll browser."""
        try:
            from penguin.tools.pydoll_tools import pydoll_browser_manager

            if not await pydoll_browser_manager.initialize(headless=False):
                return "Failed to initialize PyDoll browser"

            # Get a page and navigate to the URL
            page = await pydoll_browser_manager.get_page()
            await page.go_to(params.strip())

            return f"Successfully navigated to {params.strip()} using PyDoll browser"
        except Exception as e:
            error_message = f"Error navigating with PyDoll browser: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _pydoll_browser_interact(self, params: str) -> str:
        """Interact with browser elements using PyDoll. Format: action:selector[:selector_type][:text]"""
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserInteractionTool

            parts = params.split(":", 3)
            if len(parts) < 2:
                return (
                    "Error: Invalid format. Use action:selector[:selector_type][:text]"
                )

            action = parts[0].strip()
            selector = parts[1].strip()
            selector_type = (
                parts[2].strip() if len(parts) > 2 and parts[2].strip() else "css"
            )
            text = parts[3].strip() if len(parts) > 3 else None

            if action not in ["click", "input", "submit"]:
                return f"Error: Invalid action '{action}'. Use click, input, or submit."

            # Create and execute the tool
            tool = PyDollBrowserInteractionTool()
            result = await tool.execute(action, selector, selector_type, text)
            return result
        except Exception as e:
            error_message = f"Error interacting with PyDoll browser: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _pydoll_browser_screenshot(self, params: str) -> str:
        """Take a screenshot using PyDoll browser."""
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserScreenshotTool

            # Execute the screenshot tool
            tool = PyDollBrowserScreenshotTool()
            result = await tool.execute()

            # Debug the result
            logger.info(f"PyDoll screenshot result: {result}")

            if "filepath" in result and os.path.exists(result["filepath"]):
                # Extract description from params or use default
                description = (
                    params.strip()
                    if params
                    else "What can you see in this PyDoll screenshot?"
                )

                # Determine target 'add_message' method
                add_message_fn = None
                if callable(getattr(self.conversation_system, "add_message", None)):
                    add_message_fn = self.conversation_system.add_message
                elif hasattr(self.conversation_system, "conversation") and callable(
                    getattr(self.conversation_system.conversation, "add_message", None)
                ):
                    add_message_fn = self.conversation_system.conversation.add_message

                # Create multimodal content
                multimodal_content = [
                    {"type": "text", "text": description},
                    {"type": "image_url", "image_path": result["filepath"]},
                ]

                if add_message_fn:
                    logger.info(
                        f"Adding PyDoll screenshot to conversation via {add_message_fn}: {multimodal_content}"
                    )
                    add_message_fn(
                        role="user",
                        content=multimodal_content,
                        category=MessageCategory.DIALOG,
                    )
                    return f"PyDoll screenshot saved to {result['filepath']} and added to conversation"
                else:
                    logger.warning(
                        "No suitable add_message method found; conversation update skipped"
                    )
                    return f"PyDoll screenshot saved to {result['filepath']} (conversation update skipped)"
            else:
                error_msg = result.get(
                    "error", "Failed to capture PyDoll screenshot or file not found"
                )
                logger.error(f"PyDoll screenshot error: {error_msg}")
                return error_msg
        except Exception as e:
            error_message = f"Error taking PyDoll screenshot: {str(e)}"
            logger.error(error_message, exc_info=True)
            return error_message

    async def _pydoll_browser_scroll(self, params: str) -> str:
        """Scroll the page or an element using PyDoll.
        Formats:
          - to:top|bottom
          - page:down|up|end|home[:repeat]
          - by:deltaY[:deltaX][:repeat]
          - element:selector[:selector_type][:behavior]
        Defaults: selector_type=css, behavior=auto, repeat=1
        """
        try:
            from penguin.tools.pydoll_tools import PyDollBrowserScrollTool

            parts = params.split(":") if params else []
            if not parts:
                return "Invalid scroll params"
            mode = parts[0].strip().lower()

            tool = PyDollBrowserScrollTool()

            if mode == "to" and len(parts) >= 2:
                to = parts[1].strip().lower()
                return await tool.execute(mode="to", to=to)

            if mode == "page":
                direction = parts[1].strip().lower() if len(parts) >= 2 else "down"
                repeat = (
                    int(parts[2])
                    if len(parts) >= 3 and parts[2].strip().isdigit()
                    else 1
                )
                return await tool.execute(mode="page", to=direction, repeat=repeat)

            if mode == "by":
                dy = (
                    int(parts[1])
                    if len(parts) >= 2 and parts[1].strip().lstrip("-+").isdigit()
                    else 800
                )
                dx = (
                    int(parts[2])
                    if len(parts) >= 3 and parts[2].strip().lstrip("-+").isdigit()
                    else 0
                )
                repeat = (
                    int(parts[3])
                    if len(parts) >= 4 and parts[3].strip().isdigit()
                    else 1
                )
                return await tool.execute(
                    mode="by", delta_y=dy, delta_x=dx, repeat=repeat
                )

            if mode == "element" and len(parts) >= 2:
                selector = parts[1]
                selector_type = (
                    parts[2].strip().lower()
                    if len(parts) >= 3 and parts[2].strip()
                    else "css"
                )
                behavior = (
                    parts[3].strip().lower()
                    if len(parts) >= 4 and parts[3].strip()
                    else "auto"
                )
                return await tool.execute(
                    mode="element",
                    selector=selector,
                    selector_type=selector_type,
                    behavior=behavior,
                )

            return "Invalid scroll command"
        except Exception as e:
            error_message = f"Error scrolling with PyDoll browser: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _pydoll_debug_toggle(self, params: str) -> str:
        """Toggle PyDoll debug mode. Format: [on|off] or empty to toggle"""
        try:
            from penguin.tools.pydoll_tools import pydoll_debug_toggle

            if params.strip().lower() == "on":
                enabled = True
            elif params.strip().lower() == "off":
                enabled = False
            else:
                # Toggle current state if no specific instruction
                enabled = None

            new_state = await pydoll_debug_toggle(enabled)
            return f"PyDoll debug mode is now {'enabled' if new_state else 'disabled'}"
        except Exception as e:
            error_message = f"Error toggling PyDoll debug mode: {str(e)}"
            logger.error(error_message)
            return error_message

    async def _analyze_codebase(self, params: str) -> str:
        """Invoke analyze_codebase tool. Format: directory:analysis_type:include_external"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else ""
        analysis_type = (
            parts[1].strip() if len(parts) > 1 and parts[1].strip() else "all"
        )
        include_external = (
            parts[2].strip().lower() == "true" if len(parts) > 2 else False
        )
        return self.tool_manager.execute_tool(
            "analyze_codebase",
            {
                "directory": directory,
                "analysis_type": analysis_type,
                "include_external": include_external,
            },
        )

    async def _reindex_workspace(self, params: str) -> str:
        """Invoke reindex_workspace tool. Format: directory:force_full"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else ""
        force_full = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        return self.tool_manager.execute_tool(
            "reindex_workspace",
            {
                "directory": directory,
                "force_full": force_full,
            },
        )

    def _list_files_filtered(self, params: str) -> str:
        """Enhanced file listing. Format: path:group_by_type:show_hidden"""
        parts = params.split(":")
        path = parts[0].strip() if parts and parts[0].strip() else "."
        group_by_type = parts[1].strip().lower() == "true" if len(parts) > 1 else False
        show_hidden = parts[2].strip().lower() == "true" if len(parts) > 2 else False

        return self.tool_manager.execute_tool(
            "list_files",
            {"path": path, "group_by_type": group_by_type, "show_hidden": show_hidden},
        )

    def _find_files_enhanced(self, params: str) -> str:
        """Enhanced file finding. Format: pattern:search_path:include_hidden:file_type"""
        parts = params.split(":")
        if not parts or not parts[0].strip():
            return "Error: Pattern is required"

        pattern = parts[0].strip()
        search_path = parts[1].strip() if len(parts) > 1 and parts[1].strip() else "."
        include_hidden = parts[2].strip().lower() == "true" if len(parts) > 2 else False
        file_type = parts[3].strip() if len(parts) > 3 and parts[3].strip() else None

        return self.tool_manager.execute_tool(
            "find_file",
            {
                "filename": pattern,
                "search_path": search_path,
                "include_hidden": include_hidden,
                "file_type": file_type,
            },
        )

    def _enhanced_diff(self, params: str) -> str:
        """Compare two files with enhanced diff. Format: file1:file2:semantic"""
        parts = params.split(":")
        if len(parts) < 2:
            return "Error: Need at least two files to compare"

        file1 = parts[0].strip()
        file2 = parts[1].strip()
        semantic = parts[2].strip().lower() == "true" if len(parts) > 2 else True

        return self.tool_manager.execute_tool(
            "enhanced_diff", {"file1": file1, "file2": file2, "semantic": semantic}
        )

    def _analyze_project(self, params: str) -> str:
        """Analyze project structure. Format: directory:include_external"""
        parts = params.split(":")
        directory = parts[0].strip() if parts and parts[0].strip() else "."
        include_external = (
            parts[1].strip().lower() == "true" if len(parts) > 1 else False
        )

        return self.tool_manager.execute_tool(
            "analyze_project",
            {"directory": directory, "include_external": include_external},
        )

    def _read_file(self, params: Any) -> str:
        """Handle canonical read_file requests with JSON-first parsing."""
        parsed = parse_read_file_payload(params)
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "read_file",
            {
                "path": parsed["path"],
                "show_line_numbers": parsed["show_line_numbers"],
                "max_lines": parsed["max_lines"],
            },
        )

    def _enhanced_read(self, params: Any) -> str:
        """Legacy enhanced_read alias routed through read_file."""
        return self._read_file(params)

    def _write_file(self, params: Any) -> str:
        """Handle canonical write_file requests with JSON-first parsing."""
        parsed = parse_write_file_payload(params)
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "write_file",
            {
                "path": parsed["path"],
                "content": parsed["content"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _enhanced_write(self, params: Any) -> str:
        """Legacy enhanced_write alias routed through write_file."""
        return self._write_file(params)

    def _patch_file(self, params: Any) -> str:
        """Handle canonical patch_file requests with nested JSON payloads."""
        parsed = parse_patch_file_payload(params)
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _apply_diff(self, params: Any) -> str:
        """Legacy apply_diff alias routed through patch_file."""
        parsed = parse_patch_file_payload(params, default_operation_type="unified_diff")
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _patch_files(self, params: Any) -> str:
        """Handle canonical patch_files requests with JSON-first parsing."""
        parsed = parse_patch_files_payload(params)
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        tool_input: Dict[str, Any] = {
            "apply": parsed.get("apply", False),
            "backup": parsed.get("backup", True),
            "_warnings": parsed.get("warnings", []),
        }
        if isinstance(parsed.get("operations"), list):
            tool_input["operations"] = parsed["operations"]
        elif isinstance(parsed.get("content"), str):
            tool_input["content"] = parsed["content"]

        return self.tool_manager.execute_tool("patch_files", tool_input)

    def _multiedit(self, params: Any) -> str:
        """Legacy multiedit alias routed through patch_files."""
        return self._patch_files(params)

    def _edit_with_pattern(self, params: Any) -> str:
        """Legacy edit_with_pattern alias routed through patch_file."""
        parsed = parse_patch_file_payload(
            params, default_operation_type="regex_replace"
        )
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _replace_lines(self, params: str) -> str:
        """Legacy replace_lines alias routed through patch_file."""
        parsed = parse_patch_file_payload(
            params, default_operation_type="replace_lines"
        )
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _insert_lines(self, params: str) -> str:
        """Legacy insert_lines alias routed through patch_file."""
        parsed = parse_patch_file_payload(params, default_operation_type="insert_lines")
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    def _delete_lines(self, params: str) -> str:
        """Legacy delete_lines alias routed through patch_file."""
        parsed = parse_patch_file_payload(params, default_operation_type="delete_lines")
        error = parsed.get("error")
        if isinstance(error, str) and error.strip():
            return f"Error: {error.strip()}"

        return self.tool_manager.execute_tool(
            "patch_file",
            {
                "path": parsed["path"],
                "operation": parsed["operation"],
                "backup": parsed["backup"],
                "_warnings": parsed.get("warnings", []),
            },
        )

    # Repository management action handlers
    def _get_repository_status(self, params: str) -> str:
        """Get status of a repository. Format: repo_owner:repo_name"""
        parts = params.split(":", 1)
        if len(parts) < 2:
            return "Error: Need repo_owner:repo_name format"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()

        return self.tool_manager.execute_tool(
            "get_repository_status", {"repo_owner": repo_owner, "repo_name": repo_name}
        )

    def _create_and_switch_branch(self, params: str) -> str:
        """Create and switch to a new git branch. Format: repo_owner:repo_name:branch_name"""
        parts = params.split(":", 2)
        if len(parts) < 3:
            return "Error: Need repo_owner:repo_name:branch_name format"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        branch_name = parts[2].strip()

        return self.tool_manager.execute_tool(
            "create_and_switch_branch",
            {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "branch_name": branch_name,
            },
        )

    def _commit_and_push_changes(self, params: str) -> str:
        """Commit and push changes. Format: repo_owner:repo_name:commit_message"""
        parts = params.split(":", 2)
        if len(parts) < 3:
            return "Error: Need repo_owner:repo_name:commit_message format"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        commit_message = parts[2].strip()

        return self.tool_manager.execute_tool(
            "commit_and_push_changes",
            {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "commit_message": commit_message,
            },
        )

    def _create_improvement_pr(self, params: str) -> str:
        """Create improvement PR. Format: repo_owner:repo_name:title:description:files_changed"""
        parts = params.split(":", 4)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:title:description format (files_changed is optional)"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        title = parts[2].strip()
        description = parts[3].strip()
        files_changed = parts[4].strip() if len(parts) > 4 else None

        return self.tool_manager.execute_tool(
            "create_improvement_pr",
            {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "title": title,
                "description": description,
                "files_changed": files_changed,
            },
        )

    def _create_feature_pr(self, params: str) -> str:
        """Create feature PR. Format: repo_owner:repo_name:feature_name:description:implementation_notes:files_modified"""
        parts = params.split(":", 5)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:feature_name:description format"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        feature_name = parts[2].strip()
        description = parts[3].strip()
        implementation_notes = parts[4].strip() if len(parts) > 4 else ""
        files_modified = parts[5].strip() if len(parts) > 5 else None

        return self.tool_manager.execute_tool(
            "create_feature_pr",
            {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "feature_name": feature_name,
                "description": description,
                "implementation_notes": implementation_notes,
                "files_modified": files_modified,
            },
        )

    def _create_bugfix_pr(self, params: str) -> str:
        """Create bug fix PR. Format: repo_owner:repo_name:bug_description:fix_description:files_fixed"""
        parts = params.split(":", 4)
        if len(parts) < 4:
            return "Error: Need repo_owner:repo_name:bug_description:fix_description format"

        repo_owner = parts[0].strip()
        repo_name = parts[1].strip()
        bug_description = parts[2].strip()
        fix_description = parts[3].strip()
        files_fixed = parts[4].strip() if len(parts) > 4 else None

        return self.tool_manager.execute_tool(
            "create_bugfix_pr",
            {
                "repo_owner": repo_owner,
                "repo_name": repo_name,
                "bug_description": bug_description,
                "fix_description": fix_description,
                "files_fixed": files_fixed,
            },
        )
