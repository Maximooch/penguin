"""Deterministic OpenCode 2 event projection for Penguin prompt streams.

The projector owns only connection-local reconstruction state. It translates the
small OpenCode 1 event subset Penguin already emits without persisting a second
event log or reading mutable application state.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from penguin import __version__

__all__ = ["OpenCodeV2EventProjector", "server_connected_event"]


_FINISH_REASONS = {
    "stop",
    "length",
    "tool-calls",
    "content-filter",
    "error",
    "unknown",
}


@dataclass
class _TextState:
    """One assistant text segment reconstructed from V1 part updates."""

    ordinal: int
    text: str = ""
    started: bool = False
    ended: bool = False


@dataclass
class _ToolState:
    """One Penguin tool part projected into a native V2 tool lifecycle."""

    part_id: str
    name: str
    input: dict[str, Any]
    metadata: dict[str, Any] = field(default_factory=dict)
    settled: bool = False


@dataclass
class _AssistantState:
    """Connection-local state for one assistant step."""

    message_id: str
    agent: str
    model: dict[str, Any]
    cost: int | float = 0
    finish: str = "stop"
    tokens: dict[str, Any] = field(default_factory=lambda: _tokens(None))
    text: dict[str, _TextState] = field(default_factory=dict)
    tools: dict[str, _ToolState] = field(default_factory=dict)
    step_started: bool = False
    completion_requested: bool = False
    completed: bool = False


@dataclass
class _SessionState:
    """Connection-local state for one V2 aggregate."""

    next_durable_sequence: int = 0
    location: dict[str, str] | None = None
    busy_requested: bool = False
    execution_started: bool = False
    execution_failed: bool = False
    pending_idle_completion: bool = False
    created: bool = False
    promoted_inputs: set[str] = field(default_factory=set)
    user_messages: dict[str, dict[str, Any]] = field(default_factory=dict)
    assistants: dict[str, _AssistantState] = field(default_factory=dict)
    active_assistant_id: str | None = None


class OpenCodeV2EventProjector:
    """Project an ordered V1 event stream into native OpenCode 2 events.

    Create one instance per SSE connection. Given the same ordered inputs and
    ``default_delivery``, separate instances produce identical outputs. The
    default is required because current V1 user-message events omit delivery.
    """

    def __init__(self, *, default_delivery: str = "steer") -> None:
        if default_delivery not in {"steer", "queue"}:
            raise ValueError("default_delivery must be steer or queue")
        self._default_delivery = default_delivery
        self._sessions: dict[str, _SessionState] = {}
        self._seen_source_ids: set[str] = set()
        self._input_index = 0
        self._output_index = 0

    def project(self, event: Mapping[str, Any]) -> list[dict[str, Any]]:
        """Translate one canonical Penguin event into zero or more V2 events."""
        self._input_index += 1
        event_type = _string(event.get("type"))
        properties = event.get("properties")
        if not event_type or not isinstance(properties, Mapping):
            return []

        props = dict(properties)
        source = _source_id(event, event_type, self._input_index)
        if source in self._seen_source_ids:
            return []
        self._seen_source_ids.add(source)
        created = _event_time(event, props)

        if event_type == "session.created":
            return self._project_session_created(props, source, created)
        if event_type == "session.status":
            return self._project_session_status(props, source, created)
        if event_type == "session.execution.interrupted":
            return self._project_execution_interrupted(props, source, created)
        if event_type == "message.updated":
            return self._project_message_updated(props, source, created)
        if event_type == "message.part.updated":
            return self._project_part_updated(props, source, created)
        return []

    def _project_session_created(
        self,
        properties: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        raw_info = properties.get("info")
        info = dict(raw_info) if isinstance(raw_info, Mapping) else properties
        session_id = _session_id(properties, info=info)
        location = _location(properties, info)
        if not session_id or not location:
            return []

        state = self._state(session_id)
        state.location = location
        if state.created:
            return []
        state.created = True

        data: dict[str, Any] = {
            "sessionID": session_id,
            "projectID": _string(info.get("projectID")) or "penguin",
            "location": location,
            "slug": _string(info.get("slug")) or session_id,
            "version": _string(info.get("version")) or __version__,
        }
        for key in ("parentID", "subpath", "title"):
            value = _string(info.get(key))
            if value:
                data[key] = value
        agent = (
            _string(info.get("agent"))
            or _string(info.get("agent_id"))
            or _string(info.get("agent_mode"))
        )
        if agent:
            data["agent"] = agent
        model = _model(info)
        if model:
            data["model"] = model

        return [
            self._emit(
                session_id,
                source=source,
                created=created,
                event_type="session.created",
                data=data,
                durable_version=1,
            )
        ]

    def _project_session_status(
        self,
        properties: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        session_id = _session_id(properties)
        status = properties.get("status")
        status_type = (
            _string(status.get("type")) if isinstance(status, Mapping) else None
        )
        if not session_id or status_type not in {"busy", "idle"}:
            return []

        state = self._state(session_id)
        self._remember_location(state, properties)
        if status_type == "busy":
            # The V1 busy event precedes its user message. Buffer it so V2 keeps
            # the durable admission -> promotion -> execution ordering.
            state.busy_requested = True
            state.pending_idle_completion = False
            return []

        output: list[dict[str, Any]] = []
        active_id = state.active_assistant_id
        assistant = state.assistants.get(active_id) if active_id else None
        if assistant and not assistant.completed:
            if _has_unsettled_tools(assistant):
                state.pending_idle_completion = True
                return []
            output.extend(
                self._finish_assistant(
                    session_id,
                    state,
                    assistant,
                    source=source,
                    created=created,
                )
            )
        if state.execution_started:
            output.append(
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.execution.succeeded",
                    data={"sessionID": session_id},
                    durable_version=1,
                )
            )
        state.busy_requested = False
        state.execution_started = False
        state.pending_idle_completion = False
        state.active_assistant_id = None
        return output

    def _project_execution_interrupted(
        self,
        properties: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        session_id = _session_id(properties)
        reason = _string(properties.get("reason"))
        if not session_id or reason not in {"user", "shutdown", "superseded"}:
            return []

        state = self._state(session_id)
        self._remember_location(state, properties)
        if state.execution_failed:
            return []

        state.busy_requested = False
        state.execution_started = False
        state.execution_failed = True
        state.pending_idle_completion = False
        state.active_assistant_id = None
        return [
            self._emit(
                session_id,
                source=source,
                created=created,
                event_type="session.execution.interrupted",
                data={"sessionID": session_id, "reason": reason},
                durable_version=1,
            )
        ]

    def _project_message_updated(
        self,
        properties: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        raw_info = properties.get("info")
        info = dict(raw_info) if isinstance(raw_info, Mapping) else properties
        role = _string(info.get("role"))
        message_id = _message_id(info)
        session_id = _session_id(properties, info=info)
        if not session_id or not message_id or role not in {"user", "assistant"}:
            return []

        state = self._state(session_id)
        self._remember_location(state, properties, info)
        if role == "user":
            state.user_messages[message_id] = dict(info)
            return []
        if state.execution_failed:
            return []

        assistant = state.assistants.get(message_id)
        if assistant is None:
            assistant = _AssistantState(
                message_id=message_id,
                agent=_string(info.get("agent")) or "build",
                model=_model(info)
                or {"providerID": "penguin", "id": "penguin-default"},
            )
            state.assistants[message_id] = assistant
        else:
            assistant.agent = _string(info.get("agent")) or assistant.agent
            assistant.model = _model(info) or assistant.model

        if assistant.completed:
            return []

        assistant.cost = _number(info.get("cost"))
        assistant.tokens = _tokens(info.get("tokens"))
        finish = _string(info.get("finish"))
        if finish in _FINISH_REASONS:
            assistant.finish = finish
        error = _session_error(info.get("error"))

        output: list[dict[str, Any]] = []
        output.extend(
            self._ensure_execution_started(
                session_id,
                state,
                source=source,
                created=created,
            )
        )
        if not assistant.step_started:
            assistant.step_started = True
            state.active_assistant_id = message_id
            output.append(
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.step.started",
                    data={
                        "sessionID": session_id,
                        "assistantMessageID": message_id,
                        "agent": assistant.agent,
                        "model": assistant.model,
                    },
                    durable_version=1,
                )
            )

        if error:
            output.extend(
                self._fail_assistant(
                    session_id,
                    state,
                    assistant,
                    error=error,
                    source=source,
                    created=created,
                )
            )
            return output

        time_data = info.get("time")
        completed = (
            time_data.get("completed") is not None
            if isinstance(time_data, Mapping)
            else False
        )
        if completed and not assistant.completed:
            assistant.completion_requested = True
            if not _has_unsettled_tools(assistant):
                output.extend(
                    self._finish_assistant(
                        session_id,
                        state,
                        assistant,
                        source=source,
                        created=created,
                    )
                )
        return output

    def _project_part_updated(
        self,
        properties: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        raw_part = properties.get("part")
        if not isinstance(raw_part, Mapping):
            return []
        part = dict(raw_part)
        part_type = _string(part.get("type"))
        if part_type == "tool":
            return self._project_tool_part_updated(
                properties,
                part,
                source=source,
                created=created,
            )
        if part_type != "text":
            return []
        session_id = _session_id(properties, part=part)
        message_id = _string(part.get("messageID"))
        part_id = _string(part.get("id"))
        if not session_id or not message_id or not part_id:
            return []

        state = self._state(session_id)
        self._remember_location(state, properties, part)
        if message_id in state.user_messages:
            if message_id in state.promoted_inputs:
                return []
            state.promoted_inputs.add(message_id)
            state.execution_failed = False
            info = state.user_messages[message_id]
            data: dict[str, Any] = {"text": str(part.get("text") or "")}
            metadata = info.get("metadata")
            if isinstance(metadata, Mapping) and metadata:
                data["metadata"] = dict(metadata)
            delivery = _string(info.get("delivery"))
            if delivery not in {"steer", "queue"}:
                delivery = self._default_delivery

            output = [
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.input.admitted",
                    data={
                        "sessionID": session_id,
                        "inputID": message_id,
                        "input": {
                            "type": "user",
                            "data": data,
                            "delivery": delivery,
                        },
                    },
                    durable_version=1,
                ),
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.input.promoted",
                    data={"sessionID": session_id, "inputID": message_id},
                    durable_version=1,
                ),
            ]
            output.extend(
                self._ensure_execution_started(
                    session_id,
                    state,
                    source=source,
                    created=created,
                )
            )
            return output

        assistant = state.assistants.get(message_id)
        if assistant is None or assistant.completed:
            return []
        text = assistant.text.get(part_id)
        if text is None:
            text = _TextState(ordinal=len(assistant.text))
            assistant.text[part_id] = text
        if text.ended:
            return []

        output: list[dict[str, Any]] = []
        if not text.started:
            text.started = True
            output.append(
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.text.started",
                    data={
                        "sessionID": session_id,
                        "assistantMessageID": message_id,
                        "ordinal": text.ordinal,
                    },
                    durable_version=1,
                )
            )

        full_text = str(part.get("text") or "")
        raw_delta = properties.get("delta")
        delta = (
            raw_delta
            if isinstance(raw_delta, str)
            else _text_delta(text.text, full_text)
        )
        if full_text:
            text.text = full_text
        elif delta:
            text.text += delta
        if delta:
            output.append(
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.text.delta",
                    data={
                        "sessionID": session_id,
                        "assistantMessageID": message_id,
                        "ordinal": text.ordinal,
                        "delta": delta,
                    },
                )
            )
        return output

    def _project_tool_part_updated(
        self,
        properties: dict[str, Any],
        part: dict[str, Any],
        *,
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        """Project Penguin's running/terminal tool-part snapshots."""
        session_id = _session_id(properties, part=part)
        message_id = _string(part.get("messageID"))
        part_id = _string(part.get("id"))
        call_id = _string(part.get("callID"))
        name = _string(part.get("tool"))
        raw_state = part.get("state")
        if (
            not session_id
            or not message_id
            or not part_id
            or not call_id
            or not name
            or not isinstance(raw_state, Mapping)
        ):
            return []

        status = _string(raw_state.get("status"))
        raw_input = raw_state.get("input")
        if status not in {"running", "completed", "error"} or not isinstance(
            raw_input, Mapping
        ):
            return []
        tool_input = _json_record(raw_input)
        if tool_input is None:
            return []

        state = self._state(session_id)
        self._remember_location(state, properties, part)
        assistant = state.assistants.get(message_id)
        if assistant is None or assistant.completed or state.execution_failed:
            return []

        metadata = _json_metadata(raw_state.get("metadata"))
        tool = assistant.tools.get(call_id)
        if tool is None:
            if status != "running":
                return []
            tool = _ToolState(
                part_id=part_id,
                name=name,
                input=tool_input,
                metadata=metadata,
            )
            assistant.tools[call_id] = tool
            output = self._end_texts(
                session_id,
                assistant,
                source=source,
                created=created,
            )
            output.extend(
                [
                    self._emit(
                        session_id,
                        source=source,
                        created=created,
                        event_type="session.tool.input.started",
                        data={
                            "sessionID": session_id,
                            "assistantMessageID": message_id,
                            "id": call_id,
                            "name": name,
                        },
                        durable_version=1,
                    ),
                    self._emit(
                        session_id,
                        source=source,
                        created=created,
                        event_type="session.tool.input.ended",
                        data={
                            "sessionID": session_id,
                            "assistantMessageID": message_id,
                            "id": call_id,
                            "text": _canonical_json(tool_input),
                        },
                        durable_version=1,
                    ),
                    self._emit(
                        session_id,
                        source=source,
                        created=created,
                        event_type="session.tool.called",
                        data={
                            "sessionID": session_id,
                            "assistantMessageID": message_id,
                            "id": call_id,
                            "input": tool_input,
                            "executed": False,
                        },
                        durable_version=1,
                    ),
                ]
            )
            if metadata:
                output.append(
                    self._tool_progress(
                        session_id,
                        message_id,
                        call_id,
                        metadata,
                        source=source,
                        created=created,
                    )
                )
            return output

        if (
            tool.part_id != part_id
            or tool.name != name
            or tool.input != tool_input
            or tool.settled
        ):
            return []
        if status == "running":
            if not metadata or metadata == tool.metadata:
                return []
            tool.metadata = metadata
            return [
                self._tool_progress(
                    session_id,
                    message_id,
                    call_id,
                    metadata,
                    source=source,
                    created=created,
                )
            ]

        terminal_metadata = metadata or tool.metadata
        if status == "completed":
            if "output" not in raw_state:
                return []
            terminal_type = "session.tool.success"
            terminal_data: dict[str, Any] = {
                "sessionID": session_id,
                "assistantMessageID": message_id,
                "id": call_id,
                "content": [
                    {"type": "text", "text": _tool_output_text(raw_state["output"])}
                ],
                "executed": False,
            }
        else:
            error = _string(raw_state.get("error"))
            if not error:
                return []
            terminal_type = "session.tool.failed"
            terminal_data = {
                "sessionID": session_id,
                "assistantMessageID": message_id,
                "id": call_id,
                "error": {"type": "tool.execution", "message": error},
                "executed": False,
            }
        if terminal_metadata:
            terminal_data["metadata"] = terminal_metadata

        tool.settled = True
        tool.metadata = terminal_metadata
        output = [
            self._emit(
                session_id,
                source=source,
                created=created,
                event_type=terminal_type,
                data=terminal_data,
                durable_version=2,
            )
        ]
        tools_settled = not _has_unsettled_tools(assistant)
        if tools_settled and (
            assistant.completion_requested or state.pending_idle_completion
        ):
            output.extend(
                self._finish_assistant(
                    session_id,
                    state,
                    assistant,
                    source=source,
                    created=created,
                )
            )
        if tools_settled and state.pending_idle_completion:
            if state.execution_started and not state.execution_failed:
                output.append(
                    self._emit(
                        session_id,
                        source=source,
                        created=created,
                        event_type="session.execution.succeeded",
                        data={"sessionID": session_id},
                        durable_version=1,
                    )
                )
            state.busy_requested = False
            state.execution_started = False
            state.pending_idle_completion = False
            state.active_assistant_id = None
        return output

    def _tool_progress(
        self,
        session_id: str,
        message_id: str,
        call_id: str,
        metadata: dict[str, Any],
        *,
        source: str,
        created: int,
    ) -> dict[str, Any]:
        return self._emit(
            session_id,
            source=source,
            created=created,
            event_type="session.tool.progress",
            data={
                "sessionID": session_id,
                "assistantMessageID": message_id,
                "id": call_id,
                "metadata": metadata,
            },
        )

    def _ensure_execution_started(
        self,
        session_id: str,
        state: _SessionState,
        *,
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        if state.execution_started:
            return []
        state.execution_started = True
        state.busy_requested = False
        state.pending_idle_completion = False
        return [
            self._emit(
                session_id,
                source=source,
                created=created,
                event_type="session.execution.started",
                data={"sessionID": session_id},
                durable_version=1,
            )
        ]

    def _finish_assistant(
        self,
        session_id: str,
        state: _SessionState,
        assistant: _AssistantState,
        *,
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        if assistant.completed:
            return []
        output = self._end_texts(
            session_id,
            assistant,
            source=source,
            created=created,
        )
        assistant.completed = True
        output.append(
            self._emit(
                session_id,
                source=source,
                created=created,
                event_type="session.step.ended",
                data={
                    "sessionID": session_id,
                    "assistantMessageID": assistant.message_id,
                    "finish": assistant.finish,
                    "cost": assistant.cost,
                    "tokens": assistant.tokens,
                },
                durable_version=1,
            )
        )
        if state.active_assistant_id == assistant.message_id:
            state.active_assistant_id = None
        return output

    def _fail_assistant(
        self,
        session_id: str,
        state: _SessionState,
        assistant: _AssistantState,
        *,
        error: dict[str, Any],
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        if assistant.completed:
            return []
        output = self._end_texts(
            session_id,
            assistant,
            source=source,
            created=created,
        )
        assistant.completed = True
        output.extend(
            [
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.step.failed",
                    data={
                        "sessionID": session_id,
                        "assistantMessageID": assistant.message_id,
                        "error": dict(error),
                    },
                    durable_version=1,
                ),
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.execution.failed",
                    data={"sessionID": session_id, "error": dict(error)},
                    durable_version=1,
                ),
            ]
        )
        state.busy_requested = False
        state.execution_started = False
        state.execution_failed = True
        state.pending_idle_completion = False
        if state.active_assistant_id == assistant.message_id:
            state.active_assistant_id = None
        return output

    def _end_texts(
        self,
        session_id: str,
        assistant: _AssistantState,
        *,
        source: str,
        created: int,
    ) -> list[dict[str, Any]]:
        output: list[dict[str, Any]] = []
        for text in sorted(assistant.text.values(), key=lambda item: item.ordinal):
            if not text.started or text.ended:
                continue
            text.ended = True
            output.append(
                self._emit(
                    session_id,
                    source=source,
                    created=created,
                    event_type="session.text.ended",
                    data={
                        "sessionID": session_id,
                        "assistantMessageID": assistant.message_id,
                        "ordinal": text.ordinal,
                        "text": text.text,
                    },
                    durable_version=1,
                )
            )
        return output

    def _state(self, session_id: str) -> _SessionState:
        return self._sessions.setdefault(session_id, _SessionState())

    @staticmethod
    def _remember_location(
        state: _SessionState,
        properties: Mapping[str, Any],
        info: Mapping[str, Any] | None = None,
    ) -> None:
        location = _location(properties, info or {})
        if location:
            state.location = location

    def _emit(
        self,
        session_id: str,
        *,
        source: str,
        created: int,
        event_type: str,
        data: dict[str, Any],
        durable_version: int | None = None,
    ) -> dict[str, Any]:
        self._output_index += 1
        state = self._state(session_id)
        event: dict[str, Any] = {
            "id": _event_id(source, event_type, self._output_index),
            "created": created,
            "type": event_type,
            "data": data,
        }
        if state.location:
            event["location"] = dict(state.location)
        if durable_version is not None:
            event["durable"] = {
                "aggregateID": session_id,
                "seq": state.next_durable_sequence,
                "version": durable_version,
            }
            state.next_durable_sequence += 1
        return event


def server_connected_event(connection_id: str = "connection") -> dict[str, Any]:
    """Return the exact deterministic V2 event-stream handshake."""
    source = _string(connection_id) or "connection"
    return {
        "id": _event_id(source, "server.connected", 0),
        "type": "server.connected",
        "data": {},
    }


def _source_id(event: Mapping[str, Any], event_type: str, index: int) -> str:
    direct = _string(event.get("id"))
    runtime = event.get("runtime_event")
    runtime_id = _string(runtime.get("id")) if isinstance(runtime, Mapping) else None
    return direct or runtime_id or f"{event_type}:{index}"


def _event_time(event: Mapping[str, Any], properties: Mapping[str, Any]) -> int:
    direct = _integer(event.get("time"))
    if direct is not None:
        return direct
    runtime = event.get("runtime_event")
    if isinstance(runtime, Mapping):
        runtime_time = _integer(runtime.get("time"))
        if runtime_time is not None:
            return runtime_time
    info = properties.get("info")
    if not isinstance(info, Mapping):
        info = properties
    time_data = info.get("time") if isinstance(info, Mapping) else None
    if isinstance(time_data, Mapping):
        created = _integer(time_data.get("created"))
        if created is not None:
            return created
    return 0


def _session_id(
    properties: Mapping[str, Any],
    *,
    info: Mapping[str, Any] | None = None,
    part: Mapping[str, Any] | None = None,
) -> str | None:
    for candidate in (
        properties.get("sessionID"),
        properties.get("session_id"),
        info.get("sessionID") if info else None,
        info.get("session_id") if info else None,
        part.get("sessionID") if part else None,
        part.get("session_id") if part else None,
    ):
        value = _string(candidate)
        if value:
            return value
    if info:
        return _string(info.get("id"))
    return None


def _message_id(info: Mapping[str, Any]) -> str | None:
    value = _string(info.get("id"))
    return value if value and value.startswith("msg_") else None


def _location(
    properties: Mapping[str, Any], info: Mapping[str, Any]
) -> dict[str, str] | None:
    raw_location = info.get("location")
    if not isinstance(raw_location, Mapping):
        raw_location = properties.get("location")
    directory = (
        _string(raw_location.get("directory"))
        if isinstance(raw_location, Mapping)
        else None
    )
    directory = (
        directory
        or _string(info.get("directory"))
        or _string(properties.get("directory"))
    )
    path = info.get("path")
    if not directory and isinstance(path, Mapping):
        directory = _string(path.get("cwd"))
    if not directory:
        return None
    result = {"directory": directory}
    if isinstance(raw_location, Mapping):
        workspace_id = _string(raw_location.get("workspaceID"))
        if workspace_id:
            result["workspaceID"] = workspace_id
    return result


def _model(info: Mapping[str, Any]) -> dict[str, Any] | None:
    nested = info.get("model")
    nested = nested if isinstance(nested, Mapping) else {}
    provider_id = _string(info.get("providerID")) or _string(nested.get("providerID"))
    model_id = (
        _string(info.get("modelID"))
        or _string(nested.get("id"))
        or _string(nested.get("modelID"))
    )
    if not provider_id or not model_id:
        return None
    result: dict[str, Any] = {"providerID": provider_id, "id": model_id}
    variant = _string(info.get("variant")) or _string(nested.get("variant"))
    if variant:
        result["variant"] = variant
    return result


def _tokens(value: Any) -> dict[str, Any]:
    source = value if isinstance(value, Mapping) else {}
    cache = source.get("cache")
    cache = cache if isinstance(cache, Mapping) else {}
    return {
        "input": _number(source.get("input")),
        "output": _number(source.get("output")),
        "reasoning": _number(source.get("reasoning")),
        "cache": {
            "read": _number(cache.get("read")),
            "write": _number(cache.get("write")),
        },
    }


def _session_error(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping):
        return None
    data = value.get("data")
    data = data if isinstance(data, Mapping) else {}
    error_type = _string(value.get("type")) or _string(value.get("name"))
    message = data.get("message")
    if not isinstance(message, str):
        message = value.get("message")
    if not error_type or not isinstance(message, str):
        return None

    result: dict[str, Any] = {"type": error_type, "message": message}
    status = data.get("statusCode", data.get("status", value.get("status")))
    if (
        isinstance(status, int)
        and not isinstance(status, bool)
        and 100 <= status <= 599
    ):
        result["status"] = status
    return result


def _has_unsettled_tools(assistant: _AssistantState) -> bool:
    return any(not tool.settled for tool in assistant.tools.values())


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    )


def _tool_output_text(value: Any) -> str:
    if isinstance(value, str):
        return value
    try:
        return _canonical_json(value)
    except (TypeError, ValueError):
        return str(value)


def _json_metadata(value: Any) -> dict[str, Any]:
    return _json_record(value) or {}


def _json_record(value: Any) -> dict[str, Any] | None:
    if not isinstance(value, Mapping) or not all(isinstance(key, str) for key in value):
        return None
    try:
        decoded = json.loads(_canonical_json(dict(value)))
    except (TypeError, ValueError):
        return None
    return decoded if isinstance(decoded, dict) else None


def _number(value: Any) -> int | float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not math.isfinite(value):
        return 0
    return max(value, 0)


def _integer(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    if not math.isfinite(value):
        return None
    return max(int(value), 0)


def _text_delta(previous: str, current: str) -> str:
    if current.startswith(previous):
        return current[len(previous) :]
    return current if current != previous else ""


def _event_id(source: str, event_type: str, index: int) -> str:
    digest = hashlib.sha256(f"{source}:{event_type}:{index}".encode()).hexdigest()
    return f"evt_{digest[:24]}"


def _string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
