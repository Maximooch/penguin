from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from starlette.websockets import WebSocketDisconnect

from penguin.core_runtime.process_lifecycle import (
    finalize_opencode_process_request,
    register_opencode_process_request,
)
from penguin.web.routes import (
    MessageRequest,
    handle_chat_message,
    session_terminal_state,
    stream_chat,
)

if TYPE_CHECKING:
    from pathlib import Path


class _SessionManager:
    def __init__(self, session_id: str) -> None:
        self.session = SimpleNamespace(id=session_id, metadata={}, messages=[])
        self.sessions = {session_id: self.session}
        self.session_index: dict[str, dict[str, Any]] = {}
        self.saved: list[dict[str, Any]] = []

    def mark_session_modified(self, _session_id: str) -> None:
        return None

    def save_session(self, session: Any) -> None:
        self.saved.append(deepcopy(session.metadata))


class _Core:
    def __init__(
        self,
        root: Path,
        session_id: str,
        responses: list[dict[str, Any]],
    ) -> None:
        self.runtime_config = SimpleNamespace(
            workspace_root=str(root),
            project_root=str(root),
            active_root=str(root),
        )
        self._opencode_session_directories: dict[str, str] = {}
        self.manager = _SessionManager(session_id)
        self.conversation_manager = SimpleNamespace(
            session_manager=self.manager,
            agent_session_managers={},
        )
        self.responses = responses
        self.process_calls: list[dict[str, Any]] = []
        self.status_events: list[tuple[str, str]] = []

    def _ensure_opencode_session_status_heartbeat(self, _session_id: str) -> None:
        return None

    def _cancel_opencode_session_status_heartbeat(self, _session_id: str) -> None:
        return None

    async def _emit_opencode_session_status(
        self,
        session_id: str,
        status: str,
    ) -> None:
        self.status_events.append((session_id, status))

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.process_calls.append(kwargs)
        return self.responses.pop(0)


@pytest.fixture(autouse=True)
def _disable_title_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "penguin.web.routes._queue_session_title_refresh",
        lambda *_args, **_kwargs: None,
    )
    monkeypatch.setattr(
        "penguin.web.routes.get_session_info",
        lambda *_args, **_kwargs: None,
    )


@pytest.mark.asyncio
async def test_rest_terminal_contract_preserves_provider_partial_and_truth(
    tmp_path: Path,
) -> None:
    session_id = "session-terminal"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "Provider error occurred: stream stalled",
                "action_results": [{"action": "read_file", "status": "completed"}],
                "iterations": 4,
                "status": "provider_recoverable_error",
                "recoverable": True,
                "error": {
                    "code": "provider_timeout",
                    "provider_data": {"partial_output": "preserved partial"},
                },
            }
        ],
    )

    response = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )

    assert response["completed"] is False
    assert response["state"] == "provider_exhausted"
    assert response["terminal_reason"] == "provider_recoverable_error"
    assert response["partial_response"] == "preserved partial"
    assert response["action_count"] == 1
    assert response["iterations"] == 4
    continuation = response["continuation"]
    assert continuation["action"] == "retry"
    assert continuation["request"]["continuation"]["generation"] == 1
    assert core.manager.saved


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("process_result", "state", "completed"),
    [
        ({"status": "completed"}, "completed", True),
        ({"status": "max_iterations"}, "max_iterations", False),
        (
            {"status": "repeated_empty_tool_only_iterations"},
            "stalled",
            False,
        ),
        ({"status": "aborted", "aborted": True}, "aborted", False),
        ({"status": "cancelled", "cancelled": True}, "cancelled", False),
        ({"status": "error", "error": "boom"}, "failed", False),
    ],
)
async def test_rest_preserves_each_terminal_state(
    tmp_path: Path,
    process_result: dict[str, Any],
    state: str,
    completed: bool,
) -> None:
    session_id = f"session-{state}"
    result = {
        "assistant_response": "result",
        "action_results": [],
        "iterations": 1,
        **process_result,
    }
    core = _Core(tmp_path, session_id, [result])

    response = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )

    assert response["status"] == process_result["status"]
    assert response["terminal_reason"] == process_result["status"]
    assert response["state"] == state
    assert response["completed"] is completed


@pytest.mark.asyncio
async def test_rest_uses_unbounded_default_and_explicit_iteration_override(
    tmp_path: Path,
) -> None:
    session_id = "session-iterations"
    core = _Core(
        tmp_path,
        session_id,
        [
            {"assistant_response": "one", "action_results": [], "status": "completed"},
            {"assistant_response": "two", "action_results": [], "status": "completed"},
        ],
    )

    await handle_chat_message(
        MessageRequest(text="default", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )
    await handle_chat_message(
        MessageRequest(
            text="override",
            session_id=session_id,
            directory=str(tmp_path),
            max_iterations=7,
        ),
        core=cast(Any, core),
    )

    assert core.process_calls[0]["max_iterations"] is None
    assert core.process_calls[1]["max_iterations"] == 7


@pytest.mark.asyncio
async def test_durable_continuation_round_trip_is_explicit_and_one_shot(
    tmp_path: Path,
) -> None:
    session_id = "session-continuation"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [],
                "iterations": 3,
                "status": "max_iterations",
            },
            {
                "assistant_response": "done",
                "action_results": [],
                "iterations": 1,
                "status": "completed",
            },
        ],
    )

    first = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )
    continuation_body = first["continuation"]["request"]

    second = await handle_chat_message(
        MessageRequest(**continuation_body),
        core=cast(Any, core),
    )

    assert second["completed"] is True
    assert second["continuation"] is None
    generated_prompt = core.process_calls[1]["input_data"]["text"]
    assert "durable conversation state" in generated_prompt
    assert "max_iterations" in generated_prompt

    replay = await handle_chat_message(
        MessageRequest(**continuation_body),
        core=cast(Any, core),
    )
    assert replay["completed"] is False
    assert replay["status"] == "continuation_conflict"
    assert replay["error"]["code"] == "stale_continuation"
    assert len(core.process_calls) == 2


@pytest.mark.asyncio
async def test_successor_marker_save_failure_closes_executed_continuation(
    tmp_path: Path,
) -> None:
    session_id = "session-continuation-terminal-save-failure"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [
                    {"action": "read_file", "status": "completed"}
                ],
                "status": "max_iterations",
            },
            {
                "assistant_response": "tool work completed before persistence failed",
                "action_results": [
                    {"action": "write_file", "status": "completed"}
                ],
                "status": "completed",
            },
        ],
    )
    original_save = core.manager.save_session
    save_count = 0

    def fail_only_successor_marker(session: Any) -> bool | None:
        nonlocal save_count
        save_count += 1
        # First terminal marker, continuation lease, and execution-start marker
        # are durable. The successor terminal marker is not.
        if save_count == 4:
            return False
        original_save(session)
        return None

    core.manager.save_session = fail_only_successor_marker  # type: ignore[method-assign]
    first = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )
    continuation_body = first["continuation"]["request"]

    failed = await handle_chat_message(
        MessageRequest(**continuation_body),
        core=cast(Any, core),
    )

    assert failed["completed"] is False
    assert failed["status"] == "terminal_state_persistence_error"
    assert failed["error"]["code"] == "terminal_state_persistence_error"
    assert failed["response"] == "tool work completed before persistence failed"
    assert failed["action_results"] == [
        {"action": "write_file", "status": "completed"}
    ]
    assert failed["continuation"] is None
    assert failed["actions"] == []

    replay = await handle_chat_message(
        MessageRequest(**continuation_body),
        core=cast(Any, core),
    )
    assert replay["status"] == "continuation_conflict"
    assert len(core.process_calls) == 2


@pytest.mark.asyncio
async def test_failed_terminal_marker_save_does_not_advertise_resume(
    tmp_path: Path,
) -> None:
    session_id = "session-save-failed"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [],
                "status": "max_iterations",
            }
        ],
    )
    core.manager.save_session = lambda _session: False  # type: ignore[method-assign]

    response = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )

    assert response["completed"] is False
    assert response["status"] == "max_iterations"
    assert response["continuation"] is None
    assert response["actions"] == []


@pytest.mark.asyncio
async def test_continuation_context_tampering_is_rejected_before_process(
    tmp_path: Path,
) -> None:
    session_id = "session-context-tamper"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [{"action": "write", "status": "completed"}],
                "status": "max_iterations",
            },
            {"assistant_response": "unexpected", "action_results": []},
        ],
    )

    async def resolve_runtime(_model: str | None) -> tuple[Any, None]:
        return (
            SimpleNamespace(
                provider="openai",
                model="gpt-5",
                service_tier=None,
                reasoning_enabled=False,
            ),
            None,
        )

    core.resolve_request_runtime = resolve_runtime  # type: ignore[attr-defined]
    first = await handle_chat_message(
        MessageRequest(
            text="work",
            session_id=session_id,
            directory=str(tmp_path),
            model="openai/gpt-5",
            agent_id="general",
            agent_mode="build",
            variant="high",
            service_tier="priority",
        ),
        core=cast(Any, core),
    )
    request = deepcopy(first["continuation"]["request"])
    request["model"] = "openai/other"

    rejected = await handle_chat_message(
        MessageRequest(**request),
        core=cast(Any, core),
    )

    assert rejected["status"] == "continuation_conflict"
    assert "context" in rejected["error"]["message"]
    assert len(core.process_calls) == 1


@pytest.mark.asyncio
async def test_invalidation_save_failure_blocks_new_process_side_effects(
    tmp_path: Path,
) -> None:
    session_id = "session-invalidation-failure"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [],
                "status": "max_iterations",
            },
            {"assistant_response": "unexpected", "action_results": []},
        ],
    )
    await handle_chat_message(
        MessageRequest(text="first", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )
    core.manager.save_session = lambda _session: False  # type: ignore[method-assign]

    rejected = await handle_chat_message(
        MessageRequest(text="second", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )

    assert rejected["status"] == "terminal_state_persistence_error"
    assert len(core.process_calls) == 1


@pytest.mark.asyncio
async def test_terminal_read_endpoint_recovers_lost_response(
    tmp_path: Path,
) -> None:
    session_id = "session-lost-response"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [{"action": "read", "status": "completed"}],
                "status": "max_iterations",
            }
        ],
    )
    original = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )

    hydrated = await session_terminal_state(session_id, core=cast(Any, core))

    assert hydrated["status"] == original["status"]
    assert hydrated["partial_response"] == original["partial_response"]
    assert hydrated["action_results"] == original["action_results"]
    assert hydrated["continuation"] == original["continuation"]


@pytest.mark.asyncio
async def test_rest_gate_wait_is_bounded_and_does_not_start_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_SESSION_REQUEST_GATE_TIMEOUT_SECONDS", "0.01")
    session_id = "session-busy"
    core = _Core(
        tmp_path,
        session_id,
        [{"assistant_response": "unexpected", "action_results": []}],
    )
    held_gate = asyncio.Lock()
    await held_gate.acquire()
    core._opencode_request_gates = {session_id: held_gate}

    try:
        response = await handle_chat_message(
            MessageRequest(
                text="queued", session_id=session_id, directory=str(tmp_path)
            ),
            core=cast(Any, core),
        )
    finally:
        held_gate.release()

    assert response["completed"] is False
    assert response["status"] == "request_gate_timeout"
    assert response["state"] == "stalled"
    assert response["recoverable"] is True
    assert response["continuation"] is None
    assert core.process_calls == []


@pytest.mark.asyncio
async def test_terminal_marker_is_durable_before_session_gate_releases(
    tmp_path: Path,
) -> None:
    session_id = "session-marker-boundary"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "first",
                "action_results": [],
                "status": "completed",
            },
            {
                "assistant_response": "second",
                "action_results": [],
                "status": "completed",
            },
        ],
    )
    save_started = threading.Event()
    release_save = threading.Event()
    original_save = core.manager.save_session

    def blocking_save(session: Any) -> None:
        save_started.set()
        release_save.wait(timeout=2)
        original_save(session)

    core.manager.save_session = blocking_save  # type: ignore[method-assign]

    async def send(text: str) -> dict[str, Any]:
        return await handle_chat_message(
            MessageRequest(text=text, session_id=session_id, directory=str(tmp_path)),
            core=cast(Any, core),
        )

    first = asyncio.create_task(send("first"))
    await asyncio.wait_for(asyncio.to_thread(save_started.wait), timeout=1)
    assert core.status_events == [(session_id, "busy")]
    second = asyncio.create_task(send("second"))
    try:
        await asyncio.sleep(0.02)
        assert len(core.process_calls) == 1
    finally:
        release_save.set()

    first_response, second_response = await asyncio.gather(first, second)
    assert first_response["completed"] is True
    assert second_response["completed"] is True
    assert len(core.process_calls) == 2
    assert core.status_events == [
        (session_id, "busy"),
        (session_id, "idle"),
        (session_id, "busy"),
        (session_id, "idle"),
    ]


@pytest.mark.asyncio
async def test_nested_core_lifecycle_keeps_busy_until_terminal_marker_is_durable(
    tmp_path: Path,
) -> None:
    session_id = "session-nested-lifecycle-marker"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "done",
                "action_results": [],
                "status": "completed",
            }
        ],
    )
    save_started = threading.Event()
    release_save = threading.Event()
    original_save = core.manager.save_session
    original_process = core.process

    def blocking_save(session: Any) -> None:
        save_started.set()
        release_save.wait(timeout=2)
        original_save(session)

    async def nested_core_process(**kwargs: Any) -> dict[str, Any]:
        request_task = asyncio.current_task()
        tracked = await register_opencode_process_request(
            core,
            session_id,
            request_task,
        )
        try:
            return await original_process(**kwargs)
        finally:
            await finalize_opencode_process_request(
                core,
                session_id,
                request_task,
                request_tracked=tracked,
            )

    core.manager.save_session = blocking_save  # type: ignore[method-assign]
    core.process = nested_core_process  # type: ignore[method-assign]
    task = asyncio.create_task(
        handle_chat_message(
            MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
            core=cast(Any, core),
        )
    )
    await asyncio.wait_for(asyncio.to_thread(save_started.wait), timeout=1)
    try:
        assert core.status_events == [(session_id, "busy")]
        assert core._opencode_active_requests == {session_id: 1}
    finally:
        release_save.set()

    response = await task
    assert response["completed"] is True
    assert core.status_events == [(session_id, "busy"), (session_id, "idle")]


@pytest.mark.asyncio
async def test_websocket_complete_event_uses_same_terminal_truth_shape(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session-websocket-terminal"
    process_result = {
        "assistant_response": "Provider error occurred: idle timeout",
        "action_results": [{"action": "read_file", "status": "completed"}],
        "iterations": 2,
        "status": "provider_recoverable_error",
        "recoverable": True,
        "error": {
            "code": "provider_timeout",
            "provider_data": {"partial_output": "ws partial"},
        },
    }
    core = _Core(tmp_path, session_id, [process_result])

    class _WebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []
            self.client_state = SimpleNamespace(name="CONNECTED")
            self.received = False

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, Any]:
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return {
                "text": "work",
                "session_id": session_id,
                "directory": str(tmp_path),
            }

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.events.append(payload)

    class _EventBus:
        def subscribe(self, *_args: Any) -> None:
            return None

        def unsubscribe(self, *_args: Any) -> None:
            return None

    async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("penguin.web.routes.require_websocket_auth", _noop_async)
    monkeypatch.setattr(
        "penguin.web.routes._setup_approval_websocket_callbacks", lambda: None
    )
    monkeypatch.setattr(
        "penguin.web.routes._setup_question_event_callbacks", lambda: None
    )
    monkeypatch.setattr("penguin.web.routes._persist_session_agent_mode", _noop_async)
    monkeypatch.setattr(
        "penguin.web.routes._persist_session_model_selection", _noop_async
    )
    monkeypatch.setattr("penguin.web.routes.CLIEventBus.get_sync", lambda: _EventBus())

    websocket = _WebSocket()
    await stream_chat(cast(Any, websocket), core=cast(Any, core))

    complete = next(event for event in websocket.events if event["event"] == "complete")
    payload = complete["data"]
    assert payload["completed"] is False
    assert payload["state"] == "provider_exhausted"
    assert payload["terminal_reason"] == "provider_recoverable_error"
    assert payload["partial_response"] == "ws partial"
    assert payload["action_count"] == 1
    assert payload["iterations"] == 2
    assert payload["continuation"]["action"] == "retry"
    assert core.process_calls[0]["max_iterations"] is None


@pytest.mark.asyncio
async def test_websocket_gate_timeout_never_finalizes_another_active_stream(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("PENGUIN_SESSION_REQUEST_GATE_TIMEOUT_SECONDS", "0.01")
    session_id = "session-websocket-busy"
    core = _Core(
        tmp_path,
        session_id,
        [{"assistant_response": "unexpected", "action_results": []}],
    )
    held_gate = asyncio.Lock()
    await held_gate.acquire()
    core._opencode_request_gates = {session_id: held_gate}
    finalized: list[str] = []
    core.finalize_streaming_message = (  # type: ignore[attr-defined]
        lambda **_kwargs: finalized.append("finalized")
    )

    class _WebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []
            self.client_state = SimpleNamespace(name="CONNECTED")
            self.received = False

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, Any]:
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return {
                "text": "queued",
                "session_id": session_id,
                "directory": str(tmp_path),
            }

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.events.append(payload)

    async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("penguin.web.routes.require_websocket_auth", _noop_async)
    monkeypatch.setattr(
        "penguin.web.routes._setup_approval_websocket_callbacks", lambda: None
    )
    monkeypatch.setattr(
        "penguin.web.routes._setup_question_event_callbacks", lambda: None
    )
    websocket = _WebSocket()
    try:
        await stream_chat(cast(Any, websocket), core=cast(Any, core))
    finally:
        held_gate.release()

    complete = next(event for event in websocket.events if event["event"] == "complete")
    assert complete["data"]["status"] == "request_gate_timeout"
    assert complete["data"]["completed"] is False
    assert core.process_calls == []
    assert finalized == []


@pytest.mark.asyncio
async def test_websocket_continuation_rejects_client_controls_before_process(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session_id = "session-websocket-continuation-controls"
    core = _Core(
        tmp_path,
        session_id,
        [
            {
                "assistant_response": "partial",
                "action_results": [],
                "status": "max_iterations",
            },
            {"assistant_response": "unexpected", "action_results": []},
        ],
    )
    first = await handle_chat_message(
        MessageRequest(text="work", session_id=session_id, directory=str(tmp_path)),
        core=cast(Any, core),
    )
    request = deepcopy(first["continuation"]["request"])
    request["max_iterations"] = 1

    class _WebSocket:
        def __init__(self) -> None:
            self.events: list[dict[str, Any]] = []
            self.client_state = SimpleNamespace(name="CONNECTED")
            self.received = False

        async def accept(self) -> None:
            return None

        async def receive_json(self) -> dict[str, Any]:
            if self.received:
                raise WebSocketDisconnect()
            self.received = True
            return request

        async def send_json(self, payload: dict[str, Any]) -> None:
            self.events.append(payload)

    async def _noop_async(*_args: Any, **_kwargs: Any) -> None:
        return None

    monkeypatch.setattr("penguin.web.routes.require_websocket_auth", _noop_async)
    monkeypatch.setattr(
        "penguin.web.routes._setup_approval_websocket_callbacks", lambda: None
    )
    monkeypatch.setattr(
        "penguin.web.routes._setup_question_event_callbacks", lambda: None
    )

    websocket = _WebSocket()
    await stream_chat(cast(Any, websocket), core=cast(Any, core))

    error = next(event for event in websocket.events if event["event"] == "error")
    assert error["data"]["code"] == "invalid_continuation"
    assert "exact continuation" in error["data"]["message"]
    assert len(core.process_calls) == 1
