"""Project-management MCP server tools for Penguin."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.models import TaskStatus
from penguin.web.services.project_payloads import (
    serialize_project_payload,
    serialize_task_payload,
)


def build_pm_tools(core: Any) -> list[MCPServerTool]:
    """Build default-on PM control-plane tools for a Penguin core-like object."""
    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return []

    def list_projects(arguments: dict[str, Any]) -> dict[str, Any]:
        status = _optional_str(arguments.get("status"))
        include_tasks = bool(arguments.get("include_tasks", False))
        projects = project_manager.list_projects(status=status)
        payloads = []
        for project in projects:
            tasks = (
                project_manager.list_tasks(project_id=project.id)
                if include_tasks
                else None
            )
            payloads.append(serialize_project_payload(project, tasks=tasks))
        return {"projects": payloads}

    def create_project(arguments: dict[str, Any]) -> dict[str, Any]:
        metadata = _metadata(arguments)
        project = project_manager.create_project(
            name=_required_str(arguments, "name"),
            description=_optional_str(arguments.get("description"))
            or f"Project: {_required_str(arguments, 'name')}",
            tags=_optional_str_list(arguments.get("tags")),
            budget_tokens=_optional_int(arguments.get("budget_tokens")),
            budget_minutes=_optional_int(arguments.get("budget_minutes")),
            workspace_path=_optional_path(arguments.get("workspace_path")),
            **metadata,
        )
        changed = False
        for attr in ("priority", "start_date", "due_date"):
            if attr in arguments and arguments[attr] is not None:
                setattr(project, attr, arguments[attr])
                changed = True
        if changed:
            project.updated_at = datetime.now(timezone.utc).isoformat()
            project_manager.storage.update_project(project)
        return {"project": serialize_project_payload(project)}

    def get_project(arguments: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_str(arguments, "project_id")
        project = project_manager.get_project(project_id)
        if project is None:
            return {"error": "project_not_found", "project_id": project_id}
        tasks = (
            project_manager.list_tasks(project_id=project.id)
            if bool(arguments.get("include_tasks", True))
            else None
        )
        return {"project": serialize_project_payload(project, tasks=tasks)}

    def list_tasks(arguments: dict[str, Any]) -> dict[str, Any]:
        status = _parse_status(arguments.get("status"))
        tasks = project_manager.list_tasks(
            project_id=_optional_str(arguments.get("project_id")),
            status=status,
            parent_task_id=_optional_str(arguments.get("parent_task_id")),
        )
        return {"tasks": [serialize_task_payload(task) for task in tasks]}

    def create_task(arguments: dict[str, Any]) -> dict[str, Any]:
        metadata = _metadata(arguments)
        task = project_manager.create_task(
            project_id=_optional_str(arguments.get("project_id")),
            title=_required_str(arguments, "title"),
            description=_optional_str(arguments.get("description"))
            or _required_str(arguments, "title"),
            parent_task_id=_optional_str(arguments.get("parent_task_id")),
            priority=_optional_int(arguments.get("priority"), default=1),
            tags=_optional_str_list(arguments.get("tags")),
            dependencies=_optional_str_list(arguments.get("dependencies")),
            due_date=_optional_str(arguments.get("due_date")),
            budget_tokens=_optional_int(arguments.get("budget_tokens")),
            budget_minutes=_optional_int(arguments.get("budget_minutes")),
            allowed_tools=_optional_str_list(arguments.get("allowed_tools")),
            acceptance_criteria=_optional_str_list(
                arguments.get("acceptance_criteria")
            ),
            **metadata,
        )
        changed = False
        for attr in (
            "definition_of_done",
            "blueprint_id",
            "blueprint_source",
            "recipe",
        ):
            if attr in arguments and arguments[attr] is not None:
                setattr(task, attr, arguments[attr])
                changed = True
        if changed:
            task.updated_at = datetime.now(timezone.utc).isoformat()
            project_manager.storage.update_task(task)
        return {"task": serialize_task_payload(task)}

    def get_task(arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(arguments, "task_id")
        task = project_manager.get_task(task_id)
        if task is None:
            return {"error": "task_not_found", "task_id": task_id}
        return {"task": serialize_task_payload(task)}

    return [
        MCPServerTool(
            name="penguin_pm_list_projects",
            description="List Penguin projects, optionally including their tasks.",
            input_schema=_schema(
                {
                    "status": {"type": "string"},
                    "include_tasks": {"type": "boolean"},
                }
            ),
            handler=list_projects,
        ),
        MCPServerTool(
            name="penguin_pm_create_project",
            description="Create a Penguin project with rich PM metadata.",
            input_schema=_schema(
                {
                    "name": {"type": "string"},
                    "description": {"type": "string"},
                    "workspace_path": {"type": "string"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "priority": {"type": "integer"},
                    "budget_tokens": {"type": "integer"},
                    "budget_minutes": {"type": "integer"},
                    "start_date": {"type": "string"},
                    "due_date": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                required=["name"],
            ),
            handler=create_project,
        ),
        MCPServerTool(
            name="penguin_pm_get_project",
            description="Get one Penguin project by ID, including tasks by default.",
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "include_tasks": {"type": "boolean"},
                },
                required=["project_id"],
            ),
            handler=get_project,
        ),
        MCPServerTool(
            name="penguin_pm_list_tasks",
            description="List Penguin PM tasks by project, status, or parent task.",
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "status": {"type": "string"},
                    "parent_task_id": {"type": "string"},
                }
            ),
            handler=list_tasks,
        ),
        MCPServerTool(
            name="penguin_pm_create_task",
            description="Create a rich Penguin PM task without starting execution.",
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "title": {"type": "string"},
                    "description": {"type": "string"},
                    "parent_task_id": {"type": "string"},
                    "priority": {"type": "integer"},
                    "tags": {"type": "array", "items": {"type": "string"}},
                    "dependencies": {"type": "array", "items": {"type": "string"}},
                    "due_date": {"type": "string"},
                    "budget_tokens": {"type": "integer"},
                    "budget_minutes": {"type": "integer"},
                    "allowed_tools": {"type": "array", "items": {"type": "string"}},
                    "acceptance_criteria": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "definition_of_done": {"type": "string"},
                    "blueprint_id": {"type": "string"},
                    "blueprint_source": {"type": "string"},
                    "recipe": {"type": "string"},
                    "metadata": {"type": "object"},
                },
                required=["title"],
            ),
            handler=create_task,
        ),
        MCPServerTool(
            name="penguin_pm_get_task",
            description="Get one Penguin PM task by ID with lifecycle truth.",
            input_schema=_schema(
                {"task_id": {"type": "string"}},
                required=["task_id"],
            ),
            handler=get_task,
        ),
    ]


def _schema(
    properties: dict[str, dict[str, Any]], *, required: Optional[list[str]] = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


def _metadata(arguments: dict[str, Any]) -> dict[str, Any]:
    value = arguments.get("metadata")
    return dict(value) if isinstance(value, dict) else {}


def _required_str(arguments: dict[str, Any], key: str) -> str:
    value = arguments.get(key)
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{key} is required")
    return value.strip()


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_path(value: Any) -> Optional[Path]:
    text = _optional_str(value)
    return Path(text).expanduser().resolve() if text else None


def _optional_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    return int(value)


def _optional_str_list(value: Any) -> Optional[list[str]]:
    if value is None:
        return None
    if isinstance(value, str):
        return [value]
    if isinstance(value, list):
        return [str(item) for item in value]
    return None


def _parse_status(value: Any) -> Optional[TaskStatus]:
    text = _optional_str(value)
    if text is None:
        return None
    try:
        return TaskStatus(text.lower())
    except ValueError as exc:
        valid = ", ".join(status.value for status in TaskStatus)
        raise ValueError(
            f"invalid status {text!r}, valid statuses are: {valid}"
        ) from exc


__all__ = ["build_pm_tools"]
