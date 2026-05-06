"""RunMode tools for Penguin's MCP server surface."""

from __future__ import annotations

import asyncio
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Iterable, List, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.runtime_jobs import (
    TERMINAL_RUNTIME_JOB_STATUSES,
    build_runtime_job_record,
)
from penguin.web.services.project_payloads import serialize_task_payload


@dataclass
class RunModeJobRecord:
    """Live runtime job record for MCP-triggered RunMode work."""

    job_id: str
    kind: str
    status: str = "pending"
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    started_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    updated_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
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
            "session_id": self.metadata.get("session_id"),
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "result": self.result,
            "error": self.error,
            "metadata": self.metadata,
            "cancel_requested": self.cancel_requested,
            "cancel_requested_at": self.cancel_requested_at,
            "cancel_signal_sent": self.cancel_signal_sent,
            "durable": bool(self.metadata.get("durable")),
            "live": True,
            "controllable": self.status not in TERMINAL_RUNTIME_JOB_STATUSES,
        }


class RunModeJobRegistry:
    """Registry for runtime MCP jobs.

    The registry starts jobs in daemon threads, records final results/errors,
    and persists records through ProjectManager when available. Live handles are
    still process-local, so restarted servers can recover history but cannot
    force-control orphaned non-terminal jobs.
    """

    def __init__(self, project_manager: Optional[Any] = None) -> None:
        self.project_manager = project_manager
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
        record.metadata["durable"] = self._durable_enabled
        with self._lock:
            self._jobs[record.job_id] = record
        self._persist(record)

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
            live_jobs: Iterable[RunModeJobRecord] = list(self._jobs.values())
        live_payloads = [job.to_dict() for job in live_jobs]
        durable_payloads = self._list_durable_jobs(
            status=status,
            project_id=project_id,
            task_id=task_id,
        )
        merged: Dict[str, Dict[str, Any]] = {}
        for payload in durable_payloads:
            merged[payload["job_id"]] = payload
        for payload in live_payloads:
            merged[payload["job_id"]] = {**merged.get(payload["job_id"], {}), **payload}
        jobs = list(merged.values())
        if status:
            jobs = [job for job in jobs if job.get("status") == status]
        if project_id:
            jobs = [job for job in jobs if job.get("project_id") == project_id]
        if task_id:
            jobs = [job for job in jobs if job.get("task_id") == task_id]
        return jobs

    def get_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return one job record if known."""
        with self._lock:
            job = self._jobs.get(job_id)
            if job:
                durable = self._get_durable_job(job_id) or {}
                return {**durable, **job.to_dict()}
        return self._get_durable_job(job_id)

    def cancel_job(self, job_id: str, reason: Optional[str] = None) -> Dict[str, Any]:
        """Request cooperative cancellation for one in-process job."""
        with self._lock:
            record = self._jobs.get(job_id)
            if record is None:
                durable = self._get_durable_job(job_id)
                if durable is None:
                    return {
                        "error": "job_not_found",
                        "job_id": job_id,
                        "message": "No runtime MCP job exists with this ID.",
                        "registry": self.summary(),
                    }
                if durable.get("status") in TERMINAL_RUNTIME_JOB_STATUSES:
                    return {
                        "job": durable,
                        "cancel_requested": False,
                        "message": "Job is already terminal.",
                        "registry": self.summary(),
                    }
                self._persist_cancel_intent(job_id, reason)
                durable = self._get_durable_job(job_id) or durable
                return {
                    "job": durable,
                    "cancel_requested": True,
                    "cancel_signal_sent": False,
                    "hard_cancel_supported": False,
                    "controllable": False,
                    "message": (
                        "Cancellation intent persisted, but this job has no live "
                        "in-process handle in the current MCP server."
                    ),
                    "registry": self.summary(),
                }
            if record.status in TERMINAL_RUNTIME_JOB_STATUSES:
                return {
                    "job": record.to_dict(),
                    "cancel_requested": False,
                    "message": "Job is already terminal.",
                    "registry": self.summary(),
                }
            record.cancel_requested = True
            record.cancel_requested_at = datetime.now(timezone.utc).isoformat()
            record.updated_at = record.cancel_requested_at
            record.metadata["cancel_reason"] = reason
            record.status = "cancel_requested"
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
            self._persist(record)
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
        durable_jobs = self._list_durable_jobs()
        orphaned_count = sum(
            1
            for job in durable_jobs
            if not job.get("live") and job.get("metadata", {}).get("orphaned")
        )
        return {
            "type": "project_storage_backed" if self._durable_enabled else "in_process",
            "job_count": len({job["job_id"] for job in durable_jobs} | set(self._jobs)),
            "live_job_count": job_count,
            "running_count": running_count,
            "durable_job_count": len(durable_jobs),
            "orphaned_job_count": orphaned_count,
            "supports_start": True,
            "supports_cancel": True,
            "hard_cancel_supported": False,
            "durable": self._durable_enabled,
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
            record.updated_at = datetime.now(timezone.utc).isoformat()
        self._persist(record)
        try:
            result = asyncio.run(runner(record))
            with self._lock:
                record.result = result
                mapped_status = _job_status_from_result(result)
                if record.cancel_requested and mapped_status == "completed":
                    record.metadata["completed_after_cancel_requested"] = True
                record.status = mapped_status
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.updated_at = record.finished_at
                record.cancel_callback = None
            self._persist(record)
        except Exception as exc:  # pragma: no cover - defensive job boundary
            with self._lock:
                record.status = "failed"
                record.error = str(exc)
                record.finished_at = datetime.now(timezone.utc).isoformat()
                record.updated_at = record.finished_at
                record.cancel_callback = None
            self._persist(record)

    @property
    def _durable_enabled(self) -> bool:
        """Return whether ProjectManager-backed durable jobs are available."""
        return all(
            hasattr(self.project_manager, method)
            for method in (
                "upsert_runtime_job",
                "get_runtime_job",
                "list_runtime_jobs",
            )
        )

    def _persist(self, record: RunModeJobRecord) -> None:
        """Persist one live job record when ProjectManager supports it."""
        if not self._durable_enabled:
            return
        durable = build_runtime_job_record(
            job_id=record.job_id,
            kind=record.kind,
            status=record.status,
            project_id=record.project_id,
            task_id=record.task_id,
            session_id=record.metadata.get("session_id"),
            started_at=record.started_at,
            updated_at=record.updated_at,
            finished_at=record.finished_at,
            cancel_requested=record.cancel_requested,
            cancel_reason=record.metadata.get("cancel_reason"),
            result=record.result,
            error=record.error,
            metadata=record.metadata,
        )
        self.project_manager.upsert_runtime_job(durable)

    def _get_durable_job(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Return one durable job payload if present."""
        if not self._durable_enabled:
            return None
        record = self.project_manager.get_runtime_job(job_id)
        if record is None:
            return None
        payload = record.to_dict()
        live = job_id in self._jobs
        payload["live"] = live
        payload["controllable"] = (
            live and payload.get("status") not in TERMINAL_RUNTIME_JOB_STATUSES
        )
        if not live and payload.get("status") not in TERMINAL_RUNTIME_JOB_STATUSES:
            metadata = dict(payload.get("metadata") or {})
            metadata["orphaned"] = True
            metadata["orphaned_reason"] = (
                "No live in-process job handle exists in this MCP server."
            )
            payload["metadata"] = metadata
        return payload

    def _list_durable_jobs(
        self,
        *,
        status: Optional[str] = None,
        project_id: Optional[str] = None,
        task_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List durable job payloads if ProjectManager supports them."""
        if not self._durable_enabled:
            return []
        records = self.project_manager.list_runtime_jobs(
            status=status,
            project_id=project_id,
            task_id=task_id,
            limit=None,
        )
        payloads = []
        for record in records:
            payload = record.to_dict()
            live = payload["job_id"] in self._jobs
            payload["live"] = live
            payload["controllable"] = (
                live and payload.get("status") not in TERMINAL_RUNTIME_JOB_STATUSES
            )
            if not live and payload.get("status") not in TERMINAL_RUNTIME_JOB_STATUSES:
                metadata = dict(payload.get("metadata") or {})
                metadata["orphaned"] = True
                metadata["orphaned_reason"] = (
                    "No live in-process job handle exists in this MCP server."
                )
                payload["metadata"] = metadata
            payloads.append(payload)
        return payloads

    def _persist_cancel_intent(self, job_id: str, reason: Optional[str]) -> None:
        """Persist cancellation intent for a durable non-live job."""
        if not self._durable_enabled:
            return
        record = self.project_manager.get_runtime_job(job_id)
        if record is None:
            return
        record.cancel_requested = True
        record.cancel_reason = reason
        record.status = "cancel_requested"
        record.updated_at = datetime.now(timezone.utc).isoformat()
        record.metadata["cancel_request_without_live_handle"] = True
        self.project_manager.upsert_runtime_job(record)


def _job_status_from_result(result: Dict[str, Any]) -> str:
    """Map a runtime result payload to job status."""
    status = str(result.get("status") or result.get("completion_type") or "").lower()
    if status in {"error", "failed", "failure"}:
        return "failed"
    if status in {"cancelled", "canceled"}:
        return "cancelled"
    if status in {"waiting_input", "clarification_needed", "needs_input"}:
        return "waiting_input"
    if status in {"completed", "complete", "success", "succeeded", "done"}:
        return "completed"
    return status or "unknown"


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
    """Build the Slice 5B capabilities payload."""
    return {
        "runtime_tools_enabled": True,
        "slice": "5B",
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
            "Durable job records persist in ProjectStorage when ProjectManager is available.",
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
    payload = result if isinstance(result, dict) else {"result": result}
    status = _job_status_from_result(payload)
    if status == "completed":
        raw_status = str(payload.get("status") or "").lower()
        if raw_status in {"error", "failed", "failure"}:
            status = "failed"
    return {"status": status, "execution": payload}


def _resolve_project_id(core: Any, project_identifier: str) -> Optional[str]:
    """Resolve a project identifier/name to a canonical project ID when possible."""
    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return None
    get_project = getattr(project_manager, "get_project", None)
    project = get_project(project_identifier) if callable(get_project) else None
    if project is not None:
        return project.id
    get_by_name = getattr(project_manager, "get_project_by_name", None)
    if callable(get_by_name):
        project = get_by_name(project_identifier)
        if project is not None:
            return project.id
    return None


def _resolve_task_project_id(core: Any, task_id: str) -> Optional[str]:
    """Resolve the project ID for a task when ProjectManager is available."""
    project_manager = getattr(core, "project_manager", None)
    if project_manager is None:
        return None
    get_task = getattr(project_manager, "get_task", None)
    task = get_task(task_id) if callable(get_task) else None
    return getattr(task, "project_id", None) if task is not None else None


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
    project_manager = getattr(core, "project_manager", None)
    job_registry = registry or RunModeJobRegistry(project_manager=project_manager)

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
        canonical_project_id = _resolve_task_project_id(core, str(task_id)) or arguments.get("project_id")
        return job_registry.start_job(
            kind="task",
            runner=lambda job: _execute_task_job(core, arguments, job),
            task_id=str(task_id),
            project_id=canonical_project_id,
            metadata={
                "project_lookup": arguments.get("project_id"),
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
        canonical_project_id = _resolve_task_project_id(core, str(task_id)) or arguments.get("project_id")
        return job_registry.start_job(
            kind="clarification_resume",
            runner=lambda job: _resume_clarification_job(core, arguments, job),
            task_id=str(task_id),
            project_id=canonical_project_id,
            metadata={
                "project_lookup": arguments.get("project_id"),
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
        canonical_project_id = _resolve_project_id(core, str(project_identifier)) or str(project_identifier)
        return job_registry.start_job(
            kind="project",
            runner=lambda job: _execute_project_job(core, arguments, job),
            project_id=canonical_project_id,
            metadata={
                "project_lookup": str(project_identifier),
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
            description="List durable and live RunMode MCP jobs with optional filters.",
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
            description="Return one durable/live RunMode MCP job by ID if it exists.",
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
