"""Execution bridge for persisted session goals."""

from __future__ import annotations

import asyncio
import inspect
import logging
import time
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from math import isfinite
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, TypeVar
from uuid import uuid4

from penguin.core_runtime import conversations, process_lifecycle
from penguin.core_runtime.session_goal_store import (
    get_session_goal_lock,
    load_session_goal_record,
    save_session_goal,
)
from penguin.core_runtime.session_goals import (
    GoalNotFoundError,
    goal_status_from_run_result,
)
from penguin.llm.runtime import apply_reasoning_variant_override
from penguin.run_mode import RunMode
from penguin.system.execution_context import ExecutionContext, execution_context_scope
from penguin.web.services.session_events import emit_session_goal_updated_events

_PERSISTED_RESULT_TEXT_CHARS = 8_000
_GOAL_EVENT_TIMEOUT_SECONDS = 5.0
_COMPLETION_EMIT_TIMEOUT_SECONDS = 10.0
_PERSISTED_USAGE_FIELDS = (
    "input_tokens",
    "output_tokens",
    "reasoning_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
    "total_tokens",
    "cost",
)

_AGENT_MODE_KEY = "_opencode_agent_mode_v1"
_MODEL_ID_KEY = "_opencode_model_id_v1"
_PROVIDER_ID_KEY = "_opencode_provider_id_v1"
_VARIANT_KEY = "_opencode_variant_v1"

__all__ = [
    "GoalRunConflictError",
    "GoalRunError",
    "GoalRunExecutionError",
    "GoalRunNotFoundError",
    "GoalRunStateError",
    "GoalRunValidationError",
    "run_session_goal",
]

logger = logging.getLogger(__name__)
_T = TypeVar("_T")


class GoalRunError(RuntimeError):
    """Base exception for goal execution failures."""


class GoalRunNotFoundError(GoalRunError):
    """Raised when the target session or goal does not exist."""


class GoalRunStateError(GoalRunError):
    """Raised when a goal is not runnable in its current state."""


class GoalRunConflictError(GoalRunError):
    """Raised when the session already has active work."""


class GoalRunValidationError(GoalRunError):
    """Raised when caller-supplied run limits or scope are invalid."""


class GoalRunExecutionError(GoalRunError):
    """Raised after an infrastructure failure has been safely finalized."""


class _GoalRunDeadlineExceeded(asyncio.TimeoutError):
    """Raised only when an explicitly configured goal deadline expires."""


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _optional_positive_limit(value: int | None, *, field: str) -> int | None:
    """Validate an explicitly configured positive limit without inventing one."""

    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise GoalRunValidationError(f"{field} must be a positive integer")
    return value


async def _await_with_run_deadline(
    awaitable: Awaitable[_T],
    *,
    started: float,
    timeout_seconds: int | None,
) -> _T:
    """Await one setup/execution step within the run's wall-clock deadline."""

    if timeout_seconds is None:
        return await awaitable
    remaining = timeout_seconds - (time.monotonic() - started)
    try:
        return await asyncio.wait_for(awaitable, timeout=max(remaining, 0.0))
    except asyncio.TimeoutError as exc:
        raise _GoalRunDeadlineExceeded from exc


@asynccontextmanager
async def _goal_lock_with_run_deadline(
    lock: asyncio.Lock,
    *,
    started: float,
    timeout_seconds: int | None,
) -> AsyncIterator[None]:
    try:
        await _await_with_run_deadline(
            lock.acquire(),
            started=started,
            timeout_seconds=timeout_seconds,
        )
    except _GoalRunDeadlineExceeded as exc:
        raise GoalRunConflictError(
            "Timed out waiting for a session goal mutation"
        ) from exc
    try:
        yield
    finally:
        lock.release()


def _directory(value: Any, *, field: str) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise GoalRunValidationError(f"{field} must be a non-empty directory")
    try:
        path = Path(value).expanduser().resolve(strict=True)
    except (OSError, RuntimeError) as exc:
        raise GoalRunValidationError(f"{field} does not exist: {value}") from exc
    if not path.is_dir():
        raise GoalRunValidationError(f"{field} is not a directory: {value}")
    return str(path)


def _directories_match(left: str, right: str) -> bool:
    if left == right:
        return True
    try:
        return Path(left).samefile(right)
    except OSError:
        return False


def _runtime_owner_id(core: Any) -> str:
    owner_id = getattr(core, "_goal_runtime_owner_id", None)
    if not isinstance(owner_id, str) or not owner_id:
        owner_id = f"goalowner_{uuid4().hex}"
        core._goal_runtime_owner_id = owner_id
    return owner_id


def _live_runs(core: Any) -> dict[str, str]:
    runs = getattr(core, "_goal_live_runs", None)
    if not isinstance(runs, dict):
        runs = {}
        core._goal_live_runs = runs
    return runs


def _string(metadata: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = metadata.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return None


def _resolve_agent_id(core: Any, manager: Any, metadata: dict[str, Any]) -> str:
    conversation_manager = getattr(core, "conversation_manager", None)
    agent_managers = getattr(conversation_manager, "agent_session_managers", {})
    metadata_agent = _string(metadata, "agent_id", "agentID")
    if metadata_agent and isinstance(agent_managers, dict) and agent_managers:
        if metadata_agent not in agent_managers:
            raise GoalRunStateError(
                f"Persisted session agent {metadata_agent} is no longer available"
            )
        bound_manager = agent_managers.get(metadata_agent)
        if bound_manager is not None and bound_manager is not manager:
            raise GoalRunStateError(
                f"Session agent {metadata_agent} does not own the persisted session"
            )
    if metadata_agent:
        return metadata_agent
    if isinstance(agent_managers, dict):
        for agent_id, candidate in agent_managers.items():
            if candidate is manager and isinstance(agent_id, str) and agent_id:
                return agent_id
    current = getattr(conversation_manager, "current_agent_id", None)
    if isinstance(current, str) and current:
        return current
    return str(getattr(getattr(core, "engine", None), "default_agent_id", "default"))


def _resolve_scope(
    core: Any,
    session_id: str,
    requested_directory: str | None,
) -> tuple[Any, Any, dict[str, Any], str, str, str | None]:
    record = load_session_goal_record(core, session_id, require_goal=True)
    assert record.goal is not None
    metadata = getattr(record.session, "metadata", None)
    session_metadata = metadata if isinstance(metadata, dict) else {}

    persisted_directory = _directory(
        session_metadata.get("directory"), field="persisted session directory"
    )
    explicit_directory = _directory(requested_directory, field="directory")
    if (
        persisted_directory
        and explicit_directory
        and not _directories_match(persisted_directory, explicit_directory)
    ):
        raise GoalRunConflictError(
            f"Session {session_id} is bound to {persisted_directory}, not "
            f"{explicit_directory}"
        )
    resolved_directory = persisted_directory or explicit_directory
    if resolved_directory is None:
        raise GoalRunValidationError(
            f"Session {session_id} has no persisted working directory"
        )

    if persisted_directory is None:
        previous = deepcopy(session_metadata)
        session_metadata["directory"] = resolved_directory
        try:
            record.manager.mark_session_modified(session_id)
            saved = record.manager.save_session(record.session)
            if saved is False:
                raise GoalRunExecutionError("Failed to persist session directory")
        except Exception:
            record.session.metadata = previous
            raise

    scoped_provider = _string(
        session_metadata, _PROVIDER_ID_KEY, "providerID", "provider_id"
    )
    scoped_model = _string(
        session_metadata,
        _MODEL_ID_KEY,
        "modelID",
        "model_id",
    )
    if bool(scoped_provider) != bool(scoped_model):
        raise GoalRunStateError(
            "Persisted session model scope must include both provider and model IDs"
        )

    agent_id = _resolve_agent_id(core, record.manager, session_metadata)
    agent_mode = _string(session_metadata, _AGENT_MODE_KEY, "agent_mode") or "build"
    if agent_mode not in {"build", "plan"}:
        raise GoalRunStateError(f"Unsupported persisted agent mode: {agent_mode}")
    return (
        record.session,
        record.manager,
        session_metadata,
        agent_id,
        agent_mode,
        resolved_directory,
    )


async def _resolve_model_runtime(
    core: Any,
    metadata: dict[str, Any],
) -> tuple[Any | None, Any | None, str | None, str | None, str | None]:
    provider_id = _string(metadata, _PROVIDER_ID_KEY, "providerID", "provider_id")
    model_id = _string(metadata, _MODEL_ID_KEY, "modelID", "model_id")
    variant = _string(metadata, _VARIANT_KEY, "variant")
    if bool(provider_id) != bool(model_id):
        raise GoalRunStateError(
            "Persisted session model scope must include both provider and model IDs"
        )
    requested_model = (
        f"{provider_id}/{model_id}" if provider_id and model_id else model_id
    )
    resolver = getattr(core, "resolve_request_runtime", None)
    if callable(resolver):
        model_config, api_client = await resolver(requested_model)
    else:
        model_config = getattr(core, "model_config", None)
        api_client = None
    if variant and model_config is not None:
        apply_reasoning_variant_override(model_config, variant)
    return model_config, api_client, provider_id, model_id, variant


def _goal_prompt(goal: dict[str, Any]) -> str:
    return (
        "You are executing the active session goal.\n\n"
        f"Goal: {goal['objective']}\n"
        f"Status: {goal['status']}\n\n"
        "Work toward this goal using the available tools. Make concrete progress.\n"
        "When fully satisfied, call finish_task with status done and a concise "
        "user-facing summary.\n"
        "If blocked, call finish_task with status blocked and explain the blocker, "
        "or use the existing clarification flow.\n"
        "Continue until the goal is complete, interrupted, blocked on user input, "
        "or a real runtime/provider failure prevents further progress."
    )


def _factory_accepts(factory: Callable[..., Any], parameter: str) -> bool:
    try:
        parameters = inspect.signature(factory).parameters.values()
    except (TypeError, ValueError):
        return False
    return any(
        item.name == parameter or item.kind is inspect.Parameter.VAR_KEYWORD
        for item in parameters
    )


def _make_run_mode(
    factory: Callable[..., Any],
    core: Any,
    *,
    max_iterations: int | None,
    api_client: Any | None,
    model_config: Any | None,
) -> Any:
    kwargs: dict[str, Any] = {"max_iterations": max_iterations}
    if api_client is not None and _factory_accepts(factory, "api_client_override"):
        kwargs["api_client_override"] = api_client
    if model_config is not None and _factory_accepts(factory, "model_config_override"):
        kwargs["model_config_override"] = model_config
    return factory(core, **kwargs)


def _run_tokens(result: dict[str, Any]) -> int:
    usage = result.get("usage")
    if not isinstance(usage, dict):
        return 0
    value = usage.get("total_tokens", 0)
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return 0
    if not isfinite(float(value)):
        return 0
    return max(int(value), 0)


def _persisted_result(result: dict[str, Any]) -> dict[str, Any]:
    """Return a bounded, JSON-safe goal result summary for session metadata."""

    persisted: dict[str, Any] = {}
    for key in ("status", "completion_type", "finish_status"):
        value = result.get(key)
        if isinstance(value, str) and value:
            persisted[key] = value[:256]
    for key in ("message", "finish_summary"):
        value = result.get(key)
        if isinstance(value, str) and value:
            persisted[key] = value[:_PERSISTED_RESULT_TEXT_CHARS]
    for key in ("iterations", "execution_time"):
        value = result.get(key)
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(float(value))
        ):
            persisted[key] = max(value, 0)
    usage = result.get("usage")
    if isinstance(usage, dict):
        persisted_usage = {
            key: value
            for key in _PERSISTED_USAGE_FIELDS
            if (value := usage.get(key)) is not None
            and isinstance(value, (int, float))
            and not isinstance(value, bool)
            and isfinite(float(value))
        }
        if persisted_usage:
            persisted["usage"] = persisted_usage
    action_results = result.get("action_results")
    if isinstance(action_results, list):
        persisted["action_count"] = len(action_results)
    return persisted


def _completion_text(
    result: dict[str, Any],
    status: str,
    goal: dict[str, Any],
) -> str | None:
    result_status = result.get("status")
    if result_status == "budget_limited":
        token_budget = goal.get("token_budget")
        if isinstance(token_budget, int):
            return (
                "Goal token budget exhausted — "
                f"{goal['tokens_used']:,} / {token_budget:,} tokens used."
            )
        return "Goal token budget exhausted."
    if result_status in {"iterations_exceeded", "max_iterations"}:
        iterations = result.get("iterations")
        detail = (
            f" after {int(iterations):,} iterations"
            if isinstance(iterations, int) and not isinstance(iterations, bool)
            else ""
        )
        return (
            f"Goal progress saved — the configured iteration limit was reached{detail}."
        )

    message = result.get("message")
    if isinstance(message, str) and message.strip():
        return None
    finish_status = result.get("finish_status")
    if finish_status not in {"done", "partial", "blocked"}:
        return None
    summary = result.get("finish_summary")
    clean_summary = summary.strip() if isinstance(summary, str) else ""
    clean_summary = clean_summary[:4_000]
    prefix = {
        "complete": "Goal complete",
        "blocked": "Goal blocked",
        "active": "Goal progress saved",
    }.get(status, "Goal run finished")
    return f"{prefix} — {clean_summary}" if clean_summary else f"{prefix}."


async def _emit_completion_message(
    core: Any,
    text: str,
    *,
    agent_id: str,
    model_id: str | None,
    provider_id: str | None,
) -> bool:
    start = getattr(core, "_emit_opencode_stream_start", None)
    chunk = getattr(core, "_emit_opencode_stream_chunk", None)
    end = getattr(core, "_emit_opencode_stream_end", None)
    if not all(callable(item) for item in (start, chunk, end)):
        return False

    async def _emit() -> None:
        message_id, part_id = await start(
            agent_id=agent_id,
            model_id=model_id,
            provider_id=provider_id,
        )
        await chunk(message_id, part_id, text, "assistant")
        await end(message_id, part_id)

    try:
        await asyncio.wait_for(
            _emit(),
            timeout=_COMPLETION_EMIT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError as exc:
        raise GoalRunExecutionError(
            "Timed out emitting synthesized goal completion"
        ) from exc
    except Exception as exc:
        if isinstance(exc, GoalRunExecutionError):
            raise
        raise GoalRunExecutionError(
            "Failed to emit synthesized goal completion"
        ) from exc
    return True


async def _emit_goal_events_bounded(
    core: Any,
    session_id: str,
    goal: dict[str, Any] | None,
) -> None:
    """Publish goal state without allowing a stalled subscriber to block runs."""

    try:
        await asyncio.wait_for(
            emit_session_goal_updated_events(core, session_id, goal),
            timeout=_GOAL_EVENT_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        logger.warning("Timed out emitting goal events for %s", session_id)
    except Exception:
        logger.warning("Failed to emit goal events for %s", session_id, exc_info=True)


def _save_completion_transcript(core: Any, session_id: str) -> None:
    record = load_session_goal_record(core, session_id)
    try:
        record.manager.mark_session_modified(session_id)
        saved = record.manager.save_session(record.session)
    except Exception as exc:
        raise GoalRunExecutionError(
            f"Failed to persist synthesized goal completion for {session_id}: {exc}"
        ) from exc
    if saved is False:
        raise GoalRunExecutionError(
            f"Failed to persist synthesized goal completion for {session_id}"
        )


async def _bind_conversation(
    core: Any,
    *,
    session_id: str,
    agent_id: str,
) -> Any:
    conversation_manager = conversations.resolve_conversation_manager(
        core,
        agent_id,
        log=logger,
    )
    load_result = conversations.load_process_conversation(
        conversation_manager,
        session_id,
        log=logger,
    )
    if not load_result.ok or load_result.scoped_session_id != session_id:
        raise GoalRunStateError(f"Failed to bind goal run to session {session_id}")
    engine = getattr(core, "engine", None)
    if engine is not None and hasattr(engine, "prime_scoped_conversation_manager"):
        engine.prime_scoped_conversation_manager(agent_id, conversation_manager)
    return conversation_manager


def _discard_pending_scope(core: Any, run_id: str, agent_id: str) -> None:
    pending = getattr(
        getattr(core, "engine", None),
        "_pending_scoped_conversation_managers",
        None,
    )
    if isinstance(pending, dict):
        pending.pop((run_id, agent_id), None)


def _finalize_goal_locked(
    core: Any,
    session_id: str,
    *,
    goal_id: str,
    run_id: str,
    claimed_revision: int,
    result: dict[str, Any],
    elapsed_seconds: float,
) -> tuple[dict[str, Any] | None, bool, str | None]:
    """Finalize goal state while the caller owns the session goal lock."""

    try:
        record = load_session_goal_record(core, session_id, require_goal=True)
    except GoalNotFoundError:
        return None, False, None
    latest = record.goal
    assert latest is not None
    if latest["id"] != goal_id or latest.get("active_run_id") != run_id:
        return latest, False, None

    updated = deepcopy(latest)
    updated["tokens_used"] += _run_tokens(result)
    updated["time_used_seconds"] += max(elapsed_seconds, 0.0)
    if latest["revision"] == claimed_revision and latest["status"] == "active":
        next_status = goal_status_from_run_result(result)
        token_budget = updated.get("token_budget")
        if (
            next_status == "active"
            and isinstance(token_budget, int)
            and updated["tokens_used"] >= token_budget
        ):
            next_status = "budget_limited"
        updated["status"] = next_status

    completion_text = _completion_text(result, updated["status"], updated)
    if completion_text:
        result["message"] = completion_text
    updated["last_result"] = _persisted_result(result)

    updated["active_run_id"] = None
    updated["active_run_owner"] = None
    updated["active_run_started_at"] = None
    updated["revision"] = latest["revision"] + 1
    updated["updated_at"] = _timestamp()
    changed = save_session_goal(
        core,
        session_id,
        updated,
        expected_goal_id=goal_id,
        expected_revision=latest["revision"],
        expected_run_id=run_id,
    )
    if not changed:
        current = load_session_goal_record(core, session_id, require_goal=True).goal
        return current, False, None
    return updated, True, completion_text


async def _complete_claimed_goal_run(
    core: Any,
    session_id: str,
    *,
    claimed: dict[str, Any],
    claimed_revision: int,
    run_id: str,
    result: dict[str, Any],
    started: float,
    live_runs: dict[str, str],
    execution_context: ExecutionContext,
    agent_id: str,
    model_id: str | None,
    provider_id: str | None,
    infrastructure_error: Exception | None,
) -> dict[str, Any]:
    """Finalize state and transcript while the caller owns the session gate."""

    elapsed = time.monotonic() - started
    lock = get_session_goal_lock(core, session_id)
    try:
        async with lock:
            final_goal, goal_changed, completion_text = _finalize_goal_locked(
                core,
                session_id,
                goal_id=claimed["id"],
                run_id=run_id,
                claimed_revision=claimed_revision,
                result=result,
                elapsed_seconds=elapsed,
            )

            completion_error: GoalRunExecutionError | None = None
            if isinstance(completion_text, str) and completion_text.strip():
                try:
                    with execution_context_scope(execution_context):
                        emitted = await _emit_completion_message(
                            core,
                            completion_text,
                            agent_id=agent_id,
                            model_id=model_id,
                            provider_id=provider_id,
                        )
                    if emitted:
                        _save_completion_transcript(core, session_id)
                except GoalRunExecutionError as exc:
                    logger.error("Goal completion transcript failed", exc_info=True)
                    completion_error = exc

            if goal_changed:
                await _emit_goal_events_bounded(core, session_id, final_goal)
    finally:
        if live_runs.get(session_id) == run_id:
            live_runs.pop(session_id, None)

    if infrastructure_error is not None:
        raise GoalRunExecutionError(str(infrastructure_error)) from infrastructure_error
    if completion_error is not None:
        raise completion_error
    return {
        "goal": final_goal,
        "status": final_goal["status"] if final_goal is not None else "cleared",
        "result": _persisted_result(result),
    }


async def run_session_goal(
    core: Any,
    session_id: str,
    *,
    max_iterations: int | None = None,
    timeout_seconds: int | None = None,
    directory: str | None = None,
    run_mode_factory: Callable[..., Any] = RunMode,
) -> dict[str, Any]:
    """Run a persisted active goal until a configured or terminal outcome."""

    started = time.monotonic()
    resolved_iterations = _optional_positive_limit(
        max_iterations,
        field="max_iterations",
    )
    resolved_timeout = _optional_positive_limit(
        timeout_seconds,
        field="timeout_seconds",
    )
    try:
        (
            _session,
            _manager,
            session_metadata,
            agent_id,
            agent_mode,
            resolved_directory,
        ) = _resolve_scope(core, session_id, directory)
    except GoalNotFoundError as exc:
        raise GoalRunNotFoundError(str(exc)) from exc

    owner_id = _runtime_owner_id(core)
    live_runs = _live_runs(core)
    goal_lock = get_session_goal_lock(core, session_id)
    tracked = False
    request_gate: asyncio.Lock | None = None
    gate_acquired = False
    admission_failed = False
    result: dict[str, Any] = {"status": "error", "message": "Goal run failed"}
    infrastructure_error: Exception | None = None
    model_config: Any | None = None
    api_client: Any | None = None
    provider_id: str | None = None
    model_id: str | None = None
    recovered: dict[str, Any] | None = None
    limited: dict[str, Any] | None = None
    async with _goal_lock_with_run_deadline(
        goal_lock,
        started=started,
        timeout_seconds=resolved_timeout,
    ):
        try:
            record = load_session_goal_record(core, session_id, require_goal=True)
        except GoalNotFoundError as exc:
            raise GoalRunNotFoundError(str(exc)) from exc
        current = record.goal
        assert current is not None

        active_run_id = current.get("active_run_id")
        if active_run_id:
            if (
                current.get("active_run_owner") == owner_id
                and live_runs.get(session_id) == active_run_id
            ):
                raise GoalRunConflictError("Goal is already running")
            recovered = deepcopy(current)
            recovered["status"] = "paused"
            recovered["active_run_id"] = None
            recovered["active_run_owner"] = None
            recovered["active_run_started_at"] = None
            recovered["last_result"] = {
                "status": "orphaned_run",
                "message": "Recovered an unfinished goal run after server restart",
            }
            recovered["revision"] += 1
            recovered["updated_at"] = _timestamp()
            if not save_session_goal(
                core,
                session_id,
                recovered,
                expected_goal_id=current["id"],
                expected_revision=current["revision"],
                expected_run_id=active_run_id,
            ):
                raise GoalRunConflictError("Goal changed during orphan recovery")
            await _emit_goal_events_bounded(core, session_id, recovered)
        elif current["status"] != "active":
            raise GoalRunStateError(f"Goal status {current['status']} is not runnable")
        else:
            active_requests = getattr(core, "_opencode_active_requests", {})
            if (
                isinstance(active_requests, dict)
                and active_requests.get(session_id, 0) > 0
            ):
                raise GoalRunConflictError("Session already has active work")
            request_gate = process_lifecycle.get_session_request_gate(
                core,
                session_id,
            )
            if request_gate.locked():
                raise GoalRunConflictError("Session request gate is already reserved")

            token_budget = current.get("token_budget")
            if isinstance(token_budget, int) and current["tokens_used"] >= token_budget:
                limited = deepcopy(current)
                limited["status"] = "budget_limited"
                limited["revision"] += 1
                limited["updated_at"] = _timestamp()
                if not save_session_goal(
                    core,
                    session_id,
                    limited,
                    expected_goal_id=current["id"],
                    expected_revision=current["revision"],
                ):
                    raise GoalRunConflictError("Goal changed before budget update")
                await _emit_goal_events_bounded(core, session_id, limited)
            else:
                run_id = f"goalrun_{uuid4().hex}"
                claimed = deepcopy(current)
                claimed_revision = current["revision"] + 1
                claimed["revision"] = claimed_revision
                claimed["active_run_id"] = run_id
                claimed["active_run_owner"] = owner_id
                claimed["active_run_started_at"] = _timestamp()
                claimed["last_run_id"] = run_id
                claimed["updated_at"] = _timestamp()
                if not save_session_goal(
                    core,
                    session_id,
                    claimed,
                    expected_goal_id=current["id"],
                    expected_revision=current["revision"],
                ):
                    raise GoalRunConflictError("Goal changed before execution started")
                live_runs[session_id] = run_id
                try:
                    await _await_with_run_deadline(
                        request_gate.acquire(),
                        started=started,
                        timeout_seconds=resolved_timeout,
                    )
                    gate_acquired = True
                    tracked = await _await_with_run_deadline(
                        process_lifecycle.register_opencode_process_request(
                            core,
                            session_id,
                            asyncio.current_task(),
                        ),
                        started=started,
                        timeout_seconds=resolved_timeout,
                    )
                    await _await_with_run_deadline(
                        _emit_goal_events_bounded(core, session_id, claimed),
                        started=started,
                        timeout_seconds=resolved_timeout,
                    )
                except _GoalRunDeadlineExceeded:
                    admission_failed = True
                    result = {
                        "status": "timeout",
                        "message": (
                            f"Goal run reached the {resolved_timeout}-second time limit"
                        ),
                        "completion_type": "timeout",
                    }
                except asyncio.CancelledError:
                    admission_failed = True
                    result = {
                        "status": "cancelled",
                        "message": "Goal run cancelled",
                        "completion_type": "cancelled",
                    }
                except Exception as exc:
                    admission_failed = True
                    infrastructure_error = exc
                    result = {
                        "status": "error",
                        "message": str(exc) or type(exc).__name__,
                        "completion_type": "error",
                    }

    if recovered is not None:
        raise GoalRunStateError(
            "Recovered an orphaned goal run; resume the paused goal to continue"
        )
    if limited is not None:
        raise GoalRunStateError("Goal token budget is exhausted")

    remaining_budget = None
    if isinstance(claimed.get("token_budget"), int):
        remaining_budget = max(
            claimed["token_budget"] - claimed["tokens_used"],
            1,
        )

    execution_context = ExecutionContext(
        session_id=session_id,
        conversation_id=session_id,
        agent_id=agent_id,
        agent_mode=agent_mode,
        directory=resolved_directory,
        project_root=resolved_directory,
        workspace_root=resolved_directory,
        request_id=run_id,
    )
    context = {
        "run_kind": "session_goal",
        "session_id": session_id,
        "conversation_id": session_id,
        "agent_id": agent_id,
        "agent_mode": agent_mode,
        "goal_id": claimed["id"],
        "goal_revision": claimed_revision,
        "goal_objective": claimed["objective"],
        "max_iterations": resolved_iterations,
        "internal_prompt": True,
        "metadata": {"goal_id": claimed["id"], "run_id": run_id},
    }
    if remaining_budget is not None:
        context["run_token_budget"] = remaining_budget

    try:
        if not admission_failed:
            with execution_context_scope(execution_context):
                (
                    model_config,
                    api_client,
                    provider_id,
                    model_id,
                    variant,
                ) = await _await_with_run_deadline(
                    _resolve_model_runtime(core, session_metadata),
                    started=started,
                    timeout_seconds=resolved_timeout,
                )
                if provider_id:
                    context["provider_id"] = provider_id
                if model_id:
                    context["model_id"] = model_id
                if variant:
                    context["variant"] = variant

                await _await_with_run_deadline(
                    _bind_conversation(
                        core,
                        session_id=session_id,
                        agent_id=agent_id,
                    ),
                    started=started,
                    timeout_seconds=resolved_timeout,
                )
                run_mode = _make_run_mode(
                    run_mode_factory,
                    core,
                    max_iterations=resolved_iterations,
                    api_client=api_client,
                    model_config=model_config,
                )
                result_value = await _await_with_run_deadline(
                    run_mode.start(
                        name=f"Session goal: {claimed['objective']}",
                        description=_goal_prompt(claimed),
                        context=context,
                    ),
                    started=started,
                    timeout_seconds=resolved_timeout,
                )
                if not isinstance(result_value, dict):
                    raise GoalRunExecutionError("RunMode returned a non-object result")
                result = result_value
    except _GoalRunDeadlineExceeded:
        result = {
            "status": "timeout",
            "message": f"Goal run reached the {resolved_timeout}-second time limit",
            "completion_type": "timeout",
        }
    except asyncio.CancelledError:
        result = {
            "status": "cancelled",
            "message": "Goal run cancelled",
            "completion_type": "cancelled",
        }
    except Exception as exc:
        logger.exception("Session goal execution failed for %s", session_id)
        infrastructure_error = exc
        result = {
            "status": "error",
            "message": str(exc) or type(exc).__name__,
            "completion_type": "error",
        }
    finally:
        _discard_pending_scope(core, run_id, agent_id)

    completion_task = asyncio.create_task(
        _complete_claimed_goal_run(
            core,
            session_id,
            claimed=claimed,
            claimed_revision=claimed_revision,
            run_id=run_id,
            result=result,
            started=started,
            live_runs=live_runs,
            execution_context=execution_context,
            agent_id=agent_id,
            model_id=model_id,
            provider_id=provider_id,
            infrastructure_error=infrastructure_error,
        )
    )
    cancellation: asyncio.CancelledError | None = None
    try:
        while not completion_task.done():
            try:
                await asyncio.shield(completion_task)
            except asyncio.CancelledError as exc:
                cancellation = exc
        completion_result = completion_task.result()
        if cancellation is not None:
            raise cancellation
        return completion_result
    finally:
        try:
            await asyncio.shield(
                process_lifecycle.finalize_opencode_process_request(
                    core,
                    session_id,
                    asyncio.current_task(),
                    request_tracked=tracked,
                )
            )
        finally:
            if gate_acquired and request_gate is not None and request_gate.locked():
                request_gate.release()
