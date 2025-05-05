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
import multiprocessing as mp
from typing import Any, Callable, Coroutine, List, Optional, Sequence, Dict, Awaitable

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
    max_iterations_default: int = 5
    token_budget_stop_enabled: bool = False
    wall_clock_stop_seconds: Optional[int] = None


class StopCondition:
    """Base class for pluggable stop conditions."""

    async def should_stop(self, engine: "Engine") -> bool:  # noqa: F821
        raise NotImplementedError


class TokenBudgetStop(StopCondition):
    async def should_stop(self, engine: "Engine") -> bool:
        cw = engine.conversation_manager.context_window
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
        self.conversation_manager = conversation_manager
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.action_executor = action_executor
        self.stop_conditions: List[StopCondition] = list(stop_conditions or [])

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
    # Public API
    # ------------------------------------------------------------------

    async def run_single_turn(self, prompt: str, *, tools_enabled: bool = True, streaming: Optional[bool] = None):
        """Run a single reasoning → (optional) action → response cycle.

        Returns the same structured dict that ``_llm_step`` emits so callers
        may access both the assistant text **and** any action_results.
        """
        self.conversation_manager.conversation.prepare_conversation(prompt)
        response_data = await self._llm_step(tools_enabled=tools_enabled, streaming=streaming)
        return response_data

    async def stream(self, prompt: str):
        """Yield chunks as they arrive (if provider supports streaming)."""
        async for chunk in self._llm_stream(prompt):
            yield chunk

    async def run_task(
        self, 
        task_prompt: str, 
        max_iterations: Optional[int] = None,
        task_context: Optional[Dict[str, Any]] = None,
        task_id: Optional[str] = None,
        task_name: Optional[str] = None,
        completion_phrases: Optional[List[str]] = None,
        on_completion: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
        enable_events: bool = True,
        message_callback: Optional[Callable[[str, str], Awaitable[None]]] = None
    ) -> Dict[str, Any]:
        """
        Multi‑step reasoning loop with comprehensive task handling.
        
        Args:
            task_prompt: The prompt for the task
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
        self.conversation_manager.conversation.prepare_conversation(task_prompt)
        
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
                    "context": task_context
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
                logger.debug("Engine iteration %s", self.current_iteration)

                # Get the next response via LLM
                response_data = await self._llm_step()
                last_response = response_data.get("assistant_response", "")
                
                # Call the message callback if provided
                if message_callback and last_response:
                    await message_callback(last_response, "assistant")
                
                # Add any action results from this step
                iteration_results = response_data.get("action_results", [])
                if iteration_results:
                    all_action_results.extend(iteration_results)
                    
                    # Display action results via callback
                    if message_callback:
                        for result in iteration_results:
                            if isinstance(result, dict):
                                result_type = "output" if result.get("status") == "completed" else "error"
                                result_msg = f"{result.get('action', 'Unknown')}: {result.get('result', 'No output')}"
                            else:
                                # Handle string results
                                result_type = "output"
                                result_msg = str(result)
                            await message_callback(result_msg, result_type)

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
                            "progress": min(100, int(100 * self.current_iteration / max_iters))
                        })
                    except (ImportError, AttributeError):
                        pass

                # Check for any stop conditions
                if await self._check_stop():
                    completion_status = "stopped"
                    break
                
                # Check for completion phrases
                completed = any(phrase in last_response for phrase in all_completion_phrases)
                if completed:
                    completion_status = "completed"
                    logger.debug(f"Task completion detected. Found one of these phrases: {all_completion_phrases}")
                    
                    # Publish completion event
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
                                "context": task_context
                            })
                        except (ImportError, AttributeError):
                            pass
                            
                    break
        
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
                        "max_iterations": max_iters
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

    # ------------------------------------------------------------------
    # Child‑engine spawning (stub – process mode)
    # ------------------------------------------------------------------

    async def spawn_child(self, *, purpose: str = "child", inherit_tools: bool = False, shared_conversation: bool = False) -> "Engine":
        """Spawn a sub‑engine in a separate process.  Minimal stub for now."""
        logger.warning("spawn_child is a stub – running in‑process for now")
        cm = self.conversation_manager if shared_conversation else ConversationManager(
            model_config=self.conversation_manager.model_config,
            api_client=self.api_client,
            workspace_path=self.conversation_manager.workspace_path,
            system_prompt=self.conversation_manager.conversation.system_prompt,
        )
        tm = self.tool_manager if inherit_tools else ToolManager(self.tool_manager.error_handler)
        ae = ActionExecutor(tm, self.action_executor.task_manager, cm.conversation)
        return Engine(self.settings, cm, self.api_client, tm, ae, stop_conditions=self.stop_conditions)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _llm_step(self, *, tools_enabled: bool = True, streaming: Optional[bool] = None):
        messages = self.conversation_manager.conversation.get_formatted_messages()
        assistant_response = await self.api_client.get_response(messages, stream=streaming)

        # Add assistant message to conversation
        self.conversation_manager.conversation.add_assistant_message(assistant_response)

        action_results = []
        if tools_enabled:
            actions: List[CodeActAction] = parse_action(assistant_response)
            for act in actions:
                result = await self.action_executor.execute_action(act)
                action_results.append(result)
                # Persist result
                self.conversation_manager.add_action_result(act.action_type.value, str(result))

        # Persist conversation state
        self.conversation_manager.save()
        return {"assistant_response": assistant_response, "action_results": action_results}

    async def _llm_stream(self, prompt: str):
        """Helper to stream chunks to caller."""
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[str] = asyncio.Queue()

        async def run():
            # Prepare conversation
            self.conversation_manager.conversation.prepare_conversation(prompt)

            # Inner callback forwards chunks into queue
            async def _cb(chunk: str):
                await queue.put(chunk)

            # Call provider with streaming enabled
            messages = self.conversation_manager.conversation.get_formatted_messages()
            full_response = await self.api_client.get_response(
                messages,
                stream=True,
                stream_callback=lambda c: asyncio.create_task(_cb(c)),
            )

            # Persist full assistant response now that streaming done
            self.conversation_manager.conversation.add_assistant_message(full_response)
            self.conversation_manager.save()

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
