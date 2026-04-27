from __future__ import annotations

"""Engine – high‑level coordination layer for Penguin.

The Engine owns the reasoning loop (single‑turn and multi‑step), delegates
LLM calls to ``APIClient`` and tool execution to ``ActionExecutor``, and
maintains light run‑time state (start‑time, iteration counter, active
stop‑conditions).  It receives pre‑constructed managers from PenguinCore so it
remains test‑friendly and avoids hidden globals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
import uuid
import asyncio
import copy
from contextlib import contextmanager
from contextvars import ContextVar, Token
from penguin.constants import UI_ASYNC_SLEEP_SECONDS
import re
import time

# Removed unused: import multiprocessing as mp
from typing import (
    Any,
    Awaitable,
    Callable,
    Coroutine,
    Dict,
    List,
    Optional,
    Sequence,
    Tuple,
)
from penguin.utils.errors import LLMEmptyResponseError

from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.utils.parser import (  # type: ignore
    ActionExecutor,
    ActionType,
    CodeActAction,
    parse_action,
)
from penguin.system.state import MessageCategory  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.llm.runtime import (
    build_empty_response_diagnostics as build_llm_empty_response_diagnostics,
    build_reasoning_fallback_note,
    call_with_retry as call_llm_with_retry,
    execute_pending_tool_calls,
    handler_has_pending_tool_call,
    prepare_responses_tool_kwargs,
)
from penguin.tools import ToolManager  # type: ignore
from penguin.tools.runtime import (
    ToolExecutionPolicy,
    execute_tool_calls_serially,
    legacy_action_result_from_tool_result,
    tool_calls_from_codeact_actions,
    tool_results_loop_identity,
)
from penguin.config import TASK_COMPLETION_PHRASE  # Add this import
from penguin.constants import get_engine_max_iterations_default
from penguin.system.execution_context import get_current_execution_context

import logging

# MessageBus for inter-agent communication (optional import)
try:
    from penguin.system.message_bus import MessageBus, ProtocolMessage
except ImportError:
    MessageBus = None  # type: ignore
    ProtocolMessage = None  # type: ignore

logger = logging.getLogger(__name__)


def _trace_log_info(message: str, *args: Any) -> None:
    """Mirror engine trace logs to uvicorn for live server debugging."""
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


_ACTION_TAG_NAME_PATTERN = "|".join(action_type.value for action_type in ActionType)

# ---------------------------------------------------------------------------
# Settings & Stop‑conditions
# ---------------------------------------------------------------------------


@dataclass
class ResourceSnapshot:
    """Represents resource usage at a point in time."""

    tokens_prompt: int = 0
    tokens_completion: int = 0
    wall_clock_sec: float = 0.0
    # Future: cpu_sec, mem_mb, network_kb, docker_exit_code, …


@dataclass
class LoopConfig:
    """Configuration for _iteration_loop() to handle both run_response and run_task modes.

    This dataclass captures the differences between the two modes, allowing
    a single loop implementation to serve both entry points.
    """

    # Mode identifier for logging
    mode: str  # "response" or "task"

    # Termination signal - which action name triggers explicit completion
    termination_action: str  # "finish_response" or "finish_task"

    # Termination phrases for non-action completion hints when applicable
    completion_phrases: Optional[List[str]] = None

    # Streaming configuration
    streaming: bool = True
    stream_callback: Optional[Callable[[str], None]] = None

    # Whether to reset/finalize streaming state between iterations
    manage_streaming_state: bool = False

    # How to save conversation (sync vs async)
    async_save: bool = False

    # Event publishing configuration
    enable_events: bool = False
    task_metadata: Optional[Dict[str, Any]] = None

    # Message callback for tool results (run_task mode)
    message_callback: Optional[Callable[..., Awaitable[None]]] = None

    # Default completion status when loop ends without explicit signal
    default_completion_status: str = "completed"

@dataclass
class LoopState:
    """Consolidated state for iteration loops (run_response, run_task).

    This dataclass replaces scattered dynamic attributes that were
    created on-demand with `if not hasattr(self, '_xxx')` patterns.
    Now all state is initialized upfront and reset per-run.
    """

    # Empty/trivial response tracking
    empty_response_count: int = 0

    # Response repetition detection
    last_response_hash: Optional[int] = None
    repeat_count: int = 0

    # Empty tool-only iteration tracking
    empty_tool_only_count: int = 0
    last_tool_only_signature: Optional[str] = None
    last_tool_only_summary: str = ""
    repeated_tool_only_count: int = 0

    def reset(self) -> None:
        """Reset state for a new run."""
        self.empty_response_count = 0
        self.last_response_hash = None
        self.repeat_count = 0
        self.empty_tool_only_count = 0
        self.last_tool_only_signature = None
        self.last_tool_only_summary = ""
        self.repeated_tool_only_count = 0

    def check_repeated(self, response: str) -> bool:
        """Check if response is repeated, return True if should break.

        Returns True if this response has been seen >= 2 times consecutively.
        """
        response_signature = hash((response or "")[:200])
        if response_signature == self.last_response_hash:
            self.repeat_count += 1
            if self.repeat_count >= 2:
                return True
        else:
            self.repeat_count = 0
        self.last_response_hash = response_signature
        return False

    def check_trivial(self, response: str, threshold: int = 10) -> Tuple[bool, bool]:
        """Check if response is trivial, return (is_trivial, should_break).

        Returns:
            Tuple of (is_empty_or_trivial, should_break_after_3)
        """
        stripped_response = (response or "").strip()
        is_empty_or_trivial = (
            not stripped_response or len(stripped_response) < threshold
        )

        if is_empty_or_trivial:
            self.empty_response_count += 1
            should_break = self.empty_response_count >= 3
        else:
            self.empty_response_count = 0
            should_break = False

        return is_empty_or_trivial, should_break

    def check_empty_tool_only(
        self,
        response: str,
        iteration_results: List[Dict[str, Any]],
        *,
        placeholder: str = "[Empty response from model]",
        repeat_threshold: int = 3,
    ) -> Tuple[bool, Optional[str]]:
        """Track empty tool-only iterations and detect pathological loops."""
        stripped_response = (response or "").strip()
        is_empty_tool_only = bool(iteration_results) and (
            not stripped_response or stripped_response == placeholder
        )

        if not is_empty_tool_only:
            self.empty_tool_only_count = 0
            self.last_tool_only_signature = None
            self.last_tool_only_summary = ""
            self.repeated_tool_only_count = 0
            return False, None

        self.empty_tool_only_count += 1
        identity = tool_results_loop_identity(iteration_results)
        signature = identity.fingerprint
        self.last_tool_only_summary = identity.summary

        if signature == self.last_tool_only_signature:
            self.repeated_tool_only_count += 1
        else:
            self.last_tool_only_signature = signature
            self.repeated_tool_only_count = 1

        if self.repeated_tool_only_count >= repeat_threshold:
            return True, "repeated_empty_tool_only_iterations"

        return False, None


_EMPTY_RESPONSE_PLACEHOLDER = "[Empty response from model]"
_TOOL_ONLY_STALL_NOTES = {
    "repeated_empty_tool_only_iterations": (
        "Stopping because empty tool-only turns repeated the same tool result "
        "identity; this is probably a stale loop rather than forward progress."
    ),
}


@dataclass
class EngineSettings:
    """Immutable configuration for an Engine instance."""

    retry_attempts: int = 2
    backoff_seconds: float = 1.5
    streaming_default: bool = False
    max_iterations_default: int = field(
        default_factory=get_engine_max_iterations_default
    )
    token_budget_stop_enabled: bool = False
    wall_clock_stop_seconds: Optional[int] = None


class StopCondition:
    """Base class for pluggable stop conditions."""

    async def should_stop(self, engine: "Engine") -> bool:  # noqa: F821
        raise NotImplementedError


# TODO: Look into how the mechanics of this work
# It would be redundant to stop something that happens to go over the budget
# when the context window manager is designed exactly to deal with this...
class TokenBudgetStop(StopCondition):
    async def should_stop(self, engine: "Engine") -> bool:
        # Use the active agent's conversation window if available
        cm = engine.get_conversation_manager()
        cw = None
        if cm:
            if hasattr(cm, "get_current_context_window"):
                try:
                    cw = cm.get_current_context_window()  # type: ignore[attr-defined]
                except Exception:
                    cw = getattr(cm, "context_window", None)
            else:
                cw = getattr(cm, "context_window", None)
        return cw.is_over_budget() if cw else False


class WallClockStop(StopCondition):
    def __init__(self, max_seconds: int):
        self.max_delta = timedelta(seconds=max_seconds)

    async def should_stop(self, engine: "Engine") -> bool:
        return datetime.utcnow() - engine.start_time >= self.max_delta


class ExternalCallbackStop(StopCondition):
    def __init__(self, coro: Callable[["Engine"], Coroutine[Any, Any, bool]]):
        self.coro = coro

    async def should_stop(self, engine: "Engine") -> bool:
        return await self.coro(engine)


# ---------------------------------------------------------------------------
# Engine core
# ---------------------------------------------------------------------------


@dataclass
class EngineAgent:
    """Registered agent runtime with its own conversation manager and optional
    component overrides.

    By default, agents inherit the Engine's shared `api_client`, `tool_manager`,
    and `action_executor` unless explicitly provided.
    """

    agent_id: str
    conversation_manager: ConversationManager
    settings: Optional[EngineSettings] = None
    api_client: Optional[APIClient] = None
    tool_manager: Optional[ToolManager] = None
    action_executor: Optional[ActionExecutor] = None


@dataclass
class EngineRunState:
    """Per-request run state for concurrent Engine usage."""

    current_agent_id: Optional[str] = None
    current_iteration: int = 0
    start_time: datetime = field(default_factory=datetime.utcnow)
    loop_state: LoopState = field(default_factory=LoopState)
    scoped_conversation_managers: Dict[tuple[int, str], Any] = field(
        default_factory=dict
    )
    api_client: Optional[Any] = None
    model_config: Optional[Any] = None


_CURRENT_ENGINE_RUN_STATE: ContextVar[Optional[EngineRunState]] = ContextVar(
    "penguin_engine_run_state",
    default=None,
)


class _ScopedConversationManager:
    """Agent-scoped ConversationManager view without mutating global pointers."""

    def __init__(self, base_manager: ConversationManager, agent_id: str):
        self._base_manager = base_manager
        self._agent_id = agent_id
        self.core = getattr(base_manager, "core", None)
        conversation = None
        if hasattr(base_manager, "get_agent_conversation"):
            conversation = base_manager.get_agent_conversation(
                agent_id, create_if_missing=True
            )
        if conversation is None:
            conversation = getattr(base_manager, "conversation", None)
        self._conversation = self._clone_conversation(conversation)

    def _clone_conversation(self, conversation: Any) -> Any:
        if conversation is None:
            return None
        try:
            cloned = copy.copy(conversation)
        except Exception:
            return conversation

        session = getattr(conversation, "session", None)
        if session is None:
            return cloned

        try:
            cloned_session = copy.copy(session)
            if isinstance(getattr(session, "messages", None), list):
                cloned_session.messages = list(session.messages)
            if isinstance(getattr(session, "metadata", None), dict):
                cloned_session.metadata = dict(session.metadata)
            cloned.session = cloned_session
        except Exception:
            return cloned
        return cloned

    @property
    def conversation(self) -> Any:
        return self._conversation

    def save(self) -> bool:
        if self._conversation is not None and hasattr(self._conversation, "save"):
            return bool(self._conversation.save())
        if hasattr(self._base_manager, "save"):
            return bool(self._base_manager.save())
        return False

    def add_action_result(
        self,
        action_type: str,
        result: str,
        status: str = "completed",
        *,
        tool_call_id: Optional[str] = None,
        tool_arguments: Optional[str] = None,
    ) -> Any:
        if self._conversation is not None and hasattr(
            self._conversation, "add_action_result"
        ):
            return self._conversation.add_action_result(
                action_type,
                result,
                status,
                tool_call_id=tool_call_id,
                tool_arguments=tool_arguments,
            )
        return self._base_manager.add_action_result(
            action_type,
            result,
            status,
            tool_call_id=tool_call_id,
            tool_arguments=tool_arguments,
        )

    def get_current_session(self) -> Any:
        session = getattr(self._conversation, "session", None)
        if session is not None:
            return session
        if hasattr(self._base_manager, "get_current_session"):
            return self._base_manager.get_current_session()
        return None

    def get_current_context_window(self) -> Any:
        try:
            windows = getattr(self._base_manager, "agent_context_windows", None)
            if isinstance(windows, dict):
                scoped = windows.get(self._agent_id)
                if scoped is not None:
                    return scoped
        except Exception:
            pass
        if hasattr(self._base_manager, "get_current_context_window"):
            return self._base_manager.get_current_context_window()
        return getattr(self._base_manager, "context_window", None)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._base_manager, name)


class Engine:
    """High‑level coordinator for reasoning / action loops."""

    def __init__(
        self,
        settings: EngineSettings,
        conversation_manager: ConversationManager,
        api_client: APIClient,
        tool_manager: ToolManager,
        action_executor: ActionExecutor,
        *,
        stop_conditions: Optional[Sequence[StopCondition]] = None,
    ) -> None:
        self.settings = settings
        # Shared components (agents can override per-agent)
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.action_executor = action_executor
        self.stop_conditions: List[StopCondition] = list(stop_conditions or [])

        # Multi-agent registry and defaults
        self.agents: Dict[str, EngineAgent] = {}
        # Must be initialized before property-backed fields are assigned.
        self._default_run_state = EngineRunState()
        self.default_agent_id: str = "default"
        self.current_agent_id = None
        # Register a default agent backed by the provided ConversationManager
        self.register_agent(
            agent_id=self.default_agent_id, conversation_manager=conversation_manager
        )
        # Back-compat: keep attribute pointing at default agent's manager
        self.conversation_manager = conversation_manager

        # Inject default conditions based on settings
        if settings.token_budget_stop_enabled and not any(
            isinstance(s, TokenBudgetStop) for s in self.stop_conditions
        ):
            self.stop_conditions.append(TokenBudgetStop())
        if settings.wall_clock_stop_seconds and not any(
            isinstance(s, WallClockStop) for s in self.stop_conditions
        ):
            self.stop_conditions.append(WallClockStop(settings.wall_clock_stop_seconds))

        # Light run‑time state
        self._interrupted: bool = False
        self._pending_scoped_conversation_managers: Dict[tuple[str, str], Any] = {}

    @staticmethod
    def _trace_preview(value: Any, limit: int = 120) -> str:
        text = str(value or "")
        text = text.replace("\n", "\\n")
        if len(text) <= limit:
            return text
        return text[: max(limit - 3, 0)] + "..."

    def _trace_request_fields(self) -> tuple[str, str]:
        execution_context = get_current_execution_context()
        request_id = (
            execution_context.request_id
            if execution_context and execution_context.request_id
            else "unknown"
        )
        session_id = (
            execution_context.session_id
            if execution_context and execution_context.session_id
            else (
                execution_context.conversation_id
                if execution_context and execution_context.conversation_id
                else ""
            )
        )
        return request_id, session_id

    @staticmethod
    def _conversation_session_id(cm: Any) -> Optional[str]:
        try:
            session = (
                cm.get_current_session() if hasattr(cm, "get_current_session") else None
            )
        except Exception:
            session = None
        if session is None:
            session = getattr(getattr(cm, "conversation", None), "session", None)
        return getattr(session, "id", None) if session is not None else None

    def _get_loop_state(self) -> LoopState:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            return run_state.loop_state
        return self._default_run_state.loop_state

    def _get_runtime_api_client(self) -> Any:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None and run_state.api_client is not None:
            return run_state.api_client
        return self.api_client

    def _get_runtime_model_config(self) -> Any:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None and run_state.model_config is not None:
            return run_state.model_config
        return getattr(self, "model_config", None)

    @property
    def current_agent_id(self) -> Optional[str]:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            return run_state.current_agent_id
        return self._default_run_state.current_agent_id

    @current_agent_id.setter
    def current_agent_id(self, value: Optional[str]) -> None:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            run_state.current_agent_id = value
            return
        self._default_run_state.current_agent_id = value

    @property
    def current_iteration(self) -> int:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            return run_state.current_iteration
        return self._default_run_state.current_iteration

    @current_iteration.setter
    def current_iteration(self, value: int) -> None:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            run_state.current_iteration = value
            return
        self._default_run_state.current_iteration = value

    @property
    def start_time(self) -> datetime:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            return run_state.start_time
        return self._default_run_state.start_time

    @start_time.setter
    def start_time(self, value: datetime) -> None:
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is not None:
            run_state.start_time = value
            return
        self._default_run_state.start_time = value

    @contextmanager
    def _run_state_scope(self, agent_id: Optional[str]) -> Any:
        """Scope mutable run state to a single in-flight request."""
        token: Token[Optional[EngineRunState]] = _CURRENT_ENGINE_RUN_STATE.set(
            EngineRunState(current_agent_id=agent_id)
        )
        try:
            yield
        finally:
            _CURRENT_ENGINE_RUN_STATE.reset(token)

    # ------------------------------------------------------------------
    # Agent registry API
    # ------------------------------------------------------------------

    def register_agent(
        self,
        *,
        agent_id: str,
        conversation_manager: ConversationManager,
        settings: Optional[EngineSettings] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        action_executor: Optional[ActionExecutor] = None,
    ) -> None:
        """Register or replace an agent in the Engine registry."""
        self.agents[agent_id] = EngineAgent(
            agent_id=agent_id,
            conversation_manager=conversation_manager,
            settings=settings,
            api_client=api_client,
            tool_manager=tool_manager,
            action_executor=action_executor,
        )

    def get_agent(self, agent_id: Optional[str] = None) -> Optional[EngineAgent]:
        return self.agents.get(agent_id or self.default_agent_id)

    def list_agents(self) -> List[str]:
        return list(self.agents.keys())

    def set_default_agent(self, agent_id: str) -> None:
        if agent_id not in self.agents:
            raise KeyError(f"Agent '{agent_id}' is not registered")
        self.default_agent_id = agent_id

    def unregister_agent(self, agent_id: str) -> None:
        """Remove an agent from the registry."""
        if agent_id == self.default_agent_id:
            raise ValueError("Cannot unregister the default agent")
        self.agents.pop(agent_id, None)
        if self.current_agent_id == agent_id:
            self.current_agent_id = self.default_agent_id

    def get_conversation_manager(self, agent_id: Optional[str] = None) -> Optional[Any]:
        resolved_agent_id = agent_id or self.current_agent_id
        agent = self.get_agent(resolved_agent_id)
        if not agent:
            return None
        if resolved_agent_id:
            try:
                return self._get_scoped_conversation_manager(
                    agent.conversation_manager,
                    resolved_agent_id,
                )
            except Exception:
                logger.exception(
                    "Failed to build scoped conversation manager for agent '%s'",
                    resolved_agent_id,
                )
        return agent.conversation_manager

    # ------------------------------------------------------------------
    # MessageBus integration
    # ------------------------------------------------------------------

    def setup_message_bus(
        self,
        ui_event_callback: Optional[
            Callable[[str, Dict[str, Any]], Awaitable[None]]
        ] = None,
    ) -> None:
        """Register MessageBus handlers for inter-agent communication.

        Call this after Engine initialization to enable message routing.

        Args:
            ui_event_callback: Optional callback to emit UI events (e.g., core.emit_ui_event)
        """
        if not (MessageBus and ProtocolMessage):
            logger.debug("MessageBus not available, skipping setup")
            return

        try:
            bus = MessageBus.get_instance()

            async def _human_handler(msg: ProtocolMessage) -> None:
                """Forward messages to 'human' recipient to UI."""
                if ui_event_callback:
                    payload = {
                        "agent_id": msg.sender,
                        "recipient_id": msg.recipient,
                        "content": msg.content,
                        "message_type": msg.message_type,
                        "metadata": msg.metadata,
                        "session_id": msg.session_id,
                        "message_id": msg.message_id,
                    }
                    await ui_event_callback("human_message", payload)

            bus.register_handler("human", _human_handler)
            logger.debug("MessageBus human handler registered")
        except Exception as e:
            logger.debug(f"MessageBus setup failed: {e}")

    async def route_message(
        self,
        recipient_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        agent_id: Optional[str] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Route a message to another agent or recipient via MessageBus.

        Args:
            recipient_id: Target agent or "human"
            content: Message content
            message_type: Type of message (default: "message")
            metadata: Optional metadata dict
            agent_id: Sender agent ID (defaults to current agent)
            channel: Optional channel identifier

        Returns:
            True if message was sent, False otherwise
        """
        try:
            if not (MessageBus and ProtocolMessage):
                logger.warning("MessageBus not available for routing")
                return False

            sender = agent_id or self.current_agent_id or self.default_agent_id
            session_id = None
            try:
                cm = self.get_conversation_manager(sender)
                if cm:
                    session = cm.get_current_session()
                    session_id = getattr(session, "id", None)
            except Exception:
                pass

            msg = ProtocolMessage(
                sender=sender,
                recipient=recipient_id,
                content=content,
                message_type=message_type,
                metadata=metadata or {},
                session_id=session_id,
                channel=channel,
            )
            await MessageBus.get_instance().send(msg)
            return True
        except Exception as e:
            logger.error(f"route_message failed: {e}")
            return False

    async def send_to_agent(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a message to an agent."""
        return await self.route_message(
            agent_id,
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def send_to_human(
        self,
        content: Any,
        *,
        message_type: str = "status",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a message to the human (UI)."""
        return await self.route_message(
            "human",
            content,
            message_type=message_type,
            metadata=metadata,
            channel=channel,
        )

    async def human_reply(
        self,
        agent_id: str,
        content: Any,
        *,
        message_type: str = "message",
        metadata: Optional[Dict[str, Any]] = None,
        channel: Optional[str] = None,
    ) -> bool:
        """Send a reply from human to an agent.

        This forces the sender identity to "human" in the envelope.
        """
        try:
            if not (MessageBus and ProtocolMessage):
                # Fallback: add as user message to the conversation
                cm = self.get_conversation_manager(agent_id)
                if cm and cm.conversation:
                    cm.conversation.add_message(
                        role="user",
                        content=content,
                        category=MessageCategory.DIALOG,
                        metadata={"via": "human_reply", **(metadata or {})},
                        message_type=message_type,
                    )
                    cm.save()
                return True

            session_id = None
            try:
                cm = self.get_conversation_manager(agent_id)
                if cm:
                    session = cm.get_current_session()
                    session_id = getattr(session, "id", None)
            except Exception:
                pass

            msg = ProtocolMessage(
                sender="human",
                recipient=agent_id,
                content=content,
                message_type=message_type,
                metadata=metadata or {},
                session_id=session_id,
                channel=channel,
            )
            await MessageBus.get_instance().send(msg)
            return True
        except Exception as e:
            logger.error(f"human_reply failed: {e}")
            return False

    def _resolve_components(self, agent_id: Optional[str] = None):
        """Return (conversation_manager, api_client, tool_manager, action_executor)
        for the target agent, falling back to Engine shared instances.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            # Fallback to defaults for safety
            cm = self.conversation_manager
            if agent_id:
                try:
                    cm = self._get_scoped_conversation_manager(cm, agent_id)
                except Exception:
                    logger.exception(
                        "Failed to build scoped conversation manager for agent '%s'",
                        agent_id,
                    )
            return (
                cm,
                self._get_runtime_api_client(),
                self.tool_manager,
                self.action_executor,
            )
        cm = agent.conversation_manager
        if agent_id:
            try:
                cm = self._get_scoped_conversation_manager(cm, agent_id)
            except Exception:
                logger.exception(
                    "Failed to build scoped conversation manager for agent '%s'",
                    agent_id,
                )
        return (
            cm,
            agent.api_client or self._get_runtime_api_client(),
            agent.tool_manager or self.tool_manager,
            agent.action_executor or self.action_executor,
        )

    def _get_scoped_conversation_manager(
        self,
        base_manager: ConversationManager,
        agent_id: str,
    ) -> _ScopedConversationManager:
        """Return a request-scoped conversation view reused within the same run."""
        request_id, session_id = self._trace_request_fields()
        run_state = _CURRENT_ENGINE_RUN_STATE.get()
        if run_state is None:
            scoped = _ScopedConversationManager(base_manager, agent_id)
            _trace_log_info(
                "engine.scope.create request=%s session=%s agent=%s cache=none base_cm=%s scoped_cm=%s scoped_session=%s",
                request_id,
                session_id or "unknown",
                agent_id,
                hex(id(base_manager)),
                hex(id(scoped)),
                self._conversation_session_id(scoped) or "unknown",
            )
            return scoped

        key = (id(base_manager), agent_id)
        cached = run_state.scoped_conversation_managers.get(key)
        if isinstance(cached, _ScopedConversationManager):
            _trace_log_info(
                "engine.scope.reuse request=%s session=%s agent=%s cache=%s base_cm=%s scoped_cm=%s scoped_session=%s",
                request_id,
                session_id or "unknown",
                agent_id,
                len(run_state.scoped_conversation_managers),
                hex(id(base_manager)),
                hex(id(cached)),
                self._conversation_session_id(cached) or "unknown",
            )
            return cached

        pending_key = (request_id, agent_id)
        pending = self._pending_scoped_conversation_managers.pop(pending_key, None)
        if pending is not None:
            run_state.scoped_conversation_managers[key] = pending
            _trace_log_info(
                "engine.scope.adopt request=%s session=%s agent=%s cache=%s base_cm=%s scoped_cm=%s scoped_session=%s",
                request_id,
                session_id or "unknown",
                agent_id,
                len(run_state.scoped_conversation_managers),
                hex(id(base_manager)),
                hex(id(pending)),
                self._conversation_session_id(pending) or "unknown",
            )
            return pending

        scoped = _ScopedConversationManager(base_manager, agent_id)
        run_state.scoped_conversation_managers[key] = scoped
        _trace_log_info(
            "engine.scope.create request=%s session=%s agent=%s cache=%s base_cm=%s scoped_cm=%s scoped_session=%s",
            request_id,
            session_id or "unknown",
            agent_id,
            len(run_state.scoped_conversation_managers),
            hex(id(base_manager)),
            hex(id(scoped)),
            self._conversation_session_id(scoped) or "unknown",
        )
        return scoped

    def prime_scoped_conversation_manager(
        self,
        agent_id: str,
        conversation_manager: Any,
    ) -> None:
        """Prime the next request-local engine run with a preloaded scoped manager."""
        execution_context = get_current_execution_context()
        request_id = (
            execution_context.request_id
            if execution_context and execution_context.request_id
            else None
        )
        if not request_id:
            return
        self._pending_scoped_conversation_managers[(request_id, agent_id)] = (
            conversation_manager
        )
        _trace_log_info(
            "engine.scope.prime request=%s session=%s agent=%s scoped_cm=%s scoped_session=%s",
            request_id,
            execution_context.session_id if execution_context else "unknown",
            agent_id,
            hex(id(conversation_manager)),
            self._conversation_session_id(conversation_manager) or "unknown",
        )

    def _extract_usage_from_api_client(self, api_client: Any) -> Dict[str, Any]:
        """Read normalized usage metadata from the active API client handler."""
        handler = getattr(api_client, "client_handler", None)
        getter = getattr(handler, "get_last_usage", None)
        if not callable(getter):
            return {}
        try:
            usage = getter()
        except Exception:
            return {}
        return usage if isinstance(usage, dict) else {}

    # ------------------------------------------------------------------
    # Iteration Loop Helpers
    # ------------------------------------------------------------------

    def _check_wallet_guard_termination(
        self,
        last_response: str,
        iteration_results: List[Dict[str, Any]],
        mode: str = "response",
    ) -> Tuple[bool, Optional[str]]:
        """Check WALLET_GUARD conditions that should terminate the loop.

        Consolidates the common termination checks used by both run_response and run_task.

        Args:
            last_response: The assistant's response text
            iteration_results: List of action results from this iteration
            mode: "response" or "task" for logging context

        Returns:
            Tuple of (should_break, completion_status)
            - should_break: True if loop should terminate
            - completion_status: Status string if breaking, None otherwise
        """
        stripped_response = (last_response or "").strip()
        loop_state = self._get_loop_state()

        tool_only_break, tool_only_reason = loop_state.check_empty_tool_only(
            last_response,
            iteration_results,
        )
        if tool_only_break:
            logger.warning(
                "[WALLET_GUARD] Breaking %s: %s after %s consecutive empty tool-only iterations (repeated_signature=%s)",
                mode,
                tool_only_reason,
                loop_state.empty_tool_only_count,
                loop_state.repeated_tool_only_count,
            )
            return True, tool_only_reason

        # Check for no-action completion (models that don't use CodeAct format)
        if not iteration_results and last_response:
            if self._looks_like_malformed_action_output(last_response):
                logger.warning(
                    "[WALLET_GUARD] Suppressing implicit completion for malformed %s response",
                    mode,
                )
                return False, None
            has_action_tags = bool(
                re.search(r"<\w+>.*?</\w+>", last_response, re.DOTALL)
            )
            if not has_action_tags:
                logger.debug(
                    f"[WALLET_GUARD] No actions in {mode} response, treating as complete (model may not support CodeAct)"
                )
                return True, "implicit_completion" if mode == "task" else None

        # Tool-only turns are valid for providers like OpenAI/Codex. Treat an
        # empty assistant transcript as in-progress work rather than a loop.
        if iteration_results and not stripped_response:
            loop_state.empty_response_count = 0
            loop_state.repeat_count = 0
            loop_state.last_response_hash = None
            return False, None

        # Check for confused model echoing tool results
        if last_response and "[Tool Result]" in last_response:
            logger.warning(
                f"[WALLET_GUARD] Breaking {mode}: model is echoing tool results as text"
            )
            return True, "implicit_completion" if mode == "task" else None

        # Check for repeated/looping responses
        if loop_state.check_repeated(last_response):
            logger.warning(
                f"[WALLET_GUARD] Breaking {mode}: response repeated {loop_state.repeat_count} times"
            )
            return True, "implicit_completion" if mode == "task" else None

        # Check for empty/trivial responses
        # Tool-bearing turns with assistant text still reset the trivial counter.
        if iteration_results:
            loop_state.empty_response_count = 0
            return False, None

        is_empty_or_trivial, should_break = loop_state.check_trivial(last_response)

        # DIAGNOSTIC: Log trivial responses
        if is_empty_or_trivial or len(last_response or "") < 20:
            last_action = (
                iteration_results[-1].get("action") if iteration_results else "none"
            )
            logger.warning(
                f"[WALLET_GUARD] Trivial response in {mode}: "
                f"raw={repr(last_response)}, "
                f"stripped_len={len(stripped_response)}, "
                f"last_action={last_action}, "
                f"iter={self.current_iteration}"
            )

        if is_empty_or_trivial:
            logger.debug(
                f"Empty/trivial response #{loop_state.empty_response_count} ({mode}): '{stripped_response[:20] if stripped_response else '(empty)'}'"
            )

        if should_break:
            logger.warning(
                f"[WALLET_GUARD] Breaking {mode}: {loop_state.empty_response_count} consecutive trivial responses"
            )
            return True, "implicit_completion" if mode == "task" else None

        return False, None

    def _suppress_empty_tool_only_placeholder(
        self,
        cm: ConversationManager,
        assistant_response: str,
        iteration_results: List[Dict[str, Any]],
    ) -> str:
        """Remove generic empty placeholders for valid tool-only turns."""
        if not iteration_results or assistant_response != _EMPTY_RESPONSE_PLACEHOLDER:
            return assistant_response

        try:
            conversation = getattr(cm, "conversation", None)
            session = getattr(conversation, "session", None)
            messages = getattr(session, "messages", None)
            last_message = messages[-1] if isinstance(messages, list) and messages else None
            if (
                last_message is not None
                and getattr(last_message, "role", None) == "assistant"
                and getattr(last_message, "content", None) == assistant_response
            ):
                messages.pop()
                if hasattr(conversation, "_modified"):
                    conversation._modified = True
                if getattr(conversation, "session_manager", None) and getattr(session, "id", None):
                    try:
                        conversation.session_manager.mark_session_modified(session.id)
                    except Exception:
                        logger.debug(
                            "Failed to mark session modified after suppressing empty tool-only placeholder",
                            exc_info=True,
                        )
                logger.info(
                    "Suppressed generic empty-response placeholder for valid tool-only turn"
                )
        except Exception:
            logger.debug(
                "Failed to suppress empty tool-only placeholder",
                exc_info=True,
            )
        return ""

    def _build_tool_only_stall_note(self, status: Optional[str]) -> str:
        """Return a user-facing explanation for stalled tool-only loops."""
        if not isinstance(status, str):
            return ""
        note = _TOOL_ONLY_STALL_NOTES.get(status, "")
        if not note:
            return ""

        loop_state = self._get_loop_state()
        repeated_tool = loop_state.last_tool_only_summary.strip()
        if repeated_tool:
            note = f"{note} Repeated tool result: {repeated_tool}."
        return (
            f"{note} To continue, send a new message with the next file, range, "
            "query, or command to try."
        )

    async def _record_tool_only_stall_note(
        self,
        cm: ConversationManager,
        status: Optional[str],
    ) -> str:
        """Persist a clearer terminal note for stalled tool-only loops."""
        note = self._build_tool_only_stall_note(status)
        if not note:
            return ""

        try:
            session_messages = (
                cm.conversation.session.messages
                if hasattr(cm.conversation, "session")
                else []
            )
            last_msg = session_messages[-1] if session_messages else None
            already_added = (
                last_msg
                and getattr(last_msg, "role", None) == "assistant"
                and getattr(last_msg, "content", None) == note
            )
        except Exception:
            already_added = False

        if not already_added:
            cm.conversation.add_assistant_message(note)
            await self._save_conversation(cm, async_save=True)
        return note

    def _looks_like_malformed_action_output(self, response: str) -> bool:
        """Return whether text looks like a partial or malformed tool call."""
        if not isinstance(response, str) or not response.strip():
            return False
        if parse_action(response):
            return False

        stripped = response.strip()
        if re.search(rf"</(?:{_ACTION_TAG_NAME_PATTERN})>", stripped, re.IGNORECASE):
            return True
        if re.search(
            rf"<(?:{_ACTION_TAG_NAME_PATTERN})>(?:(?!</).)*$",
            stripped,
            re.DOTALL | re.IGNORECASE,
        ):
            return True
        if re.search(
            rf"<(?:{_ACTION_TAG_NAME_PATTERN})?[^>]*$", stripped, re.IGNORECASE
        ):
            return True
        return False

    def _queue_malformed_action_repair_note(
        self,
        cm: Any,
        response: str,
        *,
        mode: str,
    ) -> bool:
        """Add a repair note when the model emits broken tool syntax."""
        if not self._looks_like_malformed_action_output(response):
            return False

        request_id, session_id = self._trace_request_fields()
        preview = self._trace_preview(response)
        logger.warning(
            "[WALLET_GUARD] Malformed action syntax in %s response request=%s session=%s preview=%r",
            mode,
            request_id,
            session_id or "unknown",
            preview,
        )
        try:
            cm.conversation.add_message(
                role="system",
                content=(
                    "The previous assistant response ended with malformed or partial tool syntax. "
                    "Do not treat it as complete. Repair by continuing with either plain assistant text "
                    "or one complete valid tool tag. Do not emit dangling XML-like fragments."
                ),
                category=MessageCategory.SYSTEM_OUTPUT,
                metadata={
                    "type": "malformed_action_output",
                    "mode": mode,
                    "preview": preview,
                },
                message_type="status",
            )
        except Exception:
            logger.exception("Failed to record malformed action repair note")
            return False

        _trace_log_info(
            "engine.action.repair request=%s session=%s mode=%s conv_session=%s preview=%r",
            request_id,
            session_id or "unknown",
            mode,
            self._conversation_session_id(cm) or "unknown",
            preview,
        )
        return True

    async def _iteration_loop(
        self,
        cm: ConversationManager,
        config: LoopConfig,
        max_iterations: int,
    ) -> Dict[str, Any]:
        """Unified iteration loop for both run_response and run_task modes.

        This method consolidates the shared loop logic, using LoopConfig to handle
        the differences between modes.

        Args:
            cm: Conversation manager for the target agent
            config: Loop configuration specifying mode-specific behavior
            max_iterations: Maximum iterations before forced termination

        Returns:
            Dict with 'assistant_response', 'iterations', 'action_results', 'status', 'execution_time'
        """
        last_response = ""
        all_action_results = []
        latest_usage: Dict[str, Any] = {}
        completion_status = config.default_completion_status

        # Reset loop state for this run
        self._get_loop_state().reset()

        # Publish task start event if enabled
        if config.enable_events and config.task_metadata:
            await self._publish_task_event(
                "STARTED",
                config.task_metadata,
                {
                    "task_prompt": config.task_metadata.get("prompt", ""),
                    "max_iterations": max_iterations,
                    "context": config.task_metadata.get("context"),
                },
            )

        try:
            while self.current_iteration < max_iterations:
                self.current_iteration += 1
                logger.debug(
                    f"Engine iteration {self.current_iteration} ({config.mode})"
                )

                # Check for external stop conditions
                if await self._check_stop():
                    completion_status = "stopped"
                    break

                # Execute LLM step
                response_data = await self._llm_step(
                    tools_enabled=True,
                    streaming=config.streaming,
                    stream_callback=config.stream_callback,
                    agent_id=self.current_agent_id,
                )

                last_response = response_data.get("assistant_response", "")
                iteration_results = response_data.get("action_results", [])
                usage_data = response_data.get("usage")
                if isinstance(usage_data, dict) and usage_data:
                    latest_usage = usage_data
                last_response = self._suppress_empty_tool_only_placeholder(
                    cm,
                    last_response,
                    iteration_results,
                )

                logger.debug(
                    f"[LOOP DEBUG] {config.mode} iter {self.current_iteration}: "
                    f"response_len={len(last_response or '')}, actions={len(iteration_results)}"
                )

                # Finalize streaming message after each iteration (for UI panel boundaries)
                if config.manage_streaming_state and hasattr(cm, "core") and cm.core:
                    session = (
                        cm.get_current_session()
                        if hasattr(cm, "get_current_session")
                        else None
                    )
                    session_id = getattr(session, "id", None)
                    cm.core.finalize_streaming_message(
                        agent_id=self.current_agent_id,
                        session_id=session_id,
                        conversation_id=session_id,
                    )
                    await asyncio.sleep(UI_ASYNC_SLEEP_SECONDS)

                # Save conversation state
                await self._save_conversation(cm, async_save=config.async_save)

                # Collect action results
                if iteration_results:
                    all_action_results.extend(iteration_results)

                    # Display results via message callback (run_task mode)
                    if config.message_callback:
                        for result_info in iteration_results:
                            if isinstance(result_info, dict):
                                action_name = result_info.get("action", "UnknownAction")
                                result_str = result_info.get("result", "")
                                status = result_info.get("status", "completed")
                                callback_type = (
                                    "tool_result"
                                    if status == "completed"
                                    else "tool_error"
                                )
                                await config.message_callback(
                                    result_str, callback_type, action_name=action_name
                                )
                            else:
                                await config.message_callback(
                                    str(result_info), "system_output"
                                )

                # Publish progress event if enabled
                if config.enable_events and config.task_metadata:
                    await self._publish_task_event(
                        "PROGRESSED",
                        config.task_metadata,
                        {
                            "iteration": self.current_iteration,
                            "max_iterations": max_iterations,
                            "response": last_response,
                            "progress": min(
                                100, int(100 * self.current_iteration / max_iterations)
                            ),
                        },
                    )

                # Check for explicit termination signal
                termination_detected, finish_status = self._check_termination_signal(
                    iteration_results, config.termination_action
                )
                if termination_detected:
                    if config.mode == "task":
                        completion_status = "pending_review"
                        logger.info(
                            f"Task completion signal detected via '{config.termination_action}' (status: {finish_status})"
                        )

                        if config.enable_events and config.task_metadata:
                            await self._publish_task_event(
                                "COMPLETED",
                                config.task_metadata,
                                {
                                    "response": last_response,
                                    "iteration": self.current_iteration,
                                    "max_iterations": max_iterations,
                                    "finish_status": finish_status,
                                    "requires_review": True,
                                },
                            )
                    else:
                        logger.debug(
                            f"Response completion: {config.termination_action} tool called"
                        )
                    break

                # Debug: Check if termination signal mentioned but not parsed correctly
                if (
                    last_response
                    and config.termination_action in last_response.lower()
                    and not termination_detected
                ):
                    logger.warning(
                        f"[LOOP DEBUG] Response contains '{config.termination_action}' text but wasn't parsed as action. "
                        f"Preview: {last_response[:100]}..."
                    )

                if (
                    last_response
                    and config.completion_phrases
                    and any(phrase in last_response for phrase in config.completion_phrases)
                    and not termination_detected
                ):
                    logger.info(
                        "Completion phrase detected in %s loop output without explicit action.",
                        config.mode,
                    )
                    completion_status = (
                        "pending_review" if config.mode == "task" else config.default_completion_status
                    )
                    if config.mode == "task" and config.enable_events and config.task_metadata:
                        await self._publish_task_event(
                            "COMPLETED",
                            config.task_metadata,
                            {
                                "response": last_response,
                                "iteration": self.current_iteration,
                                "max_iterations": max_iterations,
                                "completion_status": completion_status,
                                "finish_status": "completion_phrase",
                                "requires_review": True,
                            },
                        )
                    break

                if not iteration_results and self._queue_malformed_action_repair_note(
                    cm,
                    last_response,
                    mode=config.mode,
                ):
                    await self._save_conversation(cm, async_save=config.async_save)
                    if config.message_callback:
                        await config.message_callback(
                            "Assistant returned malformed tool syntax; requesting a repair turn.",
                            "system_output",
                        )
                    continue

                # WALLET_GUARD: Consolidated termination checks
                should_break, guard_status = self._check_wallet_guard_termination(
                    last_response, iteration_results, mode=config.mode
                )
                if should_break:
                    if guard_status in _TOOL_ONLY_STALL_NOTES:
                        last_response = await self._record_tool_only_stall_note(
                            cm,
                            guard_status,
                        )
                    completion_status = guard_status or "implicit_completion"
                    break

            # If loop exhausted iterations
            if self.current_iteration >= max_iterations:
                completion_status = (
                    "max_iterations"
                    if config.mode == "response"
                    else "iterations_exceeded"
                )

        except LLMEmptyResponseError as e:
            logger.warning(f"LLM returned empty response during {config.mode}: {e}")
            completion_status = "llm_empty_response_error"
            if config.message_callback:
                await config.message_callback(f"LLM Empty Response: {str(e)}", "error")

        except Exception as e:
            logger.error(f"Error in {config.mode} loop: {str(e)}")
            completion_status = "error"
            if config.message_callback:
                await config.message_callback(f"Error: {str(e)}", "error")

            if config.enable_events and config.task_metadata:
                await self._publish_task_event(
                    "FAILED",
                    config.task_metadata,
                    {
                        "error": str(e),
                        "iteration": self.current_iteration,
                        "max_iterations": max_iterations,
                    },
                )

        return {
            "assistant_response": last_response,
            "iterations": self.current_iteration,
            "action_results": all_action_results,
            "usage": latest_usage,
            "status": completion_status,
            "execution_time": (datetime.utcnow() - self.start_time).total_seconds(),
        }

    def _check_termination_signal(
        self,
        iteration_results: List[Dict[str, Any]],
        termination_action: str,
    ) -> Tuple[bool, str]:
        """Check if termination signal was received in iteration results.

        Args:
            iteration_results: Action results from current iteration
            termination_action: Action name that signals termination

        Returns:
            Tuple of (signal_detected, finish_status)
        """
        for result in iteration_results:
            if isinstance(result, dict):
                action_name = result.get("action", "")
                # Also check for legacy "task_completed" action
                if action_name == termination_action or (
                    termination_action == "finish_task"
                    and action_name == "task_completed"
                ):
                    # Extract status from machine-readable marker [FINISH_STATUS:xxx]
                    result_output = result.get("result", "")
                    status_match = re.search(r"\[FINISH_STATUS:(\w+)\]", result_output)
                    finish_status = status_match.group(1) if status_match else "done"
                    return True, finish_status
        return False, ""

    async def _publish_task_event(
        self,
        event_type: str,
        task_metadata: Dict[str, Any],
        extra_data: Dict[str, Any],
    ) -> None:
        """Publish a task event to EventBus.

        Args:
            event_type: Event type (STARTED, PROGRESSED, COMPLETED, FAILED)
            task_metadata: Task metadata dict with id, name, context
            extra_data: Additional event-specific data
        """
        try:
            from penguin.utils.events import EventBus, TaskEvent

            event_bus = EventBus.get_instance()
            event_value = getattr(TaskEvent, event_type, None)
            if event_value:
                await event_bus.publish(
                    event_value.value,
                    {
                        "task_id": task_metadata.get("id"),
                        "task_name": task_metadata.get("name"),
                        "context": task_metadata.get("context"),
                        "message_type": "status",
                        **extra_data,
                    },
                )
        except (ImportError, AttributeError):
            logger.debug(f"EventBus not available for {event_type} event")

    async def _save_conversation(
        self, cm: ConversationManager, async_save: bool = False
    ) -> None:
        """Save conversation state, optionally using async executor.

        Args:
            cm: ConversationManager to save
            async_save: If True, use run_in_executor for non-blocking save
        """
        if async_save:
            try:
                loop = asyncio.get_running_loop()
                await loop.run_in_executor(None, cm.save)
            except Exception as save_err:
                logger.warning(f"Failed to save conversation state: {save_err}")
        else:
            cm.save()

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_single_turn(
        self,
        prompt: str,
        *,
        image_paths: Optional[List[str]] = None,
        tools_enabled: bool = True,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
        api_client_override: Optional[Any] = None,
        model_config_override: Optional[Any] = None,
    ):
        """Run a single reasoning cycle for the requested agent/role."""
        selected, lite_output = await self._resolve_agent(
            agent_id=agent_id, agent_role=agent_role, prompt=prompt
        )
        if lite_output is not None:
            return lite_output
        if selected is None:
            return {
                "assistant_response": "",
                "action_results": [],
                "status": "no_agent",
            }

        token: Token[Optional[EngineRunState]] = _CURRENT_ENGINE_RUN_STATE.set(
            EngineRunState(
                current_agent_id=selected,
                api_client=api_client_override,
                model_config=model_config_override,
            )
        )
        try:
            cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
            cm.conversation.prepare_conversation(prompt, image_paths=image_paths)
            response_data = await self._llm_step(
                tools_enabled=tools_enabled,
                streaming=streaming,
                stream_callback=stream_callback,
                agent_id=self.current_agent_id,
            )
            return response_data
        finally:
            _CURRENT_ENGINE_RUN_STATE.reset(token)

    async def stream(self, prompt: str, *, agent_id: Optional[str] = None):
        """Yield chunks as they arrive (if provider supports streaming)."""
        async for chunk in self._llm_stream(prompt, agent_id=agent_id):
            yield chunk

    async def run_response(
        self,
        prompt: str,
        *,
        image_paths: Optional[List[str]] = None,
        max_iterations: Optional[int] = None,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
        api_client_override: Optional[Any] = None,
        model_config_override: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """
        Multi-step conversational loop for natural conversation flow.

        Termination conditions (in priority order):
        1. Explicit `finish_response` tool call (preferred)
        2. No actions taken in an iteration (implicit completion fallback)
        3. Max iterations reached

        Each iteration creates separate messages in the conversation.

        Args:
            prompt: The initial prompt to process
            image_paths: Optional list of image paths for multi-modal inputs
            max_iterations: Maximum number of iterations (default: 10)
            streaming: Whether to use streaming for responses
            stream_callback: Optional callback for streaming chunks

        Returns:
            Dictionary with final response and execution metadata
        """
        max_iters = (
            max_iterations
            if max_iterations is not None
            else self.settings.max_iterations_default
        )
        # Prepare conversation with initial prompt for the selected agent
        selected, lite_output = await self._resolve_agent(
            agent_id=agent_id, agent_role=agent_role, prompt=prompt
        )
        if lite_output is not None:
            lite_output.setdefault("iterations", 0)
            lite_output.setdefault("execution_time", 0.0)
            return lite_output
        if selected is None:
            return {
                "assistant_response": "",
                "iterations": 0,
                "action_results": [],
                "status": "no_agent",
                "execution_time": 0.0,
            }

        token: Token[Optional[EngineRunState]] = _CURRENT_ENGINE_RUN_STATE.set(
            EngineRunState(
                current_agent_id=selected,
                api_client=api_client_override,
                model_config=model_config_override,
            )
        )
        all_action_results: List[Dict[str, Any]] = []
        try:
            self.current_iteration = 0
            self.start_time = datetime.utcnow()
            cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
            cm.conversation.prepare_conversation(prompt, image_paths=image_paths)

            last_response = ""
            latest_usage: Dict[str, Any] = {}
            final_status = "completed"

            # Reset loop state for this run
            self._get_loop_state().reset()

            while self.current_iteration < max_iters:
                self.current_iteration += 1
                logger.debug(
                    "Engine iteration %s (run_response)", self.current_iteration
                )

                # Check for external stop conditions
                if await self._check_stop():
                    break

                # NOTE: Pre-iteration finalize removed - post-iteration finalize (after _llm_step) handles cleanup
                # The _llm_step finalize gets content for parsing, post-iteration finalize ensures UI boundaries

                # Determine effective streaming flag
                streaming_flag = (
                    streaming
                    if streaming is not None
                    else self.settings.streaming_default
                )

                # Execute LLM step with streaming support
                response_data = await self._llm_step(
                    tools_enabled=True,
                    streaming=streaming_flag,
                    stream_callback=stream_callback,
                    agent_id=self.current_agent_id,
                )

                last_response = response_data.get("assistant_response", "")
                iteration_results = response_data.get("action_results", [])
                usage_data = response_data.get("usage")
                if isinstance(usage_data, dict) and usage_data:
                    latest_usage = usage_data
                last_response = self._suppress_empty_tool_only_placeholder(
                    cm,
                    last_response,
                    iteration_results,
                )

                # Debug: Log response length and action count to help diagnose loops
                logger.debug(
                    f"[LOOP DEBUG] run_response iter {self.current_iteration}: response_len={len(last_response or '')}, actions={len(iteration_results)}"
                )

                # CRITICAL: Finalize streaming message after each iteration to force separate UI panels
                if hasattr(cm, "core") and cm.core:
                    # Force finalize any active streaming to break message boundaries
                    session = (
                        cm.get_current_session()
                        if hasattr(cm, "get_current_session")
                        else None
                    )
                    session_id = getattr(session, "id", None)
                    cm.core.finalize_streaming_message(
                        agent_id=self.current_agent_id,
                        session_id=session_id,
                        conversation_id=session_id,
                    )

                    # Small delay to allow UI to process the message boundary
                    await asyncio.sleep(UI_ASYNC_SLEEP_SECONDS)

                # Save conversation state after each iteration (async to avoid blocking event loop)
                await self._save_conversation(cm, async_save=True)

                # Collect all action results
                if iteration_results:
                    all_action_results.extend(iteration_results)

                # Check for explicit finish_response signal (primary termination)
                # NOTE: Only check finish_response here - finish_task is for task mode (run_task)
                finish_response_called = any(
                    isinstance(r, dict) and r.get("action") == "finish_response"
                    for r in iteration_results
                )
                if finish_response_called:
                    logger.debug("Response completion: finish_response tool called")
                    break

                # Debug: Check if LLM mentioned finish_response but didn't format it correctly
                if (
                    last_response
                    and "finish_response" in last_response.lower()
                    and not finish_response_called
                ):
                    logger.warning(
                        f"[LOOP DEBUG] Response contains 'finish_response' text but wasn't parsed as action. Response preview: {last_response[:100]}..."
                    )

                if not iteration_results and self._queue_malformed_action_repair_note(
                    cm,
                    last_response,
                    mode="response",
                ):
                    await self._save_conversation(cm, async_save=True)
                    continue

                # WALLET_GUARD: Consolidated termination checks
                should_break, guard_status = self._check_wallet_guard_termination(
                    last_response, iteration_results, mode="response"
                )
                if should_break:
                    if guard_status:
                        final_status = guard_status
                    if guard_status in _TOOL_ONLY_STALL_NOTES:
                        last_response = await self._record_tool_only_stall_note(
                            cm,
                            guard_status,
                        )
                    break

            # Determine final status
            if final_status == "completed" and self.current_iteration >= max_iters:
                final_status = "max_iterations"

            return {
                "assistant_response": last_response,
                "iterations": self.current_iteration,
                "action_results": all_action_results,
                "usage": latest_usage,
                "status": final_status,
                "execution_time": (datetime.utcnow() - self.start_time).total_seconds(),
            }

        except Exception as e:
            logger.error(f"Error in run_response: {str(e)}")
            return {
                "assistant_response": f"Error occurred: {str(e)}",
                "iterations": self.current_iteration,
                "action_results": all_action_results,
                "usage": {},
                "status": "error",
                "execution_time": (datetime.utcnow() - self.start_time).total_seconds(),
            }
        finally:
            _CURRENT_ENGINE_RUN_STATE.reset(token)

    async def run_task(
        self,
        task_prompt: str,
        image_paths: Optional[List[str]] = None,
        max_iterations: Optional[int] = None,
        task_context: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        completion_phrases: Optional[List[str]] = None,
        on_completion: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        enable_events: bool = True,
        message_callback: Optional[Callable[[str, str], Awaitable[None]]] = None,
        agent_id: Optional[str] = None,
        agent_role: Optional[str] = None,
        api_client_override: Optional[Any] = None,
        model_config_override: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run a task-oriented reasoning loop using the shared iteration engine.

        This method performs task-mode setup, prepares task_metadata, builds a
        task-mode LoopConfig, and delegates the actual loop mechanics to
        `_iteration_loop(...)`.

        Args:
            task_prompt: The prompt describing the task to execute.
            image_paths: Optional image inputs for multimodal task execution.
            max_iterations: Maximum iterations for the task loop. If ``None``,
                ``self.settings.max_iterations_default`` is used.
            task_context: Optional task-scoped metadata/context.
            task_id: Optional explicit task identifier. If omitted, a generated
                fallback identifier is used.
            task_name: Optional human-readable task name.
            completion_phrases: Optional additional completion phrases checked by
                `_iteration_loop(...)` through ``LoopConfig.completion_phrases``.
            on_completion: Optional async callback invoked with the final result.
            enable_events: Whether task progress/completion events should be
                published.
            message_callback: Optional async callback for streamed assistant/tool
                output. The public callback contract is ``(chunk, message_type)``.
            agent_id: Optional explicit agent id override.
            agent_role: Optional agent role for agent resolution.
            api_client_override: Optional API client override for the resolved run.
            model_config_override: Optional model config override for the resolved
                run.

        Returns:
            A dictionary containing the final assistant response, iteration count,
            action results, status, execution time, and attached ``task`` metadata.
            Task-mode success typically resolves to ``pending_review`` after an
            explicit task finish signal or equivalent completion phrase.

        Raises:
            Exception: Propagates agent resolution, component preparation,
                `_iteration_loop(...)`, and ``on_completion`` callback failures.

        Examples:
            ```python
            result = await engine.run_task(
                task_prompt="Implement the feature",
                task_name="Feature Work",
            )

            async def callback(chunk: str, message_type: str):
                print(message_type, chunk)

            result = await engine.run_task(
                task_prompt="Investigate the bug",
                message_callback=callback,
            )
            ```
        """
        max_iters = (
            max_iterations
            if max_iterations is not None
            else self.settings.max_iterations_default
        )
        selected, lite_output = await self._resolve_agent(
            agent_id=agent_id,
            agent_role=agent_role,
            prompt=task_prompt,
            context=task_context,
        )
        if lite_output is not None:
            lite_output.setdefault("completion_type", "lite_agent")
            return lite_output
        if selected is None:
            selected = self.default_agent_id

        token: Token[Optional[EngineRunState]] = _CURRENT_ENGINE_RUN_STATE.set(
            EngineRunState(
                current_agent_id=selected,
                api_client=api_client_override,
                model_config=model_config_override,
            )
        )
        self.current_iteration = 0
        self.start_time = datetime.utcnow()

        try:
            cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
            cm.conversation.prepare_conversation(task_prompt, image_paths=image_paths)

            telemetry = getattr(self, "telemetry", None)
            if telemetry is not None:
                await telemetry.record_task(self.current_agent_id, task_name)

            task_metadata = {
                "id": task_id
                or f"task_{datetime.now(timezone.utc).strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}",
                "name": task_name or "Unnamed Task",
                "context": task_context or {},
                "max_iterations": max_iters,
                "start_time": self.start_time.isoformat(),
                "prompt": task_prompt,
            }

            all_completion_phrases = [TASK_COMPLETION_PHRASE]
            if completion_phrases:
                all_completion_phrases.extend(completion_phrases)

            async def task_message_callback_wrapper(
                chunk: str,
                message_type: str,
                action_name: Optional[str] = None,
            ) -> None:
                if message_callback:
                    await message_callback(chunk, message_type)

            async def task_stream_adapter(
                chunk: str,
                message_type: str = "assistant",
                action_name: Optional[str] = None,
            ) -> None:
                await task_message_callback_wrapper(
                    chunk,
                    message_type,
                    action_name=action_name,
                )

            config = LoopConfig(
                mode="task",
                termination_action="finish_task",
                completion_phrases=all_completion_phrases,
                streaming=self.settings.streaming_default,
                stream_callback=task_stream_adapter if message_callback else None,
                manage_streaming_state=False,
                async_save=True,
                enable_events=enable_events,
                task_metadata=task_metadata,
                message_callback=(
                    task_message_callback_wrapper if message_callback else None
                ),
                default_completion_status="iterations_exceeded",
            )

            result = await self._iteration_loop(cm, config, max_iters)
            result["task"] = task_metadata

            if on_completion:
                try:
                    await on_completion(result)
                except Exception:
                    logger.exception("Error in completion callback")
                    raise

            return result
        finally:
            _CURRENT_ENGINE_RUN_STATE.reset(token)

    async def _execute_lite_agent(
        self,
        role: Optional[str],
        prompt: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        if not role:
            return None
        coordinator = getattr(self, "coordinator", None)
        if not coordinator:
            return None
        result = await coordinator.execute_lite_agents(role, prompt, metadata=metadata)
        if result:
            result.setdefault("iterations", 0)
            result.setdefault("execution_time", 0.0)
            result.setdefault("action_results", [])
        return result

    async def _resolve_agent(
        self,
        *,
        agent_id: Optional[str],
        agent_role: Optional[str],
        prompt: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[str], Optional[Dict[str, Any]]]:
        if agent_id:
            return agent_id, None
        coordinator = getattr(self, "coordinator", None)
        if not coordinator or not agent_role:
            return self.default_agent_id, None
        selected = coordinator.select_agent(agent_role)
        if selected:
            return selected, None
        lite = await self._execute_lite_agent(agent_role, prompt, metadata=context)
        if lite is not None:
            return None, lite
        return self.default_agent_id, None

    # ------------------------------------------------------------------
    # Child‑engine spawning (stub – process mode)
    # ------------------------------------------------------------------

    async def spawn_child(
        self,
        *,
        purpose: str = "child",
        inherit_tools: bool = False,
        shared_conversation: bool = False,
    ) -> "Engine":
        """Spawn a sub‑engine in a separate process.  Minimal stub for now."""
        logger.warning("spawn_child is a stub – running in‑process for now")
        base_cm = self.get_conversation_manager() or self.conversation_manager
        cm = (
            base_cm
            if shared_conversation
            else ConversationManager(
                model_config=base_cm.model_config,
                api_client=self.api_client,
                workspace_path=base_cm.workspace_path,
                system_prompt=base_cm.conversation.system_prompt,
            )
        )
        tm = (
            self.tool_manager
            if inherit_tools
            else ToolManager(
                config=self.tool_manager.config
                if hasattr(self.tool_manager, "config")
                else {},
                log_error_func=self.tool_manager.error_handler,
            )
        )
        ae = ActionExecutor(tm, self.action_executor.task_manager, cm.conversation)
        return Engine(
            self.settings,
            cm,
            self.api_client,
            tm,
            ae,
            stop_conditions=self.stop_conditions,
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_responses_tools(self, tool_manager) -> Dict[str, Any]:
        """Prepare Responses API tools payload if enabled.

        Returns:
            Dict with 'tools' and 'tool_choice' keys if applicable, empty dict otherwise.
        """
        try:
            return prepare_responses_tool_kwargs(
                self._get_runtime_model_config(),
                tool_manager,
            )
        except Exception as exc:
            logger.debug("Failed to prepare Responses tools: %s", exc)
            return {}

    def _build_empty_response_diagnostics(
        self,
        api_client: APIClient,
        messages: List[Dict[str, Any]],
        raw_response: Optional[str],
    ) -> Dict[str, Any]:
        """Build detailed diagnostics for empty response errors.

        Args:
            api_client: The API client used
            messages: The messages sent to the API
            raw_response: The raw response (may be empty string, whitespace, or None)

        Returns:
            Dict with 'summary', 'user_message', and detailed diagnostic fields
        """
        provider_error = None
        try:
            error_getter = getattr(api_client, "get_last_error", None)
            provider_error = error_getter() if callable(error_getter) else None
        except Exception:
            provider_error = None

        return build_llm_empty_response_diagnostics(
            messages=messages,
            raw_response=raw_response,
            model_config=getattr(self, "model_config", None),
            provider_error=provider_error,
            handler=getattr(api_client, "client_handler", None),
        )

    def _handler_has_pending_tool_call(self, api_client: APIClient) -> bool:
        """Return whether the active handler captured a tool call to execute."""
        try:
            return handler_has_pending_tool_call(api_client)
        except Exception:
            logger.debug("Failed to check handler for pending tool call", exc_info=True)
            return False

    async def _call_llm_with_retry(
        self,
        api_client: APIClient,
        messages: List[Dict[str, Any]],
        streaming: Optional[bool],
        stream_callback: Optional[Callable],
        extra_kwargs: Dict[str, Any],
    ) -> str:
        """Call LLM API with fallback retry on empty response.

        Args:
            api_client: The API client to use
            messages: Formatted conversation messages
            streaming: Whether to use streaming
            stream_callback: Optional callback for streaming chunks
            extra_kwargs: Additional kwargs (tools, tool_choice, etc.)

        Returns:
            Assistant response text

        Raises:
            LLMEmptyResponseError: If response is empty after retry
        """
        try:
            return await call_llm_with_retry(
                api_client=api_client,
                messages=messages,
                streaming=streaming,
                stream_callback=stream_callback,
                extra_kwargs=extra_kwargs,
                model_config=getattr(self, "model_config", None),
            )
        except LLMEmptyResponseError:
            diagnostics = self._build_empty_response_diagnostics(
                api_client,
                messages,
                None,
            )
            logger.error("[EMPTY_RESPONSE] %s", diagnostics["summary"])
            logger.error("[EMPTY_RESPONSE] Details: %s", diagnostics)
            raise

    async def _handle_responses_tool_call(
        self,
        api_client: APIClient,
        tool_manager,
        cm: ConversationManager,
    ) -> Optional[Dict[str, Any]]:
        """Handle Responses API tool_call if one was triggered.

        Args:
            api_client: The API client (to get tool_call info from handler)
            tool_manager: Tool manager to execute the tool
            cm: Conversation manager to persist result

        Returns:
            Action result dict if tool was executed, None otherwise
        """
        results = await self._handle_responses_tool_calls(
            api_client,
            tool_manager,
            cm,
        )
        return results[0] if results else None

    async def _handle_responses_tool_calls(
        self,
        api_client: APIClient,
        tool_manager,
        cm: ConversationManager,
    ) -> List[Dict[str, Any]]:
        """Handle all pending Responses API tool calls.

        Args:
            api_client: The API client (to get tool_call info from handler)
            tool_manager: Tool manager to execute the tools
            cm: Conversation manager to persist results

        Returns:
            Action result dicts for executed tools.
        """
        return await execute_pending_tool_calls(
            api_client=api_client,
            tool_manager=tool_manager,
            persist_action_result=lambda action_result,
            tool_context: cm.add_action_result(
                action_type=action_result["action"],
                result=action_result["result"],
                status=action_result["status"],
                tool_call_id=tool_context.get("tool_call_id"),
                tool_arguments=tool_context.get("tool_arguments"),
            ),
            emit_action_start=(
                (lambda payload: cm.core.emit_ui_event("action", payload))
                if hasattr(cm, "core") and cm.core
                else None
            ),
            emit_action_result=(
                (lambda payload: cm.core.emit_ui_event("action_result", payload))
                if hasattr(cm, "core") and cm.core
                else None
            ),
            emit_tool_timeline=lambda action_result: self._emit_tool_event(
                cm, action_result
            ),
        )

    async def _emit_tool_event(
        self, cm: ConversationManager, action_result: Dict[str, Any]
    ) -> None:
        """Emit UI event for tool execution result.

        Args:
            cm: Conversation manager (to access core for event emission)
            action_result: Dict with 'action', 'result', 'status' keys
        """
        if not hasattr(cm, "core") or not cm.core:
            return

        try:
            # Check config to see if tool results should be hidden
            from penguin.config import config

            hide_tool_results = False
            if isinstance(config, dict):
                cli_config = config.get("cli", {})
                display_config = cli_config.get("display", {})
                hide_tool_results = display_config.get("hide_tool_results", False)

            if hide_tool_results:
                return

            # Emit tool event for chronological timeline display
            await cm.core.emit_ui_event(
                "tool",
                {
                    "id": f"{action_result['action']}-{int(time.time() * 1000)}",
                    "phase": "end",
                    "action": action_result["action"],
                    "ts": int(time.time() * 1000),
                    "status": action_result.get("status", "completed"),
                    "result": str(action_result["result"])[
                        :200
                    ],  # Truncate for display
                },
            )
            await asyncio.sleep(0.01)  # Yield control to allow UI to render

        except Exception as e:
            logger.warning(f"Failed to emit tool result UI event: {e}")

    def _build_reasoning_fallback_note(self, api_client: Any) -> Optional[str]:
        """Return a fallback note when reasoning ran but no visible summary exists."""
        return build_reasoning_fallback_note(
            api_client,
            usage=self._extract_usage_from_api_client(api_client),
        )

    async def _inject_reasoning_fallback_note(
        self,
        cm: ConversationManager,
        api_client: Any,
        *,
        agent_id: Optional[str],
        session_id: Optional[str],
    ) -> None:
        """Inject fallback reasoning text into the active stream before finalize."""

        note = self._build_reasoning_fallback_note(api_client)
        if not note:
            return
        if not hasattr(cm, "core") or not cm.core:
            return

        request_id, request_session_id = self._trace_request_fields()
        _trace_log_info(
            "engine.reasoning.fallback request=%s session=%s agent=%s note=%r",
            request_id,
            request_session_id or "unknown",
            agent_id or self.current_agent_id or self.default_agent_id,
            note,
        )

        await cm.core._handle_stream_chunk(
            note,
            message_type="reasoning",
            agent_id=agent_id or self.current_agent_id,
            session_id=session_id,
            conversation_id=session_id,
        )

    async def _finalize_streaming_response(
        self,
        cm: ConversationManager,
        assistant_response: str,
        streaming: Optional[bool],
        agent_id: Optional[str] = None,
        api_client: Optional[Any] = None,
    ) -> str:
        """Finalize streaming response and persist to conversation.

        Args:
            cm: Conversation manager
            assistant_response: Current response text
            streaming: Whether streaming was used

        Returns:
            Finalized response text (may be updated from streaming buffer)
        """
        request_id, request_session_id = self._trace_request_fields()
        _trace_log_info(
            "engine.stream.finalize.start request=%s session=%s agent=%s conv_session=%s streaming=%s response_len=%s",
            request_id,
            request_session_id or "unknown",
            agent_id or self.current_agent_id or self.default_agent_id,
            self._conversation_session_id(cm) or "unknown",
            streaming,
            len(assistant_response or ""),
        )
        if not streaming:
            # Non-streaming: check if message already added, add if not
            try:
                session_messages = (
                    cm.conversation.session.messages
                    if hasattr(cm.conversation, "session")
                    else []
                )
                last_msg = session_messages[-1] if session_messages else None
                message_already_added = (
                    last_msg
                    and last_msg.role == "assistant"
                    and last_msg.content == assistant_response
                )
            except Exception:
                logger.exception(
                    "Failed to check if message already added to conversation"
                )
                message_already_added = False

            if not message_already_added:
                # add_assistant_message automatically strips action tags
                cm.conversation.add_assistant_message(assistant_response)
                logger.debug(
                    f"Added assistant message to conversation ({len(assistant_response)} chars)"
                )

            _trace_log_info(
                "engine.stream.finalize.done request=%s session=%s agent=%s conv_session=%s response_len=%s finalized=%s",
                request_id,
                request_session_id or "unknown",
                agent_id or self.current_agent_id or self.default_agent_id,
                self._conversation_session_id(cm) or "unknown",
                len(assistant_response or ""),
                False,
            )

            return assistant_response

        # Streaming: finalize streaming message
        if not hasattr(cm, "core") or not cm.core:
            return assistant_response

        finalized_content = ""
        try:
            session = (
                cm.get_current_session() if hasattr(cm, "get_current_session") else None
            )
            session_id = getattr(session, "id", None)
            await self._inject_reasoning_fallback_note(
                cm,
                api_client,
                agent_id=agent_id,
                session_id=session_id,
            )
            finalized = cm.core.finalize_streaming_message(
                agent_id=agent_id or self.current_agent_id,
                session_id=session_id,
                conversation_id=session_id,
            )
            if finalized and finalized.get("content"):
                old_len = len(assistant_response) if assistant_response else 0
                assistant_response = finalized["content"]
                finalized_content = assistant_response
                logger.debug(
                    f"[AUTO-CONTINUE FIX] Using finalized content for parsing. "
                    f"Length: {old_len} -> {len(assistant_response)}"
                )
            else:
                logger.debug(
                    f"[AUTO-CONTINUE FIX] No finalized content available. "
                    f"Using original response (len={len(assistant_response) if assistant_response else 0})"
                )
            logger.debug("Finalized streaming message with reasoning")
        except Exception as _fin_err:
            logger.warning("Failed to finalise streaming message: %s", _fin_err)

        if assistant_response and not finalized_content:
            try:
                session_messages = (
                    cm.conversation.session.messages
                    if hasattr(cm.conversation, "session")
                    else []
                )
                last_msg = session_messages[-1] if session_messages else None
                message_already_added = (
                    last_msg
                    and last_msg.role == "assistant"
                    and last_msg.content == assistant_response
                )
            except Exception:
                logger.exception(
                    "Failed to inspect conversation for streaming fallback persistence"
                )
                message_already_added = False

            if not message_already_added:
                cm.conversation.add_assistant_message(assistant_response)
                logger.debug(
                    "Persisted non-chunk streaming response as assistant message (%s chars)",
                    len(assistant_response),
                )

        _trace_log_info(
            "engine.stream.finalize.done request=%s session=%s agent=%s conv_session=%s response_len=%s finalized=%s",
            request_id,
            request_session_id or "unknown",
            agent_id or self.current_agent_id or self.default_agent_id,
            self._conversation_session_id(cm) or "unknown",
            len(assistant_response or ""),
            bool(finalized_content),
        )

        return assistant_response

    async def _execute_codeact_actions(
        self,
        cm: ConversationManager,
        action_executor: ActionExecutor,
        assistant_response: str,
    ) -> List[Dict[str, Any]]:
        """Parse and execute CodeAct actions from assistant response.

        Args:
            cm: Conversation manager to persist results
            action_executor: Executor for actions
            assistant_response: Response text to parse for actions

        Returns:
            List of action result dicts with 'action', 'result', 'status' keys
        """
        action_results = []

        # WALLET_GUARD: Skip action parsing if model is echoing tool results
        if assistant_response and "[Tool Result]" in assistant_response:
            logger.warning(
                f"[WALLET_GUARD] Skipping action parsing: response contains echoed '[Tool Result]' "
                f"(model confused about format, len={len(assistant_response)})"
            )
            return action_results

        actions: List[CodeActAction] = parse_action(assistant_response)
        tool_calls = tool_calls_from_codeact_actions(actions)
        logger.debug(
            "[AUTO-CONTINUE FIX] Parsed %s actions from response", len(tool_calls)
        )

        async def _execute_actionxml_call(tool_call):
            return await action_executor.execute_action(tool_call.raw)

        scheduler_results = await execute_tool_calls_serially(
            tool_calls,
            _execute_actionxml_call,
            policy=ToolExecutionPolicy(max_calls=1),
        )

        for tool_call, tool_result in zip(tool_calls[:1], scheduler_results):
            legacy_action_result = legacy_action_result_from_tool_result(tool_result)
            runtime_action_result = {
                **legacy_action_result,
                "tool_call_id": tool_call.id,
                "tool_arguments": tool_call.arguments
                if isinstance(tool_call.arguments, str)
                else str(tool_call.arguments),
                "output_hash": tool_result.output_hash,
            }
            action_results.append(runtime_action_result)

            # Persist result in conversation
            cm.add_action_result(
                action_type=legacy_action_result["action"],
                result=legacy_action_result["result"],
                status=legacy_action_result["status"],
                tool_call_id=tool_call.id,
                tool_arguments=runtime_action_result["tool_arguments"],
            )
            logger.debug(
                f"Added action result to conversation: {legacy_action_result['action']}"
            )

            # Emit UI event
            await self._emit_tool_event(cm, legacy_action_result)

            # NOTE: Removed hardcoded action_to_tool mapping (architectural violation)
            # ActionExecutor in parser.py handles CodeAct action → tool routing
            # Engine should not duplicate tool knowledge - see architecture.md

        return action_results

    def _apply_agent_mode_notice(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Append a plan-mode system notice for the current request context."""
        execution_context = get_current_execution_context()
        if execution_context is None:
            return messages

        raw_mode = execution_context.agent_mode
        mode = raw_mode.strip().lower() if isinstance(raw_mode, str) else None
        if mode != "plan":
            return messages

        marker = "[PENGUIN_AGENT_MODE_PLAN]"
        for message in messages:
            if not isinstance(message, dict):
                continue
            if message.get("role") != "system":
                continue
            content = message.get("content")
            if isinstance(content, str) and marker in content:
                return messages

        notice = (
            f"{marker} Plan mode is active for this session. You must stay read-only "
            "and avoid mutating operations. Do not attempt file writes, destructive "
            "shell commands, or process execution intended to modify state. "
            "If implementation is required, provide a plan and request build mode."
        )
        logger.info(
            "agent.mode.notice_applied mode=plan session=%s agent=%s",
            execution_context.session_id,
            execution_context.agent_id,
        )
        return [*messages, {"role": "system", "content": notice}]

    async def _llm_step(
        self,
        *,
        tools_enabled: bool = True,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        agent_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Execute a single LLM step: call model, handle tool calls, execute actions.

        This is a slim orchestrator that delegates to helper methods:
        - _prepare_responses_tools(): Prepare Responses API tools
        - _call_llm_with_retry(): Make LLM call with retry on empty
        - _handle_responses_tool_call(): Execute Responses API tool if triggered
        - _finalize_streaming_response(): Finalize streaming and persist message
        - _execute_codeact_actions(): Parse and execute CodeAct actions

        Args:
            tools_enabled: Whether to parse and execute CodeAct actions
            streaming: Whether to use streaming for LLM call
            stream_callback: Callback for streaming chunks
            agent_id: Target agent ID

        Returns:
            Dict with 'assistant_response' and 'action_results' keys
        """
        # Resolve components for target agent
        cm, api_client, tool_manager, action_executor = self._resolve_components(
            agent_id or self.current_agent_id
        )
        messages = cm.conversation.get_formatted_messages()
        messages = self._apply_agent_mode_notice(messages)
        request_id, session_id = self._trace_request_fields()
        last_message = messages[-1] if messages else {}
        _trace_log_info(
            "engine.llm_step.start request=%s session=%s agent=%s cm=%s conv=%s conv_session=%s msgs=%s last_role=%s last_preview=%r streaming=%s tools=%s",
            request_id,
            session_id or "unknown",
            agent_id or self.current_agent_id or self.default_agent_id,
            hex(id(cm)),
            hex(id(getattr(cm, "conversation", None)))
            if getattr(cm, "conversation", None) is not None
            else "none",
            self._conversation_session_id(cm) or "unknown",
            len(messages),
            last_message.get("role") if isinstance(last_message, dict) else None,
            self._trace_preview(
                last_message.get("content", "")
                if isinstance(last_message, dict)
                else ""
            ),
            streaming,
            tools_enabled,
        )

        # Step 1: Prepare Responses API tools if enabled
        extra_kwargs = self._prepare_responses_tools(tool_manager)

        # Step 2: Call LLM with retry on empty response
        assistant_response = await self._call_llm_with_retry(
            api_client, messages, streaming, stream_callback, extra_kwargs
        )

        # Step 3: Finalize streaming response and persist message.
        # This must happen before Responses tool execution so any provider
        # preamble text is attached to the current assistant turn before the
        # tool result is persisted against it.
        assistant_response = await self._finalize_streaming_response(
            cm,
            assistant_response,
            streaming,
            agent_id=agent_id or self.current_agent_id,
            api_client=api_client,
        )

        # Step 4: Handle Responses API tool_calls if they were triggered
        responses_action_results = await self._handle_responses_tool_calls(
            api_client,
            tool_manager,
            cm,
        )

        # Step 5: Execute CodeAct actions if enabled
        action_results = list(responses_action_results)
        if tools_enabled:
            action_results.extend(
                await self._execute_codeact_actions(
                    cm, action_executor, assistant_response
                )
            )

        usage = self._extract_usage_from_api_client(api_client)
        _trace_log_info(
            "engine.llm_step.done request=%s session=%s agent=%s conv_session=%s response_len=%s actions=%s usage=%s",
            request_id,
            session_id or "unknown",
            agent_id or self.current_agent_id or self.default_agent_id,
            self._conversation_session_id(cm) or "unknown",
            len(assistant_response or ""),
            len(action_results),
            usage,
        )

        # Note: cm.save() removed - caller (run_response/run_task) handles persistence
        # This avoids redundant saves per iteration

        return {
            "assistant_response": assistant_response,
            "action_results": action_results,
            "usage": usage,
        }

    async def _llm_stream(self, prompt: str, *, agent_id: Optional[str] = None):
        """Helper to stream chunks to caller."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def run():
            # Prepare conversation
            cm, api_client, _tm, _ae = self._resolve_components(
                agent_id or self.current_agent_id
            )
            cm.conversation.prepare_conversation(prompt)

            # Inner callback forwards chunks into queue
            async def _cb(chunk: str):
                await queue.put(chunk)

            # Call provider with streaming enabled
            messages = cm.conversation.get_formatted_messages()
            messages = self._apply_agent_mode_notice(messages)
            full_response = await api_client.get_response(
                messages,
                stream=True,
                stream_callback=lambda c: asyncio.create_task(_cb(c)),
            )

            # Persist full assistant response now that streaming done
            # add_assistant_message automatically strips action tags
            cm.conversation.add_assistant_message(full_response)
            cm.save()

            await queue.put(None)  # sentinel

        loop.create_task(run())
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk

    async def _check_stop(self) -> bool:
        for cond in self.stop_conditions:
            if await cond.should_stop(self):
                logger.info("Engine stopping due to %s", cond.__class__.__name__)
                return True
        return False

    # ------------------------------------------------------------------
    # Convenience: explicit per-agent single-turn helper
    # ------------------------------------------------------------------
    async def run_agent_turn(
        self,
        agent_id: str,
        prompt: str,
        *,
        image_path: Optional[str] = None,
        tools_enabled: bool = True,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
    ):
        return await self.run_single_turn(
            prompt,
            image_path=image_path,
            tools_enabled=tools_enabled,
            streaming=streaming,
            stream_callback=stream_callback,
            agent_id=agent_id,
        )
