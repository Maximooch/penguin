"""Shared Blueprint payload serializers for web and MCP surfaces."""

from __future__ import annotations

from typing import Any


def serialize_blueprint_diagnostic(diagnostic: Any) -> dict[str, Any]:
    """Return a JSON-safe Blueprint diagnostic payload."""
    if hasattr(diagnostic, "to_dict"):
        return diagnostic.to_dict()
    return {
        "code": getattr(diagnostic, "code", None),
        "severity": getattr(diagnostic, "severity", None),
        "message": getattr(diagnostic, "message", None),
        "source": getattr(diagnostic, "source", None),
        "line": getattr(diagnostic, "line", None),
        "task_id": getattr(diagnostic, "task_id", None),
        "suggestion": getattr(diagnostic, "suggestion", None),
    }


def serialize_blueprint_diagnostics_report(report: Any) -> dict[str, Any]:
    """Serialize a Blueprint diagnostics report."""
    diagnostics = [
        serialize_blueprint_diagnostic(diagnostic)
        for diagnostic in getattr(report, "diagnostics", [])
    ]
    return {
        "has_errors": bool(getattr(report, "has_errors", False)),
        "has_warnings": bool(getattr(report, "has_warnings", False)),
        "diagnostics": diagnostics,
        "error_count": sum(
            1 for item in diagnostics if item.get("severity") == "error"
        ),
        "warning_count": sum(
            1 for item in diagnostics if item.get("severity") == "warning"
        ),
    }


def serialize_blueprint_summary(blueprint: Any) -> dict[str, Any]:
    """Serialize high-signal Blueprint metadata without dumping full content."""
    items = list(getattr(blueprint, "items", []) or [])
    return {
        "title": getattr(blueprint, "title", None),
        "project_key": getattr(blueprint, "project_key", None),
        "version": getattr(blueprint, "version", None),
        "status": getattr(blueprint, "status", None),
        "item_count": len(items),
        "labels": list(getattr(blueprint, "labels", []) or []),
        "owners": list(getattr(blueprint, "owners", []) or []),
        "ituv_enabled": getattr(blueprint, "ituv_enabled", None),
        "default_agent_role": getattr(blueprint, "default_agent_role", None),
        "default_required_tools": list(
            getattr(blueprint, "default_required_tools", []) or []
        ),
        "default_skills": list(getattr(blueprint, "default_skills", []) or []),
        "recipes": list(getattr(blueprint, "recipes", []) or []),
        "validation": list(getattr(blueprint, "validation", []) or []),
    }


def serialize_blueprint_graph(blueprint: Any) -> dict[str, Any]:
    """Serialize Blueprint task dependency graph as nodes and edges."""
    nodes = []
    edges = []
    for item in getattr(blueprint, "items", []) or []:
        nodes.append(
            {
                "id": item.id,
                "title": item.title,
                "priority": getattr(item, "priority", None),
                "acceptance_criteria_count": len(
                    getattr(item, "acceptance_criteria", []) or []
                ),
                "parallelizable": bool(getattr(item, "parallelizable", False)),
                "batch": getattr(item, "batch", None),
                "recipe": getattr(item, "recipe", None),
            }
        )
        dependency_specs = list(getattr(item, "dependency_specs", []) or [])
        if dependency_specs:
            for spec in dependency_specs:
                edges.append(
                    {
                        "from": spec.task_id,
                        "to": item.id,
                        "policy": getattr(spec.policy, "value", spec.policy),
                        "artifact_key": getattr(spec, "artifact_key", None),
                    }
                )
        else:
            for dependency_id in getattr(item, "depends_on", []) or []:
                edges.append(
                    {
                        "from": dependency_id,
                        "to": item.id,
                        "policy": "completion_required",
                        "artifact_key": None,
                    }
                )
    return {"nodes": nodes, "edges": edges}


def _escape_dot(value: object) -> str:
    """Escape a value for safe insertion into quoted DOT strings."""
    return (
        str(value)
        .replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\r", "\\n")
        .replace("\n", "\\n")
    )


def blueprint_graph_to_dot(graph: dict[str, Any]) -> str:
    """Render a serialized Blueprint graph as DOT."""
    lines = ["digraph BlueprintDAG {", "  rankdir=LR;", "  node [shape=box];"]
    for node in graph.get("nodes", []):
        node_id = _escape_dot(node.get("id") or "")
        label = _escape_dot(str(node.get("title") or node.get("id") or "")[:40])
        lines.append(f'  "{node_id}" [label="{label}"];')
    for edge in graph.get("edges", []):
        source = _escape_dot(edge.get("from") or "")
        target = _escape_dot(edge.get("to") or "")
        label = _escape_dot(edge.get("policy") or "")
        lines.append(f'  "{source}" -> "{target}" [label="{label}"];')
    lines.append("}")
    return "\n".join(lines)


__all__ = [
    "blueprint_graph_to_dot",
    "serialize_blueprint_diagnostic",
    "serialize_blueprint_diagnostics_report",
    "serialize_blueprint_graph",
    "serialize_blueprint_summary",
]
