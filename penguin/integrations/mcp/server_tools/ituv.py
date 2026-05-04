"""Read-only ITUV orchestration tools for Penguin's MCP server surface."""

from __future__ import annotations

from typing import Any, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.models import DependencyPolicy, TaskPhase, TaskStatus
from penguin.web.services.project_payloads import (
    serialize_project_payload,
    serialize_task_payload,
)


def build_ituv_tools(core: Any) -> list[MCPServerTool]:
    """Build read-only ITUV status/frontier tools for a Penguin core."""
    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return []

    def capabilities(_arguments: dict[str, Any]) -> dict[str, Any]:
        return _capabilities_payload()

    def status(arguments: dict[str, Any]) -> dict[str, Any]:
        project_id = _optional_str(arguments.get("project_id"))
        task_id = _optional_str(arguments.get("task_id"))
        include_tasks = _optional_bool(arguments.get("include_tasks"), False)
        include_ready = _optional_bool(arguments.get("include_ready"), True)
        include_blocked = _optional_bool(arguments.get("include_blocked"), True)

        if not project_id and not task_id:
            return {
                "error": "missing_scope",
                "message": "project_id or task_id is required.",
            }

        project = None
        task = None
        if task_id:
            task = project_manager.get_task(task_id)
            if task is None:
                return {"error": "task_not_found", "task_id": task_id}
            project_id = project_id or getattr(task, "project_id", None)
        if project_id:
            project = project_manager.get_project(project_id)
            if project is None:
                return {"error": "project_not_found", "project_id": project_id}

        payload: dict[str, Any] = {
            "scope": {"project_id": project_id, "task_id": task_id},
            "capabilities": _capabilities_payload(),
        }
        if project is not None:
            project_tasks = project_manager.list_tasks(project_id=project.id)
            payload["project"] = serialize_project_payload(
                project,
                tasks=project_tasks if include_tasks else None,
            )
            payload["dag"] = _safe_project_dag_stats(project_manager, project.id)
            if include_ready:
                payload["ready_tasks"] = [
                    serialize_task_payload(item)
                    for item in project_manager.get_ready_tasks(project.id)
                ]
            if include_blocked:
                payload["blocked_ready_candidates"] = (
                    project_manager.get_blocked_ready_candidates(project.id)
                )
        if task is not None:
            payload["task"] = serialize_task_payload(task)
            payload["task_readiness"] = _task_readiness(project_manager, task)
        return payload

    def frontier(arguments: dict[str, Any]) -> dict[str, Any]:
        project_id = _required_str(arguments, "project_id")
        project = project_manager.get_project(project_id)
        if project is None:
            return {"error": "project_not_found", "project_id": project_id}
        limit = _optional_int(arguments.get("limit"), default=10) or 10
        include_blocked = _optional_bool(arguments.get("include_blocked"), True)
        ready_tasks = project_manager.get_ready_tasks(project_id)
        next_task = project_manager.get_next_task_dag(project_id)
        payload: dict[str, Any] = {
            "project": serialize_project_payload(project),
            "ready_count": len(ready_tasks),
            "ready_tasks": [
                serialize_task_payload(task) for task in ready_tasks[:limit]
            ],
            "next_task": serialize_task_payload(next_task) if next_task else None,
            "dag": _safe_project_dag_stats(project_manager, project_id),
        }
        if include_blocked:
            payload["blocked_ready_candidates"] = (
                project_manager.get_blocked_ready_candidates(project_id)
            )
        return payload

    return [
        MCPServerTool(
            name="penguin_ituv_capabilities",
            description=(
                "Report Penguin ITUV lifecycle/status semantics and read-only MCP "
                "orchestration capabilities."
            ),
            input_schema=_schema({}),
            handler=capabilities,
        ),
        MCPServerTool(
            name="penguin_ituv_status",
            description=(
                "Return read-only ITUV/project/task lifecycle truth, including "
                "status, phase, dependencies, artifact evidence, and DAG readiness."
            ),
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "task_id": {"type": "string"},
                    "include_tasks": {"type": "boolean"},
                    "include_ready": {"type": "boolean"},
                    "include_blocked": {"type": "boolean"},
                }
            ),
            handler=status,
        ),
        MCPServerTool(
            name="penguin_ituv_frontier",
            description=(
                "Return the current dependency-aware DAG frontier for a project "
                "without starting or mutating execution."
            ),
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "limit": {"type": "integer"},
                    "include_blocked": {"type": "boolean"},
                },
                required=["project_id"],
            ),
            handler=frontier,
        ),
    ]


def _capabilities_payload() -> dict[str, Any]:
    transitions = {
        status.value: [target.value for target in targets]
        for status, targets in TaskStatus.valid_transitions().items()
    }
    return {
        "slice": "4A",
        "read_only": True,
        "mutation_tools_exposed": False,
        "tools": [
            "penguin_ituv_capabilities",
            "penguin_ituv_status",
            "penguin_ituv_frontier",
        ],
        "phases": [phase.value for phase in TaskPhase],
        "statuses": [status.value for status in TaskStatus],
        "status_transitions": transitions,
        "dependency_policies": [policy.value for policy in DependencyPolicy],
        "dependency_readiness_rules": {
            "completion_required": "Unlocks only when upstream status is completed.",
            "review_ready_ok": (
                "Unlocks when upstream phase is done and status is pending_review "
                "or completed."
            ),
            "artifact_ready": (
                "Unlocks when valid matching artifact evidence exists on the "
                "upstream dependency task."
            ),
        },
        "known_gaps": [
            "ITUV mutation/signaling is not exposed in Slice 4A.",
            "Task-specific readiness uses current ProjectManager dependency semantics.",
            "Durable runtime job records are deferred to Slice 5.",
        ],
    }


def _safe_project_dag_stats(project_manager: Any, project_id: str) -> dict[str, Any]:
    try:
        return project_manager.get_dag_stats(project_id)
    except Exception as exc:
        return {"error": "dag_stats_failed", "message": str(exc)}


def _task_readiness(project_manager: Any, task: Any) -> dict[str, Any]:
    blockers = []
    try:
        tasks = project_manager.list_tasks(project_id=task.project_id)
        task_map = {item.id: item for item in tasks}
        blockers = project_manager._get_unsatisfied_dependencies(task, task_map)
    except Exception as exc:  # pragma: no cover - defensive read-only boundary
        return {
            "ready_for_runmode": False,
            "error": "readiness_failed",
            "message": str(exc),
        }
    return {
        "ready_for_runmode": task.status == TaskStatus.ACTIVE and not blockers,
        "blocked": bool(blockers),
        "blockers": blockers,
        "status": task.status.value,
        "phase": task.phase.value,
    }


def _schema(
    properties: dict[str, dict[str, Any]], *, required: Optional[list[str]] = None
) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required or [],
        "additionalProperties": False,
    }


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


def _optional_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _optional_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    if value is None:
        return default
    return int(value)


__all__ = ["build_ituv_tools"]
