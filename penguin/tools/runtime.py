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
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable, Literal, Optional, Union, cast

from penguin.utils.parser import CodeActAction, parse_action

ToolCallSource = Literal["action_xml", "responses", "mcp", "internal"]
ToolResultStatus = Literal["completed", "error", "cancelled", "requires_approval"]
ToolArguments = Union[dict[str, Any], str]


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

    def __post_init__(self) -> None:
        if not self.output_hash:
            object.__setattr__(self, "output_hash", hash_tool_output(self.output))


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


def hash_tool_output(output: Any) -> str:
    """Return a stable hash for tool output identity checks."""

    output_text = str(output if output is not None else "")
    return hashlib.sha256(output_text.encode()).hexdigest()


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
    tool_arguments = _first_non_none(
        structured_output, ("tool_arguments", "arguments")
    )
    return {
        "action": tool_result.name,
        "result": tool_result.output,
        "status": tool_result.status,
        "tool_call_id": tool_result.call_id,
        "output_hash": tool_result.output_hash,
        "metadata": structured_output,
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
        arguments = _first_non_none(
            metadata, ("tool_arguments", "arguments", "params")
        )
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
        try:
            output = execute_call(tool_call)
            if inspect.isawaitable(output):
                output = await output
            ended_at = time.time()
            if isinstance(output, ToolResult):
                results.append(output)
                continue
            if isinstance(output, dict):
                action_output = dict(output)
                if not action_output.get("action") and not action_output.get("name"):
                    action_output["action"] = tool_call.name
                results.append(
                    tool_result_from_action_result(
                        action_output,
                        call_id=tool_call.id,
                        started_at=started_at,
                        ended_at=ended_at,
                        structured_output={
                            "tool_call_id": tool_call.id,
                            "tool_arguments": tool_call.arguments,
                        },
                    )
                )
                continue
            results.append(
                ToolResult(
                    call_id=tool_call.id,
                    name=tool_call.name,
                    status="completed",
                    output=str(output if output is not None else ""),
                    started_at=started_at,
                    ended_at=ended_at,
                )
            )
        except Exception as exc:
            if not active_policy.catch_exceptions:
                raise
            results.append(
                ToolResult(
                    call_id=tool_call.id,
                    name=tool_call.name,
                    status="error",
                    output=f"Error executing tool {tool_call.name}: {exc}",
                    started_at=started_at,
                    ended_at=time.time(),
                )
            )
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
        tool_info.get("arguments")
        if tool_info.get("arguments") is not None
        else "{}"
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
        lines.append("next: inspect page_info or take a screenshot before retrying open_tab")

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
    )


def legacy_action_result_from_tool_result(tool_result: ToolResult) -> dict[str, str]:
    """Convert a normalized tool result back to Penguin's current result shape."""

    return {
        "action": tool_result.name,
        "result": tool_result.output,
        "status": tool_result.status,
    }


__all__ = [
    "ToolArguments",
    "ToolCall",
    "ToolCallSource",
    "ToolExecutionPolicy",
    "ToolExecutor",
    "ToolLoopIdentity",
    "ToolResult",
    "ToolResultStatus",
    "execute_tool_calls_serially",
    "hash_tool_output",
    "legacy_action_result_from_tool_result",
    "select_tool_calls_for_policy",
    "tool_call_from_responses_info",
    "tool_calls_from_actionxml",
    "tool_calls_from_codeact_actions",
    "tool_loop_signature",
    "tool_result_from_action_result",
    "tool_results_loop_identity",
    "tool_results_loop_signature",
]
