"""OpenCode/TUI action-to-tool mapping helpers.

This module is intentionally free of :class:`penguin.core.PenguinCore` state.
PenguinCore keeps private compatibility shims that delegate here.
"""

from __future__ import annotations

import json
import re
from typing import Any, Callable

from penguin.utils.parser import (
    parse_apply_patch_payload as default_parse_apply_patch_payload,
    parse_edit_file_payload as default_parse_edit_file_payload,
    parse_patch_file_payload as default_parse_patch_file_payload,
    parse_patch_files_payload as default_parse_patch_files_payload,
    parse_read_file_payload as default_parse_read_file_payload,
    parse_write_file_payload as default_parse_write_file_payload,
)

PayloadParser = Callable[[Any], dict[str, Any]]

__all__ = [
    "build_spawn_subagent_task_card",
    "build_task_card_summary",
    "ensure_unified_diff",
    "extract_result_file_paths",
    "extract_todos_from_result",
    "extract_tool_file_path",
    "extract_unified_diff_from_result",
    "humanize_subagent_name",
    "map_action_result_metadata",
    "map_action_to_tool",
    "normalize_todo_items",
    "parse_action_payload",
    "strip_diff_fences",
    "summarize_subagent_description",
    "summary_status",
]


def strip_diff_fences(diff_content: str) -> str:
    if not diff_content:
        return diff_content
    stripped = diff_content.strip()
    if not stripped.startswith("```"):
        return diff_content
    lines = stripped.splitlines()
    if len(lines) < 2:
        return diff_content
    if not lines[-1].startswith("```"):
        return diff_content
    return "\n".join(lines[1:-1])


def ensure_unified_diff(file_path: str, diff_content: str) -> str:
    if not diff_content:
        return diff_content
    cleaned = strip_diff_fences(diff_content)
    stripped = cleaned.lstrip()
    if stripped.startswith("--- ") or stripped.startswith("*** "):
        return cleaned
    rel = (file_path or "").lstrip("./")
    if not rel:
        return cleaned
    header = f"--- a/{rel}\n+++ b/{rel}\n"
    body = cleaned.lstrip("\n")
    return f"{header}{body}"


def extract_unified_diff_from_result(result: Any) -> str:
    if result is None:
        return ""
    text = str(result)
    if not text:
        return ""

    lines = text.strip().splitlines()
    start_index = -1
    for index, line in enumerate(lines):
        if line.startswith("--- "):
            start_index = index
            break
    if start_index < 0:
        return ""

    diff_lines = lines[start_index:]
    if not any(line.startswith("+++ ") for line in diff_lines):
        return ""
    return "\n".join(diff_lines).strip()


def extract_tool_file_path(tool_input: Any) -> str:
    if not isinstance(tool_input, dict):
        return ""
    for key in ("filePath", "file_path", "path", "file", "target"):
        value = tool_input.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def normalize_todo_items(value: Any) -> list[dict[str, str]]:
    if isinstance(value, dict):
        value = value.get("todos")
    if not isinstance(value, list):
        return []

    statuses = {"pending", "in_progress", "completed", "cancelled"}
    priorities = {"high", "medium", "low"}
    normalized: list[dict[str, str]] = []
    seen_ids: set[str] = set()
    for index, item in enumerate(value):
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
        todo_id = (
            todo_id_raw.strip()
            if isinstance(todo_id_raw, str) and todo_id_raw.strip()
            else f"todo_{index + 1}"
        )
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


def extract_todos_from_result(result: Any) -> list[dict[str, str]]:
    if isinstance(result, list):
        return normalize_todo_items(result)
    if isinstance(result, dict):
        return normalize_todo_items(result)
    if result is None:
        return []

    text = str(result).strip()
    if not text:
        return []
    try:
        parsed = json.loads(text)
    except Exception:
        return []
    return normalize_todo_items(parsed)


def parse_action_payload(params: Any) -> dict[str, Any]:
    if isinstance(params, dict):
        return dict(params)
    if not isinstance(params, str):
        return {}
    text = params.strip()
    if not text.startswith("{"):
        return {}
    try:
        parsed = json.loads(text)
    except Exception:
        return {}
    if isinstance(parsed, dict):
        return parsed
    return {}


def extract_result_file_paths(result: Any) -> list[str]:
    payload = parse_action_payload(result)
    if not payload:
        return []

    files: list[str] = []
    single_file = payload.get("file")
    if isinstance(single_file, str) and single_file.strip():
        files.append(single_file.strip())

    for key in ("files", "created", "files_edited"):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        files.extend(
            str(item).strip()
            for item in value
            if isinstance(item, str) and item.strip()
        )

    deduped: list[str] = []
    seen: set[str] = set()
    for path in files:
        if path in seen:
            continue
        seen.add(path)
        deduped.append(path)
    return deduped


def humanize_subagent_name(value: Any) -> str:
    text = str(value or "subagent").strip() or "subagent"
    return text.replace("_", " ").replace("-", " ")


def summarize_subagent_description(value: Any, fallback: str) -> str:
    text = " ".join(str(value or "").split()).strip()
    if not text:
        return fallback
    if len(text) <= 120:
        return text
    return text[:117].rstrip() + "..."


def build_task_card_summary(
    label: str,
    status: str,
    *,
    item_id: str | None = None,
    title: str | None = None,
) -> list[dict[str, Any]]:
    state: dict[str, Any] = {"status": status}
    if isinstance(title, str) and title.strip():
        state["title"] = title.strip()
    return [
        {
            "id": item_id or f"task_{label.lower().replace(' ', '_')}",
            "tool": label,
            "state": state,
        }
    ]


def summary_status(metadata: dict[str, Any], default: str) -> str:
    summary = metadata.get("summary")
    if not isinstance(summary, list) or not summary:
        return default
    first = summary[0]
    if not isinstance(first, dict):
        return default
    state = first.get("state")
    if not isinstance(state, dict):
        return default
    value = state.get("status")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def build_spawn_subagent_task_card(
    params: Any,
) -> tuple[dict[str, Any], dict[str, Any]]:
    payload = parse_action_payload(params)
    share_session = bool(payload.get("share_session", False))
    if share_session:
        if isinstance(params, dict):
            return dict(params), {}
        return {"params": params}, {}

    raw_agent = payload.get("persona") or payload.get("id") or "subagent"
    subagent_type = humanize_subagent_name(raw_agent)
    description = summarize_subagent_description(
        payload.get("description") or payload.get("initial_prompt"),
        f"Subagent session for {subagent_type}",
    )
    tool_input = {
        "description": description,
        "prompt": payload.get("initial_prompt") or "",
        "subagent_type": subagent_type,
    }
    metadata = {
        "summary": build_task_card_summary(
            "subagent",
            "running",
            item_id=str(payload.get("id") or "subagent"),
        )
    }
    return tool_input, metadata


def map_action_to_tool(
    action: str,
    params: Any,
    *,
    parse_apply_patch: PayloadParser = default_parse_apply_patch_payload,
    parse_edit_file: PayloadParser = default_parse_edit_file_payload,
    parse_patch_file: PayloadParser = default_parse_patch_file_payload,
    parse_patch_files: PayloadParser = default_parse_patch_files_payload,
    parse_read_file: PayloadParser = default_parse_read_file_payload,
    parse_write_file: PayloadParser = default_parse_write_file_payload,
) -> tuple[str, dict[str, Any], dict[str, Any]]:
    action_name = (action or "").strip().lower()
    tool_input: dict[str, Any] = {}
    metadata: dict[str, Any] = {}
    raw = params if isinstance(params, str) else ""
    if isinstance(params, dict):
        raw = params.get("code") or params.get("command") or params.get("params") or ""

    if action_name in {"execute", "code_execution"}:
        tool_input = {"command": raw, "description": "IPython"}
        return "bash", tool_input, metadata

    if action_name == "execute_command":
        tool_input = {"command": raw, "description": "Shell"}
        return "bash", tool_input, metadata

    if action_name == "todowrite":
        todos = normalize_todo_items(params)
        if not todos and isinstance(params, str):
            try:
                parsed = json.loads(params)
                todos = normalize_todo_items(parsed)
            except Exception:
                todos = []
        tool_input = {"todos": todos}
        return "todowrite", tool_input, metadata

    if action_name == "todoread":
        return "todoread", {}, metadata

    if action_name == "question":
        questions: list[dict[str, Any]] = []
        if isinstance(params, dict):
            raw_questions = params.get("questions")
            if isinstance(raw_questions, list):
                questions = [item for item in raw_questions if isinstance(item, dict)]
        elif isinstance(raw, str) and raw.strip():
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, dict):
                    raw_questions = parsed.get("questions")
                    if isinstance(raw_questions, list):
                        questions = [
                            item for item in raw_questions if isinstance(item, dict)
                        ]
                elif isinstance(parsed, list):
                    questions = [item for item in parsed if isinstance(item, dict)]
            except Exception:
                questions = []
        tool_input = {"questions": questions}
        return "question", tool_input, metadata

    if action_name == "spawn_sub_agent":
        tool_input, metadata = build_spawn_subagent_task_card(params)
        if metadata:
            return "task", tool_input, metadata
        return action_name, tool_input, metadata

    if action_name == "apply_diff":
        if isinstance(params, dict):
            file_path = params.get("file_path") or params.get("path") or ""
            diff_content = params.get("diff_content") or params.get("diff") or ""
        else:
            first_sep = raw.find(":")
            if first_sep != -1:
                file_path = raw[:first_sep].strip()
                remainder = raw[first_sep + 1 :]
            else:
                file_path = ""
                remainder = raw
            diff_content = remainder
            if ":" in remainder:
                diff_part, flag = remainder.rsplit(":", 1)
                flag_stripped = flag.strip().lower()
                if (
                    flag_stripped in {"true", "false"}
                    and "\n" not in flag
                    and "\r" not in flag
                ):
                    diff_content = diff_part
        tool_input = {"filePath": file_path}
        metadata["diff"] = ensure_unified_diff(file_path, diff_content)
        return "edit", tool_input, metadata

    if action_name == "edit_file":
        parsed = parse_edit_file(params)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            return "edit", {"filePath": ""}, metadata
        tool_input = {
            "filePath": parsed.get("path", ""),
            "oldString": parsed.get("old_string", ""),
            "newString": parsed.get("new_string", ""),
            "replaceAll": bool(parsed.get("replace_all", False)),
        }
        return "edit", tool_input, metadata

    if action_name == "apply_patch":
        parsed = parse_apply_patch(params)
        patch = parsed.get("patch", "") if isinstance(parsed, dict) else ""
        files = []
        if isinstance(patch, str):
            for line in patch.splitlines():
                match = re.match(
                    r"^\*\*\* (?:Add|Update|Delete) File:\s+(.+?)\s*$",
                    line,
                )
                if match:
                    files.append(match.group(1).strip())
            if files:
                metadata["files"] = files
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            if isinstance(patch, str) and patch.strip():
                metadata["diff"] = patch
            return "edit", {"filePath": "(patch)"}, metadata
        tool_input = {"filePath": "(patch)", "patch": patch}
        return "edit", tool_input, metadata

    if action_name == "patch_file":
        parsed = parse_patch_file(params)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            return "edit", {"filePath": ""}, metadata
        tool_input = {"filePath": parsed.get("path", "")}
        operation = parsed.get("operation") if isinstance(parsed, dict) else None
        if isinstance(operation, dict):
            operation_type = operation.get("type")
            if operation_type == "unified_diff":
                diff_content = operation.get("diff_content") or ""
                metadata["diff"] = ensure_unified_diff(
                    tool_input.get("filePath", ""),
                    str(diff_content),
                )
            elif operation_type == "replace_lines":
                if isinstance(operation.get("start_line"), int):
                    tool_input["startLine"] = operation["start_line"]
                if isinstance(operation.get("end_line"), int):
                    tool_input["endLine"] = operation["end_line"]
                if isinstance(operation.get("new_content"), str):
                    tool_input["newContent"] = operation["new_content"]
            elif operation_type == "insert_lines":
                if isinstance(operation.get("after_line"), int):
                    tool_input["afterLine"] = operation["after_line"]
                if isinstance(operation.get("new_content"), str):
                    tool_input["newContent"] = operation["new_content"]
            elif operation_type == "delete_lines":
                if isinstance(operation.get("start_line"), int):
                    tool_input["startLine"] = operation["start_line"]
                if isinstance(operation.get("end_line"), int):
                    tool_input["endLine"] = operation["end_line"]
            elif operation_type == "regex_replace":
                tool_input["pattern"] = operation.get("search_pattern")
                tool_input["replacement"] = operation.get("replacement")
        return "edit", tool_input, metadata

    if action_name == "replace_lines":
        if isinstance(params, dict):
            path = params.get("path") or params.get("file_path") or ""
            start_line = params.get("start_line")
            end_line = params.get("end_line")
            tool_input = {"filePath": path}
            if isinstance(start_line, int):
                tool_input["startLine"] = start_line
            if isinstance(end_line, int):
                tool_input["endLine"] = end_line
            if isinstance(params.get("new_content"), str):
                tool_input["newContent"] = params.get("new_content")
        else:
            parts = raw.split(":", 3)
            if len(parts) >= 4:
                path = parts[0].strip()
                try:
                    start_line = int(parts[1].strip())
                    end_line = int(parts[2].strip())
                    content = parts[3]
                    verify = True
                    if ":" in content:
                        content_part, flag = content.rsplit(":", 1)
                        flag_stripped = flag.strip().lower()
                        if (
                            flag_stripped in {"true", "false"}
                            and "\n" not in flag
                            and "\r" not in flag
                        ):
                            verify = flag_stripped == "true"
                            content = content_part
                    tool_input = {
                        "filePath": path,
                        "startLine": start_line,
                        "endLine": end_line,
                        "newContent": content,
                        "verify": verify,
                    }
                except ValueError:
                    tool_input = {"filePath": path}
        return "edit", tool_input, metadata

    if action_name == "insert_lines":
        if isinstance(params, dict):
            tool_input = {
                "filePath": params.get("path") or params.get("file_path") or "",
                "newContent": params.get("new_content") or "",
            }
            after_line = params.get("after_line")
            if isinstance(after_line, int):
                tool_input["afterLine"] = after_line
        else:
            parts = raw.split(":", 2)
            if len(parts) >= 3:
                tool_input = {
                    "filePath": parts[0].strip(),
                    "newContent": parts[2],
                }
                try:
                    tool_input["afterLine"] = int(parts[1].strip())
                except ValueError:
                    pass
        return "edit", tool_input, metadata

    if action_name == "delete_lines":
        if isinstance(params, dict):
            tool_input = {
                "filePath": params.get("path") or params.get("file_path") or "",
            }
            start_line = params.get("start_line")
            end_line = params.get("end_line")
            if isinstance(start_line, int):
                tool_input["startLine"] = start_line
            if isinstance(end_line, int):
                tool_input["endLine"] = end_line
        else:
            parts = raw.split(":", 2)
            if len(parts) >= 3:
                tool_input = {
                    "filePath": parts[0].strip(),
                }
                try:
                    tool_input["startLine"] = int(parts[1].strip())
                    tool_input["endLine"] = int(parts[2].strip())
                except ValueError:
                    pass
        return "edit", tool_input, metadata

    if action_name == "edit_with_pattern":
        if isinstance(params, dict):
            tool_input = {
                "filePath": params.get("file_path") or params.get("path") or "",
                "pattern": params.get("search_pattern") or params.get("pattern"),
                "replacement": params.get("replacement"),
            }
            if isinstance(params.get("backup"), bool):
                tool_input["backup"] = params.get("backup")
        else:
            content = raw
            backup: bool | None = None
            parts = raw.rsplit(":", 1)
            if len(parts) == 2 and parts[1].strip().lower() in ("true", "false"):
                content = parts[0]
                backup = parts[1].strip().lower() == "true"
            fields = content.split(":", 2)
            if len(fields) >= 3:
                tool_input = {
                    "filePath": fields[0].strip(),
                    "pattern": fields[1],
                    "replacement": fields[2],
                }
                if backup is not None:
                    tool_input["backup"] = backup
        return "edit", tool_input, metadata

    if action_name == "enhanced_write":
        if isinstance(params, dict):
            tool_input = {
                "filePath": params.get("path") or params.get("file_path") or "",
                "content": params.get("content") or "",
            }
            if isinstance(params.get("backup"), bool):
                tool_input["backup"] = params.get("backup")
        else:
            first_sep = raw.find(":")
            if first_sep != -1:
                file_path = raw[:first_sep].strip()
                remainder = raw[first_sep + 1 :]
                backup = True
                content = remainder
                if ":" in remainder:
                    content_part, flag = remainder.rsplit(":", 1)
                    flag_stripped = flag.strip().lower()
                    if (
                        flag_stripped in {"true", "false"}
                        and "\n" not in flag
                        and "\r" not in flag
                    ):
                        backup = flag_stripped == "true"
                        content = content_part
                tool_input = {
                    "filePath": file_path,
                    "content": content,
                    "backup": backup,
                }
        return "write", tool_input, metadata

    if action_name == "write_file":
        parsed = parse_write_file(params)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            return "write", {"filePath": ""}, metadata
        tool_input = {
            "filePath": parsed.get("path") or "",
            "content": parsed.get("content") or "",
            "backup": parsed.get("backup", True),
        }
        return "write", tool_input, metadata

    if action_name == "multiedit":
        apply_flag: bool | None = None
        content = raw
        if isinstance(params, dict):
            content = str(params.get("content") or "")
            if isinstance(params.get("apply"), bool):
                apply_flag = params.get("apply")
        else:
            first_line = content.split("\n", 1)[0].strip().lower()
            if first_line.startswith("apply=") or first_line.startswith("apply:"):
                maybe_value = first_line.split("=", 1)[-1].split(":", 1)[-1].strip()
                if maybe_value in {"true", "false"}:
                    apply_flag = maybe_value == "true"
        tool_input = {
            "filePath": "(multiple files)",
            "content": content,
        }
        if apply_flag is not None:
            tool_input["apply"] = apply_flag
        return "edit", tool_input, metadata

    if action_name == "patch_files":
        parsed = parse_patch_files(params)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            return "edit", {"filePath": "(multiple files)"}, metadata
        tool_input = {"filePath": "(multiple files)"}
        if isinstance(parsed.get("operations"), list):
            files = []
            for item in parsed["operations"]:
                if not isinstance(item, dict):
                    continue
                path = item.get("path")
                if isinstance(path, str) and path.strip():
                    files.append(path.strip())
            if files:
                metadata["files"] = files
        if isinstance(parsed.get("content"), str):
            tool_input["content"] = parsed["content"]
        if isinstance(parsed.get("apply"), bool):
            tool_input["apply"] = parsed["apply"]
        return "edit", tool_input, metadata

    if action_name == "enhanced_diff":
        if isinstance(params, dict):
            tool_input = {
                "filePath": params.get("file1") or params.get("path1") or "",
                "comparePath": params.get("file2") or params.get("path2") or "",
            }
            if isinstance(params.get("semantic"), bool):
                tool_input["semantic"] = params.get("semantic")
        else:
            parts = raw.split(":", 2)
            tool_input = {
                "filePath": parts[0].strip() if len(parts) > 0 else "",
                "comparePath": parts[1].strip() if len(parts) > 1 else "",
            }
            if len(parts) > 2 and parts[2].strip().lower() in {"true", "false"}:
                tool_input["semantic"] = parts[2].strip().lower() == "true"
        return "read", tool_input, metadata

    if action_name == "workspace_search":
        if isinstance(params, dict):
            tool_input = {
                "pattern": params.get("query") or params.get("pattern") or "",
                "path": params.get("path") or ".",
            }
        else:
            parts = raw.split(":", 1)
            tool_input = {
                "pattern": parts[0].strip() if len(parts) > 0 else "",
                "path": ".",
            }
        return "grep", tool_input, metadata

    if action_name in {"enhanced_read", "read_file"}:
        parsed = parse_read_file(params)
        error = parsed.get("error") if isinstance(parsed, dict) else None
        if isinstance(error, str):
            return "read", {"filePath": ""}, metadata
        tool_input = {"filePath": parsed.get("path", "")}
        if parsed.get("max_lines") is not None:
            tool_input["limit"] = parsed.get("max_lines")
        return "read", tool_input, metadata

    if action_name == "list_files_filtered":
        if isinstance(params, dict):
            tool_input = {"path": params.get("path") or params.get("directory") or "."}
        else:
            parts = raw.split(":")
            path = parts[0].strip() if parts and parts[0].strip() else "."
            tool_input = {"path": path}
        return "list", tool_input, metadata

    if action_name == "find_files_enhanced":
        if isinstance(params, dict):
            tool_input = {
                "pattern": params.get("pattern") or params.get("filename") or "",
                "path": params.get("search_path") or params.get("path") or ".",
            }
        else:
            parts = raw.split(":")
            pattern = parts[0].strip() if parts and parts[0].strip() else ""
            search_path = (
                parts[1].strip() if len(parts) > 1 and parts[1].strip() else "."
            )
            tool_input = {"pattern": pattern, "path": search_path}
        return "glob", tool_input, metadata

    if action_name == "search":
        if isinstance(params, dict):
            tool_input = {"pattern": params.get("pattern") or params.get("query") or ""}
        else:
            tool_input = {"pattern": raw}
        return "grep", tool_input, metadata

    if isinstance(params, dict):
        tool_input = params
    else:
        tool_input = {"params": params}
    return action_name or "unknown", tool_input, metadata


def map_action_result_metadata(
    action: str,
    result: Any,
    existing: dict[str, Any] | None = None,
    tool_input: dict[str, Any] | None = None,
    status: str | None = None,
    event_metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    metadata = dict(existing or {})
    if isinstance(event_metadata, dict):
        metadata.update(event_metadata)
    action_name = (action or "").strip().lower()
    edit_actions = {
        "edit",
        "edit_file",
        "apply_patch",
        "patch_file",
        "patch_files",
        "apply_diff",
        "replace_lines",
        "edit_with_pattern",
        "write_file",
        "enhanced_write",
        "insert_lines",
        "delete_lines",
        "multiedit",
    }
    if status == "error" and action_name in edit_actions:
        raw_diff = metadata.pop("diff", None)
        if isinstance(raw_diff, str) and raw_diff.strip():
            metadata["attemptedDiff"] = raw_diff

    if action_name in {"execute", "execute_command", "code_execution"}:
        metadata.setdefault("output", "" if result is None else str(result))
    if status != "error" and action_name in {"todowrite", "todoread"}:
        todos = extract_todos_from_result(result)
        if todos:
            metadata["todos"] = todos
    if status != "error" and action_name in edit_actions:
        file_path = extract_tool_file_path(tool_input)
        if file_path:
            metadata.setdefault("filePath", file_path)
        diff_text = extract_unified_diff_from_result(result)
        if diff_text:
            metadata["diff"] = ensure_unified_diff(file_path, diff_text)
        result_files = extract_result_file_paths(result)
        if result_files:
            metadata["files"] = result_files
            if len(result_files) == 1:
                metadata.setdefault("filePath", result_files[0])
    if action_name == "spawn_sub_agent":
        payload = parse_action_payload(result)
        if isinstance(payload.get("session_id"), str) and payload["session_id"].strip():
            metadata.setdefault("sessionId", payload["session_id"].strip())
        if (
            isinstance(payload.get("session_title"), str)
            and payload["session_title"].strip()
        ):
            metadata.setdefault("title", payload["session_title"].strip())
        label = "subagent"
        item_id = None
        if isinstance(metadata.get("sessionId"), str) and metadata["sessionId"].strip():
            item_id = metadata["sessionId"].strip()
        title = (
            metadata.get("title") if isinstance(metadata.get("title"), str) else None
        )
        summary_value = (
            "error"
            if status == "error"
            else summary_status(
                metadata,
                "completed",
            )
        )
        if status != "error":
            summary_value = "completed"
        metadata["summary"] = build_task_card_summary(
            label,
            summary_value,
            item_id=item_id,
            title=title if status != "error" else "Subagent session failed",
        )
    return metadata
