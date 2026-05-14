"""Provider-neutral tool-call runtime primitives.

This module is intentionally additive. It gives the current ActionXML and
Responses paths a shared internal representation without changing the legacy
action-result dictionaries that the engine, API, and UI already consume.
"""

from __future__ import annotations

# Keep Optional/Union annotations for Python 3.9 compatibility.
# ruff: noqa: UP007
import hashlib
import inspect
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Awaitable, Callable, Literal, Optional, Union, cast

from penguin.system.execution_context import get_current_execution_context
from penguin.utils.parser import CodeActAction, parse_action

logger = logging.getLogger(__name__)

ToolCallSource = Literal["action_xml", "responses", "mcp", "internal"]
ToolResultStatus = Literal["completed", "error", "cancelled", "requires_approval"]
ToolArguments = Union[dict[str, Any], str]
TOOL_RECORD_OUTPUT_PREVIEW_CHARS = 500
TOOL_RECORD_ARGUMENT_PREVIEW_CHARS = 500
DEFAULT_TOOL_MODEL_OUTPUT_MAX_CHARS = 24_000


@dataclass(frozen=True)
class ToolCall:
    """Normalized tool call captured from any model/tool protocol."""

    id: str
    name: str
    arguments: ToolArguments
    source: ToolCallSource
    raw: Any = None
    mutates_state: bool = True
    parallel_safe: bool = False
    requires_approval: bool = True


ToolExecutor = Callable[[ToolCall], Union[Any, Awaitable[Any]]]


@dataclass(frozen=True)
class ToolResult:
    """Normalized result for a single tool call."""

    call_id: str
    name: str
    status: ToolResultStatus
    output: str
    structured_output: Optional[dict[str, Any]] = None
    started_at: float = field(default_factory=time.time)
    ended_at: float = field(default_factory=time.time)
    output_hash: str = ""
    byte_count: int = 0
    line_count: int = 0
    truncated: bool = False
    truncation_direction: str = "none"
    artifact_path: Optional[str] = None

    def __post_init__(self) -> None:
        output_text = str(self.output if self.output is not None else "")
        if not self.output_hash:
            object.__setattr__(self, "output_hash", hash_tool_output(output_text))
        if self.byte_count <= 0 and output_text:
            object.__setattr__(self, "byte_count", len(output_text.encode("utf-8")))
        if self.line_count <= 0 and output_text:
            object.__setattr__(self, "line_count", output_text.count("\n") + 1)


@dataclass(frozen=True)
class ToolCallRecord:
    """Lightweight persisted envelope for a captured tool call."""

    call_id: str
    name: str
    source: ToolCallSource
    arguments_hash: str
    arguments: Any = None
    arguments_preview: str = ""
    mutates_state: bool = True
    parallel_safe: bool = False
    requires_approval: bool = True
    created_at: float = field(default_factory=time.time)
    raw_type: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable tool-call record."""

        return {
            "record_type": "tool_call",
            "call_id": self.call_id,
            "name": self.name,
            "source": self.source,
            "arguments": self.arguments,
            "arguments_hash": self.arguments_hash,
            "arguments_preview": self.arguments_preview,
            "mutates_state": self.mutates_state,
            "parallel_safe": self.parallel_safe,
            "requires_approval": self.requires_approval,
            "created_at": self.created_at,
            "raw_type": self.raw_type,
        }


@dataclass(frozen=True)
class ToolResultRecord:
    """Lightweight persisted envelope for a completed tool result."""

    call_id: str
    name: str
    status: ToolResultStatus
    output_hash: str
    started_at: float
    ended_at: float
    byte_count: int
    line_count: int
    source: Optional[ToolCallSource] = None
    duration_ms: float = 0.0
    truncated: bool = False
    truncation_direction: str = "none"
    artifact_path: Optional[str] = None
    arguments_hash: Optional[str] = None
    output_preview: str = ""

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable tool-result record."""

        return {
            "record_type": "tool_result",
            "call_id": self.call_id,
            "name": self.name,
            "source": self.source,
            "status": self.status,
            "started_at": self.started_at,
            "ended_at": self.ended_at,
            "duration_ms": self.duration_ms,
            "output_hash": self.output_hash,
            "byte_count": self.byte_count,
            "line_count": self.line_count,
            "truncated": self.truncated,
            "truncation_direction": self.truncation_direction,
            "artifact_path": self.artifact_path,
            "arguments_hash": self.arguments_hash,
            "output_preview": self.output_preview,
        }


@dataclass(frozen=True)
class ToolOutputView:
    """Model-visible preview plus full-output artifact metadata."""

    model_output: str
    full_output: str
    truncated: bool
    byte_count: int
    line_count: int
    output_hash: str
    truncation_direction: str = "none"
    artifact_path: Optional[str] = None
    artifact_id: Optional[str] = None
    max_chars: Optional[int] = None

    def to_metadata(self) -> dict[str, Any]:
        """Return serializable output metadata for tool result records."""

        return {
            "truncated": self.truncated,
            "byte_count": self.byte_count,
            "line_count": self.line_count,
            "output_hash": self.output_hash,
            "truncation_direction": self.truncation_direction,
            "artifact_path": self.artifact_path,
            "artifact_id": self.artifact_id,
            "max_chars": self.max_chars,
        }


@dataclass(frozen=True)
class ToolLoopIdentity:
    """Stable identity for one tool-only loop iteration."""

    fingerprint: str
    entries: tuple[dict[str, Any], ...]
    summary: str


@dataclass(frozen=True)
class ToolExecutionPolicy:
    """Conservative execution policy for the serial scheduler."""

    max_calls: Optional[int] = None
    catch_exceptions: bool = False
    max_output_chars: Optional[int] = None
    artifact_dir: Optional[Union[str, Path]] = None
    truncation_direction: Literal["head", "tail", "middle"] = "tail"


def hash_tool_output(output: Any) -> str:
    """Return a stable hash for tool output identity checks."""

    output_text = str(output if output is not None else "")
    return hashlib.sha256(output_text.encode()).hexdigest()


def hash_tool_arguments(arguments: Any) -> str:
    """Return a stable hash for normalized tool arguments."""

    return hashlib.sha256(
        _stable_json(_normalize_arguments(arguments)).encode()
    ).hexdigest()


def _preview_text(value: Any, *, max_chars: int) -> str:
    """Return a bounded text preview for lightweight persisted records.

    Negative ``max_chars`` values are treated as 0 and produce an empty preview.
    """

    max_chars = max(0, max_chars)
    text = str(value if value is not None else "")
    if len(text) <= max_chars:
        return text
    return text[:max_chars]


def _render_arguments(arguments: Any) -> str:
    """Render normalized arguments as stable text for previews/replay metadata."""

    normalized = _normalize_arguments(arguments)
    if isinstance(normalized, (dict, list)):
        return _stable_json(normalized)
    return str(normalized if normalized is not None else "")


def tool_call_record_from_tool_call(tool_call: ToolCall) -> ToolCallRecord:
    """Build a lightweight persisted record for a captured tool call."""

    normalized_arguments = _normalize_arguments(tool_call.arguments)
    rendered_arguments = _render_arguments(normalized_arguments)
    return ToolCallRecord(
        call_id=tool_call.id,
        name=tool_call.name,
        source=tool_call.source,
        arguments=normalized_arguments,
        arguments_hash=hash_tool_arguments(normalized_arguments),
        arguments_preview=_preview_text(
            rendered_arguments,
            max_chars=TOOL_RECORD_ARGUMENT_PREVIEW_CHARS,
        ),
        mutates_state=tool_call.mutates_state,
        parallel_safe=tool_call.parallel_safe,
        requires_approval=tool_call.requires_approval,
        raw_type=type(tool_call.raw).__name__ if tool_call.raw is not None else "",
    )


def tool_result_record_from_tool_result(
    tool_result: ToolResult,
    *,
    tool_call: Optional[ToolCall] = None,
    arguments: Any = None,
) -> ToolResultRecord:
    """Build a lightweight persisted record for a normalized tool result."""

    resolved_arguments = tool_call.arguments if tool_call is not None else arguments
    arguments_hash = (
        hash_tool_arguments(resolved_arguments)
        if resolved_arguments is not None
        else None
    )
    duration_ms = max((tool_result.ended_at - tool_result.started_at) * 1000, 0.0)
    return ToolResultRecord(
        call_id=tool_result.call_id,
        name=tool_result.name,
        source=tool_call.source if tool_call is not None else None,
        status=tool_result.status,
        started_at=tool_result.started_at,
        ended_at=tool_result.ended_at,
        duration_ms=duration_ms,
        output_hash=tool_result.output_hash,
        byte_count=tool_result.byte_count,
        line_count=tool_result.line_count,
        truncated=tool_result.truncated,
        truncation_direction=tool_result.truncation_direction,
        artifact_path=tool_result.artifact_path,
        arguments_hash=arguments_hash,
        output_preview=_preview_text(
            tool_result.output,
            max_chars=TOOL_RECORD_OUTPUT_PREVIEW_CHARS,
        ),
    )


def tool_result_with_model_output_policy(
    tool_result: ToolResult,
    *,
    max_chars: Optional[int] = None,
    artifact_dir: Optional[Union[str, Path]] = None,
    artifact_id: Optional[str] = None,
    truncation_direction: Literal["head", "tail", "middle"] = "tail",
) -> ToolResult:
    """Return a tool result whose output is bounded for model replay."""

    if max_chars is None:
        return tool_result

    view = prepare_model_visible_tool_output(
        tool_result.output,
        max_chars=max_chars,
        artifact_dir=artifact_dir,
        artifact_id=artifact_id or tool_result.call_id,
        truncation_direction=truncation_direction,
    )
    structured_output = {
        **(tool_result.structured_output or {}),
        **view.to_metadata(),
    }
    return ToolResult(
        call_id=tool_result.call_id,
        name=tool_result.name,
        status=tool_result.status,
        output=view.model_output,
        structured_output=structured_output,
        started_at=tool_result.started_at,
        ended_at=tool_result.ended_at,
        output_hash=view.output_hash,
        byte_count=view.byte_count,
        line_count=view.line_count,
        truncated=view.truncated,
        truncation_direction=view.truncation_direction,
        artifact_path=view.artifact_path,
    )


def _line_count(output_text: str) -> int:
    """Count model-visible output lines without treating empty output as one line."""

    return output_text.count("\n") + 1 if output_text else 0


def _safe_artifact_id(artifact_id: Optional[str], output_hash: str) -> str:
    """Return a filesystem-safe artifact id."""

    raw_id = str(artifact_id or "").strip()
    if raw_id and all(char.isalnum() or char in {"-", "_", "."} for char in raw_id):
        return raw_id[:96]
    return output_hash[:16]


def _truncate_output_preview(
    output_text: str,
    *,
    budget: int,
    direction: Literal["head", "tail", "middle"],
) -> str:
    """Return a deterministic preview that fits the provided character budget."""

    if budget <= 0:
        return ""
    if len(output_text) <= budget:
        return output_text
    if direction == "head":
        return output_text[:budget]
    if direction == "middle":
        left = max(budget // 2, 0)
        right = max(budget - left, 0)
        return f"{output_text[:left]}{output_text[-right:]}"[:budget]
    return output_text[-budget:]


def prepare_model_visible_tool_output(
    output: Any,
    *,
    max_chars: Optional[int] = None,
    artifact_dir: Optional[Union[str, Path]] = None,
    artifact_id: Optional[str] = None,
    truncation_direction: Literal["head", "tail", "middle"] = "tail",
) -> ToolOutputView:
    """Build a capped model-visible tool output and optional full artifact.

    Args:
        output: Raw full tool output.
        max_chars: Maximum characters to expose to the model. ``None`` means
            no truncation.
        artifact_dir: Directory where full output should be written when
            truncation occurs.
        artifact_id: Optional stable id for the artifact filename.
        truncation_direction: Which part of the output should be retained in
            the model-visible preview.

    Returns:
        A ``ToolOutputView`` with preview, full-output metadata, and optional
        artifact path.
    """

    full_output = str(output if output is not None else "")
    output_hash = hash_tool_output(full_output)
    byte_count = len(full_output.encode("utf-8"))
    line_count = _line_count(full_output)

    if max_chars is None or len(full_output) <= max_chars:
        return ToolOutputView(
            model_output=full_output,
            full_output=full_output,
            truncated=False,
            byte_count=byte_count,
            line_count=line_count,
            output_hash=output_hash,
            artifact_id=artifact_id,
            max_chars=max_chars,
        )

    artifact_path: Optional[str] = None
    safe_id = _safe_artifact_id(artifact_id, output_hash)
    if artifact_dir is not None:
        directory = Path(artifact_dir)
        directory.mkdir(parents=True, exist_ok=True)
        path = directory / f"tool-output-{safe_id}.txt"
        path.write_text(full_output, encoding="utf-8")
        artifact_path = str(path)

    effective_max = max(int(max_chars), 0)
    notice_parts = [
        "Tool output truncated",
        f"bytes={byte_count}",
        f"lines={line_count}",
        f"hash={output_hash}",
    ]
    if artifact_path:
        notice_parts.append(f"artifact={artifact_path}")
    notice = "\n\n[" + " ".join(notice_parts) + "]"
    preview_budget = max(effective_max - len(notice), 0)
    preview = _truncate_output_preview(
        full_output,
        budget=preview_budget,
        direction=truncation_direction,
    )
    if preview_budget <= 0:
        model_output = notice[:effective_max]
    else:
        model_output = f"{preview}{notice}"[:effective_max]

    return ToolOutputView(
        model_output=model_output,
        full_output=full_output,
        truncated=True,
        byte_count=byte_count,
        line_count=line_count,
        output_hash=output_hash,
        truncation_direction=truncation_direction,
        artifact_path=artifact_path,
        artifact_id=safe_id,
        max_chars=max_chars,
    )


def _stable_json(value: Any) -> str:
    """Serialize values deterministically for identity signatures."""

    try:
        return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)
    except Exception:
        return str(value)


def _normalize_arguments(arguments: Any) -> Any:
    """Parse JSON-like argument strings while preserving non-JSON payloads."""

    if isinstance(arguments, str):
        stripped = arguments.strip()
        if not stripped:
            return ""
        try:
            return json.loads(stripped)
        except Exception:
            return stripped
    return arguments


def _first_non_none(mapping: dict[str, Any], keys: tuple[str, ...]) -> Any:
    """Return the first explicitly present non-None value from a mapping.

    Args:
        mapping: Source dictionary to inspect.
        keys: Candidate keys in priority order.

    Returns:
        The first value whose key exists and whose value is not None, preserving
        falsy values such as ``{}`` and ``""``. Returns None when no key has a
        non-None value.

    Raises:
        None. Non-dict callers should normalize before calling this helper.
    """

    for key in keys:
        if key in mapping and mapping.get(key) is not None:
            return mapping.get(key)
    return None


def _metadata_from_result(action_result: dict[str, Any]) -> dict[str, Any]:
    """Extract structured metadata from a legacy action result.

    Args:
        action_result: Legacy action-result dictionary that may include a
            ``metadata`` field.

    Returns:
        The metadata dictionary when present and dict-shaped; otherwise an
        empty dictionary.

    Raises:
        None. Non-dict metadata is treated as absent.
    """

    metadata = action_result.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def _coerce_int(value: Any, default: int = 0) -> int:
    """Convert metadata values to ints without raising on malformed records."""

    try:
        return int(value)
    except Exception:
        return default


def _tool_result_to_action_result(tool_result: ToolResult) -> dict[str, Any]:
    """Convert a normalized tool result into a legacy action-result dict.

    Args:
        tool_result: Normalized ``ToolResult`` produced by the scheduler.

    Returns:
        A legacy action-result dictionary with action, result, status,
        tool-call metadata, output hash, and structured metadata. Empty
        ``tool_arguments`` values are preserved when explicitly present.

    Raises:
        None. Missing structured output is treated as an empty dictionary.
    """

    structured_output = tool_result.structured_output or {}
    tool_arguments = _first_non_none(structured_output, ("tool_arguments", "arguments"))
    metadata = {
        **structured_output,
        "output_hash": tool_result.output_hash,
        "byte_count": tool_result.byte_count,
        "line_count": tool_result.line_count,
        "truncated": tool_result.truncated,
        "truncation_direction": tool_result.truncation_direction,
        "artifact_path": tool_result.artifact_path,
    }
    return {
        "action": tool_result.name,
        "result": tool_result.output,
        "status": tool_result.status,
        "tool_call_id": tool_result.call_id,
        "output_hash": tool_result.output_hash,
        "metadata": metadata,
        "tool_arguments": tool_arguments,
    }


def _normalize_tool_loop_input(action_result: Any) -> dict[str, Any]:
    """Normalize loop-guard input to a legacy action-result dictionary.

    Args:
        action_result: A legacy action-result dictionary, ``ToolResult``, or
            arbitrary value from older call sites.

    Returns:
        A dict suitable for loop-signature extraction. ``ToolResult`` values are
        converted to legacy result shape; non-dict unsupported values become an
        empty dict.

    Raises:
        None. Unsupported inputs are intentionally normalized to ``{}``.
    """

    if isinstance(action_result, ToolResult):
        return _tool_result_to_action_result(action_result)
    return action_result if isinstance(action_result, dict) else {}


def tool_loop_signature(action_result: Any) -> dict[str, Any]:
    """Build a loop-guard identity payload for one tool result."""

    action_result = _normalize_tool_loop_input(action_result)

    metadata = _metadata_from_result(action_result)
    arguments = _first_non_none(
        action_result, ("tool_arguments", "arguments", "params")
    )
    if arguments is None:
        arguments = _first_non_none(metadata, ("tool_arguments", "arguments", "params"))
    normalized_arguments = _normalize_arguments(arguments)
    argument_fields = (
        normalized_arguments if isinstance(normalized_arguments, dict) else {}
    )
    common_fields = {}
    for key in (
        "path",
        "file_path",
        "filePath",
        "directory",
        "query",
        "pattern",
        "start_line",
        "end_line",
        "line_start",
        "line_end",
        "limit",
        "max_lines",
        "offset",
        "recursive",
    ):
        value = action_result.get(key, metadata.get(key, argument_fields.get(key)))
        if value is not None:
            common_fields[key] = value

    output = action_result.get("result", action_result.get("output", ""))
    output_hash = (
        action_result.get("output_hash")
        or metadata.get("output_hash")
        or hash_tool_output(output)
    )
    return {
        "call_id": str(
            action_result.get("tool_call_id")
            or action_result.get("call_id")
            or metadata.get("tool_call_id")
            or metadata.get("call_id")
            or ""
        ).strip(),
        "name": str(
            action_result.get("action")
            or action_result.get("name")
            or action_result.get("action_type")
            or ""
        ).strip(),
        "status": str(action_result.get("status") or "completed").strip(),
        "arguments": normalized_arguments,
        "fields": common_fields,
        "output_hash": output_hash,
    }


def _fingerprint_entry(entry: dict[str, Any]) -> dict[str, Any]:
    """Return the stable portion of a tool-loop identity entry."""

    return {key: value for key, value in entry.items() if key != "call_id"}


def _summarize_tool_loop_entry(entry: dict[str, Any]) -> str:
    name = str(entry.get("name") or "tool").strip() or "tool"
    status = str(entry.get("status") or "completed").strip() or "completed"
    fields = entry.get("fields") if isinstance(entry.get("fields"), dict) else {}
    arguments = entry.get("arguments")

    detail_parts: list[str] = []
    for key in (
        "path",
        "file_path",
        "directory",
        "start_line",
        "end_line",
        "max_lines",
        "limit",
        "query",
        "pattern",
    ):
        value = fields.get(key)
        if value is not None:
            detail_parts.append(f"{key}={value}")

    if not detail_parts and isinstance(arguments, dict):
        for key in ("path", "file_path", "directory", "query", "pattern"):
            value = arguments.get(key)
            if value is not None:
                detail_parts.append(f"{key}={value}")

    detail = f"({', '.join(detail_parts[:4])})" if detail_parts else ""
    output_hash = str(entry.get("output_hash") or "")
    hash_preview = output_hash[:12] if output_hash else "none"
    return f"{name}{detail} status={status} output={hash_preview}"


def tool_results_loop_identity(action_results: list[Any]) -> ToolLoopIdentity:
    """Return stable identity details for one empty tool-only iteration."""

    payload = [
        tool_loop_signature(result)
        for result in action_results
        if isinstance(result, (dict, ToolResult))
    ]
    fingerprint_payload = [_fingerprint_entry(entry) for entry in payload]
    fingerprint = hashlib.sha256(_stable_json(fingerprint_payload).encode()).hexdigest()
    summary = "; ".join(_summarize_tool_loop_entry(entry) for entry in payload)
    return ToolLoopIdentity(
        fingerprint=fingerprint,
        entries=tuple(payload),
        summary=summary,
    )


def tool_results_loop_signature(action_results: list[Any]) -> str:
    """Return a deterministic signature for one empty tool-only iteration."""

    return tool_results_loop_identity(action_results).fingerprint


def tool_calls_from_actionxml(content: str) -> list[ToolCall]:
    """Convert ActionXML tags in assistant content into normalized tool calls."""

    return tool_calls_from_codeact_actions(parse_action(content))


def tool_calls_from_codeact_actions(actions: list[CodeActAction]) -> list[ToolCall]:
    """Convert parsed CodeAct actions into normalized tool calls."""

    calls: list[ToolCall] = []
    for index, action in enumerate(actions):
        name = (
            action.action_type.value
            if hasattr(action.action_type, "value")
            else str(action.action_type)
        )
        calls.append(
            ToolCall(
                id=f"action_xml_{index}_{name}",
                name=name,
                arguments=action.params,
                source="action_xml",
                raw=action,
            )
        )
    return calls


def select_tool_calls_for_policy(
    tool_calls: list[ToolCall],
    policy: Optional[ToolExecutionPolicy] = None,
) -> list[ToolCall]:
    """Select the calls a scheduler should execute under the policy."""

    active_policy = policy or ToolExecutionPolicy()
    if active_policy.max_calls is None:
        return list(tool_calls)
    return list(tool_calls[: max(active_policy.max_calls, 0)])


def _current_trace_fields() -> dict[str, str]:
    """Return active request/session fields for runtime diagnostics."""

    context = get_current_execution_context()
    if context is None:
        return {"request_id": "unknown", "session_id": "unknown"}
    return {
        "request_id": context.request_id or "unknown",
        "session_id": context.session_id or context.conversation_id or "unknown",
    }


def _argument_size(arguments: Any) -> int:
    """Return argument size in characters using stable JSON where possible."""

    return len(_render_arguments(arguments))


def _log_tool_runtime_result(
    *,
    tool_call: ToolCall,
    tool_result: ToolResult,
    duration_ms: float,
) -> None:
    """Emit a compact structured tool runtime summary."""

    fields = _current_trace_fields()
    logger.info(
        "tool.exec.done request=%s session=%s call_id=%s tool=%s source=%s "
        "status=%s duration_ms=%.2f args_chars=%s output_bytes=%s "
        "output_lines=%s truncated=%s artifact=%s",
        fields["request_id"],
        fields["session_id"],
        tool_call.id,
        tool_call.name,
        tool_call.source,
        tool_result.status,
        duration_ms,
        _argument_size(tool_call.arguments),
        tool_result.byte_count,
        tool_result.line_count,
        tool_result.truncated,
        tool_result.artifact_path,
    )


async def execute_tool_calls_serially(
    tool_calls: list[ToolCall],
    execute_call: ToolExecutor,
    *,
    policy: Optional[ToolExecutionPolicy] = None,
) -> list[ToolResult]:
    """Execute normalized tool calls serially and return normalized results."""

    active_policy = policy or ToolExecutionPolicy()
    results: list[ToolResult] = []
    for tool_call in select_tool_calls_for_policy(tool_calls, active_policy):
        started_at = time.time()
        started_perf = time.perf_counter()
        trace_fields = _current_trace_fields()
        logger.info(
            "tool.exec.start request=%s session=%s call_id=%s tool=%s source=%s "
            "args_chars=%s parallel_safe=%s mutates_state=%s",
            trace_fields["request_id"],
            trace_fields["session_id"],
            tool_call.id,
            tool_call.name,
            tool_call.source,
            _argument_size(tool_call.arguments),
            tool_call.parallel_safe,
            tool_call.mutates_state,
        )
        try:
            output = execute_call(tool_call)
            if inspect.isawaitable(output):
                output = await output
            ended_at = time.time()
            duration_ms = (time.perf_counter() - started_perf) * 1000
            if isinstance(output, ToolResult):
                result = tool_result_with_model_output_policy(
                    output,
                    max_chars=active_policy.max_output_chars,
                    artifact_dir=active_policy.artifact_dir,
                    artifact_id=tool_call.id,
                    truncation_direction=active_policy.truncation_direction,
                )
                _log_tool_runtime_result(
                    tool_call=tool_call,
                    tool_result=result,
                    duration_ms=duration_ms,
                )
                results.append(result)
                continue
            if isinstance(output, dict):
                action_output = dict(output)
                if not action_output.get("action") and not action_output.get("name"):
                    action_output["action"] = tool_call.name
                tool_result = tool_result_from_action_result(
                    action_output,
                    call_id=tool_call.id,
                    started_at=started_at,
                    ended_at=ended_at,
                    structured_output={
                        **action_output,
                        "tool_call_id": tool_call.id,
                        "tool_arguments": tool_call.arguments,
                    },
                )
                result = tool_result_with_model_output_policy(
                    tool_result,
                    max_chars=active_policy.max_output_chars,
                    artifact_dir=active_policy.artifact_dir,
                    artifact_id=tool_call.id,
                    truncation_direction=active_policy.truncation_direction,
                )
                _log_tool_runtime_result(
                    tool_call=tool_call,
                    tool_result=result,
                    duration_ms=duration_ms,
                )
                results.append(result)
                continue
            tool_result = ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                status="completed",
                output=str(output if output is not None else ""),
                started_at=started_at,
                ended_at=ended_at,
            )
            result = tool_result_with_model_output_policy(
                tool_result,
                max_chars=active_policy.max_output_chars,
                artifact_dir=active_policy.artifact_dir,
                artifact_id=tool_call.id,
                truncation_direction=active_policy.truncation_direction,
            )
            _log_tool_runtime_result(
                tool_call=tool_call,
                tool_result=result,
                duration_ms=duration_ms,
            )
            results.append(result)
        except Exception as exc:
            duration_ms = (time.perf_counter() - started_perf) * 1000
            logger.warning(
                "tool.exec.error request=%s session=%s call_id=%s tool=%s "
                "source=%s duration_ms=%.2f args_chars=%s error=%s",
                trace_fields["request_id"],
                trace_fields["session_id"],
                tool_call.id,
                tool_call.name,
                tool_call.source,
                duration_ms,
                _argument_size(tool_call.arguments),
                exc,
            )
            if not active_policy.catch_exceptions:
                raise
            tool_result = ToolResult(
                call_id=tool_call.id,
                name=tool_call.name,
                status="error",
                output=f"Error executing tool {tool_call.name}: {exc}",
                started_at=started_at,
                ended_at=time.time(),
            )
            result = tool_result_with_model_output_policy(
                tool_result,
                max_chars=active_policy.max_output_chars,
                artifact_dir=active_policy.artifact_dir,
                artifact_id=tool_call.id,
                truncation_direction=active_policy.truncation_direction,
            )
            _log_tool_runtime_result(
                tool_call=tool_call,
                tool_result=result,
                duration_ms=duration_ms,
            )
            results.append(result)
    return results


def tool_call_from_responses_info(tool_info: dict[str, Any]) -> Optional[ToolCall]:
    """Convert provider-captured Responses tool metadata into a tool call."""

    if not isinstance(tool_info, dict):
        return None

    name = str(tool_info.get("name") or "").strip()
    if not name:
        return None

    call_id = (
        tool_info.get("call_id")
        or tool_info.get("tool_call_id")
        or tool_info.get("item_id")
        or f"call_{uuid.uuid4().hex}"
    )
    raw_args = (
        tool_info.get("arguments") if tool_info.get("arguments") is not None else "{}"
    )
    arguments: ToolArguments = (
        raw_args if isinstance(raw_args, (dict, str)) else str(raw_args)
    )

    return ToolCall(
        id=str(call_id),
        name=name,
        arguments=arguments,
        source="responses",
        raw=tool_info,
    )


def _format_browser_tool_output(action_result: dict[str, Any]) -> str:
    """Return model-visible browser/read-image metadata for tool outputs.

    Native function-call tool results only replay the legacy ``result`` string
    back to the model. Browser tools need a little more: page URL/title after
    navigation, screenshot filepath, and image metadata. Keep this concise and
    stable so the tool loop guard can still recognize repeated no-op calls.
    """

    action = str(action_result.get("action") or action_result.get("name") or "")
    result = str(action_result.get("result") or action_result.get("output") or "")
    lines = [result] if result else [action]

    page_info = action_result.get("page_info")
    if isinstance(page_info, dict):
        url = page_info.get("url")
        title = page_info.get("title")
        if url:
            lines.append(f"url: {url}")
        if title:
            lines.append(f"title: {title}")
        viewport = page_info.get("viewport")
        if isinstance(viewport, dict):
            width = viewport.get("width")
            height = viewport.get("height")
            if width and height:
                lines.append(f"viewport: {width}x{height}")

    if action == "browser_open_tab":
        loaded = action_result.get("loaded")
        if loaded is not None:
            lines.append(f"loaded: {loaded}")
        lines.append(
            "next: inspect page_info or take a screenshot before retrying open_tab"
        )

    if action == "browser_harness_screenshot":
        filepath = action_result.get("filepath")
        size_bytes = action_result.get("size_bytes")
        if filepath:
            lines.append(f"filepath: {filepath}")
            lines.append(f"image_path: {filepath}")
            lines.append("next: call read_image with this filepath to inspect pixels")
        if size_bytes is not None:
            lines.append(f"size_bytes: {size_bytes}")

    if action == "read_image":
        filepath = action_result.get("filepath") or action_result.get("path")
        if filepath:
            lines.append(f"filepath: {filepath}")
            lines.append(f"image_path: {filepath}")
        width = action_result.get("width")
        height = action_result.get("height")
        if width and height:
            lines.append(f"dimensions: {width}x{height}")
        mime_type = action_result.get("mime_type")
        if mime_type:
            lines.append(f"mime_type: {mime_type}")

    if action == "browser_list_tabs":
        tabs = action_result.get("tabs")
        if isinstance(tabs, list):
            lines.append(f"tabs_count: {len(tabs)}")
        current = action_result.get("current_tab")
        if current:
            lines.append(f"current_tab: {current}")

    if action == "browser_cleanup":
        for key in ("target", "cleaned", "removed_record", "refused", "reason"):
            value = action_result.get(key)
            if value is not None:
                lines.append(f"{key}: {value}")

    return "\n".join(dict.fromkeys(line for line in lines if line))


def _model_visible_tool_output(action_result: dict[str, Any]) -> str:
    action = str(action_result.get("action") or action_result.get("name") or "")
    if action.startswith("browser_") or action == "read_image":
        return _format_browser_tool_output(action_result)
    raw_output = action_result.get("result", action_result.get("output", ""))
    return str(raw_output if raw_output is not None else "")


def tool_result_from_action_result(
    action_result: dict[str, Any],
    *,
    call_id: Optional[str] = None,
    started_at: Optional[float] = None,
    ended_at: Optional[float] = None,
    structured_output: Optional[dict[str, Any]] = None,
) -> ToolResult:
    """Convert a legacy action-result dict into a normalized tool result."""

    raw_name = action_result.get("action", action_result.get("name", ""))
    name = str(raw_name).strip()
    output = _model_visible_tool_output(action_result)
    metadata = _metadata_from_result(action_result)
    raw_status = str(action_result.get("status") or "completed").strip().lower()
    status = cast(
        ToolResultStatus,
        raw_status
        if raw_status in {"completed", "error", "cancelled", "requires_approval"}
        else "error",
    )

    return ToolResult(
        call_id=str(
            call_id
            or action_result.get("call_id")
            or action_result.get("tool_call_id")
            or name
            or "tool_call"
        ),
        name=name,
        status=status,
        output=output,
        structured_output=structured_output,
        started_at=started_at if started_at is not None else time.time(),
        ended_at=ended_at if ended_at is not None else time.time(),
        byte_count=_coerce_int(
            action_result.get("byte_count", metadata.get("byte_count")),
            default=0,
        ),
        line_count=_coerce_int(
            action_result.get("line_count", metadata.get("line_count")),
            default=0,
        ),
        truncated=bool(
            action_result.get("truncated", metadata.get("truncated", False))
        ),
        truncation_direction=str(
            action_result.get(
                "truncation_direction",
                metadata.get("truncation_direction", "none"),
            )
            or "none"
        ),
        artifact_path=(
            str(
                action_result.get(
                    "artifact_path",
                    metadata.get("artifact_path"),
                )
            )
            if action_result.get("artifact_path", metadata.get("artifact_path"))
            is not None
            else None
        ),
    )


def image_artifacts_from_action_result(
    action_result: dict[str, Any],
) -> list[dict[str, Any]]:
    """Extract model-visible image artifacts from a tool result.

    Args:
        action_result: Structured tool result, usually from browser screenshot
            or ``read_image`` tools.

    Returns:
        A list of image artifact dictionaries. Each dictionary includes at
        least ``image_path`` when extraction succeeds. Returns an empty list
        when the result has no image payload or the tool failed.
    """

    if not isinstance(action_result, dict) or action_result.get("error"):
        return []

    action = str(action_result.get("action") or action_result.get("name") or "")
    artifacts: list[dict[str, Any]] = []

    artifact = action_result.get("artifact")
    if isinstance(artifact, dict) and artifact.get("type") == "image":
        image_path = artifact.get("image_path") or artifact.get("path")
        if isinstance(image_path, str) and image_path.strip():
            artifacts.append(
                {
                    "source_action": action,
                    "image_path": image_path.strip(),
                    "mime_type": artifact.get("mime_type"),
                    "width": artifact.get("width"),
                    "height": artifact.get("height"),
                    "format": artifact.get("format"),
                }
            )

    fallback_path = action_result.get("image_path") or action_result.get("filepath")
    if action in {"browser_harness_screenshot", "read_image"}:
        if isinstance(fallback_path, str) and fallback_path.strip():
            image_path = fallback_path.strip()
            if not any(item.get("image_path") == image_path for item in artifacts):
                artifacts.append(
                    {
                        "source_action": action,
                        "image_path": image_path,
                        "mime_type": action_result.get("mime_type"),
                        "width": action_result.get("width"),
                        "height": action_result.get("height"),
                        "format": action_result.get("format"),
                    }
                )

    return artifacts


def legacy_action_result_from_tool_result(tool_result: ToolResult) -> dict[str, str]:
    """Convert a normalized tool result back to Penguin's current result shape."""

    return {
        "action": tool_result.name,
        "result": tool_result.output,
        "status": tool_result.status,
    }


__all__ = [
    "ToolArguments",
    "DEFAULT_TOOL_MODEL_OUTPUT_MAX_CHARS",
    "ToolCall",
    "ToolCallRecord",
    "ToolCallSource",
    "ToolExecutionPolicy",
    "ToolExecutor",
    "ToolLoopIdentity",
    "ToolOutputView",
    "ToolResult",
    "ToolResultRecord",
    "ToolResultStatus",
    "execute_tool_calls_serially",
    "hash_tool_arguments",
    "hash_tool_output",
    "image_artifacts_from_action_result",
    "legacy_action_result_from_tool_result",
    "prepare_model_visible_tool_output",
    "select_tool_calls_for_policy",
    "tool_call_record_from_tool_call",
    "tool_call_from_responses_info",
    "tool_calls_from_actionxml",
    "tool_calls_from_codeact_actions",
    "tool_loop_signature",
    "tool_result_record_from_tool_result",
    "tool_result_from_action_result",
    "tool_result_with_model_output_policy",
    "tool_results_loop_identity",
    "tool_results_loop_signature",
]
