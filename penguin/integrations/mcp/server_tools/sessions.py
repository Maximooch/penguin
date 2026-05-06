"""Session, artifact, and checkpoint read tools for Penguin's MCP server."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.web.services.session_view import (
    get_session_info,
    get_session_messages,
    list_session_infos,
)


_TEXT_PREVIEW_LIMIT = 500
_DEFAULT_MESSAGE_LIMIT = 20
_DEFAULT_LIST_LIMIT = 50


def build_session_tools(core: Any) -> List[MCPServerTool]:
    """Build default-on session/context/evidence read tools."""
    if core is None:
        return []

    def list_sessions(arguments: Dict[str, Any]) -> Dict[str, Any]:
        limit = _positive_int(arguments.get("limit"), default=_DEFAULT_LIST_LIMIT)
        sessions = list_session_infos(
            core,
            limit=limit,
            search=_optional_str(arguments.get("search")),
            directory=_optional_str(arguments.get("directory")),
            roots=bool(arguments.get("roots", False)),
        )
        return {"sessions": sessions, "count": len(sessions)}

    def session_summary(arguments: Dict[str, Any]) -> Dict[str, Any]:
        session_id = _optional_str(arguments.get("session_id"))
        if not session_id:
            return {"error": "missing_session_id", "message": "session_id is required."}

        info = get_session_info(core, session_id)
        if info is None:
            return {
                "error": "session_not_found",
                "session_id": session_id,
                "message": "No Penguin session exists with this ID.",
            }

        message_limit = _positive_int(
            arguments.get("message_limit"),
            default=_DEFAULT_MESSAGE_LIMIT,
        )
        messages = get_session_messages(core, session_id, limit=message_limit) or []
        preview = [_message_preview(row) for row in messages]
        return {
            "session": info,
            "message_count_returned": len(preview),
            "message_limit": message_limit,
            "messages_preview": preview,
            "summary": _compact_session_summary(info, preview),
        }

    def artifacts_list(arguments: Dict[str, Any]) -> Dict[str, Any]:
        project_manager = getattr(core, "project_manager", None)
        if project_manager is None:
            return {
                "error": "project_manager_unavailable",
                "message": "Project manager is not available.",
            }

        task_id = _optional_str(arguments.get("task_id"))
        project_id = _optional_str(arguments.get("project_id"))
        artifact_key = _optional_str(arguments.get("artifact_key"))
        valid_only = bool(arguments.get("valid_only", False))
        limit = _positive_int(arguments.get("limit"), default=_DEFAULT_LIST_LIMIT)

        if task_id:
            task = project_manager.get_task(task_id)
            tasks = [task] if task is not None else []
        else:
            tasks = project_manager.list_tasks(project_id=project_id)

        artifacts: List[Dict[str, Any]] = []
        for task in tasks:
            if task is None:
                continue
            for artifact in getattr(task, "artifact_evidence", []) or []:
                payload = _artifact_to_dict(artifact)
                payload_key = payload.get("artifact_key") or payload.get("key")
                if artifact_key and payload_key != artifact_key:
                    continue
                if valid_only and not bool(payload.get("valid")):
                    continue
                if "artifact_key" not in payload and payload_key is not None:
                    payload["artifact_key"] = payload_key
                payload["task_id"] = getattr(task, "id", None)
                payload["task_title"] = getattr(task, "title", None)
                payload["project_id"] = getattr(task, "project_id", None)
                artifacts.append(payload)
                if len(artifacts) >= limit:
                    return {"artifacts": artifacts, "count": len(artifacts)}

        return {"artifacts": artifacts, "count": len(artifacts)}

    def checkpoints_list(arguments: Dict[str, Any]) -> Dict[str, Any]:
        session_id = _optional_str(arguments.get("session_id"))
        checkpoint_type = _optional_str(arguments.get("checkpoint_type"))
        limit = _positive_int(arguments.get("limit"), default=_DEFAULT_LIST_LIMIT)

        if not hasattr(core, "list_checkpoints"):
            return {
                "error": "checkpoints_unavailable",
                "message": "Checkpoint listing is not available on this core.",
            }

        checkpoints = core.list_checkpoints(session_id=session_id, limit=limit)
        if checkpoint_type:
            checkpoints = [
                item for item in checkpoints if str(item.get("type")) == checkpoint_type
            ]
        stats = core.get_checkpoint_stats() if hasattr(core, "get_checkpoint_stats") else {}
        return {
            "checkpoints": checkpoints,
            "count": len(checkpoints),
            "stats": stats,
        }

    return [
        MCPServerTool(
            name="penguin_session_list",
            description="List Penguin sessions in a compact OpenCode-compatible shape.",
            input_schema={
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "Maximum sessions to return. Defaults to 50.",
                    },
                    "search": {
                        "type": "string",
                        "description": "Optional case-insensitive title search.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional directory filter.",
                    },
                    "roots": {
                        "type": "boolean",
                        "description": "When true, only return root sessions.",
                    },
                },
                "required": [],
            },
            handler=list_sessions,
        ),
        MCPServerTool(
            name="penguin_session_summary",
            description=(
                "Return one Penguin session with compact recent message previews. "
                "This is read-only and does not call a model."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {"type": "string", "description": "Session ID."},
                    "message_limit": {
                        "type": "integer",
                        "description": "Recent messages to include. Defaults to 20.",
                    },
                },
                "required": ["session_id"],
            },
            handler=session_summary,
        ),
        MCPServerTool(
            name="penguin_artifacts_list",
            description="List task artifact evidence from Penguin project storage.",
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID filter.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Optional task ID filter.",
                    },
                    "artifact_key": {
                        "type": "string",
                        "description": "Optional artifact key filter.",
                    },
                    "valid_only": {
                        "type": "boolean",
                        "description": "Only include valid artifact evidence.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum artifacts to return. Defaults to 50.",
                    },
                },
                "required": [],
            },
            handler=artifacts_list,
        ),
        MCPServerTool(
            name="penguin_checkpoints_list",
            description="List Penguin conversation checkpoints and checkpoint stats.",
            input_schema={
                "type": "object",
                "properties": {
                    "session_id": {
                        "type": "string",
                        "description": "Optional session ID filter.",
                    },
                    "checkpoint_type": {
                        "type": "string",
                        "description": "Optional checkpoint type filter.",
                    },
                    "limit": {
                        "type": "integer",
                        "description": "Maximum checkpoints to return. Defaults to 50.",
                    },
                },
                "required": [],
            },
            handler=checkpoints_list,
        ),
    ]


def _message_preview(row: Dict[str, Any]) -> Dict[str, Any]:
    info = row.get("info") if isinstance(row, dict) else {}
    info = info if isinstance(info, dict) else {}
    role = str(info.get("role") or "unknown")
    message_id = str(info.get("id") or "")
    text = _extract_text(row.get("parts") if isinstance(row, dict) else [])
    return {
        "id": message_id,
        "role": role,
        "text_preview": _truncate(text, _TEXT_PREVIEW_LIMIT),
    }


def _compact_session_summary(
    info: Dict[str, Any],
    preview: List[Dict[str, Any]],
) -> Dict[str, Any]:
    last_user = next(
        (
            item.get("text_preview")
            for item in reversed(preview)
            if item.get("role") == "user" and item.get("text_preview")
        ),
        None,
    )
    return {
        "session_id": info.get("id"),
        "title": info.get("title"),
        "directory": info.get("directory"),
        "updated": (info.get("time") or {}).get("updated")
        if isinstance(info.get("time"), dict)
        else None,
        "last_user_message_preview": last_user,
    }


def _extract_text(parts: Any) -> str:
    if not isinstance(parts, list):
        return ""
    chunks: List[str] = []
    for part in parts:
        if not isinstance(part, dict):
            continue
        if str(part.get("type", "")).lower() != "text":
            continue
        text = part.get("text")
        if isinstance(text, str) and text.strip():
            chunks.append(" ".join(text.split()))
    return "\n".join(chunks)


def _artifact_to_dict(artifact: Any) -> Dict[str, Any]:
    if hasattr(artifact, "to_dict"):
        return artifact.to_dict()
    if isinstance(artifact, dict):
        return dict(artifact)
    return {"raw": str(artifact)}


def _optional_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped or None


def _positive_int(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _truncate(value: str, limit: int) -> str:
    if len(value) <= limit:
        return value
    return value[:limit].rstrip() + "…"


__all__ = ["build_session_tools"]
