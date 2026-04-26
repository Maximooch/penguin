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


def _metadata_from_result(action_result: dict[str, Any]) -> dict[str, Any]:
    metadata = action_result.get("metadata")
    return metadata if isinstance(metadata, dict) else {}


def tool_loop_signature(action_result: dict[str, Any]) -> dict[str, Any]:
    """Build a loop-guard identity payload for a legacy action result."""

    metadata = _metadata_from_result(action_result)
    arguments = (
        action_result.get("tool_arguments")
        or action_result.get("arguments")
        or action_result.get("params")
        or metadata.get("tool_arguments")
        or metadata.get("arguments")
        or metadata.get("params")
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
    output_hash = action_result.get("output_hash") or hash_tool_output(output)
    return {
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


def tool_results_loop_signature(action_results: list[dict[str, Any]]) -> str:
    """Return a deterministic signature for one empty tool-only iteration."""

    payload = [
        tool_loop_signature(result)
        for result in action_results
        if isinstance(result, dict)
    ]
    return hashlib.sha256(_stable_json(payload).encode()).hexdigest()


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
                results.append(
                    tool_result_from_action_result(
                        output,
                        call_id=tool_call.id,
                        started_at=started_at,
                        ended_at=ended_at,
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
        or f"call_{int(time.time() * 1000)}"
    )
    raw_args = tool_info.get("arguments") or "{}"
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
    raw_output = action_result.get("result", action_result.get("output", ""))
    name = str(raw_name).strip()
    output = str(raw_output if raw_output is not None else "")
    raw_status = str(action_result.get("status") or "completed").strip().lower()
    status = cast(
        ToolResultStatus,
        raw_status
        if raw_status in {"completed", "error", "cancelled", "requires_approval"}
        else "error",
    )

    return ToolResult(
        call_id=str(call_id or action_result.get("call_id") or name or "tool_call"),
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
    "tool_results_loop_signature",
]
