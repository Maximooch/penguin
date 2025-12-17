from __future__ import annotations

"""Engine – high‑level coordination layer for Penguin.

The Engine owns the reasoning loop (single‑turn and multi‑step), delegates
LLM calls to ``APIClient`` and tool execution to ``ActionExecutor``, and
maintains light run‑time state (start‑time, iteration counter, active
stop‑conditions).  It receives pre‑constructed managers from PenguinCore so it
remains test‑friendly and avoids hidden globals.
"""

from dataclasses import dataclass, field
from datetime import datetime, timedelta
import asyncio
from penguin.constants import UI_ASYNC_SLEEP_SECONDS
import re
import time
# Removed unused: import multiprocessing as mp
from typing import Any, Awaitable, Callable, Dict, List, Optional, Sequence, Union, AsyncGenerator, Tuple
from penguin.utils.errors import LLMEmptyResponseError

from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.utils.parser import parse_action, CodeActAction, ActionExecutor  # type: ignore
from penguin.system.state import MessageCategory  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.tools import ToolManager  # type: ignore
from penguin.config import TASK_COMPLETION_PHRASE  # Add this import
from penguin.constants import get_engine_max_iterations_default

import logging

logger = logging.getLogger(__name__)

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

    # Streaming configuration
    streaming: bool = True
    stream_callback: Optional[Callable[[str, str], Awaitable[None]]] = None

    # Whether to reset/finalize streaming state between iterations
    manage_streaming_state: bool = False

    # How to save conversation (sync vs async)
    async_save: bool = False

    # Event publishing configuration
    enable_events: bool = False
    task_metadata: Optional[Dict[str, Any]] = None

    # Message callback for tool results (run_task mode)
    message_callback: Optional[Callable] = None

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

    def reset(self) -> None:
        """Reset state for a new run."""
        self.empty_response_count = 0
        self.last_response_hash = None
        self.repeat_count = 0

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
        is_empty_or_trivial = not stripped_response or len(stripped_response) < threshold

        if is_empty_or_trivial:
            self.empty_response_count += 1
            should_break = self.empty_response_count >= 3
        else:
            self.empty_response_count = 0
            should_break = False

        return is_empty_or_trivial, should_break

@dataclass
class EngineSettings:
    """Immutable configuration for an Engine instance."""

    retry_attempts: int = 2
    backoff_seconds: float = 1.5
    streaming_default: bool = False
    max_iterations_default: int = field(default_factory=get_engine_max_iterations_default)
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
        self.default_agent_id: str = "default"
        self.current_agent_id: Optional[str] = None
        # Register a default agent backed by the provided ConversationManager
        self.register_agent(agent_id=self.default_agent_id, conversation_manager=conversation_manager)
        # Back-compat: keep attribute pointing at default agent's manager
        self.conversation_manager = conversation_manager

        # Inject default conditions based on settings
        if settings.token_budget_stop_enabled and not any(isinstance(s, TokenBudgetStop) for s in self.stop_conditions):
            self.stop_conditions.append(TokenBudgetStop())
        if settings.wall_clock_stop_seconds and not any(isinstance(s, WallClockStop) for s in self.stop_conditions):
            self.stop_conditions.append(WallClockStop(settings.wall_clock_stop_seconds))

        # Light run‑time state
        self.start_time: datetime = datetime.utcnow()
        self.current_iteration: int = 0
        self._interrupted: bool = False

        # Consolidated loop state (replaces scattered dynamic attributes)
        self._loop_state = LoopState()

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

    def get_conversation_manager(self, agent_id: Optional[str] = None) -> Optional[ConversationManager]:
        agent = self.get_agent(agent_id or self.current_agent_id)
        return agent.conversation_manager if agent else None

    def _resolve_components(
        self, agent_id: Optional[str] = None
    ):
        """Return (conversation_manager, api_client, tool_manager, action_executor)
        for the target agent, falling back to Engine shared instances.
        """
        agent = self.get_agent(agent_id)
        if agent is None:
            # Fallback to defaults for safety
            cm = self.conversation_manager
            # If the CM supports multi-agents, set the active one when provided
            if agent_id and hasattr(cm, "set_current_agent"):
                try:
                    cm.set_current_agent(agent_id)  # type: ignore[attr-defined]
                except Exception:
                    logger.exception(f"Failed to set current agent '{agent_id}' on conversation manager")
            return (
                cm,
                self.api_client,
                self.tool_manager,
                self.action_executor,
            )
        cm = agent.conversation_manager
        # If the CM supports multi-agents, set the active one explicitly
        if agent_id and hasattr(cm, "set_current_agent"):
            try:
                cm.set_current_agent(agent_id)  # type: ignore[attr-defined]
            except Exception:
                logger.exception(f"Failed to set current agent '{agent_id}' on agent's conversation manager")
        return (
            cm,
            agent.api_client or self.api_client,
            agent.tool_manager or self.tool_manager,
            agent.action_executor or self.action_executor,
        )

    # ------------------------------------------------------------------
    # Iteration Loop Helpers
    # ------------------------------------------------------------------

    def _check_wallet_guard_termination(
        self,
        last_response: str,
        iteration_results: List[Dict[str, Any]],
        mode: str = "response"
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
        # Check for no-action completion (models that don't use CodeAct format)
        if not iteration_results and last_response:
            has_action_tags = bool(re.search(r'<\w+>.*?</\w+>', last_response, re.DOTALL))
            if not has_action_tags:
                logger.debug(f"[WALLET_GUARD] No actions in {mode} response, treating as complete (model may not support CodeAct)")
                return True, "implicit_completion" if mode == "task" else None

        # Check for confused model echoing tool results
        if last_response and "[Tool Result]" in last_response:
            logger.warning(f"[WALLET_GUARD] Breaking {mode}: model is echoing tool results as text")
            return True, "implicit_completion" if mode == "task" else None

        # Check for repeated/looping responses
        if self._loop_state.check_repeated(last_response):
            logger.warning(f"[WALLET_GUARD] Breaking {mode}: response repeated {self._loop_state.repeat_count} times")
            return True, "implicit_completion" if mode == "task" else None

        # Check for empty/trivial responses
        stripped_response = (last_response or "").strip()
        is_empty_or_trivial, should_break = self._loop_state.check_trivial(last_response)

        # DIAGNOSTIC: Log trivial responses
        if is_empty_or_trivial or len(last_response or "") < 20:
            last_action = iteration_results[-1].get("action") if iteration_results else "none"
            logger.warning(
                f"[WALLET_GUARD] Trivial response in {mode}: "
                f"raw={repr(last_response)}, "
                f"stripped_len={len(stripped_response)}, "
                f"last_action={last_action}, "
                f"iter={self.current_iteration}"
            )

        if is_empty_or_trivial:
            logger.debug(f"Empty/trivial response #{self._loop_state.empty_response_count} ({mode}): '{stripped_response[:20] if stripped_response else '(empty)'}'")

        if should_break:
            logger.warning(f"[WALLET_GUARD] Breaking {mode}: {self._loop_state.empty_response_count} consecutive trivial responses")
            return True, "implicit_completion" if mode == "task" else None

        return False, None

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
        completion_status = config.default_completion_status

        # Reset loop state for this run
        self._loop_state.reset()

        # Publish task start event if enabled
        if config.enable_events and config.task_metadata:
            await self._publish_task_event("STARTED", config.task_metadata, {
                "task_prompt": config.task_metadata.get("prompt", ""),
                "max_iterations": max_iterations,
                "context": config.task_metadata.get("context"),
            })

        try:
            while self.current_iteration < max_iterations:
                self.current_iteration += 1
                logger.debug(f"Engine iteration {self.current_iteration} ({config.mode})")

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

                logger.debug(
                    f"[LOOP DEBUG] {config.mode} iter {self.current_iteration}: "
                    f"response_len={len(last_response or '')}, actions={len(iteration_results)}"
                )

                # Finalize streaming message after each iteration (for UI panel boundaries)
                if config.manage_streaming_state and hasattr(cm, 'core') and cm.core:
                    cm.core.finalize_streaming_message()
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
                                callback_type = "tool_result" if status == "completed" else "tool_error"
                                await config.message_callback(result_str, callback_type, action_name=action_name)
                            else:
                                await config.message_callback(str(result_info), "system_output")

                # Publish progress event if enabled
                if config.enable_events and config.task_metadata:
                    await self._publish_task_event("PROGRESSED", config.task_metadata, {
                        "iteration": self.current_iteration,
                        "max_iterations": max_iterations,
                        "response": last_response,
                        "progress": min(100, int(100 * self.current_iteration / max_iterations)),
                    })

                # Check for explicit termination signal
                termination_detected, finish_status = self._check_termination_signal(
                    iteration_results, config.termination_action
                )
                if termination_detected:
                    if config.mode == "task":
                        completion_status = "pending_review"
                        logger.info(f"Task completion signal detected via '{config.termination_action}' (status: {finish_status})")

                        if config.enable_events and config.task_metadata:
                            await self._publish_task_event("COMPLETED", config.task_metadata, {
                                "response": last_response,
                                "iteration": self.current_iteration,
                                "max_iterations": max_iterations,
                                "finish_status": finish_status,
                                "requires_review": True,
                            })
                    else:
                        logger.debug(f"Response completion: {config.termination_action} tool called")
                    break

                # Debug: Check if termination signal mentioned but not parsed correctly
                if last_response and config.termination_action in last_response.lower() and not termination_detected:
                    logger.warning(
                        f"[LOOP DEBUG] Response contains '{config.termination_action}' text but wasn't parsed as action. "
                        f"Preview: {last_response[:100]}..."
                    )

                # WALLET_GUARD: Consolidated termination checks
                should_break, guard_status = self._check_wallet_guard_termination(
                    last_response, iteration_results, mode=config.mode
                )
                if should_break:
                    completion_status = guard_status or "implicit_completion"
                    break

            # If loop exhausted iterations
            if self.current_iteration >= max_iterations:
                completion_status = "max_iterations" if config.mode == "response" else "iterations_exceeded"

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
                await self._publish_task_event("FAILED", config.task_metadata, {
                    "error": str(e),
                    "iteration": self.current_iteration,
                    "max_iterations": max_iterations,
                })

        return {
            "assistant_response": last_response,
            "iterations": self.current_iteration,
            "action_results": all_action_results,
            "status": completion_status,
            "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
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
                if action_name == termination_action or (termination_action == "finish_task" and action_name == "task_completed"):
                    # Extract status from machine-readable marker [FINISH_STATUS:xxx]
                    result_output = result.get("result", "")
                    status_match = re.search(r'\[FINISH_STATUS:(\w+)\]', result_output)
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
                await event_bus.publish(event_value.value, {
                    "task_id": task_metadata.get("id"),
                    "task_name": task_metadata.get("name"),
                    "context": task_metadata.get("context"),
                    "message_type": "status",
                    **extra_data,
                })
        except (ImportError, AttributeError):
            logger.debug(f"EventBus not available for {event_type} event")

    async def _save_conversation(self, cm: ConversationManager, async_save: bool = False) -> None:
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
    ):
        """Run a single reasoning cycle for the requested agent/role."""
        selected, lite_output = await self._resolve_agent(agent_id=agent_id, agent_role=agent_role, prompt=prompt)
        if lite_output is not None:
            return lite_output
        if selected is None:
            return {"assistant_response": "", "action_results": [], "status": "no_agent"}

        self.current_agent_id = selected
        cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
        cm.conversation.prepare_conversation(prompt, image_paths=image_paths)
        response_data = await self._llm_step(
            tools_enabled=tools_enabled,
            streaming=streaming,
            stream_callback=stream_callback,
            agent_id=self.current_agent_id,
        )
        return response_data

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
        max_iters = max_iterations if max_iterations is not None else self.settings.max_iterations_default
        self.current_iteration = 0
        self.start_time = datetime.utcnow()

        # Prepare conversation with initial prompt for the selected agent
        selected, lite_output = await self._resolve_agent(agent_id=agent_id, agent_role=agent_role, prompt=prompt)
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

        self.current_agent_id = selected
        cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
        cm.conversation.prepare_conversation(prompt, image_paths=image_paths)
        
        last_response = ""
        all_action_results = []

        # Reset loop state for this run
        self._loop_state.reset()

        try:
            while self.current_iteration < max_iters:
                self.current_iteration += 1
                logger.debug("Engine iteration %s (run_response)", self.current_iteration)
                
                # Check for external stop conditions
                if await self._check_stop():
                    break
                
                # NOTE: Pre-iteration finalize removed - post-iteration finalize (after _llm_step) handles cleanup
                # The _llm_step finalize gets content for parsing, post-iteration finalize ensures UI boundaries

                # Determine effective streaming flag
                streaming_flag = streaming if streaming is not None else self.settings.streaming_default

                # Execute LLM step with streaming support
                response_data = await self._llm_step(
                    tools_enabled=True,
                    streaming=streaming_flag,
                    stream_callback=stream_callback,
                    agent_id=self.current_agent_id,
                )
                
                last_response = response_data.get("assistant_response", "")
                iteration_results = response_data.get("action_results", [])

                # Debug: Log response length and action count to help diagnose loops
                logger.debug(f"[LOOP DEBUG] run_response iter {self.current_iteration}: response_len={len(last_response or '')}, actions={len(iteration_results)}")

                # CRITICAL: Finalize streaming message after each iteration to force separate UI panels
                if hasattr(cm, 'core') and cm.core:
                    # Force finalize any active streaming to break message boundaries
                    cm.core.finalize_streaming_message()
                    
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
                if last_response and "finish_response" in last_response.lower() and not finish_response_called:
                    logger.warning(f"[LOOP DEBUG] Response contains 'finish_response' text but wasn't parsed as action. Response preview: {last_response[:100]}...")

                # WALLET_GUARD: Consolidated termination checks
                should_break, _ = self._check_wallet_guard_termination(last_response, iteration_results, mode="response")
                if should_break:
                    break

            # Determine final status
            final_status = "completed" if self.current_iteration < max_iters else "max_iterations"

            return {
                "assistant_response": last_response,
                "iterations": self.current_iteration,
                "action_results": all_action_results,
                "status": final_status,
                "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
            }
            
        except Exception as e:
            logger.error(f"Error in run_response: {str(e)}")
            return {
                "assistant_response": f"Error occurred: {str(e)}",
                "iterations": self.current_iteration,
                "action_results": all_action_results,
                "status": "error",
                "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
            }


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
    ) -> Dict[str, Any]:
        """
        Multi-step reasoning loop with comprehensive task handling.

        Args:
            task_prompt: The prompt for the task
            image_paths: Optional list of image paths for multi-modal inputs
            max_iterations: Maximum number of iterations (overrides settings default)
            task_context: Additional context for the task (metadata, environment, etc.)
            task_id: Optional task ID for tracking and events
            task_name: Optional task name for display and logging
            completion_phrases: Additional completion phrases to check for
            on_completion: Optional callback when task completes
            enable_events: Whether to publish events (defaults to True)
            message_callback: Optional callback to display messages during execution (message, type)

        Returns:
            Dictionary with task execution results including:
            - assistant_response: The final response from the assistant
            - iterations: Number of iterations performed
            - status: Task status (completed, iterations_exceeded, stopped)
            - action_results: Results of any actions executed
        """
        max_iters = max_iterations or self.settings.max_iterations_default
        self.current_iteration = 0
        self.start_time = datetime.utcnow()
        # Select agent and prepare its conversation
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

        self.current_agent_id = selected
        cm, _api, _tm, _ae = self._resolve_components(self.current_agent_id)
        cm.conversation.prepare_conversation(task_prompt, image_paths=image_paths)

        telemetry = getattr(self, "telemetry", None)
        if telemetry is not None:
            await telemetry.record_task(self.current_agent_id, task_name)
        
        # Prepare task metadata
        task_metadata = {
            "id": task_id or f"task_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}",
            "name": task_name or "Unnamed Task",
            "context": task_context or {},
            "max_iterations": max_iters,
            "start_time": self.start_time.isoformat(),
        }
        
        # Get standard and custom completion phrases
        standard_phrase = TASK_COMPLETION_PHRASE
        all_completion_phrases = [standard_phrase]
        if completion_phrases:
            all_completion_phrases.extend(completion_phrases)
        
        # Store action results from all iterations
        all_action_results = []

        # Reset loop state for this run
        self._loop_state.reset()

        # Publish task start event if EventBus is available
        if enable_events:
            try:
                from penguin.utils.events import EventBus, TaskEvent
                event_bus = EventBus.get_instance()
                await event_bus.publish(TaskEvent.STARTED.value, {
                    "task_id": task_metadata["id"],
                    "task_name": task_metadata["name"],
                    "task_prompt": task_prompt,
                    "max_iterations": max_iters,
                    "context": task_context,
                    "message_type": "status",
                })
            except (ImportError, AttributeError):
                # EventBus not available yet, continue with normal operation
                logger.warning("EventBus not available, continuing without event publishing")

        last_response = ""
        completion_status = "iterations_exceeded"  # Default status
        
        try:
            # Main execution loop
            while self.current_iteration < max_iters:
                self.current_iteration += 1
                logger.debug("Engine iteration %s (run_task)", self.current_iteration)

                # Check for external stop conditions
                if await self._check_stop():
                    completion_status = "stopped"
                    break

                # Execute LLM step with streaming support
                response_data = await self._llm_step(
                    tools_enabled=True,
                    streaming=self.settings.streaming_default,
                    stream_callback=message_callback if message_callback else None,
                    agent_id=self.current_agent_id,
                )
                
                last_response = response_data.get("assistant_response", "")
                iteration_results = response_data.get("action_results", [])
                
                # Collect action results
                if iteration_results:
                    all_action_results.extend(iteration_results)
                    
                    # Display action results via callback
                    if message_callback:
                        for tool_result_info in iteration_results:
                            if isinstance(tool_result_info, dict):
                                action_name = tool_result_info.get("action", "UnknownAction")
                                result_str = tool_result_info.get("result", "")
                                status = tool_result_info.get("status", "completed")

                                callback_message_type = "tool_result" if status == "completed" else "tool_error"
                                await message_callback(result_str, callback_message_type, action_name=action_name)
                            else:
                                await message_callback(str(tool_result_info), "system_output")

                # Publish progress event
                if enable_events:
                    try:
                        from penguin.utils.events import EventBus, TaskEvent
                        event_bus = EventBus.get_instance()
                        await event_bus.publish(TaskEvent.PROGRESSED.value, {
                            "task_id": task_metadata["id"],
                            "task_name": task_metadata["name"],
                            "iteration": self.current_iteration,
                            "max_iterations": max_iters,
                            "response": last_response,
                            "progress": min(100, int(100 * self.current_iteration / max_iters)),
                            "message_type": "status",
                        })
                    except (ImportError, AttributeError):
                        logger.debug("EventBus not available for progress event")
                
                # CRITICAL FIX: Persist conversation after each iteration using async save
                cm, _, _, _ = self._resolve_components(self.current_agent_id)
                await self._save_conversation(cm, async_save=True)

                # Check for task completion via finish_task tool call (primary)
                finish_task_called = False
                finish_status = "done"  # Default status
                for tool_result in iteration_results:
                    if isinstance(tool_result, dict):
                        action_name = tool_result.get("action", "")
                        if action_name in ("finish_task", "task_completed"):
                            finish_task_called = True
                            # Extract status from machine-readable marker [FINISH_STATUS:xxx]
                            # This avoids false positives from user summaries containing words like "blocked"
                            result_output = tool_result.get("result", "")
                            status_match = re.search(r'\[FINISH_STATUS:(\w+)\]', result_output)
                            if status_match:
                                finish_status = status_match.group(1)
                            break

                if finish_task_called:
                    # Task goes to PENDING_REVIEW, not COMPLETED
                    # Human must approve to mark COMPLETED
                    completion_status = "pending_review"
                    logger.info(f"Task completion signal detected via 'finish_task' tool (status: {finish_status}). Marking for human review.")
                    
                    # Publish completion event (task is pending review, not fully completed)
                    if enable_events:
                        try:
                            from penguin.utils.events import EventBus, TaskEvent
                            event_bus = EventBus.get_instance()
                            await event_bus.publish(TaskEvent.COMPLETED.value, {
                                "task_id": task_metadata["id"],
                                "task_name": task_metadata["name"],
                                "response": last_response,
                                "iteration": self.current_iteration,
                                "max_iterations": max_iters,
                                "context": task_context,
                                "finish_status": finish_status,
                                "requires_review": True,
                                "message_type": "status",
                            })
                        except (ImportError, AttributeError):
                            logger.debug("EventBus not available for completion event")
                    break

                # WALLET_GUARD: Consolidated termination checks
                should_break, guard_status = self._check_wallet_guard_termination(last_response, iteration_results, mode="task")
                if should_break:
                    completion_status = guard_status or "implicit_completion"
                    break
        
        except LLMEmptyResponseError as e:
            logger.warning(f"LLM returned empty response during task: {e}")
            completion_status = "llm_empty_response_error"
            if message_callback:
                await message_callback(f"LLM Empty Response: {str(e)}", "error")
            
        except Exception as e:
            # Handle any execution errors
            logger.error(f"Error executing task: {str(e)}")
            completion_status = "error"
            
            # Call message callback if provided
            if message_callback:
                await message_callback(f"Error executing task: {str(e)}", "error")
            
            # Publish error event
            if enable_events:
                try:
                    from penguin.utils.events import EventBus, TaskEvent
                    event_bus = EventBus.get_instance()
                    await event_bus.publish(TaskEvent.FAILED.value, {
                        "task_id": task_metadata["id"],
                        "task_name": task_metadata["name"],
                        "error": str(e),
                        "iteration": self.current_iteration,
                        "max_iterations": max_iters,
                        "message_type": "status",
                    })
                except (ImportError, AttributeError):
                    logger.debug("EventBus not available for error event")

        # Prepare result structure
        result = {
            "assistant_response": last_response,
            "iterations": self.current_iteration,
            "status": completion_status,
            "action_results": all_action_results,
            "task": task_metadata,
            "execution_time": (datetime.utcnow() - self.start_time).total_seconds()
        }
        
        # Call completion callback if provided
        if on_completion:
            try:
                await on_completion(result)
            except Exception as e:
                logger.error(f"Error in completion callback: {str(e)}")
        
        return result

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

    async def spawn_child(self, *, purpose: str = "child", inherit_tools: bool = False, shared_conversation: bool = False) -> "Engine":
        """Spawn a sub‑engine in a separate process.  Minimal stub for now."""
        logger.warning("spawn_child is a stub – running in‑process for now")
        base_cm = self.get_conversation_manager() or self.conversation_manager
        cm = base_cm if shared_conversation else ConversationManager(
            model_config=base_cm.model_config,
            api_client=self.api_client,
            workspace_path=base_cm.workspace_path,
            system_prompt=base_cm.conversation.system_prompt,
        )
        tm = self.tool_manager if inherit_tools else ToolManager(
            config=self.tool_manager.config if hasattr(self.tool_manager, 'config') else {},
            log_error_func=self.tool_manager.error_handler
        )
        ae = ActionExecutor(tm, self.action_executor.task_manager, cm.conversation)
        return Engine(self.settings, cm, self.api_client, tm, ae, stop_conditions=self.stop_conditions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _prepare_responses_tools(self, tool_manager) -> Dict[str, Any]:
        """Prepare Responses API tools payload if enabled.

        Returns:
            Dict with 'tools' and 'tool_choice' keys if applicable, empty dict otherwise.
        """
        extra_kwargs = {}
        try:
            model_cfg = getattr(self, "model_config", None)
            if model_cfg and getattr(model_cfg, "use_responses_api", False):
                tools_payload = tool_manager.get_responses_tools() if hasattr(tool_manager, "get_responses_tools") else []
                if tools_payload:
                    extra_kwargs["tools"] = tools_payload
                    extra_kwargs["tool_choice"] = "auto"
        except Exception as _tools_err:
            logger.debug(f"Failed to prepare Responses tools: {_tools_err}")

        return extra_kwargs

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
        diagnostics: Dict[str, Any] = {
            "raw_response": repr(raw_response) if raw_response else "(None)",
            "response_length": len(raw_response) if raw_response else 0,
        }

        # Message stats
        try:
            diagnostics["message_count"] = len(messages)
            diagnostics["total_chars"] = sum(len(str(m.get('content', ''))) for m in messages)
            diagnostics["approx_tokens"] = diagnostics["total_chars"] // 4
        except Exception:
            diagnostics["message_stats_error"] = "Failed to compute message stats"

        # Model config
        try:
            model_cfg = getattr(self, "model_config", None)
            if model_cfg:
                diagnostics["model"] = getattr(model_cfg, "model", "unknown")
                diagnostics["provider"] = getattr(model_cfg, "provider", "unknown")
                diagnostics["max_context_window_tokens"] = getattr(model_cfg, "max_context_window_tokens", None)
                diagnostics["max_output_tokens"] = getattr(model_cfg, "max_output_tokens", None)
        except Exception:
            diagnostics["model_config_error"] = "Failed to get model config"

        # Check for API error in response
        api_error_detected = False
        error_type = "unknown"
        error_detail = None

        if raw_response:
            stripped = raw_response.strip()
            if stripped.startswith("[Error:"):
                api_error_detected = True
                error_detail = stripped
                # Parse error type
                if "context" in stripped.lower() or "token" in stripped.lower():
                    error_type = "context_window_exceeded"
                elif "quota" in stripped.lower() or "credit" in stripped.lower():
                    error_type = "quota_exceeded"
                elif "rate" in stripped.lower() or "429" in stripped:
                    error_type = "rate_limited"
                elif "auth" in stripped.lower() or "key" in stripped.lower():
                    error_type = "authentication_error"
                elif "model" in stripped.lower() and "not found" in stripped.lower():
                    error_type = "model_not_found"
                else:
                    error_type = "api_error"

        diagnostics["api_error_detected"] = api_error_detected
        diagnostics["error_type"] = error_type
        if error_detail:
            diagnostics["error_detail"] = error_detail

        # Check for handler-level errors
        try:
            handler = getattr(api_client, "client_handler", None)
            if handler:
                last_error = getattr(handler, "last_error", None) or getattr(handler, "_last_error", None)
                if last_error:
                    diagnostics["handler_error"] = str(last_error)
        except Exception:
            pass

        # Build user-friendly message based on error type
        user_messages = {
            "context_window_exceeded": (
                f"Context window exceeded. Your conversation has ~{diagnostics.get('approx_tokens', '?')} tokens "
                f"but the model limit may be lower. Try starting a new conversation."
            ),
            "quota_exceeded": (
                "API quota/credits exceeded. Check your account balance and billing status."
            ),
            "rate_limited": (
                "Rate limit exceeded. Wait a moment and try again, or reduce request frequency."
            ),
            "authentication_error": (
                "API authentication failed. Check your API key is valid and properly configured."
            ),
            "model_not_found": (
                f"Model '{diagnostics.get('model', 'unknown')}' not found. "
                "Check the model name is correct and you have access to it."
            ),
            "api_error": (
                f"API returned an error: {error_detail or 'Unknown error'}. "
                "Check the API status and your request parameters."
            ),
            "unknown": (
                f"Model returned empty response after retry. "
                f"Conversation has {diagnostics.get('message_count', '?')} messages, "
                f"~{diagnostics.get('approx_tokens', '?')} tokens. "
                f"Possible causes: (1) Context too large, (2) API issue, (3) Model refusing to respond."
            ),
        }

        diagnostics["user_message"] = user_messages.get(error_type, user_messages["unknown"])
        diagnostics["summary"] = (
            f"Empty response from {diagnostics.get('model', 'unknown')} "
            f"(type={error_type}, msgs={diagnostics.get('message_count', '?')}, "
            f"tokens≈{diagnostics.get('approx_tokens', '?')})"
        )

        return diagnostics

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
        # First attempt – honour requested streaming setting
        assistant_response = await api_client.get_response(
            messages,
            stream=streaming,
            stream_callback=stream_callback,
            **extra_kwargs,
        )

        # If empty, retry once with stream=False (some providers fail in streaming mode)
        if not assistant_response or not assistant_response.strip():
            logger.warning("_llm_step got empty response (stream=%s). Retrying once without streaming.", streaming)
            assistant_response = await api_client.get_response(messages, stream=False)

        # Still empty? Raise exception to prevent infinite loops
        if not assistant_response or not assistant_response.strip():
            # Build detailed diagnostics
            diagnostics = self._build_empty_response_diagnostics(
                api_client, messages, assistant_response
            )
            logger.error(f"[EMPTY_RESPONSE] {diagnostics['summary']}")
            logger.error(f"[EMPTY_RESPONSE] Details: {diagnostics}")

            raise LLMEmptyResponseError(diagnostics["user_message"])

        return assistant_response

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
        # Check if gateway interrupted due to Responses tool_call
        try:
            handler = getattr(api_client, "client_handler", None)
            getter = getattr(handler, "get_and_clear_last_tool_call", None)
            tool_info = await getter() if callable(getter) and asyncio.iscoroutinefunction(getter) else (getter() if callable(getter) else None)
        except Exception:
            logger.exception("Failed to get tool_call info from handler")
            return None

        if not tool_info or not isinstance(tool_info, dict):
            return None

        try:
            tool_name = str(tool_info.get("name") or "").strip()
            raw_args = tool_info.get("arguments") or "{}"
            import json as _json
            try:
                tool_args = _json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else {}
            except Exception:
                logger.exception(f"Failed to parse tool arguments for '{tool_name}': {raw_args[:100]}")
                tool_args = {}

            # Execute via ToolManager
            output = tool_manager.execute_tool(tool_name, tool_args)

            # Format result (using standardized field names: action/result)
            action_result = {
                "action": tool_name,
                "result": str(output if output is not None else ""),
                "status": "completed"
            }

            # Persist result
            cm.add_action_result(
                action_type=action_result["action"],
                result=action_result["result"],
                status=action_result["status"],
            )

            # Emit UI event
            await self._emit_tool_event(cm, action_result)

            # NOTE: Removed forced tool_choice (architectural violation)
            # Model should decide next action based on tool result, not be forced

            return action_result

        except Exception as _tool_exec_err:
            logger.debug(f"Responses tool_call execution failed: {_tool_exec_err}")
            return None

    async def _emit_tool_event(self, cm: ConversationManager, action_result: Dict[str, Any]) -> None:
        """Emit UI event for tool execution result.

        Args:
            cm: Conversation manager (to access core for event emission)
            action_result: Dict with 'action', 'result', 'status' keys
        """
        if not hasattr(cm, 'core') or not cm.core:
            return

        try:
            # Check config to see if tool results should be hidden
            from penguin.config import config
            hide_tool_results = False
            if isinstance(config, dict):
                cli_config = config.get('cli', {})
                display_config = cli_config.get('display', {})
                hide_tool_results = display_config.get('hide_tool_results', False)

            if hide_tool_results:
                return

            # Emit tool event for chronological timeline display
            await cm.core.emit_ui_event("tool", {
                "id": f"{action_result['action']}-{int(time.time() * 1000)}",
                "phase": "end",
                "action": action_result['action'],
                "ts": int(time.time() * 1000),
                "status": action_result.get('status', 'completed'),
                "result": str(action_result['result'])[:200]  # Truncate for display
            })
            await asyncio.sleep(0.01)  # Yield control to allow UI to render

        except Exception as e:
            logger.warning(f"Failed to emit tool result UI event: {e}")

    def _finalize_streaming_response(
        self,
        cm: ConversationManager,
        assistant_response: str,
        streaming: Optional[bool],
    ) -> str:
        """Finalize streaming response and persist to conversation.

        Args:
            cm: Conversation manager
            assistant_response: Current response text
            streaming: Whether streaming was used

        Returns:
            Finalized response text (may be updated from streaming buffer)
        """
        if not streaming:
            # Non-streaming: check if message already added, add if not
            try:
                session_messages = cm.conversation.session.messages if hasattr(cm.conversation, 'session') else []
                last_msg = session_messages[-1] if session_messages else None
                message_already_added = (
                    last_msg and
                    last_msg.role == "assistant" and
                    last_msg.content == assistant_response
                )
            except Exception:
                logger.exception("Failed to check if message already added to conversation")
                message_already_added = False

            if not message_already_added:
                cm.conversation.add_assistant_message(assistant_response)
                logger.debug(f"Added assistant message to conversation ({len(assistant_response)} chars)")

            return assistant_response

        # Streaming: finalize streaming message
        if not hasattr(cm, "core") or not cm.core:
            return assistant_response

        try:
            finalized = cm.core.finalize_streaming_message()
            if finalized and finalized.get("content"):
                old_len = len(assistant_response) if assistant_response else 0
                assistant_response = finalized["content"]
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
        logger.debug("[AUTO-CONTINUE FIX] Parsed %s actions from response", len(actions))

        # Enforce one action per iteration for incremental execution
        for act in (actions[:1] if actions else []):
            result = await action_executor.execute_action(act)

            # Format result (using standardized field names: action/result)
            action_result = {
                "action": act.action_type.value if hasattr(act.action_type, 'value') else str(act.action_type),
                "result": str(result if result is not None else ""),
                "status": "completed"
            }
            action_results.append(action_result)

            # Persist result in conversation
            cm.add_action_result(
                action_type=action_result["action"],
                result=action_result["result"],
                status=action_result["status"]
            )
            logger.debug(f"Added action result to conversation: {action_result['action']}")

            # Emit UI event
            await self._emit_tool_event(cm, action_result)

            # NOTE: Removed hardcoded action_to_tool mapping (architectural violation)
            # ActionExecutor in parser.py handles CodeAct action → tool routing
            # Engine should not duplicate tool knowledge - see architecture.md

        return action_results

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
        cm, api_client, tool_manager, action_executor = self._resolve_components(agent_id or self.current_agent_id)
        messages = cm.conversation.get_formatted_messages()

        # Step 1: Prepare Responses API tools if enabled
        extra_kwargs = self._prepare_responses_tools(tool_manager)

        # Step 2: Call LLM with retry on empty response
        assistant_response = await self._call_llm_with_retry(
            api_client, messages, streaming, stream_callback, extra_kwargs
        )

        # Step 3: Handle Responses API tool_call if one was triggered
        await self._handle_responses_tool_call(api_client, tool_manager, cm)

        # Step 4: Finalize streaming response and persist message
        assistant_response = self._finalize_streaming_response(cm, assistant_response, streaming)

        # Step 5: Execute CodeAct actions if enabled
        action_results = []
        if tools_enabled:
            action_results = await self._execute_codeact_actions(cm, action_executor, assistant_response)

        # Note: cm.save() removed - caller (run_response/run_task) handles persistence
        # This avoids redundant saves per iteration

        return {"assistant_response": assistant_response, "action_results": action_results}

    async def _llm_stream(self, prompt: str, *, agent_id: Optional[str] = None):
        """Helper to stream chunks to caller."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def run():
            # Prepare conversation
            cm, api_client, _tm, _ae = self._resolve_components(agent_id or self.current_agent_id)
            cm.conversation.prepare_conversation(prompt)

            # Inner callback forwards chunks into queue
            async def _cb(chunk: str):
                await queue.put(chunk)

            # Call provider with streaming enabled
            messages = cm.conversation.get_formatted_messages()
            full_response = await api_client.get_response(
                messages,
                stream=True,
                stream_callback=lambda c: asyncio.create_task(_cb(c)),
            )

            # Persist full assistant response now that streaming done
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
