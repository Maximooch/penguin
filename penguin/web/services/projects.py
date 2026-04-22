from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any, Dict, Optional

from fastapi import HTTPException

from penguin.core import PenguinCore
from penguin.project.blueprint_parser import BlueprintParseError, BlueprintParser


def _delete_project_and_tasks(core: PenguinCore, project_id: str) -> None:
    """Delete a project and its tasks for bootstrap rollback paths."""
    tasks = core.project_manager.list_tasks(project_id=project_id)
    for task in tasks:
        core.project_manager.storage.delete_task(task.id)
    core.project_manager.storage.delete_project(project_id)


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
    project = await core.project_manager.create_project_async(
        name=name,
        description=description or f"Project: {name}",
        workspace_path=Path(workspace_path).expanduser().resolve() if workspace_path else None,
    )

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
                detail={
                    "message": "Blueprint validation failed. Project initialization rolled back.",
                    "diagnostics": [d.to_dict() if hasattr(d, 'to_dict') else d.__dict__ for d in diagnostics.diagnostics],
                },
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
                d.to_dict() if hasattr(d, 'to_dict') else d.__dict__
                for d in diagnostics.diagnostics
                if getattr(d, 'severity', None) == 'warning'
            ],
        }
        return response
    except BlueprintParseError as exc:
        _delete_project_and_tasks(core, project.id)
        raise HTTPException(status_code=400, detail=f"Blueprint parse failed: {exc}") from exc
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

    result = await core.start_run_mode(
        name=project.name,
        description=project.description,
        context={"project_id": project.id},
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
        },
    }
