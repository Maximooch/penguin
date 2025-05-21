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

    async def run_single_turn(self, prompt: str, *, image_path: Optional[str] = None, tools_enabled: bool = True, streaming: Optional[bool] = None, stream_callback: Optional[Callable[[str], None]] = None):
        """Run a single reasoning → (optional) action → response cycle.

        Returns the same structured dict that ``_llm_step`` emits so callers
        may access both the assistant text **and** any action_results.
        """
        self.conversation_manager.conversation.prepare_conversation(prompt, image_path)
        response_data = await self._llm_step(tools_enabled=tools_enabled, streaming=streaming, stream_callback=stream_callback)
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

                # --- Streaming & LLM Call --- 
                llm_step_actual_stream_cb = None
                if message_callback: # message_callback is from Engine.run_task args
                    async def _engine_internal_chunk_handler(chunk: str):
                        # This calls the RunMode._engine_message_cb with type "assistant"
                        await message_callback(chunk, "assistant") 
                    llm_step_actual_stream_cb = _engine_internal_chunk_handler

                response_data = await self._llm_step(
                    tools_enabled=True, # Default for run_task
                    streaming=self.settings.streaming_default, # Engine's default streaming preference
                    stream_callback=llm_step_actual_stream_cb
                )
                last_response = response_data.get("assistant_response", "") # This is the full response

                # If not streaming (or if stream callback wasn't effectively used by _llm_step),
                # ensure the full response is passed to the message_callback for non-chunk handling.
                # The RunMode._engine_message_cb will then add it to conversation if not streamed to CLI.
                was_streamed_to_cb = self.settings.streaming_default and llm_step_actual_stream_cb is not None
                if not was_streamed_to_cb and message_callback and last_response:
                    await message_callback(last_response, "assistant")
                # --- End Streaming & LLM Call ---
                
                # Add any action results from this step
                iteration_results = response_data.get("action_results", [])
                if iteration_results:
                    all_action_results.extend(iteration_results)
                    
                    # Display action results via callback
                    if message_callback:
                        for tool_result_info in iteration_results: # iteration_results are from self._llm_step
                            if isinstance(tool_result_info, dict):
                                action_name = tool_result_info.get("action_name", "UnknownAction")
                                output_str = tool_result_info.get("output", "")
                                status = tool_result_info.get("status", "completed")

                                # Determine message_type for the callback
                                callback_message_type = "tool_result" # Default for processed tool outputs
                                if status != "completed":
                                    callback_message_type = "tool_error" # If status indicates an error
                                
                                # Pass the action_name to message_callback
                                await message_callback(output_str, callback_message_type, action_name=action_name)
                            else:
                                # Fallback for old format or direct string results (less ideal)
                                await message_callback(str(tool_result_info), "system_output") # Generic type

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

    async def _llm_step(self, *, tools_enabled: bool = True, streaming: Optional[bool] = None, stream_callback: Optional[Callable[[str], None]] = None):
        messages = self.conversation_manager.conversation.get_formatted_messages()
        # First attempt – honour requested streaming setting
        assistant_response = await self.api_client.get_response(
            messages,
            stream=streaming,
            stream_callback=stream_callback,
        )

        # If we received **no content**, retry once with *stream=False* (some providers
        # fail in streaming-mode but succeed with a normal completion request).
        if not assistant_response or not assistant_response.strip():
            logger.warning("_llm_step got empty response (stream=%s). Retrying once without streaming.", streaming)
            assistant_response = await self.api_client.get_response(messages, stream=False)

        # Still empty? Give up but do NOT pollute the history with blank messages.
        if not assistant_response or not assistant_response.strip():
            logger.error("_llm_step received empty response after fallback attempt. Skipping message persistence.")
            assistant_response = ""  # Preserve empty for caller but avoid history entry.
        else:
            # Persist only non-empty assistant messages
            self.conversation_manager.conversation.add_assistant_message(assistant_response)

        action_results = []
        if tools_enabled:
            actions: List[CodeActAction] = parse_action(assistant_response)
            for act in actions:
                result = await self.action_executor.execute_action(act)
                # Format result for display
                action_result = {
                    "action_name": act.action_type.value if hasattr(act.action_type, 'value') else str(act.action_type),
                    "output": str(result if result is not None else ""),
                    "status": "completed" # Assuming direct call to action_executor implies success if no exception
                }
                action_results.append(action_result)
                
                # Persist result in conversation - CRITICAL FIX
                self.conversation_manager.add_action_result(
                    action_type=action_result["action_name"],
                    result=action_result["output"],
                    status=action_result["status"]
                )
                logger.debug(f"Added action result to conversation: {action_result['action_name']}")

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
