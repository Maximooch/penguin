"""MCP resources and prompts for Penguin's MCP server."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional
import json

from penguin.web.services.project_payloads import (
    serialize_project_payload,
    serialize_task_payload,
)
from penguin.web.services.session_view import get_session_info, get_session_messages


_TEXT_MIME = "text/plain"
_JSON_MIME = "application/json"


def register_penguin_resources_and_prompts(mcp: Any, server: Any) -> None:
    """Register conservative MCP resources and prompts on a FastMCP instance."""
    core = getattr(server, "core", None)
    _register_resources(mcp, core)
    _register_prompts(mcp)


def _register_resources(mcp: Any, core: Any) -> None:
    @mcp.resource(
        "penguin://projects",
        name="penguin_projects",
        title="Penguin Projects",
        description="List Penguin projects visible to this MCP server.",
        mime_type=_JSON_MIME,
    )
    def projects_resource() -> str:
        project_manager = getattr(core, "project_manager", None)
        if project_manager is None:
            return _json({"projects": [], "count": 0, "error": "project_manager_unavailable"})
        projects = [serialize_project_payload(project) for project in project_manager.list_projects()]
        return _json({"projects": projects, "count": len(projects)})

    @mcp.resource(
        "penguin://project/{project_id}",
        name="penguin_project",
        title="Penguin Project",
        description="Return one Penguin project and its current tasks.",
        mime_type=_JSON_MIME,
    )
    def project_resource(project_id: str) -> str:
        project_manager = getattr(core, "project_manager", None)
        if project_manager is None:
            return _json({"error": "project_manager_unavailable"})
        project = project_manager.get_project(project_id)
        if project is None:
            return _json({"error": "project_not_found", "project_id": project_id})
        tasks = [serialize_task_payload(task) for task in project_manager.list_tasks(project_id=project.id)]
        return _json({"project": serialize_project_payload(project), "tasks": tasks})

    @mcp.resource(
        "penguin://task/{task_id}",
        name="penguin_task",
        title="Penguin Task",
        description="Return one Penguin task with lifecycle/dependency/artifact truth.",
        mime_type=_JSON_MIME,
    )
    def task_resource(task_id: str) -> str:
        project_manager = getattr(core, "project_manager", None)
        if project_manager is None:
            return _json({"error": "project_manager_unavailable"})
        task = project_manager.get_task(task_id)
        if task is None:
            return _json({"error": "task_not_found", "task_id": task_id})
        return _json({"task": serialize_task_payload(task)})

    @mcp.resource(
        "penguin://session/{session_id}/summary",
        name="penguin_session_summary_resource",
        title="Penguin Session Summary",
        description="Return compact read-only session context suitable for handoff.",
        mime_type=_JSON_MIME,
    )
    def session_summary_resource(session_id: str) -> str:
        info = get_session_info(core, session_id) if core is not None else None
        if info is None:
            return _json({"error": "session_not_found", "session_id": session_id})
        messages = get_session_messages(core, session_id, limit=20) or []
        return _json(
            {
                "session": info,
                "message_count_returned": len(messages),
                "messages_preview": [_preview_message(row) for row in messages],
            }
        )

    @mcp.resource(
        "penguin://docs-cache/{source}/{page}",
        name="penguin_docs_cache_page",
        title="Penguin Docs Cache Page",
        description="Read one markdown/json file from context/docs_cache by source/page.",
        mime_type=_TEXT_MIME,
    )
    def docs_cache_resource(source: str, page: str) -> str:
        workspace = _workspace_path(core)
        root = (workspace / "context" / "docs_cache").resolve()
        safe_source = _safe_segment(source)
        safe_page = _safe_segment(page)
        candidates = [
            root / safe_source / safe_page,
            root / safe_source / f"{safe_page}.md",
            root / safe_source / f"{safe_page}.json",
        ]
        for candidate in candidates:
            resolved = candidate.resolve()
            if not _is_relative_to(resolved, root) or not resolved.is_file():
                continue
            return resolved.read_text(encoding="utf-8")
        return f"Docs cache page not found: {source}/{page}"


def _register_prompts(mcp: Any) -> None:
    @mcp.prompt(
        name="penguin_task_brief",
        title="Penguin Task Brief",
        description="Create a concise Penguin task brief for PM/Blueprint work.",
    )
    def task_brief(title: str, goal: str, constraints: Optional[str] = None) -> str:
        constraint_text = constraints or "None provided."
        return (
            "Create or update a Penguin project task with the following brief.\n\n"
            f"Title: {title}\n"
            f"Goal: {goal}\n"
            f"Constraints: {constraint_text}\n\n"
            "Include acceptance criteria, dependencies, and evidence expectations."
        )

    @mcp.prompt(
        name="penguin_blueprint_outline",
        title="Penguin Blueprint Outline",
        description="Draft a dependency-aware Penguin Blueprint outline.",
    )
    def blueprint_outline(objective: str, scope: Optional[str] = None) -> str:
        scope_text = scope or "Use the current project/repository context."
        return (
            "Draft a Penguin Blueprint for the objective below.\n\n"
            f"Objective: {objective}\n"
            f"Scope: {scope_text}\n\n"
            "Return YAML with task IDs, dependencies, acceptance criteria, and ITUV expectations."
        )

    @mcp.prompt(
        name="penguin_runmode_handoff",
        title="Penguin RunMode Handoff",
        description="Prepare a safe handoff for starting Penguin RunMode later.",
    )
    def runmode_handoff(project_id: str, task_id: Optional[str] = None) -> str:
        target = f"task {task_id}" if task_id else f"project {project_id}"
        return (
            f"Prepare a RunMode handoff for Penguin {target}.\n\n"
            "Summarize readiness, dependencies, risks, required clarifications, and expected artifacts. "
            "Do not start execution unless runtime tools are explicitly enabled."
        )


def _preview_message(row: dict[str, Any]) -> dict[str, Any]:
    info = row.get("info") if isinstance(row, dict) else {}
    info = info if isinstance(info, dict) else {}
    parts = row.get("parts") if isinstance(row, dict) else []
    chunks: list[str] = []
    if isinstance(parts, list):
        for part in parts:
            if isinstance(part, dict) and part.get("type") == "text":
                text = part.get("text")
                if isinstance(text, str) and text.strip():
                    chunks.append(" ".join(text.split()))
    text = "\n".join(chunks)
    return {
        "id": info.get("id"),
        "role": info.get("role"),
        "text_preview": text[:500],
    }


def _json(payload: dict[str, Any]) -> str:
    return json.dumps(payload, indent=2, default=str)


def _workspace_path(core: Any) -> Path:
    config = getattr(core, "config", None)
    workspace = getattr(config, "workspace_path", None)
    if workspace is None:
        conversation_manager = getattr(core, "conversation_manager", None)
        workspace = getattr(conversation_manager, "workspace_path", None)
    return Path(workspace or Path.cwd()).expanduser().resolve()


def _safe_segment(value: str) -> str:
    return "".join(ch for ch in str(value) if ch.isalnum() or ch in {"-", "_", "."}).strip(".")


def _is_relative_to(path: Path, parent: Path) -> bool:
    try:
        path.relative_to(parent)
        return True
    except ValueError:
        return False


__all__ = ["register_penguin_resources_and_prompts"]
