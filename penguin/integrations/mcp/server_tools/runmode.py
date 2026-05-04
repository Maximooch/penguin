"""RunMode readiness tools for Penguin's MCP server surface."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, Iterable, List, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool


@dataclass
class RunModeJobRecord:
    """In-process runtime job record for future RunMode start/cancel tools."""

    job_id: str
    kind: str
    status: str = "pending"
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    finished_at: Optional[str] = None
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable job record."""
        return asdict(self)


class RunModeJobRegistry:
    """Small in-process registry for runtime MCP jobs.

    Slice 3A only exposes read/capability methods. Start/cancel tools can use this
    registry in later slices instead of inventing a second status model.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, RunModeJobRecord] = {}

    def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List job records with optional filters."""
        jobs: Iterable[RunModeJobRecord] = self._jobs.values()
        if status:
            jobs = [job for job in jobs if job.status == status]
        if project_id:
            jobs = [job for job in jobs if job.project_id == project_id]
        if task_id:
            jobs = [job for job in jobs if job.task_id == task_id]
        return [job.to_dict() for job in jobs]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return one job record if known."""
        job = self._jobs.get(job_id)
        return job.to_dict() if job else None

    def summary(self) -> Dict[str, Any]:
        """Return registry metadata."""
        return {
            "type": "in_process",
            "job_count": len(self._jobs),
            "supports_start": False,
            "supports_cancel": False,
            "durable": False,
        }


def _core_capabilities(core: Any) -> Dict[str, Any]:
    """Return runtime-related capability facts from the current core."""
    run_mode = getattr(core, "run_mode", None)
    return {
        "has_core": core is not None,
        "has_project_manager": bool(getattr(core, "project_manager", None)),
        "has_engine": bool(getattr(core, "engine", None)),
        "has_start_run_mode": hasattr(core, "start_run_mode"),
        "has_active_run_mode_instance": run_mode is not None,
        "runmode_active": bool(getattr(core, "_runmode_active", False)),
        "continuous_mode": bool(getattr(core, "_continuous_mode", False)),
        "current_status_summary": getattr(
            core, "current_runmode_status_summary", None
        ),
        "run_mode_current_task": getattr(run_mode, "current_task_name", None),
    }


def _capabilities_payload(
    core: Any,
    registry: RunModeJobRegistry,
) -> Dict[str, Any]:
    """Build the Slice 3A capabilities payload."""
    core_info = _core_capabilities(core)
    return {
        "runtime_tools_enabled": True,
        "slice": "3A",
        "tools": {
            "available": [
                "penguin_runmode_capabilities",
                "penguin_runmode_list_jobs",
                "penguin_runmode_get_job",
            ],
            "not_yet_exposed": [
                "penguin_runmode_start_task",
                "penguin_runmode_start_project",
                "penguin_runmode_cancel_job",
                "penguin_runmode_resume_clarification",
            ],
        },
        "start_supported": False,
        "cancel_supported": False,
        "resume_clarification_supported": False,
        "registry": registry.summary(),
        "core": core_info,
        "gaps": [
            "No MCP background job start tool is exposed in Slice 3A.",
            "No durable job registry exists yet; current registry is in-process only.",
            "Cancellation semantics are not exposed until Slice 3C.",
            "RunMode execution remains model-dependent and explicitly gated.",
        ],
    }


def build_runmode_tools(
    core: Any,
    registry: Optional[RunModeJobRegistry] = None,
) -> List[MCPServerTool]:
    """Build runtime readiness tools for Penguin's MCP server."""
    job_registry = registry or RunModeJobRegistry()

    def capabilities(_arguments: Dict[str, Any]) -> Dict[str, Any]:
        return _capabilities_payload(core, job_registry)

    def list_jobs(arguments: Dict[str, Any]) -> Dict[str, Any]:
        jobs = job_registry.list_jobs(
            status=arguments.get("status"),
            project_id=arguments.get("project_id"),
            task_id=arguments.get("task_id"),
        )
        return {
            "jobs": jobs,
            "count": len(jobs),
            "registry": job_registry.summary(),
        }

    def get_job(arguments: Dict[str, Any]) -> Dict[str, Any]:
        job_id = arguments.get("job_id")
        if not job_id:
            return {
                "error": "missing_job_id",
                "message": "job_id is required.",
            }
        job = job_registry.get_job(str(job_id))
        if job is None:
            return {
                "error": "job_not_found",
                "job_id": job_id,
                "message": "No runtime MCP job exists with this ID.",
                "registry": job_registry.summary(),
            }
        return {"job": job, "registry": job_registry.summary()}

    return [
        MCPServerTool(
            name="penguin_runmode_capabilities",
            description=(
                "Report current Penguin RunMode MCP readiness and known gaps. "
                "This does not start execution."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=capabilities,
        ),
        MCPServerTool(
            name="penguin_runmode_list_jobs",
            description=(
                "List in-process RunMode MCP jobs. Slice 3A exposes an empty "
                "read-only registry until start tools are implemented."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Optional job status filter.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID filter.",
                    },
                    "task_id": {
                        "type": "string",
                        "description": "Optional task ID filter.",
                    },
                },
                "required": [],
            },
            handler=list_jobs,
        ),
        MCPServerTool(
            name="penguin_runmode_get_job",
            description="Return one in-process RunMode MCP job by ID if it exists.",
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Runtime MCP job ID.",
                    }
                },
                "required": ["job_id"],
            },
            handler=get_job,
        ),
    ]


__all__ = ["RunModeJobRecord", "RunModeJobRegistry", "build_runmode_tools"]
