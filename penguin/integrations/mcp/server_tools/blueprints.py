"""Blueprint MCP server tools for Penguin."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.blueprint_parser import BlueprintParser
from penguin.project.models import Blueprint
from penguin.web.services.blueprint_payloads import (
    blueprint_graph_to_dot,
    serialize_blueprint_diagnostics_report,
    serialize_blueprint_graph,
    serialize_blueprint_summary,
)
from penguin.web.services.project_payloads import (
    serialize_project_payload,
    serialize_task_payload,
)


def build_blueprint_tools(core: Any) -> list[MCPServerTool]:
    """Build default-on Blueprint introspection tools."""
    project_manager = getattr(core, "project_manager", None)

    def lint_blueprint(arguments: dict[str, Any]) -> dict[str, Any]:
        blueprint, source = _parse_blueprint(arguments)
        parser = BlueprintParser(base_path=_base_path_for_source(source))
        report = parser.lint_blueprint(blueprint, source=source)
        payload = {
            "source": source,
            "blueprint": serialize_blueprint_summary(blueprint),
            "diagnostics": serialize_blueprint_diagnostics_report(report),
        }
        if bool(arguments.get("include_graph", False)):
            payload["graph"] = serialize_blueprint_graph(blueprint)
        return payload

    def graph_blueprint(arguments: dict[str, Any]) -> dict[str, Any]:
        blueprint, source = _parse_blueprint(arguments)
        graph = serialize_blueprint_graph(blueprint)
        output_format = _optional_str(arguments.get("output_format")) or "json"
        payload: dict[str, Any] = {
            "source": source,
            "blueprint": serialize_blueprint_summary(blueprint),
            "graph": graph,
        }
        if output_format.lower() == "dot":
            payload["dot"] = blueprint_graph_to_dot(graph)
        return payload

    def blueprint_status(arguments: dict[str, Any]) -> dict[str, Any]:
        if project_manager is None:
            return {"error": "project_manager_unavailable"}
        project_id = _required_str(arguments, "project_id")
        project = project_manager.get_project(project_id)
        if project is None:
            return {"error": "project_not_found", "project_id": project_id}
        tasks = project_manager.list_tasks(project_id=project_id)
        blueprint_tasks = [task for task in tasks if getattr(task, "blueprint_id", None)]
        stats = project_manager.get_dag_stats(project_id)
        payload: dict[str, Any] = {
            "project_id": project_id,
            "project_name": project.name,
            "stats": stats,
            "blueprint_task_count": len(blueprint_tasks),
            "blueprint_ids": [task.blueprint_id for task in blueprint_tasks],
        }
        if bool(arguments.get("include_tasks", False)):
            payload["tasks"] = [
                serialize_task_payload(task) for task in blueprint_tasks
            ]
        return payload

    def sync_blueprint(arguments: dict[str, Any]) -> dict[str, Any]:
        if project_manager is None:
            return {"error": "project_manager_unavailable"}

        blueprint, source = _parse_blueprint(arguments)
        parser = BlueprintParser(base_path=_base_path_for_source(source))
        report = parser.lint_blueprint(blueprint, source=source)
        diagnostics = serialize_blueprint_diagnostics_report(report)
        summary = serialize_blueprint_summary(blueprint)
        if report.has_errors:
            return {
                "status": "rejected",
                "reason": "lint_errors",
                "source": source,
                "blueprint": summary,
                "diagnostics": diagnostics,
            }
        if not blueprint.items:
            return {
                "status": "rejected",
                "reason": "empty_blueprint",
                "source": source,
                "blueprint": summary,
                "diagnostics": diagnostics,
            }

        project_id = _optional_str(arguments.get("project_id"))
        create_project = _optional_bool(arguments.get("create_project"), False)
        dry_run = _optional_bool(arguments.get("dry_run"), True)
        create_missing = _optional_bool(arguments.get("create_missing"), True)
        update_existing = _optional_bool(arguments.get("update_existing"), False)
        include_tasks = _optional_bool(arguments.get("include_tasks"), False)

        if project_id is None and not create_project:
            return {
                "status": "rejected",
                "reason": "project_id_required",
                "message": "project_id is required unless create_project is true.",
                "source": source,
                "blueprint": summary,
                "diagnostics": diagnostics,
            }

        if dry_run:
            return _build_sync_dry_run_payload(
                project_manager=project_manager,
                blueprint=blueprint,
                source=source,
                diagnostics=diagnostics,
                project_id=project_id,
                create_project=create_project,
                create_missing=create_missing,
                update_existing=update_existing,
            )

        result = project_manager.sync_blueprint(
            blueprint,
            project_id=project_id,
            create_missing=create_missing,
            update_existing=update_existing,
        )
        synced_project = project_manager.get_project(result["project_id"])
        payload: dict[str, Any] = {
            "status": "synced",
            "source": source,
            "blueprint": summary,
            "diagnostics": diagnostics,
            "sync": result,
            "options": {
                "create_missing": create_missing,
                "update_existing": update_existing,
            },
        }
        if synced_project is not None:
            payload["project"] = serialize_project_payload(synced_project)
        if include_tasks:
            payload["tasks"] = [
                serialize_task_payload(task)
                for task in project_manager.list_tasks(project_id=result["project_id"])
            ]
        return payload


    return [
        MCPServerTool(
            name="penguin_blueprint_lint",
            description="Parse and lint a Penguin Blueprint file or content.",
            input_schema=_schema(
                {
                    "blueprint_path": {"type": "string"},
                    "content": {"type": "string"},
                    "format": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace_path": {"type": "string"},
                    "include_graph": {"type": "boolean"},
                }
            ),
            handler=lint_blueprint,
        ),
        MCPServerTool(
            name="penguin_blueprint_graph",
            description="Return a Penguin Blueprint dependency graph as JSON and optionally DOT.",
            input_schema=_schema(
                {
                    "blueprint_path": {"type": "string"},
                    "content": {"type": "string"},
                    "format": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace_path": {"type": "string"},
                    "output_format": {"type": "string"},
                }
            ),
            handler=graph_blueprint,
        ),
        MCPServerTool(
            name="penguin_blueprint_status",
            description="Report Blueprint-derived task/DAG status for a Penguin project.",
            input_schema=_schema(
                {
                    "project_id": {"type": "string"},
                    "include_tasks": {"type": "boolean"},
                },
                required=["project_id"],
            ),
            handler=blueprint_status,
        ),
        MCPServerTool(
            name="penguin_blueprint_sync",
            description=(
                "Dry-run or sync a Penguin Blueprint into project tasks without "
                "starting execution. Defaults to dry_run=true and update_existing=false."
            ),
            input_schema=_schema(
                {
                    "blueprint_path": {"type": "string"},
                    "content": {"type": "string"},
                    "format": {"type": "string"},
                    "source": {"type": "string"},
                    "workspace_path": {"type": "string"},
                    "project_id": {"type": "string"},
                    "create_project": {"type": "boolean"},
                    "dry_run": {"type": "boolean"},
                    "create_missing": {"type": "boolean"},
                    "update_existing": {"type": "boolean"},
                    "include_tasks": {"type": "boolean"},
                }
            ),
            handler=sync_blueprint,
        ),
    ]


def _build_sync_dry_run_payload(
    *,
    project_manager: Any,
    blueprint: Any,
    source: str,
    diagnostics: dict[str, Any],
    project_id: Optional[str],
    create_project: bool,
    create_missing: bool,
    update_existing: bool,
) -> dict[str, Any]:
    project = None
    existing_tasks = []
    if project_id is not None:
        project = project_manager.get_project(project_id)
        if project is None:
            return {
                "status": "rejected",
                "reason": "project_not_found",
                "project_id": project_id,
                "source": source,
                "blueprint": serialize_blueprint_summary(blueprint),
                "diagnostics": diagnostics,
            }
        existing_tasks = project_manager.list_tasks(project_id=project_id)

    existing_by_blueprint = {
        task.blueprint_id: task
        for task in existing_tasks
        if getattr(task, "blueprint_id", None)
    }
    created: list[str] = []
    updated: list[str] = []
    skipped: list[str] = []
    for item in blueprint.items:
        existing = existing_by_blueprint.get(item.id)
        if existing is not None:
            if update_existing:
                updated.append(item.id)
            else:
                skipped.append(item.id)
        elif create_missing:
            created.append(item.id)
        else:
            skipped.append(item.id)

    payload: dict[str, Any] = {
        "status": "dry_run",
        "source": source,
        "blueprint": serialize_blueprint_summary(blueprint),
        "diagnostics": diagnostics,
        "would_create_project": project_id is None and create_project,
        "project_id": project_id,
        "options": {
            "create_missing": create_missing,
            "update_existing": update_existing,
        },
        "sync": {
            "project_id": project_id,
            "blueprint_title": blueprint.title,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total_items": len(blueprint.items),
        },
    }
    if project is not None:
        payload["project"] = serialize_project_payload(project)
    return payload


def _parse_blueprint(arguments: dict[str, Any]) -> tuple[Blueprint, str]:
    content = _optional_str(arguments.get("content"))
    fmt = (_optional_str(arguments.get("format")) or "markdown").lower()
    if content is not None:
        source = _optional_str(arguments.get("source")) or "inline-blueprint"
        parser = BlueprintParser()
        return _parse_content(parser, content, fmt, source), source

    blueprint_path = _optional_str(arguments.get("blueprint_path"))
    if blueprint_path is None:
        raise ValueError("blueprint_path or content is required")
    workspace_root = Path(
        _optional_str(arguments.get("workspace_path")) or Path.cwd()
    ).expanduser().resolve()
    path = (workspace_root / blueprint_path).expanduser().resolve()
    if not _is_relative_to(path, workspace_root):
        raise PermissionError(f"Blueprint file is outside workspace: {path}")
    if not path.exists():
        raise FileNotFoundError(f"Blueprint file not found: {path}")
    parser = BlueprintParser(base_path=path.parent)
    return parser.parse_file(path), str(path)


def _parse_content(
    parser: BlueprintParser, content: str, fmt: str, source: str
) -> Blueprint:
    if fmt == "yaml":
        return parser.parse_yaml(content, source=source)
    if fmt == "json":
        return parser.parse_json(content, source=source)
    if fmt == "markdown":
        return parser.parse_markdown(content, source=source)
    raise ValueError("format must be one of markdown, yaml, or json")


def _is_relative_to(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _base_path_for_source(source: str) -> Optional[Path]:
    path = Path(source)
    return path.parent if path.exists() else None


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
    value = _optional_str(arguments.get(key))
    if value is None:
        raise ValueError(f"{key} is required")
    return value


def _optional_str(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    return str(value)


def _optional_bool(value: Any, default: bool) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"1", "true", "yes", "on"}
    return bool(value)


__all__ = ["build_blueprint_tools"]
