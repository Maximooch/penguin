"""RunMode tools for Penguin's MCP server surface."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.web.services.project_payloads import serialize_task_payload


@dataclass
class RunModeJobRecord:
    """In-process runtime job record for MCP-triggered RunMode work."""

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
    cancel_requested: bool = False
    cancel_requested_at: Optional[str] = None
    cancel_signal_sent: bool = False
    cancel_callback: Optional[Callable[[], bool]] = field(
        default=None,
        repr=False,
        compare=False,
    )

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable job record."""
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "cancel_requested": self.cancel_requested,
            "cancel_requested_at": self.cancel_requested_at,
            "cancel_signal_sent": self.cancel_signal_sent,
        }


class RunModeJobRegistry:
    """Small in-process registry for runtime MCP jobs.

    The registry intentionally starts jobs in daemon threads and records final
    results/errors. This is not durable across process restarts; it is an MVP
    control-plane handle so MCP clients do not block on model-dependent runs.
    """

    def __init__(self) -> None:
        self._jobs: Dict[str, RunModeJobRecord] = {}
        self._threads: Dict[str, threading.Thread] = {}
        self._lock = threading.RLock()

    def start_job(
        self,
        *,
        kind: str,
        runner: Callable[[RunModeJobRecord], Awaitable[Dict[str, Any]]],
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Start a background job and return its initial record."""
        record = RunModeJobRecord(
            job_id=str(uuid.uuid4()),
            kind=kind,
            project_id=project_id,
            task_id=task_id,
            metadata=dict(metadata or {}),
        )
        with self._lock:
            self._jobs[record.job_id] = record

        thread = threading.Thread(
            target=self._run_job_thread,
            args=(record.job_id, runner),
            name=f"penguin-mcp-runmode-{record.job_id[:8]}",
            daemon=True,
        )
        with self._lock:
            self._threads[record.job_id] = thread
        thread.start()
        return {"job": record.to_dict(), "registry": self.summary()}

    def list_jobs(
        self,
        *,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List job records with optional filters."""
        with self._lock:
            jobs: Iterable[RunModeJobRecord] = list(self._jobs.values())
        if status:
            jobs = [job for job in jobs if job.status == status]
        if project_id:
            jobs = [job for job in jobs if job.project_id == project_id]
        if task_id:
            jobs = [job for job in jobs if job.task_id == task_id]
        return [job.to_dict() for job in jobs]

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return one job record if known."""
        with self._lock:
            job = self._jobs.get(job_id)
            return job.to_dict() if job else None

    def cancel_job(self, job_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Request cooperative cancellation for one in-process job."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                return {
                    "error": "job_not_found",
                    "job_id": job_id,
                    "message": "No runtime MCP job exists with this ID.",
                    "registry": self.summary(),
                }
            if record.status in {
                "completed",
                "failed",
                "cancelled",
                "completed_after_cancel_requested",
            }:
                return {
                    "job": record.to_dict(),
                    "cancel_requested": False,
                    "message": "Job is already terminal.",
                    "registry": self.summary(),
                }
            record.cancel_requested = True
            record.cancel_requested_at = datetime.utcnow().isoformat()
            record.metadata["cancel_reason"] = reason
            record.status = "cancelling"
            callback = record.cancel_callback

        signal_sent = False
        if callback:
            try:
                signal_sent = bool(callback())
            except Exception as exc:  # pragma: no cover - defensive boundary
                with self._lock:
                    record.error = f"Cancel callback failed: {exc}"
        with self._lock:
            record.cancel_signal_sent = signal_sent
            return {
                "job": record.to_dict(),
                "cancel_requested": True,
                "cancel_signal_sent": signal_sent,
                "hard_cancel_supported": False,
                "message": (
                    "Cooperative cancellation requested. The job may still finish "
                    "if the underlying RunMode path does not observe the signal."
                ),
                "registry": self.summary(),
            }

    def summary(self) -> Dict[str, Any]:
        """Return registry metadata."""
        with self._lock:
            job_count = len(self._jobs)
            running_count = sum(
                1 for job in self._jobs.values() if job.status == "running"
            )
        return {
            "type": "in_process",
            "job_count": job_count,
            "running_count": running_count,
            "supports_start": True,
            "supports_cancel": True,
            "hard_cancel_supported": False,
            "durable": False,
        }

    def _run_job_thread(
        self,
        job_id: str,
        runner: Callable[[RunModeJobRecord], Awaitable[Dict[str, Any]]],
    ) -> None:
        """Run one async job in a dedicated thread."""
        with self._lock:
            record = self._jobs[job_id]
            record.status = "running"
        try:
            result = asyncio.run(runner(record))
            with self._lock:
                record.result = result
                mapped_status = _job_status_from_result(result)
                if record.cancel_requested and mapped_status == "completed":
                    record.status = "completed_after_cancel_requested"
                else:
                    record.status = mapped_status
                record.finished_at = datetime.utcnow().isoformat()
                record.cancel_callback = None
        except Exception as exc:  # pragma: no cover - defensive job boundary
            with self._lock:
                record.status = "failed"
                record.error = str(exc)
                record.finished_at = datetime.utcnow().isoformat()
                record.cancel_callback = None


def _job_status_from_result(result: Dict[str, Any]) -> str:
    """Map a runtime result payload to job status."""
    status = str(result.get("status") or result.get("completion_type") or "").lower()
    if status in {"error", "failed", "failure"}:
        return "failed"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"waiting_input", "clarification_needed", "needs_input"}:
        return "waiting_input"
    return "completed"


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
    """Build the Slice 3C capabilities payload."""
    return {
        "runtime_tools_enabled": True,
        "slice": "3C",
        "tools": {
            "available": [
                "penguin_runmode_capabilities",
                "penguin_runmode_list_jobs",
                "penguin_runmode_get_job",
                "penguin_runmode_start_task",
                "penguin_runmode_start_project",
                "penguin_runmode_cancel_job",
                "penguin_runmode_resume_clarification",
            ],
            "not_yet_exposed": [],
        },
        "start_supported": True,
        "cancel_supported": True,
        "hard_cancel_supported": False,
        "resume_clarification_supported": True,
        "registry": registry.summary(),
        "core": _core_capabilities(core),
        "gaps": [
            "Cancellation is cooperative/best-effort; Python threads are not force-killed.",
            "Job registry is in-process only and is lost on server restart.",
            "RunMode execution is model-dependent and remains explicitly gated.",
        ],
    }


async def _execute_task_job(
    core: Any,
    arguments: Dict[str, Any],
    record: Optional[RunModeJobRecord] = None,
) -> Dict[str, Any]:
    """Execute one project task through the same RunMode path as the web route."""
    from penguin.run_mode import RunMode
    from penguin.system.execution_context import (
        ExecutionContext,
        execution_context_scope,
        normalize_directory,
    )

    task_id = arguments.get("task_id")
    if not task_id:
        return {"status": "error", "message": "task_id is required"}

    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return {"status": "error", "message": "Project manager not available"}
    if not getattr(core, "engine", None):
        return {"status": "error", "message": "Engine layer not available"}

    task = await project_manager.get_task_async(str(task_id))
    if not task:
        return {"status": "error", "message": f"Task {task_id} not found"}

    project = None
    if getattr(task, "project_id", None) and hasattr(
        project_manager,
        "get_project_async",
    ):
        project = await project_manager.get_project_async(task.project_id)
    resolved_directory = normalize_directory(
        arguments.get("directory")
    ) or normalize_directory(getattr(project, "workspace_path", None))
    session_id = arguments.get("session_id")
    execution_context = ExecutionContext(
        session_id=session_id,
        conversation_id=session_id,
        directory=resolved_directory,
        project_root=resolved_directory,
        workspace_root=resolved_directory,
        request_id=f"mcp-task-execute:{task_id}",
    )

    run_mode = RunMode(core=core)
    if record is not None:
        record.cancel_callback = lambda: _request_runmode_shutdown(run_mode)
    with execution_context_scope(execution_context):
        result = await run_mode.start(
            name=task.title,
            description=task.description,
            context={
                "task_id": task.id,
                "project_id": task.project_id,
                "priority": task.priority,
                "session_id": session_id,
                "conversation_id": session_id,
                "directory": resolved_directory,
            },
        )

    updated_task = await project_manager.get_task_async(task.id)
    return {
        "status": _job_status_from_result(result if isinstance(result, dict) else {}),
        "task_id": task.id,
        "result": result,
        "task": serialize_task_payload(updated_task or task),
    }


async def _execute_project_job(
    core: Any,
    arguments: Dict[str, Any],
    record: Optional[RunModeJobRecord] = None,
) -> Dict[str, Any]:
    """Execute project-scoped RunMode through the web service path."""
    from penguin.web.services.projects import start_project_execution

    project_identifier = (
        arguments.get("project_id")
        or arguments.get("project_identifier")
        or arguments.get("project_name")
    )
    if not project_identifier:
        return {
            "status": "error",
            "message": "project_id, project_identifier, or project_name is required",
        }

    if record is not None:
        record.metadata["cancel_signal_note"] = (
            "Project execution uses the web service path; cancellation can be "
            "recorded but may not stop the underlying run until RunMode exposes "
            "a shared cancellation handle."
        )

    result = await start_project_execution(
        core=core,
        project_identifier=str(project_identifier),
        continuous=bool(arguments.get("continuous", False)),
        time_limit=arguments.get("time_limit"),
        session_id=arguments.get("session_id"),
        directory=arguments.get("directory"),
    )
    return {"status": "completed", "execution": result}


def _request_runmode_shutdown(run_mode: Any) -> bool:
    """Request cooperative shutdown on a RunMode instance."""
    setattr(run_mode, "_shutdown_requested", True)
    setattr(run_mode, "_interrupted", True)
    return True


async def _resume_clarification_job(
    core: Any,
    arguments: Dict[str, Any],
    record: Optional[RunModeJobRecord] = None,
) -> Dict[str, Any]:
    """Answer the latest clarification request and resume task execution."""
    from penguin.run_mode import RunMode
    from penguin.system.execution_context import (
        ExecutionContext,
        execution_context_scope,
        normalize_directory,
    )

    task_id = arguments.get("task_id")
    answer = arguments.get("answer")
    if not task_id:
        return {"status": "error", "message": "task_id is required"}
    if not answer:
        return {"status": "error", "message": "answer is required"}

    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return {"status": "error", "message": "Project manager not available"}

    task = await project_manager.get_task_async(str(task_id))
    if not task:
        return {"status": "error", "message": f"Task {task_id} not found"}

    project = None
    if getattr(task, "project_id", None) and hasattr(
        project_manager,
        "get_project_async",
    ):
        project = await project_manager.get_project_async(task.project_id)
    resolved_directory = normalize_directory(
        arguments.get("directory")
    ) or normalize_directory(getattr(project, "workspace_path", None))
    session_id = arguments.get("session_id")
    execution_context = ExecutionContext(
        session_id=session_id,
        conversation_id=session_id,
        directory=resolved_directory,
        project_root=resolved_directory,
        workspace_root=resolved_directory,
        request_id=f"mcp-task-resume:{task_id}",
    )

    run_mode = RunMode(core=core)
    if record is not None:
        record.cancel_callback = lambda: _request_runmode_shutdown(run_mode)
    with execution_context_scope(execution_context):
        result = await run_mode.resume_with_clarification(
            task_id=str(task_id),
            answer=str(answer),
            answered_by=arguments.get("answered_by"),
        )

    updated_task = await project_manager.get_task_async(str(task_id))
    return {
        "status": _job_status_from_result(result if isinstance(result, dict) else {}),
        "task_id": str(task_id),
        "result": result,
        "task": serialize_task_payload(updated_task or task),
    }


def build_runmode_tools(
    core: Any,
    registry: Optional[RunModeJobRegistry] = None,
) -> List[MCPServerTool]:
    """Build runtime tools for Penguin's MCP server."""
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

    def start_task(arguments: Dict[str, Any]) -> Dict[str, Any]:
        task_id = arguments.get("task_id")
        if not task_id:
            return {"error": "missing_task_id", "message": "task_id is required."}
        return job_registry.start_job(
            kind="task",
            runner=lambda job: _execute_task_job(core, arguments, job),
            task_id=str(task_id),
            project_id=arguments.get("project_id"),
            metadata={
                "session_id": arguments.get("session_id"),
                "directory": arguments.get("directory"),
            },
        )

    def cancel_job(arguments: Dict[str, Any]) -> Dict[str, Any]:
        job_id = arguments.get("job_id")
        if not job_id:
            return {"error": "missing_job_id", "message": "job_id is required."}
        return job_registry.cancel_job(str(job_id), reason=arguments.get("reason"))

    def resume_clarification(arguments: Dict[str, Any]) -> Dict[str, Any]:
        task_id = arguments.get("task_id")
        if not task_id:
            return {"error": "missing_task_id", "message": "task_id is required."}
        if not arguments.get("answer"):
            return {"error": "missing_answer", "message": "answer is required."}
        return job_registry.start_job(
            kind="clarification_resume",
            runner=lambda job: _resume_clarification_job(core, arguments, job),
            task_id=str(task_id),
            project_id=arguments.get("project_id"),
            metadata={
                "answered_by": arguments.get("answered_by"),
                "session_id": arguments.get("session_id"),
                "directory": arguments.get("directory"),
            },
        )

    def start_project(arguments: Dict[str, Any]) -> Dict[str, Any]:
        project_identifier = (
            arguments.get("project_id")
            or arguments.get("project_identifier")
            or arguments.get("project_name")
        )
        if not project_identifier:
            return {
                "error": "missing_project_identifier",
                "message": "project_id, project_identifier, or project_name is required.",
            }
        return job_registry.start_job(
            kind="project",
            runner=lambda job: _execute_project_job(core, arguments, job),
            project_id=str(project_identifier),
            metadata={
                "continuous": bool(arguments.get("continuous", False)),
                "time_limit": arguments.get("time_limit"),
                "session_id": arguments.get("session_id"),
                "directory": arguments.get("directory"),
            },
        )

    return [
        MCPServerTool(
            name="penguin_runmode_capabilities",
            description=(
                "Report current Penguin RunMode MCP readiness, job registry, "
                "and known gaps. This does not start execution."
            ),
            input_schema={"type": "object", "properties": {}, "required": []},
            handler=capabilities,
        ),
        MCPServerTool(
            name="penguin_runmode_list_jobs",
            description="List in-process RunMode MCP jobs with optional filters.",
            input_schema={
                "type": "object",
                "properties": {
                    "status": {
                        "type": "string",
                        "description": "Optional status filter.",
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
        MCPServerTool(
            name="penguin_runmode_start_task",
            description=(
                "Start one project task in background RunMode. Requires runtime "
                "tools opt-in and returns a job_id immediately."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Project task ID."},
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID for filtering/metadata.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional Penguin session/conversation ID.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional execution directory override.",
                    },
                },
                "required": ["task_id"],
            },
            handler=start_task,
        ),
        MCPServerTool(
            name="penguin_runmode_start_project",
            description=(
                "Start project-scoped RunMode execution in a background job. "
                "Requires runtime tools opt-in and returns a job_id immediately."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "project_id": {
                        "type": "string",
                        "description": "Project ID to execute.",
                    },
                    "project_identifier": {
                        "type": "string",
                        "description": "Project ID or exact project name.",
                    },
                    "project_name": {
                        "type": "string",
                        "description": "Exact project name fallback.",
                    },
                    "continuous": {
                        "type": "boolean",
                        "description": "Whether to run project execution continuously.",
                    },
                    "time_limit": {
                        "type": "integer",
                        "description": "Optional time limit in minutes.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional Penguin session/conversation ID.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional execution directory override.",
                    },
                },
                "required": [],
            },
            handler=start_project,
        ),
        MCPServerTool(
            name="penguin_runmode_cancel_job",
            description=(
                "Request cooperative cancellation for a runtime MCP job. This is "
                "best-effort and cannot force-kill Python threads."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "job_id": {
                        "type": "string",
                        "description": "Runtime MCP job ID.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Optional cancellation reason.",
                    },
                },
                "required": ["job_id"],
            },
            handler=cancel_job,
        ),
        MCPServerTool(
            name="penguin_runmode_resume_clarification",
            description=(
                "Answer a task's latest open clarification request and resume "
                "execution in a background job."
            ),
            input_schema={
                "type": "object",
                "properties": {
                    "task_id": {"type": "string", "description": "Project task ID."},
                    "answer": {
                        "type": "string",
                        "description": "Answer to the latest open clarification request.",
                    },
                    "answered_by": {
                        "type": "string",
                        "description": "Optional actor/user answering the clarification.",
                    },
                    "project_id": {
                        "type": "string",
                        "description": "Optional project ID for metadata/filtering.",
                    },
                    "session_id": {
                        "type": "string",
                        "description": "Optional Penguin session/conversation ID.",
                    },
                    "directory": {
                        "type": "string",
                        "description": "Optional execution directory override.",
                    },
                },
                "required": ["task_id", "answer"],
            },
            handler=resume_clarification,
        ),
    ]


__all__ = ["RunModeJobRecord", "RunModeJobRegistry", "build_runmode_tools"]
