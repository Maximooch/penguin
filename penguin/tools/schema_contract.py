"""Model-visible tool schema and runtime metadata contracts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


MODEL_VISIBLE_TOOL_REQUIRED_FIELDS = ("name", "description", "input_schema")


@dataclass(frozen=True)
class ToolRuntimeMetadata:
    """Conservative runtime metadata used before scheduling policy decisions."""

    mutates_state: bool = True
    requires_approval: bool = True
    parallel_safe: bool = False
    risk: str = "unknown"
    long_running: bool = False
    streams_output: bool = False
    retry_safe: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable metadata dictionary."""

        return {
            "mutates_state": self.mutates_state,
            "requires_approval": self.requires_approval,
            "parallel_safe": self.parallel_safe,
            "risk": self.risk,
            "long_running": self.long_running,
            "streams_output": self.streams_output,
            "retry_safe": self.retry_safe,
        }


def render_tool_usage_guidance(tool_schema: Dict[str, Any]) -> str:
    """Render concise model-facing usage guidance from a tool schema."""

    name = str(tool_schema.get("name") or "tool").strip() or "tool"
    input_schema = tool_schema.get("input_schema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}

    properties = input_schema.get("properties")
    property_names = (
        sorted(str(key) for key in properties.keys())
        if isinstance(properties, dict)
        else []
    )
    required = input_schema.get("required")
    required_names = (
        sorted(str(item) for item in required)
        if isinstance(required, list)
        else []
    )

    parts = [f"Call `{name}` with JSON arguments matching its input schema."]
    if required_names:
        parts.append(f"Required fields: {', '.join(required_names)}.")
    if property_names:
        parts.append(f"Available fields: {', '.join(property_names)}.")
    return " ".join(parts)


def normalize_model_visible_tool_schema(
    tool_schema: Dict[str, Any],
) -> Dict[str, Any]:
    """Return a schema with Penguin's minimum model-visible contract."""

    normalized = dict(tool_schema)
    normalized["name"] = str(normalized.get("name") or "").strip()
    description = str(normalized.get("description") or "").strip()
    if not description and normalized["name"]:
        description = f"Tool `{normalized['name']}`."
    normalized["description"] = description
    input_schema = normalized.get("input_schema")
    if not isinstance(input_schema, dict):
        input_schema = {"type": "object", "properties": {}}
    normalized["input_schema"] = input_schema
    usage = normalized.get("usage")
    if not isinstance(usage, str) or not usage.strip():
        normalized["usage"] = render_tool_usage_guidance(normalized)
    return normalized


def validate_model_visible_tool_schema(
    tool_schema: Dict[str, Any],
) -> List[str]:
    """Return validation errors for Penguin's minimum model-visible contract."""

    errors: List[str] = []
    normalized = normalize_model_visible_tool_schema(tool_schema)
    if not normalized["name"]:
        errors.append("missing name")
    if not normalized["description"]:
        errors.append("missing description")
    if not isinstance(normalized.get("input_schema"), dict):
        errors.append("missing input_schema")
    if not str(normalized.get("usage") or "").strip():
        errors.append("missing usage guidance")
    return errors


def runtime_metadata_from_tool_schema(
    tool_schema: Dict[str, Any],
) -> ToolRuntimeMetadata:
    """Extract conservative runtime metadata from a tool schema."""

    raw_metadata = tool_schema.get("x-penguin-permissions")
    metadata = raw_metadata if isinstance(raw_metadata, dict) else {}
    risk = str(metadata.get("risk") or "unknown").strip() or "unknown"
    return ToolRuntimeMetadata(
        mutates_state=bool(metadata.get("mutates_state", True)),
        requires_approval=bool(metadata.get("requires_approval", True)),
        parallel_safe=bool(metadata.get("parallel_safe", False)),
        risk=risk,
        long_running=bool(metadata.get("long_running", False)),
        streams_output=bool(metadata.get("streams_output", False)),
        retry_safe=bool(metadata.get("retry_safe", False)),
    )


__all__ = [
    "MODEL_VISIBLE_TOOL_REQUIRED_FIELDS",
    "ToolRuntimeMetadata",
    "normalize_model_visible_tool_schema",
    "render_tool_usage_guidance",
    "runtime_metadata_from_tool_schema",
    "validate_model_visible_tool_schema",
]
