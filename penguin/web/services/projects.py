from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from penguin.config import GITHUB_REPOSITORY, WORKSPACE_PATH

from fastapi import HTTPException

from penguin.core import PenguinCore
from penguin.system.execution_context import (
    ExecutionContext,
    execution_context_scope,
    normalize_directory,
)
from penguin.project.blueprint_parser import (
    BlueprintDiagnostic,
    BlueprintDiagnosticsReport,
    BlueprintParseError,
    BlueprintParser,
)
from penguin.project.exceptions import ValidationError
from penguin.project.git_manager import GitManager
from penguin.project.spec_parser import parse_project_specification_from_markdown
from penguin.project.task_executor import ProjectTaskExecutor
from penguin.project.validation_manager import ValidationManager
from penguin.project.workflow_orchestrator import WorkflowOrchestrator


def _delete_project_and_tasks(core: PenguinCore, project_id: str) -> None:
    """Delete a project and its tasks for bootstrap rollback paths."""
    tasks = core.project_manager.list_tasks(project_id=project_id)
    for task in tasks:
        core.project_manager.storage.delete_task(task.id)
    core.project_manager.storage.delete_project(project_id)


def _serialize_diagnostic(diagnostic: BlueprintDiagnostic) -> Dict[str, Any]:
    """Return a JSON-safe diagnostic payload."""
    if hasattr(diagnostic, "to_dict"):
        return diagnostic.to_dict()
    return dict(diagnostic.__dict__)


def _bootstrap_failure_detail(
    message: str,
    diagnostics: Optional[BlueprintDiagnosticsReport] = None,
) -> Dict[str, Any]:
    """Build a consistent rollback response payload."""
    detail: Dict[str, Any] = {"message": message}
    if diagnostics is not None:
        detail["diagnostics"] = [
            _serialize_diagnostic(diagnostic)
            for diagnostic in diagnostics.diagnostics
        ]
    return detail


def _build_empty_blueprint_report(source: str) -> BlueprintDiagnosticsReport:
    """Return an error report for effectively empty Blueprint imports."""
    return BlueprintDiagnosticsReport(
        diagnostics=[
            BlueprintDiagnostic(
                code="BP-LINT-004",
                severity="error",
                message="Blueprint does not define any importable tasks.",
                source=source,
                suggestion="Add at least one task under the Tasks section before initializing a project.",
            )
        ]
    )


def resolve_project_identifier(core: PenguinCore, project_identifier: str):
    """Resolve a project by exact ID or exact unique name."""
    project = core.project_manager.get_project(project_identifier)
    if project:
        return project

    by_name = core.project_manager.get_project_by_name(project_identifier)
    if by_name:
        return by_name

    projects = core.project_manager.list_projects()
    matches = [project for project in projects if project.name == project_identifier]
    if len(matches) > 1:
        raise HTTPException(
            status_code=400,
            detail=f"Ambiguous project name '{project_identifier}'. Use the project ID instead.",
        )

    raise HTTPException(
        status_code=404,
        detail=f"Project '{project_identifier}' was not found by exact ID or exact name.",
    )


async def initialize_project_from_blueprint(
    *,
    core: PenguinCore,
    name: str,
    description: Optional[str],
    workspace_path: Optional[str],
    blueprint_path: Optional[str],
) -> Dict[str, Any]:
    """Create a project and optionally parse/lint/sync a Blueprint into it."""
    try:
        project = await core.project_manager.create_project_async(
            name=name,
            description=description or f"Project: {name}",
            workspace_path=Path(workspace_path).expanduser().resolve() if workspace_path else None,
        )
    except ValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    response: Dict[str, Any] = {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
            "workspace_path": project.workspace_path,
            "created_at": project.created_at,
        }
    }

    if not blueprint_path:
        return response

    blueprint_file = Path(blueprint_path).expanduser().resolve()

    try:
        parser = BlueprintParser(base_path=blueprint_file.parent)
        blueprint = parser.parse_file(blueprint_file)
        diagnostics = parser.lint_blueprint(blueprint, source=str(blueprint_file))
        if diagnostics.has_errors:
            _delete_project_and_tasks(core, project.id)
            raise HTTPException(
                status_code=400,
                detail=_bootstrap_failure_detail(
                    "Blueprint validation failed. Project initialization rolled back.",
                    diagnostics,
                ),
            )

        if not blueprint.items:
            empty_report = _build_empty_blueprint_report(str(blueprint_file))
            _delete_project_and_tasks(core, project.id)
            raise HTTPException(
                status_code=400,
                detail=_bootstrap_failure_detail(
                    "Blueprint import produced no tasks. Project initialization rolled back.",
                    empty_report,
                ),
            )

        sync_result = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: core.project_manager.sync_blueprint(
                blueprint,
                project_id=project.id,
                create_missing=True,
                update_existing=True,
            ),
        )
        ready_tasks = await core.project_manager.get_ready_tasks_async(project.id)
        response["blueprint"] = {
            "path": str(blueprint_file),
            "tasks_created": len(sync_result.get("created", [])),
            "tasks_updated": len(sync_result.get("updated", [])),
            "tasks_skipped": len(sync_result.get("skipped", [])),
            "ready_tasks": len(ready_tasks),
            "warnings": [
                _serialize_diagnostic(diagnostic)
                for diagnostic in diagnostics.diagnostics
                if getattr(diagnostic, "severity", None) == "warning"
            ],
        }
        return response
    except BlueprintParseError as exc:
        _delete_project_and_tasks(core, project.id)
        raise HTTPException(
            status_code=400,
            detail=_bootstrap_failure_detail(
                f"Blueprint parse failed: {exc}",
            ),
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        _delete_project_and_tasks(core, project.id)
        raise HTTPException(status_code=500, detail=f"Error initializing project: {exc}") from exc


async def start_project_execution(
    *,
    core: PenguinCore,
    project_identifier: str,
    continuous: bool,
    time_limit: Optional[int],
    session_id: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Start project-scoped execution through the real RunMode path."""
    project = resolve_project_identifier(core, project_identifier)
    tasks = await core.project_manager.list_tasks_async(project_id=project.id)
    if not tasks:
        raise HTTPException(
            status_code=400,
            detail=f"Project '{project.name}' has no tasks. Initialize or import a Blueprint first.",
        )

    ready_tasks = await core.project_manager.get_ready_tasks_async(project.id)
    if not ready_tasks:
        raise HTTPException(
            status_code=400,
            detail=f"Project '{project.name}' has no ready tasks to execute.",
        )

    resolved_directory = normalize_directory(directory) or normalize_directory(project.workspace_path)
    execution_context = ExecutionContext(
        session_id=session_id,
        conversation_id=session_id,
        directory=resolved_directory,
        project_root=resolved_directory,
        workspace_root=resolved_directory,
        request_id=f"project-start:{project.id}",
    )

    with execution_context_scope(execution_context):
        result = await core.start_run_mode(
            name=project.name,
            description=project.description,
            context={
                "project_id": project.id,
                "session_id": session_id,
                "conversation_id": session_id,
                "directory": resolved_directory,
            },
            continuous=continuous,
            time_limit=time_limit,
            mode_type="project",
        )

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
        },
        "execution": {
            "mode": "continuous" if continuous else "single-selection",
            "time_limit": time_limit,
            "ready_tasks": len(ready_tasks),
            "first_ready_task": ready_tasks[0].title if ready_tasks else None,
            "result": result,
            "session_id": session_id,
            "directory": resolved_directory,
        },
    }


async def delete_project_with_tasks(*, core: PenguinCore, project_id: str) -> Dict[str, Any]:
    """Delete a project and its tasks, returning a truthful summary."""
    project = await core.project_manager.get_project_async(project_id)
    if not project:
        raise HTTPException(status_code=404, detail=f"Project {project_id} not found")

    tasks = await core.project_manager.list_tasks_async(project_id=project.id)
    _delete_project_and_tasks(core, project.id)

    return {
        "project": {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "status": project.status,
        },
        "deleted_tasks": len(tasks),
        "message": f"Project '{project.name}' deleted successfully.",
    }


async def run_project_workflow(
    *,
    core: PenguinCore,
    spec_path: Optional[str],
    markdown_content: Optional[str],
    continuous: bool,
    time_limit: Optional[int],
    session_id: Optional[str] = None,
    directory: Optional[str] = None,
) -> Dict[str, Any]:
    """Parse a project spec into tasks, then start the resulting project.

    This is intentionally provisional. The preferred product flow is explicit
    `project init` followed by `project start` until legacy `project run`
    semantics are repaired into a crisp cross-surface contract.
    """
    has_spec_path = bool(spec_path and spec_path.strip())
    has_markdown_content = bool(markdown_content and markdown_content.strip())
    if not has_spec_path and not has_markdown_content:
        raise HTTPException(
            status_code=400,
            detail="Provide either spec_path or markdown_content to run a project workflow.",
        )

    if has_markdown_content:
        markdown_source = str(markdown_content)
        source_label = "inline_markdown"
    else:
        spec_file = Path(str(spec_path)).expanduser().resolve()
        if not spec_file.exists() or not spec_file.is_file():
            raise HTTPException(status_code=404, detail=f"Spec file '{spec_path}' was not found.")
        markdown_source = spec_file.read_text()
        source_label = str(spec_file)

    parse_result = await parse_project_specification_from_markdown(
        markdown_content=markdown_source,
        project_manager=core.project_manager,
    )
    if parse_result.get("status") != "success":
        raise HTTPException(
            status_code=400,
            detail={
                "message": parse_result.get("message", "Project spec parsing failed."),
                "source": source_label,
            },
        )

    creation_result = parse_result.get("creation_result") or {}
    project_payload = creation_result.get("project") or {}
    project_id = project_payload.get("id")
    if not project_id:
        raise HTTPException(
            status_code=500,
            detail="Project run parse result did not include a created project ID.",
        )

    execution = await start_project_execution(
        core=core,
        project_identifier=project_id,
        continuous=continuous,
        time_limit=time_limit,
        session_id=session_id,
        directory=directory,
    )

    return {
        "source": source_label,
        "parse": parse_result,
        "execution": execution,
    }
