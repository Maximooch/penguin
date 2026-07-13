from __future__ import annotations

import asyncio
from copy import deepcopy
from types import MethodType, SimpleNamespace
from typing import TYPE_CHECKING, Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from penguin.core_runtime import process_lifecycle, session_goal_runtime
from penguin.core_runtime.opencode_facade import OpenCodeCoreFacade
from penguin.core_runtime.session_goal_runtime import (
    GoalRunConflictError,
    GoalRunExecutionError,
    GoalRunStateError,
    GoalRunValidationError,
    run_session_goal,
)
from penguin.core_runtime.session_goal_store import (
    get_session_goal_lock,
    save_session_goal,
)
from penguin.system.state import Session
from penguin.web.schemas.session_goal import SessionGoalUpdateRequest
from penguin.web.services.session_goal import update_goal
from penguin.web.services.session_view import (
    get_session_goal,
    get_session_messages,
    set_session_goal,
)

if TYPE_CHECKING:
    from pathlib import Path


class _Manager:
    def __init__(self, session: Session) -> None:
        self.sessions = {session.id: (session, False)}
        self.session_index = {session.id: {}}
        self.current_session = session

    def load_session(self, session_id: str) -> Session | None:
        item = self.sessions.get(session_id)
        return item[0] if item else None

    def mark_session_modified(self, session_id: str) -> None:
        return None

    def save_session(self, session: Session) -> bool:
        self.sessions[session.id] = (session, False)
        return True


def _load_session(conversation: Any, manager: _Manager, session_id: str) -> bool:
    session = manager.load_session(session_id)
    if session is None:
        return False
    conversation.session = session
    return True


class _Core:
    def __init__(self, session: Session, result: dict[str, Any]) -> None:
        manager = _Manager(session)
        conversation = SimpleNamespace(
            session=Session(id="stale_session"),
            load=MagicMock(
                side_effect=lambda session_id: _load_session(
                    conversation, manager, session_id
                )
            ),
        )
        self.conversation_manager = SimpleNamespace(
            session_manager=manager,
            current_agent_id="default",
            agent_session_managers={"default": manager},
            conversation=conversation,
            get_agent_conversation=MagicMock(return_value=conversation),
        )
        self.engine = SimpleNamespace(
            default_agent_id="default",
            prime_scoped_conversation_manager=MagicMock(),
        )
        self._opencode_active_requests: dict[str, int] = {}
        self._goal_run_locks: dict[str, Any] = {}
        self._emit_opencode_session_status = AsyncMock()
        self._ensure_opencode_session_status_heartbeat = lambda session_id: None
        self._cancel_opencode_session_status_heartbeat = lambda session_id: None
        self.event_bus = SimpleNamespace(emit=AsyncMock())
        self._emit_opencode_stream_start = AsyncMock(
            return_value=("msg_goal_final", "part_goal_final")
        )
        self._emit_opencode_stream_chunk = AsyncMock()
        self._emit_opencode_stream_end = AsyncMock()
        self.run_mode_result = result
        self.run_mode = None
        self.run_started = asyncio.Event()
        self.run_release = asyncio.Event()


class _RunMode:
    def __init__(
        self,
        core: _Core,
        max_iterations: int | None = None,
        api_client_override: Any = None,
        model_config_override: Any = None,
    ) -> None:
        self.core = core
        self.max_iterations = max_iterations
        self.api_client_override = api_client_override
        self.model_config_override = model_config_override
        core.run_mode = self
        self.start = AsyncMock(return_value=core.run_mode_result)


class _BlockingRunMode(_RunMode):
    def __init__(self, core: _Core, **kwargs: Any) -> None:
        super().__init__(core, **kwargs)
        self.start = AsyncMock(side_effect=self._start)

    async def _start(self, **_kwargs: Any) -> dict[str, Any]:
        self.core.run_started.set()
        await self.core.run_release.wait()
        return self.core.run_mode_result


def _session(tmp_path: Path, status: str = "active") -> tuple[Session, _Core]:
    session = Session(id="session_goal")
    session.metadata["directory"] = str(tmp_path)
    core = _Core(
        session,
        {
            "status": "pending_review",
            "finish_status": "done",
            "message": "done",
            "iterations": 2,
            "execution_time": 1.25,
        },
    )
    set_session_goal(core, session.id, objective="Ship /goal")
    if status != "active":
        set_session_goal(core, session.id, status=status)
    return session, core


def _enable_real_transcript_bridge(
    core: _Core,
    session: Session,
    tmp_path: Path,
) -> None:
    core.runtime_config = SimpleNamespace(
        active_root=str(tmp_path),
        project_root=str(tmp_path),
        workspace_root=str(tmp_path),
    )
    core.model_config = SimpleNamespace(model="gpt-test", provider="openai")
    core._opencode_session_directories = {session.id: str(tmp_path)}
    core._opencode_stream_states = {}
    core._opencode_message_adapters = {}
    core._tui_adapters = {}
    core._tui_adapter = None
    for method_name in (
        "_get_tui_adapter",
        "_resolve_opencode_model_state",
        "_persist_opencode_event",
        "_emit_opencode_user_message_with_metadata",
        "_emit_opencode_stream_start",
        "_emit_opencode_stream_chunk",
        "_emit_opencode_stream_end",
    ):
        method = getattr(OpenCodeCoreFacade, method_name)
        setattr(core, method_name, MethodType(method, core))


@pytest.mark.asyncio
async def test_run_session_goal_runs_once_and_marks_complete(tmp_path: Path) -> None:
    session, core = _session(tmp_path)

    result = await run_session_goal(
        core,
        session.id,
        run_mode_factory=_RunMode,
        max_iterations=3,
        directory=str(tmp_path),
    )

    assert result["status"] == "complete"
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "complete"
    assert goal["active_run_id"] is None
    assert goal["last_run_id"]
    assert core.run_mode is not None
    call = core.run_mode.start.await_args
    assert call.kwargs["context"]["run_kind"] == "session_goal"
    assert call.kwargs["context"]["max_iterations"] == 3
    assert call.kwargs["context"]["session_id"] == session.id
    assert core.run_mode.max_iterations == 3
    core._emit_opencode_session_status.assert_any_await(session.id, "busy")
    core._emit_opencode_session_status.assert_any_await(session.id, "idle")


@pytest.mark.asyncio
async def test_run_session_goal_preserves_absent_limits(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)

    await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert core.run_mode is not None
    assert core.run_mode.max_iterations is None
    call = core.run_mode.start.await_args
    assert call.kwargs["context"]["max_iterations"] is None
    assert "run_token_budget" not in call.kwargs["context"]


@pytest.mark.asyncio
async def test_run_session_goal_has_no_deadline_when_timeout_is_omitted(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, core = _session(tmp_path)
    clock_reads = 0

    def advanced_clock() -> float:
        nonlocal clock_reads
        clock_reads += 1
        return 0.0 if clock_reads == 1 else 10_000.0

    monkeypatch.setattr(session_goal_runtime.time, "monotonic", advanced_clock)

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_run_deadline_preserves_provider_timeout_error() -> None:
    """Provider timeouts must not be relabeled as a configured goal deadline."""

    async def provider_timeout() -> None:
        raise TimeoutError("provider read timed out")

    with pytest.raises(TimeoutError, match="provider read timed out"):
        await session_goal_runtime._await_with_run_deadline(
            provider_timeout(),
            started=asyncio.get_running_loop().time(),
            timeout_seconds=60,
        )


@pytest.mark.asyncio
async def test_run_session_goal_passes_only_user_configured_token_budget(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    set_session_goal(
        core,
        session.id,
        objective="Ship within the configured budget",
        replace=True,
        token_budget=100_000_000,
    )

    await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    context = core.run_mode.start.await_args.kwargs["context"]
    assert context["run_token_budget"] == 100_000_000


@pytest.mark.asyncio
async def test_explicit_goal_budget_limit_remains_terminal_and_emits_final_message(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    set_session_goal(
        core,
        session.id,
        objective="Ship /goal with a fixed budget",
        replace=True,
        token_budget=100,
    )
    core.run_mode_result = {
        "status": "budget_limited",
        "message": "Still working.",
        "usage": {"total_tokens": 105},
    }

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    expected_message = "Goal token budget exhausted — 105 / 100 tokens used."
    assert result["status"] == "budget_limited"
    assert result["result"]["status"] == "budget_limited"
    assert result["result"]["message"] == expected_message
    core._emit_opencode_stream_chunk.assert_awaited_once_with(
        "msg_goal_final",
        "part_goal_final",
        expected_message,
        "assistant",
    )


@pytest.mark.asyncio
async def test_explicit_budget_overshoot_is_terminal(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    token_budget = 260_000
    billed_tokens = 268_797
    set_session_goal(
        core,
        session.id,
        objective="Ship /goal with an overshoot boundary",
        replace=True,
        token_budget=token_budget,
    )
    core.run_mode_result = {
        "status": "budget_limited",
        "message": "Still working.",
        "usage": {"total_tokens": billed_tokens},
    }

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert result["status"] == "budget_limited"
    assert result["result"]["status"] == "budget_limited"
    assert result["result"]["message"] == (
        "Goal token budget exhausted — "
        f"{billed_tokens:,} / {token_budget:,} tokens used."
    )


@pytest.mark.asyncio
async def test_iteration_limit_emits_resumable_checkpoint_message(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    configured_limit = 123
    core.run_mode_result = {
        "status": "iterations_exceeded",
        "message": "Still exploring.",
        "iterations": configured_limit,
    }

    result = await run_session_goal(
        core,
        session.id,
        run_mode_factory=_RunMode,
        max_iterations=configured_limit,
    )

    expected_message = (
        "Goal progress saved — the configured iteration limit was reached "
        f"after {configured_limit} iterations."
    )
    assert result["status"] == "active"
    assert result["result"]["message"] == expected_message
    core._emit_opencode_stream_chunk.assert_awaited_once_with(
        "msg_goal_final",
        "part_goal_final",
        expected_message,
        "assistant",
    )
@pytest.mark.asyncio
async def test_run_session_goal_primes_requested_session_scope(tmp_path: Path) -> None:
    session, core = _session(tmp_path)

    await run_session_goal(
        core,
        session.id,
        run_mode_factory=_RunMode,
        max_iterations=1,
    )

    conversation = core.conversation_manager.conversation
    conversation.load.assert_called_once_with(session.id)
    core.engine.prime_scoped_conversation_manager.assert_called_once_with(
        "default",
        core.conversation_manager,
    )
    assert conversation.session.id == session.id


@pytest.mark.asyncio
async def test_run_session_goal_resolves_scope_while_holding_goal_lock(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Scope metadata is read under the same lock that claims the goal run."""

    session, core = _session(tmp_path)
    original_resolve_scope = session_goal_runtime._resolve_scope
    observed_lock_states: list[bool] = []

    def resolve_scope(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[Any, Any, dict[str, Any], str, str, str | None]:
        observed_lock_states.append(get_session_goal_lock(core, session.id).locked())
        return original_resolve_scope(*args, **kwargs)

    monkeypatch.setattr(session_goal_runtime, "_resolve_scope", resolve_scope)

    await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert observed_lock_states == [True]


@pytest.mark.asyncio
async def test_run_session_goal_maps_partial_and_blocked(tmp_path: Path) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result["finish_status"] = "partial"

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)
    assert result["status"] == "active"

    set_session_goal(core, session.id, status="active")
    core.run_mode_result = {
        "status": "waiting_input",
        "completion_type": "clarification_needed",
        "message": "Need input",
    }
    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_run_session_goal_rejects_invalid_or_busy_state(tmp_path: Path) -> None:
    session, core = _session(tmp_path, status="paused")
    with pytest.raises(GoalRunStateError):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    current = get_session_goal(core, session.id)
    assert current is not None
    current["status"] = "active"
    current["revision"] += 1
    core.conversation_manager.session_manager.current_session.metadata[
        "_penguin_goal_v1"
    ] = current
    core._opencode_active_requests[session.id] = 1
    with pytest.raises(GoalRunConflictError):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)


@pytest.mark.asyncio
async def test_run_session_goal_rejects_mismatched_directory_and_invalid_limits(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    other = tmp_path / "other"
    other.mkdir()

    with pytest.raises(GoalRunConflictError, match="bound"):
        await run_session_goal(
            core,
            session.id,
            directory=str(other),
            run_mode_factory=_RunMode,
        )
    with pytest.raises(GoalRunValidationError, match="positive integer"):
        await run_session_goal(
            core,
            session.id,
            max_iterations=True,
            run_mode_factory=_RunMode,
        )
    with pytest.raises(GoalRunValidationError, match="positive integer"):
        await run_session_goal(
            core,
            session.id,
            timeout_seconds=0,
            run_mode_factory=_RunMode,
        )
    assert core.run_mode is None


@pytest.mark.asyncio
async def test_concurrent_goal_run_is_rejected_without_waiting_for_first(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    first = asyncio.create_task(
        run_session_goal(core, session.id, run_mode_factory=_BlockingRunMode)
    )
    await asyncio.wait_for(core.run_started.wait(), timeout=1)

    with pytest.raises(GoalRunConflictError, match="already running"):
        await asyncio.wait_for(
            run_session_goal(core, session.id, run_mode_factory=_BlockingRunMode),
            timeout=0.25,
        )

    core.run_release.set()
    result = await first
    assert result["status"] == "complete"


@pytest.mark.asyncio
async def test_cancelled_goal_run_releases_claim_and_pauses_goal(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    task = asyncio.create_task(
        run_session_goal(core, session.id, run_mode_factory=_BlockingRunMode)
    )
    await asyncio.wait_for(core.run_started.wait(), timeout=1)

    task.cancel()
    result = await task

    assert result["status"] == "paused"
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["active_run_id"] is None
    assert core._opencode_active_requests == {}


@pytest.mark.asyncio
async def test_locked_shared_session_gate_is_rejected_without_claim(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    gate = process_lifecycle.get_session_request_gate(core, session.id)
    await gate.acquire()
    try:
        with pytest.raises(GoalRunConflictError, match="already reserved"):
            await run_session_goal(
                core,
                session.id,
                timeout_seconds=1,
                run_mode_factory=_BlockingRunMode,
            )
    finally:
        gate.release()

    assert core.run_started.is_set() is False
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "active"
    assert goal["active_run_id"] is None
    assert core._opencode_active_requests == {}


@pytest.mark.asyncio
async def test_goal_lock_wait_respects_run_deadline(tmp_path: Path) -> None:
    session, core = _session(tmp_path)
    lock = get_session_goal_lock(core, session.id)
    await lock.acquire()
    started = asyncio.get_running_loop().time()
    try:
        with pytest.raises(GoalRunConflictError, match="goal mutation"):
            await run_session_goal(
                core,
                session.id,
                timeout_seconds=1,
                run_mode_factory=_RunMode,
            )
    finally:
        lock.release()

    assert asyncio.get_running_loop().time() - started < 2
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "active"
    assert goal["active_run_id"] is None


@pytest.mark.asyncio
async def test_registration_failure_does_not_wedge_goal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, core = _session(tmp_path)
    monkeypatch.setattr(
        "penguin.core_runtime.session_goal_runtime."
        "process_lifecycle.register_opencode_process_request",
        AsyncMock(side_effect=RuntimeError("registration failed")),
    )

    with pytest.raises(GoalRunExecutionError, match="registration failed"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "blocked"
    assert goal["active_run_id"] is None


@pytest.mark.asyncio
async def test_pause_during_run_survives_late_success(tmp_path: Path) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "done",
        "finish_summary": "Completed after the pause request",
        "message": "",
    }
    task = asyncio.create_task(
        run_session_goal(core, session.id, run_mode_factory=_BlockingRunMode)
    )
    await asyncio.wait_for(core.run_started.wait(), timeout=1)

    paused = set_session_goal(core, session.id, status="paused")
    assert paused is not None
    paused_snapshot = deepcopy(paused)
    core.run_release.set()
    result = await task

    assert result["status"] == "paused"
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "paused"
    assert goal["active_run_id"] is None
    assert goal["active_run_owner"] is None
    assert goal["active_run_started_at"] is None
    assert goal["tokens_used"] == paused_snapshot["tokens_used"]
    assert goal["time_used_seconds"] == paused_snapshot["time_used_seconds"]
    assert goal["last_result"] == paused_snapshot["last_result"]
    assert goal["revision"] == paused_snapshot["revision"] + 1
    assert "message" not in result["result"]
    core._emit_opencode_stream_chunk.assert_not_awaited()


@pytest.mark.asyncio
async def test_goal_completion_stream_aborts_after_chunk_failure(
    tmp_path: Path,
) -> None:
    """A failed synthesized completion does not leave its started stream active."""

    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "done",
        "finish_summary": "Persist this final",
        "message": "",
    }
    core._emit_opencode_stream_chunk = AsyncMock(
        side_effect=RuntimeError("chunk failed")
    )
    core.abort_streaming_message = MagicMock(return_value=True)

    with pytest.raises(GoalRunExecutionError, match="Failed to emit"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    core.abort_streaming_message.assert_called_once_with(agent_id="default")


@pytest.mark.asyncio
async def test_orphaned_claim_recovers_to_paused_and_requires_resume(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    goal = get_session_goal(core, session.id)
    assert goal is not None
    orphaned = dict(goal)
    orphaned.update(
        {
            "active_run_id": "run_from_dead_process",
            "active_run_owner": "dead_process",
            "active_run_started_at": "2026-07-09T00:00:00+00:00",
            "revision": goal["revision"] + 1,
        }
    )
    assert save_session_goal(
        core,
        session.id,
        orphaned,
        expected_goal_id=goal["id"],
        expected_revision=goal["revision"],
    )

    with pytest.raises(GoalRunStateError, match="orphaned"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    recovered = get_session_goal(core, session.id)
    assert recovered is not None
    assert recovered["status"] == "paused"
    assert recovered["active_run_id"] is None
    assert recovered["last_result"]["status"] == "orphaned_run"


@pytest.mark.asyncio
async def test_run_uses_persisted_model_scope_and_accounts_tokens(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    session.metadata.update(
        {
            "agent_id": "default",
            "_opencode_agent_mode_v1": "build",
            "_opencode_provider_id_v1": "openai",
            "_opencode_model_id_v1": "gpt-test",
            "_opencode_variant_v1": "medium",
        }
    )
    model_config = SimpleNamespace(
        provider="openai",
        model="gpt-test",
        supported_reasoning_levels=["medium"],
    )
    api_client = object()
    core.resolve_request_runtime = AsyncMock(return_value=(model_config, api_client))
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "partial",
        "finish_summary": "Implemented the first slice",
        "message": "",
        "usage": {"total_tokens": 42, "provider_debug_counter": 999},
        "action_results": [{"action": "shell", "result": "x" * 20_000}],
    }

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    core.resolve_request_runtime.assert_awaited_once_with("openai/gpt-test")
    assert core.run_mode.api_client_override is api_client
    assert core.run_mode.model_config_override is model_config
    call_context = core.run_mode.start.await_args.kwargs["context"]
    assert call_context["agent_id"] == "default"
    assert call_context["model_id"] == "gpt-test"
    assert call_context["variant"] == "medium"
    goal = result["goal"]
    assert goal["tokens_used"] == 42
    assert goal["time_used_seconds"] > 0
    assert goal["last_result"]["action_count"] == 1
    assert goal["last_result"]["usage"] == {"total_tokens": 42}
    assert "action_results" not in goal["last_result"]
    assert result["result"]["action_count"] == 1
    assert "action_results" not in result["result"]
    assert result["result"]["message"] == (
        "Goal progress saved — Implemented the first slice"
    )
    core._emit_opencode_stream_chunk.assert_awaited_once_with(
        "msg_goal_final",
        "part_goal_final",
        "Goal progress saved — Implemented the first slice",
        "assistant",
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "invalid_total_tokens",
    [float("nan"), float("inf"), float("-inf"), True],
)
async def test_malformed_non_finite_usage_does_not_wedge_goal(
    tmp_path: Path,
    invalid_total_tokens: float | bool,
) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "partial",
        "message": "Progress saved",
        "usage": {"total_tokens": invalid_total_tokens},
    }

    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert result["status"] == "active"
    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["tokens_used"] == 0
    assert goal["active_run_id"] is None
    assert "usage" not in goal["last_result"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "metadata",
    [
        {"_opencode_provider_id_v1": "openai"},
        {"_opencode_model_id_v1": "gpt-test"},
    ],
)
async def test_run_rejects_incomplete_persisted_model_scope(
    tmp_path: Path,
    metadata: dict[str, str],
) -> None:
    session, core = _session(tmp_path)
    session.metadata.update(metadata)

    with pytest.raises(GoalRunStateError, match="both provider and model IDs"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "active"
    assert goal["active_run_id"] is None


@pytest.mark.asyncio
async def test_run_rejects_stale_persisted_agent_scope(tmp_path: Path) -> None:
    session, core = _session(tmp_path)
    session.metadata["agent_id"] = "removed-agent"

    with pytest.raises(GoalRunStateError, match="no longer available"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["active_run_id"] is None


@pytest.mark.asyncio
async def test_goal_command_and_tool_only_finish_persist_in_session_transcript(
    tmp_path: Path,
) -> None:
    session = Session(id="session_goal_transcript")
    session.metadata.update(
        {
            "directory": str(tmp_path),
            "_opencode_provider_id_v1": "openai",
            "_opencode_model_id_v1": "gpt-test",
        }
    )
    core = _Core(
        session,
        {
            "status": "pending_review",
            "finish_status": "done",
            "finish_summary": "Verified the durable goal result",
            "message": "",
            "usage": {"total_tokens": 12},
        },
    )
    _enable_real_transcript_bridge(core, session, tmp_path)

    await update_goal(
        core,
        session.id,
        SessionGoalUpdateRequest(
            objective="Verify transcript durability",
            display_command='/goal "Verify transcript durability"',
            client_message_id="msg_goal_command",
            client_part_id="part_goal_command",
        ),
    )
    result = await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    assert result["status"] == "complete"
    rows = get_session_messages(core, session.id)
    assert rows is not None
    user_rows = [row for row in rows if row["info"]["role"] == "user"]
    assert len(user_rows) == 1
    assert user_rows[0]["info"]["id"] == "msg_goal_command"
    assert [part["id"] for part in user_rows[0]["parts"]] == [
        "part_goal_command"
    ]
    assert [part.get("text") for part in user_rows[0]["parts"]] == [
        '/goal "Verify transcript durability"'
    ]
    assistant_text = [
        part.get("text")
        for row in rows
        if row["info"]["role"] == "assistant"
        for part in row["parts"]
        if part.get("type") == "text" and part.get("text")
    ]
    assert assistant_text == ["Goal complete — Verified the durable goal result"]


@pytest.mark.asyncio
async def test_goal_tool_only_finish_reports_terminal_transcript_save_failure(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "done",
        "finish_summary": "Persist this final",
        "message": "",
    }
    _enable_real_transcript_bridge(core, session, tmp_path)
    manager = core.conversation_manager.session_manager
    original_save = manager.save_session
    completed_assistant_saves = 0

    def _fail_completion_checkpoint(saved_session: Session) -> bool:
        nonlocal completed_assistant_saves
        transcript = saved_session.metadata.get("_opencode_transcript_v1")
        messages = transcript.get("messages") if isinstance(transcript, dict) else None
        has_completed_assistant = any(
            isinstance(entry, dict)
            and isinstance(entry.get("info"), dict)
            and entry["info"].get("role") == "assistant"
            and isinstance(entry["info"].get("time"), dict)
            and entry["info"]["time"].get("completed") is not None
            for entry in (messages or {}).values()
        )
        if has_completed_assistant:
            completed_assistant_saves += 1
            if completed_assistant_saves == 2:
                return False
        return original_save(saved_session)

    manager.save_session = _fail_completion_checkpoint

    with pytest.raises(GoalRunExecutionError, match="synthesized goal completion"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "complete"
    assert goal["active_run_id"] is None


@pytest.mark.asyncio
async def test_goal_tool_only_finish_bounds_hung_completion_emitter(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "done",
        "finish_summary": "Persist this final",
        "message": "",
    }
    never = asyncio.Event()

    async def _hang_stream_start(**_kwargs: Any) -> tuple[str, str]:
        await never.wait()
        return "msg_never", "part_never"

    core._emit_opencode_stream_start = AsyncMock(side_effect=_hang_stream_start)
    monkeypatch.setattr(
        session_goal_runtime,
        "_COMPLETION_EMIT_TIMEOUT_SECONDS",
        0.01,
    )

    with pytest.raises(GoalRunExecutionError, match="Timed out emitting"):
        await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "complete"
    assert goal["active_run_id"] is None
    assert core._opencode_active_requests == {}
    assert not get_session_goal_lock(core, session.id).locked()


@pytest.mark.asyncio
async def test_cancellation_waits_for_terminal_goal_persistence(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)
    core.run_mode_result = {
        "status": "pending_review",
        "finish_status": "done",
        "finish_summary": "Persist before cancellation escapes",
        "message": "",
    }
    emitter_started = asyncio.Event()
    emitter_release = asyncio.Event()

    async def _blocked_stream_start(**_kwargs: Any) -> tuple[str, str]:
        emitter_started.set()
        await emitter_release.wait()
        return "msg_cancel_final", "part_cancel_final"

    core._emit_opencode_stream_start = AsyncMock(side_effect=_blocked_stream_start)
    task = asyncio.create_task(
        run_session_goal(core, session.id, run_mode_factory=_RunMode)
    )
    await asyncio.wait_for(emitter_started.wait(), timeout=1)

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert get_session_goal_lock(core, session.id).locked()
    assert core._opencode_active_requests == {session.id: 1}

    emitter_release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    goal = get_session_goal(core, session.id)
    assert goal is not None
    assert goal["status"] == "complete"
    assert goal["active_run_id"] is None
    assert core._opencode_active_requests == {}
    assert not get_session_goal_lock(core, session.id).locked()


@pytest.mark.asyncio
async def test_goal_runtime_emits_goal_and_compatibility_session_events(
    tmp_path: Path,
) -> None:
    session, core = _session(tmp_path)

    await run_session_goal(core, session.id, run_mode_factory=_RunMode)

    event_types = [
        call.args[1]["type"]
        for call in core.event_bus.emit.await_args_list
        if len(call.args) > 1 and isinstance(call.args[1], dict)
    ]
    assert event_types.count("session.goal.updated") == 2
    assert event_types.count("session.updated") == 2
