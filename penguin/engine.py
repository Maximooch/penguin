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
import re
import time
import multiprocessing as mp
from typing import Any, Awaitable, Callable, Dict, List, Optional, Union, AsyncGenerator, Tuple
from penguin.utils.errors import LLMEmptyResponseError

from penguin.system.conversation_manager import ConversationManager  # type: ignore
from penguin.utils.parser import parse_action, CodeActAction, ActionExecutor  # type: ignore
from penguin.system.state import MessageCategory  # type: ignore
from penguin.llm.api_client import APIClient  # type: ignore
from penguin.tools import ToolManager  # type: ignore
from penguin.config import TASK_COMPLETION_PHRASE  # Add this import

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
class EngineSettings:
    """Immutable configuration for an Engine instance."""

    retry_attempts: int = 2
    backoff_seconds: float = 1.5
    streaming_default: bool = False
    max_iterations_default: int = 5000
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
                    pass
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
                pass
        return (
            cm,
            agent.api_client or self.api_client,
            agent.tool_manager or self.tool_manager,
            agent.action_executor or self.action_executor,
        )

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def run_single_turn(
        self,
        prompt: str,
        *,
        image_path: Optional[str] = None,
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
        cm.conversation.prepare_conversation(prompt, image_path)
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
        image_path: Optional[str] = None,
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
            image_path: Optional image path for multi-modal inputs
            max_iterations: Maximum number of iterations (default: 10)
            streaming: Whether to use streaming for responses
            stream_callback: Optional callback for streaming chunks
            
        Returns:
            Dictionary with final response and execution metadata
        """
        max_iters = max_iterations if max_iterations is not None else 5000
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
        cm.conversation.prepare_conversation(prompt, image_path=image_path)
        
        last_response = ""
        all_action_results = []

        # Initialize empty response counter for this run
        self._empty_response_count = 0

        try:
            while self.current_iteration < max_iters:
                self.current_iteration += 1
                logger.debug("Engine iteration %s (run_response)", self.current_iteration)
                
                # Check for external stop conditions
                if await self._check_stop():
                    break
                
                # Reset streaming state before each iteration to ensure separate UI panels
                if hasattr(cm, 'core') and cm.core:
                    # Force finalize any previous streaming before starting new iteration
                    cm.core.finalize_streaming_message()
                
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
                    await asyncio.sleep(0.05)
                
                # Save conversation state after each iteration to persist separate messages
                cm.save()
                
                # Collect all action results
                if iteration_results:
                    all_action_results.extend(iteration_results)

                # Check for explicit finish_response signal (primary termination)
                # NOTE: Only check finish_response here - finish_task is for task mode (run_task)
                finish_response_called = any(
                    isinstance(r, dict) and r.get("action_name") == "finish_response"
                    for r in iteration_results
                )
                if finish_response_called:
                    logger.debug("Response completion: finish_response tool called")
                    break

                # Debug: Check if LLM mentioned finish_response but didn't format it correctly
                if last_response and "finish_response" in last_response.lower() and not finish_response_called:
                    logger.warning(f"[LOOP DEBUG] Response contains 'finish_response' text but wasn't parsed as action. Response preview: {last_response[:100]}...")

                # Track consecutive empty/near-empty responses - break after 3 (simple approach)
                # Also catch very short responses (< 10 chars) which indicate LLM has nothing to add
                stripped_response = (last_response or "").strip()
                is_empty_or_trivial = not stripped_response or len(stripped_response) < 10

                if is_empty_or_trivial:
                    self._empty_response_count += 1
                    logger.debug(f"Empty/trivial response #{self._empty_response_count}: '{stripped_response[:20] if stripped_response else '(empty)'}'")

                    # Break after 3 consecutive empty/trivial responses
                    if self._empty_response_count >= 3:
                        logger.debug("Implicit completion: 3 consecutive empty/trivial responses")
                        break
                else:
                    # Reset counter on substantive response
                    self._empty_response_count = 0

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
        image_path: Optional[str] = None,
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
        Multi‑step reasoning loop with comprehensive task handling.
        
        Args:
            task_prompt: The prompt for the task
            image_path: Optional image path for multi-modal inputs
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
        cm.conversation.prepare_conversation(task_prompt, image_path=image_path)

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

        # Initialize empty response counter for this run
        self._empty_response_count_task = 0

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
                                action_name = tool_result_info.get("action_name", "UnknownAction")
                                output_str = tool_result_info.get("output", "")
                                status = tool_result_info.get("status", "completed")
                                
                                callback_message_type = "tool_result" if status == "completed" else "tool_error"
                                await message_callback(output_str, callback_message_type, action_name=action_name)
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
                        pass
                
                # CRITICAL FIX: Persist conversation after each iteration
                # _llm_step saves after adding messages, but we need to ensure it persists
                # Use run_in_executor to avoid blocking the event loop with SQLite writes
                cm, _, _, _ = self._resolve_components(self.current_agent_id)
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, cm.save)
                except Exception as save_err:
                    logger.warning(f"Failed to save conversation state: {save_err}")

                # Check for task completion via finish_task tool call (primary)
                finish_task_called = False
                finish_status = "done"  # Default status
                for tool_result in iteration_results:
                    if isinstance(tool_result, dict):
                        action_name = tool_result.get("action_name", "")
                        if action_name in ("finish_task", "task_completed"):
                            finish_task_called = True
                            # Extract status from machine-readable marker [FINISH_STATUS:xxx]
                            # This avoids false positives from user summaries containing words like "blocked"
                            output = tool_result.get("output", "")
                            status_match = re.search(r'\[FINISH_STATUS:(\w+)\]', output)
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
                            pass
                    break

                # NOTE: Phrase-based completion detection is deprecated.
                # Keeping commented out for reference. Use finish_task tool instead.
                # if any(phrase in last_response for phrase in all_completion_phrases):
                #     completion_status = "completed"
                #     logger.debug(f"Task completion detected. Found completion phrase: {all_completion_phrases}")
                #     break

                # Track consecutive empty/near-empty responses - break after 3 (simple approach)
                # Also catch very short responses (< 10 chars) which indicate LLM has nothing to add
                stripped_response = (last_response or "").strip()
                is_empty_or_trivial = not stripped_response or len(stripped_response) < 10

                if is_empty_or_trivial:
                    self._empty_response_count_task += 1
                    logger.debug(f"Empty/trivial response #{self._empty_response_count_task} (run_task): '{stripped_response[:20] if stripped_response else '(empty)'}'")

                    # Break after 3 consecutive empty/trivial responses
                    if self._empty_response_count_task >= 3:
                        logger.debug("Implicit task completion: 3 consecutive empty/trivial responses")
                        completion_status = "implicit_completion"
                        break
                else:
                    # Reset counter on substantive response
                    self._empty_response_count_task = 0
        
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
                    # EventBus not available yet, continue with normal operation
                    logger.warning("(Engine) EventBus not available yet, continue with normal operation")
                    print("(Engine) EventBus not available yet, continue with normal operation")
                    pass

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

    async def _llm_step(
        self,
        *,
        tools_enabled: bool = True,
        streaming: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        agent_id: Optional[str] = None,
    ):
        cm, api_client, _tm, action_executor = self._resolve_components(agent_id or self.current_agent_id)
        messages = cm.conversation.get_formatted_messages()

        # Prepare Responses tools (file/code/command only) when enabled
        extra_kwargs = {}
        try:
            model_cfg = getattr(self, "model_config", None)
            if model_cfg and getattr(model_cfg, "use_responses_api", False):
                tools_payload = _tm.get_responses_tools() if hasattr(_tm, "get_responses_tools") else []
                if tools_payload:
                    extra_kwargs["tools"] = tools_payload
                    # Use forced tool_choice if set, otherwise auto
                    forced_choice = getattr(self, "_forced_tool_choice_name", None)
                    if forced_choice:
                        extra_kwargs["tool_choice"] = {"type": "function", "function": {"name": forced_choice}}
                    else:
                        extra_kwargs["tool_choice"] = "auto"
        except Exception as _tools_err:
            logger.debug(f"Failed to prepare Responses tools: {_tools_err}")

        # One-time consumption of forced tool_choice
        try:
            if hasattr(self, "_forced_tool_choice_name"):
                self._forced_tool_choice_name = None
        except Exception:
            pass
        # First attempt – honour requested streaming setting
        assistant_response = await api_client.get_response(
            messages,
            stream=streaming,
            stream_callback=stream_callback,
            **extra_kwargs,
        )

        # Phase 2: If gateway interrupted due to Responses tool_call, execute it directly
        try:
            handler = getattr(api_client, "client_handler", None)
            getter = getattr(handler, "get_and_clear_last_tool_call", None)
            tool_info = await getter() if callable(getter) and asyncio.iscoroutinefunction(getter) else (getter() if callable(getter) else None)
        except Exception:
            tool_info = None

        if tool_info and isinstance(tool_info, dict):
            try:
                tool_name = str(tool_info.get("name") or "").strip()
                raw_args = tool_info.get("arguments") or "{}"
                import json as _json
                try:
                    tool_args = _json.loads(raw_args) if isinstance(raw_args, str) and raw_args.strip() else {}
                except Exception:
                    tool_args = {}

                # Execute via ToolManager if allowed
                output = _tm.execute_tool(tool_name, tool_args)

                # Persist result
                action_result = {
                    "action_name": tool_name,
                    "output": str(output if output is not None else ""),
                    "status": "completed"
                }
                cm.add_action_result(
                    action_type=action_result["action_name"],
                    result=action_result["output"],
                    status=action_result["status"],
                )
                if hasattr(cm, 'core') and cm.core:
                    # Emit tool event for chronological timeline display
                    await cm.core.emit_ui_event("tool", {
                        "id": f"{action_result['action_name']}-{int(time.time() * 1000)}",
                        "phase": "end",
                        "action": action_result['action_name'],
                        "ts": int(time.time() * 1000),
                        "status": action_result.get('status', 'completed'),
                        "result": str(action_result['output'])[:200]  # Truncate for display
                    })
                    # Note: Removed duplicate "message" event emission - tool events are now
                    # properly handled by EventTimeline component
                    await asyncio.sleep(0.01)

                # For the next request, prefer forcing this tool_choice name if applicable
                try:
                    self._forced_tool_choice_name = tool_name
                except Exception:
                    pass

            except Exception as _tool_exec_err:
                logger.debug(f"Responses tool_call execution failed: {_tool_exec_err}")

        # If we received **no content**, retry once with *stream=False* (some providers
        # fail in streaming-mode but succeed with a normal completion request).
        if not assistant_response or not assistant_response.strip():
            logger.warning("_llm_step got empty response (stream=%s). Retrying once without streaming.", streaming)
            assistant_response = await api_client.get_response(messages, stream=False)

        # Still empty? Give up but do NOT pollute the history with blank messages.
        if not assistant_response or not assistant_response.strip():
            # Add diagnostics to help debug why we're getting empty responses
            try:
                msg_count = len(messages)
                total_tokens = sum(len(str(m.get('content', ''))) for m in messages) // 4  # Rough estimate
                logger.error(
                    f"_llm_step received empty response after fallback attempt. "
                    f"Conversation state: {msg_count} messages, ~{total_tokens} tokens. "
                    f"Possible causes: context window exceeded, API quota, rate limiting, or model refusing to respond."
                )
            except Exception as diag_err:
                logger.error(f"_llm_step received empty response (diagnostics failed: {diag_err})")
            
            # CRITICAL: Raise exception instead of returning empty string
            # This prevents infinite retry loops in RunMode/continuous mode
            from penguin.utils.errors import LLMEmptyResponseError
            raise LLMEmptyResponseError(
                "Model returned empty response after retry. "
                "This may indicate: (1) Context window exceeded, (2) API quota/rate limit, "
                "(3) Model refusing to respond. Try starting a new conversation or checking API status."
            )
        else:
            # CRITICAL FIX: Always persist assistant message, regardless of streaming mode
            # Check if message was already added to avoid duplicates
            # When streaming, finalize_streaming_message() adds the message with reasoning
            # Only add manually when NOT streaming
            if not streaming:
                try:
                    session_messages = cm.conversation.session.messages if hasattr(cm.conversation, 'session') else []
                    last_msg = session_messages[-1] if session_messages else None
                    message_already_added = (
                        last_msg and
                        last_msg.role == "assistant" and
                        last_msg.content == assistant_response
                    )
                except Exception:
                    message_already_added = False

                if not message_already_added:
                    cm.conversation.add_assistant_message(assistant_response)
                    logger.debug(f"Added assistant message to conversation ({len(assistant_response)} chars)")

        # ------------------------------------------------------------------
        # Ensure any streaming content is finalised **before** we process and
        # append tool-result messages.  This guarantees the natural order:
        #   assistant → tool-output, matching real conversational flow.
        # ------------------------------------------------------------------
        if streaming and hasattr(cm, "core") and cm.core:
            # Finalize streaming message (adds to conversation with reasoning)
            try:
                finalized = cm.core.finalize_streaming_message()
                # CRITICAL FIX: Use finalized content for action parsing
                # During streaming, the finalized content is the complete accumulated response
                if finalized and finalized.get("content"):
                    old_len = len(assistant_response) if assistant_response else 0
                    assistant_response = finalized["content"]
                    logger.debug(
                        f"[AUTO-CONTINUE FIX] Using finalized content for parsing. "
                        f"Length: {old_len} -> {len(assistant_response)}"
                    )
                    # print(f"[AUTO-CONTINUE FIX] Using finalized content for parsing. Length: {old_len} -> {len(assistant_response)}", flush=True)
                else:
                    logger.debug(
                        f"[AUTO-CONTINUE FIX] No finalized content available. "
                        f"Using original response (len={len(assistant_response) if assistant_response else 0})"
                    )
                    # print(f"[AUTO-CONTINUE FIX] No finalized content available. Using original response (len={len(assistant_response) if assistant_response else 0})", flush=True)
                logger.debug("Finalized streaming message with reasoning")
            except Exception as _fin_err:
                logger.warning("Failed to finalise streaming message: %s", _fin_err)

        action_results = []
        if tools_enabled:
            actions: List[CodeActAction] = parse_action(assistant_response)
            # Keep parsing note at debug level to avoid noisy stdout in normal runs
            logger.debug("[AUTO-CONTINUE FIX] Parsed %s actions from response", len(actions))
            # Enforce one action per iteration for incremental execution
            for act in (actions[:1] if actions else []):
                result = await action_executor.execute_action(act)
                # Format result for display
                action_result = {
                    "action_name": act.action_type.value if hasattr(act.action_type, 'value') else str(act.action_type),
                    "output": str(result if result is not None else ""),
                    "status": "completed" # Assuming direct call to action_executor implies success if no exception
                }
                action_results.append(action_result)
                
                # Persist result in conversation - CRITICAL FIX
                cm.add_action_result(
                    action_type=action_result["action_name"],
                    result=action_result["output"],
                    status=action_result["status"]
                )
                logger.debug(f"Added action result to conversation: {action_result['action_name']}")

                # Emit UI event immediately for real-time display (unless hidden by config)
                if hasattr(cm, 'core') and cm.core:
                    try:
                        # Check config to see if tool results should be hidden
                        from penguin.config import config
                        hide_tool_results = False
                        if isinstance(config, dict):
                            cli_config = config.get('cli', {})
                            display_config = cli_config.get('display', {})
                            hide_tool_results = display_config.get('hide_tool_results', False)

                        # Only emit if not hidden
                        if not hide_tool_results:
                            # Emit tool event for chronological timeline display
                            await cm.core.emit_ui_event("tool", {
                                "id": f"{action_result['action_name']}-{int(time.time() * 1000)}",
                                "phase": "end",
                                "action": action_result['action_name'],
                                "ts": int(time.time() * 1000),
                                "status": action_result.get('status', 'completed'),
                                "result": str(action_result['output'])[:200]  # Truncate for display
                            })
                            # Note: Removed duplicate "message" event emission - tool events are now
                            # properly handled by EventTimeline component
                            await asyncio.sleep(0.01)  # Yield control to allow UI to render
                    except Exception as e:
                        logger.warning(f"Failed to emit tool result UI event: {e}")

                # Bridge: map Penguin action → Responses tool_choice for next iteration
                try:
                    action_to_tool = {
                        "execute": "code_execution",
                        "execute_command": "execute_command",
                        "search": "grep_search",
                        "perplexity_search": "web_search",
                        "enhanced_diff": "enhanced_diff",
                        "analyze_project": "analyze_project",
                        "apply_diff": "apply_diff",
                        "edit_with_pattern": "edit_with_pattern",
                        "multiedit": "multiedit_apply",
                        "read_file": "read_file",
                        "write_to_file": "write_to_file",
                        "create_file": "create_file",
                        "create_folder": "create_folder",
                        "find_files_enhanced": "find_file",
                        "list_files_filtered": "list_files",
                    }
                    act_name = act.action_type.value if hasattr(act.action_type, 'value') else str(act.action_type)
                    mapped = action_to_tool.get(act_name)
                    if mapped:
                        self._forced_tool_choice_name = mapped
                except Exception:
                    pass

        # Persist conversation state
        cm.save()
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
