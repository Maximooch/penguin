"""Blueprint MCP server tools for Penguin."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Optional

from penguin.integrations.mcp.server_tools.base import MCPServerTool
from penguin.project.blueprint_parser import BlueprintParseError, BlueprintParser
from penguin.web.services.blueprint_payloads import (
    blueprint_graph_to_dot,
    serialize_blueprint_diagnostics_report,
    serialize_blueprint_graph,
    serialize_blueprint_summary,
)
from penguin.web.services.project_payloads import serialize_task_payload


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
    ]


def _parse_blueprint(arguments: dict[str, Any]):
    content = _optional_str(arguments.get("content"))
    fmt = (_optional_str(arguments.get("format")) or "markdown").lower()
    if content is not None:
        source = _optional_str(arguments.get("source")) or "inline-blueprint"
        parser = BlueprintParser()
        return _parse_content(parser, content, fmt, source), source

    blueprint_path = _optional_str(arguments.get("blueprint_path"))
    if blueprint_path is None:
        raise ValueError("blueprint_path or content is required")
    path = Path(blueprint_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"Blueprint file not found: {path}")
    parser = BlueprintParser(base_path=path.parent)
    return parser.parse_file(path), str(path)


def _parse_content(
    parser: BlueprintParser, content: str, fmt: str, source: str
):
    try:
        if fmt == "yaml":
            return parser.parse_yaml(content, source=source)
        if fmt == "json":
            return parser.parse_json(content, source=source)
        if fmt == "markdown":
            return parser.parse_markdown(content, source=source)
    except BlueprintParseError:
        raise
    raise ValueError("format must be one of markdown, yaml, or json")


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


__all__ = ["build_blueprint_tools"]
