"""Shared project/task payload serializers for web and MCP surfaces."""

from __future__ import annotations

from typing import Any, Dict, Optional, Sequence


def _enum_value(value: Any) -> Any:
    return value.value if hasattr(value, "value") else value


def _dict_list(values: Any) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for item in values or []:
        if hasattr(item, "to_dict"):
            result.append(item.to_dict())
        elif isinstance(item, dict):
            result.append(dict(item))
    return result


def serialize_task_payload(
    task: Any, *, include_metadata: bool = True
) -> Dict[str, Any]:
    """Serialize a task without flattening current lifecycle/runtime truth."""
    metadata = dict(getattr(task, "metadata", {}) or {})
    payload: Dict[str, Any] = {
        "id": task.id,
        "project_id": getattr(task, "project_id", None),
        "title": task.title,
        "description": task.description,
        "status": _enum_value(getattr(task, "status", None)),
        "phase": _enum_value(getattr(task, "phase", None)),
        "priority": getattr(task, "priority", None),
        "parent_task_id": getattr(task, "parent_task_id", None),
        "dependencies": list(getattr(task, "dependencies", []) or []),
        "dependency_specs": _dict_list(getattr(task, "dependency_specs", []) or []),
        "artifact_evidence": _dict_list(getattr(task, "artifact_evidence", []) or []),
        "recipe": getattr(task, "recipe", None),
        "clarification_requests": list(metadata.get("clarification_requests", [])),
        "tags": list(getattr(task, "tags", []) or []),
        "due_date": getattr(task, "due_date", None),
        "progress": getattr(task, "progress", None),
        "budget_tokens": getattr(task, "budget_tokens", None),
        "budget_minutes": getattr(task, "budget_minutes", None),
        "allowed_tools": getattr(task, "allowed_tools", None),
        "acceptance_criteria": list(getattr(task, "acceptance_criteria", []) or []),
        "definition_of_done": getattr(task, "definition_of_done", None),
        "blueprint_id": getattr(task, "blueprint_id", None),
        "blueprint_source": getattr(task, "blueprint_source", None),
        "created_at": getattr(task, "created_at", None),
        "updated_at": getattr(task, "updated_at", None),
    }
    if include_metadata:
        payload["metadata"] = metadata
    return payload


def serialize_project_payload(
    project: Any,
    *,
    tasks: Optional[Sequence[Any]] = None,
    include_metadata: bool = True,
) -> Dict[str, Any]:
    """Serialize a project with richer PM fields than the legacy route subset."""
    payload: Dict[str, Any] = {
        "id": project.id,
        "name": project.name,
        "description": project.description,
        "status": getattr(project, "status", None),
        "workspace_path": str(getattr(project, "workspace_path", "") or "") or None,
        "context_path": str(getattr(project, "context_path", "") or "") or None,
        "tags": list(getattr(project, "tags", []) or []),
        "priority": getattr(project, "priority", None),
        "budget_tokens": getattr(project, "budget_tokens", None),
        "budget_minutes": getattr(project, "budget_minutes", None),
        "start_date": getattr(project, "start_date", None),
        "due_date": getattr(project, "due_date", None),
        "created_at": getattr(project, "created_at", None),
        "updated_at": getattr(project, "updated_at", None),
    }
    if include_metadata:
        payload["metadata"] = dict(getattr(project, "metadata", {}) or {})
    if tasks is not None:
        payload["tasks"] = [serialize_task_payload(task) for task in tasks]
    return payload


__all__ = ["serialize_project_payload", "serialize_task_payload"]
