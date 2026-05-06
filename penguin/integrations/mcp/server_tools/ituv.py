"""ITUV orchestration tools for Penguin's MCP server surface."""

from __future__ import annotations

from datetime import datetime, timezone
import logging
from typing import Any, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.models import ArtifactEvidence, DependencyPolicy, TaskPhase, TaskStatus
from penguin.web.services.project_payloads import (
    serialize_project_payload,
    serialize_task_payload,
)

logger = logging.getLogger(__name__)


def build_ituv_tools(core: Any) -> list[MCPServerTool]:
    """Build ITUV status/frontier/mutation tools for a Penguin core."""
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



    def signal(arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(arguments, "task_id")
        action = (_optional_str(arguments.get("action")) or "").lower()
        dry_run = _optional_bool(arguments.get("dry_run"), True)
        reason = _optional_str(arguments.get("reason")) or "MCP ITUV signal"
        user_id = _optional_str(arguments.get("user_id")) or "mcp"
        task = project_manager.get_task(task_id)
        if task is None:
            return {"error": "task_not_found", "task_id": task_id}

        before = serialize_task_payload(task)
        try:
            if action == "set_status":
                status = _parse_status(_required_str(arguments, "status"))
                validation_error = _validate_status_transition(task, status)
                if validation_error:
                    return _mutation_rejected(
                        task_id=task_id,
                        action=action,
                        reason=validation_error,
                        before=before,
                    )
                if dry_run:
                    return _dry_run_payload(
                        task_id,
                        action,
                        before,
                        {"status": status.value},
                    )
                project_manager.update_task_status(
                    task_id,
                    status,
                    reason=reason,
                    user_id=user_id,
                )
            elif action == "set_phase":
                phase = _parse_phase(_required_str(arguments, "phase"))
                validation_error = _validate_phase_transition(task, phase)
                if validation_error:
                    return _mutation_rejected(
                        task_id=task_id,
                        action=action,
                        reason=validation_error,
                        before=before,
                    )
                if dry_run:
                    return _dry_run_payload(
                        task_id,
                        action,
                        before,
                        {"phase": phase.value},
                    )
                project_manager.update_task_phase(task_id, phase, reason=reason)
            elif action == "block":
                validation_error = _validate_phase_transition(task, TaskPhase.BLOCKED)
                if validation_error:
                    return _mutation_rejected(
                        task_id=task_id,
                        action=action,
                        reason=validation_error,
                        before=before,
                    )
                if dry_run:
                    return _dry_run_payload(
                        task_id,
                        action,
                        before,
                        {"phase": TaskPhase.BLOCKED.value},
                    )
                project_manager.update_task_phase(
                    task_id,
                    TaskPhase.BLOCKED,
                    reason=reason,
                )
            elif action == "unblock":
                if task.phase != TaskPhase.BLOCKED:
                    return _mutation_rejected(
                        task_id=task_id,
                        action=action,
                        reason="Task is not currently in blocked phase.",
                        before=before,
                    )
                if dry_run:
                    return _dry_run_payload(
                        task_id,
                        action,
                        before,
                        {"phase": TaskPhase.PENDING.value},
                    )
                project_manager.update_task_phase(task_id, TaskPhase.PENDING, reason=reason)
            else:
                return {
                    "error": "unsupported_action",
                    "supported_actions": ["set_status", "set_phase", "block", "unblock"],
                }
        except (ValueError, RuntimeError) as exc:
            return {
                "status": "rejected",
                "task_id": task_id,
                "action": action,
                "reason": str(exc),
                "before": before,
            }
        except Exception:  # pragma: no cover - defensive server boundary
            logger.exception(
                "Unexpected ITUV signal failure for task %s action %s",
                task_id,
                action,
            )
            return {
                "status": "rejected",
                "task_id": task_id,
                "action": action,
                "reason": "internal error",
                "before": before,
            }
        updated = project_manager.get_task(task_id)
        return {
            "status": "applied",
            "task_id": task_id,
            "action": action,
            "dry_run": False,
            "before": before,
            "after": serialize_task_payload(updated) if updated else None,
        }

    def mark_ready_for_review(arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(arguments, "task_id")
        dry_run = _optional_bool(arguments.get("dry_run"), True)
        task = project_manager.get_task(task_id)
        if task is None:
            return {"error": "task_not_found", "task_id": task_id}
        before = serialize_task_payload(task)
        validation_error = _validate_mark_ready(task)
        if validation_error:
            return _mutation_rejected(
                task_id=task_id,
                action="mark_ready_for_review",
                reason=validation_error,
                before=before,
            )
        if dry_run:
            return _dry_run_payload(
                task_id,
                "mark_ready_for_review",
                before,
                {
                    "status": TaskStatus.PENDING_REVIEW.value,
                    "phase": TaskPhase.DONE.value,
                },
            )
        updated = project_manager.mark_task_execution_ready_for_review(
            task_id=task_id,
            executor_id=_optional_str(arguments.get("executor_id")) or "mcp",
            response=(
                _optional_str(arguments.get("response"))
                or "Marked ready by MCP ITUV tool."
            ),
            task_prompt=_optional_str(arguments.get("task_prompt")),
            context=_optional_dict(arguments.get("context")),
        )
        return {
            "status": "applied",
            "task_id": task_id,
            "action": "mark_ready_for_review",
            "dry_run": False,
            "before": before,
            "after": serialize_task_payload(updated),
        }

    def record_artifact(arguments: dict[str, Any]) -> dict[str, Any]:
        task_id = _required_str(arguments, "task_id")
        dry_run = _optional_bool(arguments.get("dry_run"), True)
        task = project_manager.get_task(task_id)
        if task is None:
            return {"error": "task_not_found", "task_id": task_id}
        artifact = ArtifactEvidence(
            key=_required_str(arguments, "key"),
            kind=_required_str(arguments, "kind"),
            path=_optional_str(arguments.get("path")),
            producer_task_id=_optional_str(arguments.get("producer_task_id")) or task_id,
            created_at=_optional_str(arguments.get("created_at"))
            or datetime.now(timezone.utc).isoformat(),
            valid=_optional_bool(arguments.get("valid"), False),
            metadata=_optional_dict(arguments.get("metadata")),
        )
        before = serialize_task_payload(task)
        if dry_run:
            return {
                "status": "dry_run",
                "task_id": task_id,
                "action": "record_artifact",
                "dry_run": True,
                "before": before,
                "artifact": artifact.to_dict(),
            }
        normalized_artifacts = []
        for item in task.artifact_evidence:
            if isinstance(item, ArtifactEvidence):
                normalized_artifacts.append(item)
            elif isinstance(item, dict):
                normalized_artifacts.append(ArtifactEvidence(**item))
        task.artifact_evidence = normalized_artifacts
        task.artifact_evidence.append(artifact)
        task.updated_at = datetime.now(timezone.utc).isoformat()
        project_manager.storage.update_task(task)
        updated = project_manager.get_task(task_id)
        return {
            "status": "applied",
            "task_id": task_id,
            "action": "record_artifact",
            "dry_run": False,
            "artifact": artifact.to_dict(),
            "after": serialize_task_payload(updated) if updated else None,
        }

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
            name="penguin_ituv_signal",
            description=(
                "Dry-run or apply validated ITUV task status/phase signals. "
                "Defaults to dry_run=true."
            ),
            input_schema=_schema(
                {
                    "task_id": {"type": "string"},
                    "action": {"type": "string"},
                    "status": {"type": "string"},
                    "phase": {"type": "string"},
                    "reason": {"type": "string"},
                    "user_id": {"type": "string"},
                    "dry_run": {"type": "boolean"},
                },
                required=["task_id", "action"],
            ),
            handler=signal,
        ),
        MCPServerTool(
            name="penguin_ituv_mark_ready_for_review",
            description=(
                "Dry-run or mark a successful task execution as phase=done and "
                "status=pending_review through ProjectManager semantics."
            ),
            input_schema=_schema(
                {
                    "task_id": {"type": "string"},
                    "executor_id": {"type": "string"},
                    "response": {"type": "string"},
                    "task_prompt": {"type": "string"},
                    "context": {"type": "object"},
                    "dry_run": {"type": "boolean"},
                },
                required=["task_id"],
            ),
            handler=mark_ready_for_review,
        ),
        MCPServerTool(
            name="penguin_ituv_record_artifact",
            description=(
                "Dry-run or attach machine-checkable artifact evidence to a task. "
                "Defaults to dry_run=true."
            ),
            input_schema=_schema(
                {
                    "task_id": {"type": "string"},
                    "key": {"type": "string"},
                    "kind": {"type": "string"},
                    "path": {"type": "string"},
                    "producer_task_id": {"type": "string"},
                    "created_at": {"type": "string"},
                    "valid": {"type": "boolean"},
                    "metadata": {"type": "object"},
                    "dry_run": {"type": "boolean"},
                },
                required=["task_id", "key", "kind"],
            ),
            handler=record_artifact,
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
        "slice": "4B",
        "read_only": False,
        "mutation_tools_exposed": True,
        "tools": [
            "penguin_ituv_capabilities",
            "penguin_ituv_status",
            "penguin_ituv_frontier",
            "penguin_ituv_signal",
            "penguin_ituv_mark_ready_for_review",
            "penguin_ituv_record_artifact",
        ],
        "phases": [phase.value for phase in TaskPhase],
        "statuses": [status.value for status in TaskStatus],
        "status_transitions": transitions,
        "phase_transitions": {
            phase.value: [target.value for target in targets]
            for phase, targets in TaskPhase.allowed_transitions().items()
        },
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
            "Mutation tools default to dry_run=true and require explicit dry_run=false to apply.",
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
        blockers = project_manager.get_unsatisfied_dependencies(task, task_map)
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


def _parse_status(value: str) -> TaskStatus:
    try:
        return TaskStatus(value)
    except ValueError as exc:
        valid = ", ".join(status.value for status in TaskStatus)
        raise ValueError(f"Invalid status '{value}'. Valid statuses: {valid}") from exc


def _parse_phase(value: str) -> TaskPhase:
    try:
        return TaskPhase(value)
    except ValueError as exc:
        valid = ", ".join(phase.value for phase in TaskPhase)
        raise ValueError(f"Invalid phase '{value}'. Valid phases: {valid}") from exc


def _validate_status_transition(task: Any, status: TaskStatus) -> Optional[str]:
    if status in {TaskStatus.PENDING_REVIEW, TaskStatus.COMPLETED} and task.phase != TaskPhase.DONE:
        return (
            f"Cannot set status {status.value} while phase is {task.phase.value}. "
            "Use penguin_ituv_mark_ready_for_review for the review bridge."
        )
    if not task.can_transition_to(status):
        return f"Invalid status transition from {task.status.value} to {status.value}."
    return None


def _validate_phase_transition(task: Any, phase: TaskPhase) -> Optional[str]:
    if phase == task.phase:
        return None
    if phase == TaskPhase.DONE and task.status not in {
        TaskStatus.PENDING_REVIEW,
        TaskStatus.COMPLETED,
    }:
        return (
            f"Cannot set phase {phase.value} while status is {task.status.value}. "
            "Use penguin_ituv_mark_ready_for_review for successful execution."
        )
    if not task.phase.can_transition_to(phase):
        return f"Invalid phase transition from {task.phase.value} to {phase.value}."
    return None


def _validate_mark_ready(task: Any) -> Optional[str]:
    if task.status in {TaskStatus.PENDING_REVIEW, TaskStatus.COMPLETED}:
        return None
    if task.status not in {TaskStatus.ACTIVE, TaskStatus.RUNNING}:
        return (
            "Only active/running tasks can be marked ready for review; "
            f"current status is {task.status.value}."
        )
    return None


def _mutation_rejected(
    *, task_id: str, action: str, reason: str, before: dict[str, Any]
) -> dict[str, Any]:
    return {
        "status": "rejected",
        "task_id": task_id,
        "action": action,
        "reason": reason,
        "before": before,
    }


def _dry_run_payload(
    task_id: str, action: str, before: dict[str, Any], would_apply: dict[str, Any]
) -> dict[str, Any]:
    return {
        "status": "dry_run",
        "task_id": task_id,
        "action": action,
        "dry_run": True,
        "before": before,
        "would_apply": would_apply,
    }


def _optional_dict(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, dict) else {}


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
