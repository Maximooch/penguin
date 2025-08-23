"""
RunMode provides autonomous operation capabilities for the Penguin AI assistant.
It allows the AI to switch from interactive conversation to autonomous task execution
while maintaining the existing conversation context and tool capabilities.
"""

import asyncio
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Callable, Awaitable, Union

from penguin.config import (
    CONTINUOUS_COMPLETION_PHRASE,
    EMERGENCY_STOP_PHRASE,
    MAX_TASK_ITERATIONS,
    TASK_COMPLETION_PHRASE,
    NEED_USER_CLARIFICATION_PHRASE,
)
from penguin.system.state import MessageCategory

logger = logging.getLogger(__name__)

# Custom type for event callback
EventCallback = Callable[[Dict[str, Any]], Awaitable[None]]


@dataclass
class TaskSchedule:
    """Represents a scheduled task with timing and priority information"""
    name: str
    description: str
    schedule_type: str  # 'once', 'interval'
    interval: Optional[timedelta] = None
    next_run: Optional[datetime] = None
    priority: int = 1
    context: Dict[str, Any] = None
    max_duration: Optional[timedelta] = None


class RunMode:
    """
    Manages autonomous operation mode for PenguinCore sessions.
    
    RunMode orchestrates task execution in autonomous mode,
    delegating actual LLM interaction and execution to the Engine.
    It handles:
    
    1. Task selection and sequencing
    2. Continuous mode operation
    3. Time limits and health checks
    4. Event emission for UI updates
    
    It relies on Engine for all LLM interaction, action parsing, and execution.
    """

    def __init__(
        self,
        core,
        max_iterations: int = MAX_TASK_ITERATIONS,
        time_limit: Optional[int] = None,
        event_callback: Optional[EventCallback] = None,
    ):
        """
        Initialize RunMode.
        
        Args:
            core: PenguinCore instance to use
            max_iterations: Maximum iterations per task (default from config)
            time_limit: Optional time limit in minutes for continuous mode
            event_callback: Optional callback for emitting events to UI
        """
        self.core = core
        self.max_iterations = max_iterations
        self._interrupted = False
        self.continuous_mode = False
        self.current_task_name = None
        self.event_callback = event_callback

        # Initialize timing variables
        self.start_time = datetime.now()
        self.last_health_check = datetime.now()
        self.health_check_interval = timedelta(seconds=30)
        self.time_limit = timedelta(minutes=time_limit) if time_limit else None

        # Task completion settings from config
        self.TASK_COMPLETION_PHRASE = TASK_COMPLETION_PHRASE
        self.CONTINUOUS_COMPLETION_PHRASE = CONTINUOUS_COMPLETION_PHRASE
        self.EMERGENCY_STOP_PHRASE = EMERGENCY_STOP_PHRASE
        self.NEED_USER_CLARIFICATION_PHRASE = NEED_USER_CLARIFICATION_PHRASE
        self._shutdown_requested = False
        
        # Configure Engine for streaming if available
        if hasattr(self.core, "engine") and self.core.engine:
            # Ensure Engine is configured for streaming in continuous mode
            self.core.engine.settings.streaming_default = True
            logger.debug("RunMode configured Engine for streaming")
            
        # Setup event handling if available
        self._setup_event_handlers()

    def _setup_event_handlers(self):
        """Set up event handlers for task events if EventBus is available."""
        try:
            from penguin.utils.events import EventBus, TaskEvent, EventPriority
            
            self.event_bus = EventBus.get_instance()
            
            # Subscribe to task events
            self.event_bus.subscribe(
                TaskEvent.STARTED.value,
                self._on_task_started,
                EventPriority.NORMAL
            )
            self.event_bus.subscribe(
                TaskEvent.PROGRESSED.value,
                self._on_task_progress,
                EventPriority.NORMAL
            )
            self.event_bus.subscribe(
                TaskEvent.COMPLETED.value,
                self._on_task_completed,
                EventPriority.NORMAL
            )
            self.event_bus.subscribe(
                TaskEvent.NEEDS_INPUT.value,
                self._on_task_needs_input,
                EventPriority.HIGH
            )
        except (ImportError, AttributeError):
            # EventBus not available yet, continue with normal operation
            logger.debug("EventBus not available for RunMode, using direct event callback")
    
    async def _on_task_started(self, data):
        """Handle task started event."""
        task_prompt = data.get("task_prompt", "Unknown task")
        max_iterations = data.get("max_iterations", self.max_iterations)
        logger.info(f"Event: Task started - {task_prompt} (max {max_iterations} iterations)")
        await self._emit_event({
            "type": "status",
            "status_type": "task_started",
            "data": {
                "task_prompt": task_prompt,
                "max_iterations": max_iterations,
                **data  # include original data
            }
        })
    
    async def _on_task_progress(self, data):
        """Handle task progress event."""
        iteration = data.get("iteration", 0)
        max_iterations = data.get("max_iterations", self.max_iterations)
        progress = data.get("progress", 0)
        logger.info(f"Event: Task progress - Iteration {iteration}/{max_iterations} - Progress: {progress}%")
        await self._emit_event({
            "type": "status",
            "status_type": "task_progress",
            "data": {
                "iteration": iteration,
                "max_iterations": max_iterations,
                "progress": progress,
                **data
            }
        })
    
    async def _on_task_completed(self, data):
        """Handle task completed event."""
        iteration = data.get("iteration", 0)
        logger.info(f"Event: Task completed after {iteration} iterations")
        await self._emit_event({
            "type": "status",
            "status_type": "task_completed_eventbus",
            "data": {
                "iteration": iteration,
                **data
            }
        })
    
    async def _on_task_needs_input(self, data):
        """Handle task needs input event."""
        prompt = data.get("prompt", "Task needs input")
        logger.warning(f"Event: Task needs user input - {prompt}.")
        await self._emit_event({
            "type": "status",
            "status_type": "clarification_needed_eventbus",
            "data": {"prompt": prompt, **data}
        })

    async def _emit_event(self, event_data: Dict[str, Any]) -> None:
        """
        Emit event using Core's event system or callback.
        
        Uses both the Core's event system when available and the 
        callback provided during initialization.
        
        Args:
            event_data: Dictionary containing event information
        """
        try:
            # First try using Core's event system
            if hasattr(self.core, 'emit_ui_event'):
                event_type = event_data.get("type", "status")
                
                # Convert our event format to Core's format
                if event_type == "message":
                    if event_data.get("role") == "assistant":
                        # Assistant text is already streamed – skip to avoid duplicates
                        return
                    await self.core.emit_ui_event("message", {
                        "role": event_data.get("role", "system"),
                        "content": event_data.get("content", ""),
                        "category": event_data.get("category", MessageCategory.SYSTEM),
                        "metadata": event_data.get("metadata", {})
                    })
                elif event_type == "status":
                    # For status events
                    await self.core.emit_ui_event("status", {
                        "status_type": event_data.get("status_type", "unknown"),
                        "data": event_data.get("data", {})
                    })
                elif event_type == "error":
                    # For error events
                    await self.core.emit_ui_event("error", {
                        "message": event_data.get("message", "Unknown error"),
                        "source": event_data.get("source", "runmode"),
                        "details": event_data.get("details", {})
                    })
                else:
                    # For any other events
                    await self.core.emit_ui_event(event_type, event_data)
            
            # Also use callback if provided AND it's not the same handler already reached
            if self.event_callback and self.event_callback is not getattr(self.core, "_handle_run_mode_event", None):
                await self.event_callback(event_data)
                
        except Exception as e:
            logger.error(f"Error in RunMode._emit_event: {e}", exc_info=True)

    async def start(
        self,
        name: str,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Start autonomous execution mode with specified task details.

        Args:
            name: Name of the task
            description: Optional description (will be fetched from task if not provided)
            context: Optional additional context or parameters for the task
            
        Returns:
            Dictionary with task execution results
        """
        self.current_task_name = name
        
        try:
            # Get task from project manager
            task = None
            project_manager = self.core.project_manager
            task_id = context.get("task_id") if context else None

            if task_id:
                task = await project_manager.get_task_async(task_id)

            if not task:
                logger.warning(
                    f"RunMode could not get task by ID '{task_id}'. "
                    f"Falling back to global search by title: '{name}'"
                )
                # This is the legacy behavior and can be ambiguous across projects
                # Note: get_task_by_title is also ambiguous and may not be scoped.
                # A better fallback would be ideal in the future.
                all_tasks = await project_manager.list_tasks_async()
                for t in all_tasks:
                    if t.title.lower() == name.lower():
                        task = t
                        break

            # If task still not found and no description given, it's an error
            if not task and not description:
                error_msg = f"Task '{name}' could not be resolved to a specific record and no fallback description was provided."
                await self._emit_event(
                    {
                        "type": "error",
                        "source": "runmode_task_setup",
                        "message": error_msg,
                    }
                )
                return {
                    "status": "error",
                    "message": error_msg,
                    "completion_type": "error",
                }

            # Use task description if found and none was provided
            if task and not description:
                description = task.description

            # Emit task started event
            logger.info(f"RunMode: Starting single task mode for: {name}")
            await self._emit_event({
                "type": "message",
                "role": "system",
                "content": f"Starting task: {name}",
                "category": MessageCategory.SYSTEM
            })
            await self._emit_event({
                "type": "status",
                "status_type": "task_started",
                "data": {"task_name": name, "description": description}
            })

            # Execute the task
            task_context = context or {}
            task_result = await self._execute_task(name, description, task_context)
            
            # If task completed successfully, check if it should be marked as complete
            if task_result.get("status") == "completed":
                # Handle task completion based on type
                if task_result.get("completion_type") != "user_specified" and task:
                    try:
                        from penguin.project.models import TaskStatus
                        success = self.core.project_manager.update_task_status(
                            task.id, 
                            TaskStatus.COMPLETED
                        )
                        if not success:
                            logger.warning(f"Failed to mark task '{name}' as complete in project manager")
                    except Exception as e:
                        logger.error(f"Error marking task '{name}' as complete: {e}")
                
                # Emit completion event
                await self._emit_event({
                    "type": "message",
                    "role": "system",
                    "content": f"RunMode: Task '{name}' completed.",
                    "category": MessageCategory.SYSTEM
                })
                await self._emit_event({
                    "type": "status",
                    "status_type": "task_completed",
                    "data": {"task_name": name}
                })
            
            return task_result

        except KeyboardInterrupt:
            self._interrupted = True
            logger.info("RunMode: Interrupted by user.")
            await self._emit_event({
                "type": "status",
                "status_type": "run_interrupted",
                "data": {"reason": "user_keyboard_interrupt"}
            })
            return {
                "status": "interrupted",
                "message": "Task interrupted by user",
                "completion_type": "interrupted"
            }
        except Exception as e:
            error_msg = f"Error in run mode: {str(e)}"
            logger.error(error_msg)
            await self._emit_event({
                "type": "error",
                "source": "runmode_start",
                "message": str(e),
                "details": {"traceback": traceback.format_exc()}
            })
            return {
                "status": "error",
                "message": error_msg,
                "completion_type": "error"
            }
        finally:
            await self._cleanup()

    async def _cleanup(self) -> None:
        """Clean up run mode state."""
        self._interrupted = False
        self.current_task_name = None
        logger.debug("Cleaning up run mode state")
        
        # If not in continuous mode, emit end event
        if not self.continuous_mode:
            logger.info("RunMode: Session ended.")
            await self._emit_event({
                "type": "status", 
                "status_type": "run_mode_ended", 
                "data": {}
            })

    async def start_continuous(
        self, 
        specified_task_name: Optional[str] = None, 
        task_description: Optional[str] = None
    ) -> None:
        """
        Start continuous operation mode.
        
        Args:
            specified_task_name: Optional name of a specific task to prioritize
            task_description: Optional description/message if no specific task
        """
        try:
            self.continuous_mode = True
            logger.debug("RunMode: Starting continuous operation mode")
            
            initial_continuous_mode_message = (
                "Starting continuous operation mode\n"
                + (f"Task: {specified_task_name}\n" if specified_task_name else "")
                + (f"Description: {task_description}\n" if task_description else "")
                + (
                    f"Time limit: {self.time_limit.total_seconds() / 60:.1f} minutes\n"
                    if self.time_limit
                    else ""
                )
                + "Press Ctrl+C to initiate graceful shutdown"
            )
            
            await self._emit_event({
                "type": "message",
                "role": "system",
                "content": initial_continuous_mode_message,
                "category": MessageCategory.SYSTEM
            })

            self._shutdown_requested = False
            self.start_time = datetime.now()
            
            # If user specified a task name but no specific description, try to find its description
            if specified_task_name and not task_description:
                try:
                    task = await self.core.project_manager.get_task_by_title(specified_task_name)
                    if task:
                        task_description = task.description
                except Exception as e:
                    logger.debug(f"Could not find task '{specified_task_name}': {e}")
            
            # If user specified a description but no task name, create a temporary task
            if task_description and not specified_task_name:
                specified_task_name = "user_specified_task"

            # Main continuous mode loop
            while not self._shutdown_requested:
                logger.debug(f"RunMode: Continuous mode loop - shutdown_requested: {self._shutdown_requested}")

                # Check time limit
                if self.time_limit and (datetime.now() - self.start_time) >= self.time_limit:
                    logger.debug("RunMode: Time limit reached")
                    await self._emit_event({
                        "type": "message",
                        "role": "system",
                        "content": "RunMode: Time limit reached, initiating shutdown...",
                        "category": MessageCategory.SYSTEM
                    })
                    await self._emit_event({
                        "type": "status",
                        "status_type": "time_limit_reached",
                        "data": {"mode": "continuous"}
                    })
                    self._shutdown_requested = True
                    break

                # Check for interrupts using Core's state
                if getattr(self.core, "_interrupted", False):
                    logger.debug("Interrupt detected, waiting...")
                    await asyncio.sleep(0.1)
                    continue

                # Get next task
                task_data = await self._get_next_task_data(specified_task_name, task_description)
                if not task_data:
                    logger.debug("No tasks available, determining next step")
                    # Create general task to determine next steps
                    task_data = {
                        "name": "determine_next_step",
                        "description": "Based on the current project state, determine the next logical step to take.",
                        "context": {}
                    }

                # Execute the task
                task_result = await self._execute_task(
                    task_data["name"],
                    task_data["description"],
                    task_data["context"]
                )
                
                # Check if we should exit continuous mode based on the result
                if task_result.get("completion_type") == "user_specified":
                    msg_content = "RunMode: User-specified task completed, waiting for further instructions."
                    await self._emit_event({
                        "type": "message",
                        "role": "system",
                        "content": msg_content,
                        "category": MessageCategory.SYSTEM
                    })
                    await self._emit_event({
                        "type": "status",
                        "status_type": "continuous_mode_ending",
                        "data": {"reason": "user_specified_task_completed"}
                    })
                    self._shutdown_requested = True
                    break
                
                # If this was the user-specified task, clear it after execution
                # so we can move on to other tasks
                if specified_task_name and task_data["name"] == specified_task_name:
                    specified_task_name = None
                    task_description = None

                # Run health check
                await self._health_check()

            logger.debug("RunMode: Exiting continuous mode main loop")

        except KeyboardInterrupt:
            logger.info("RunMode: Keyboard interrupt received during continuous mode.")
            self._shutdown_requested = True
            await self._emit_event({
                "type": "message",
                "role": "system",
                "content": "RunMode: Keyboard interrupt received, initiating graceful shutdown...",
                "category": MessageCategory.SYSTEM
            })
            await self._emit_event({
                "type": "status",
                "status_type": "run_interrupted",
                "data": {"reason": "user_keyboard_interrupt_continuous"}
            })
        except Exception as e:
            logger.error(f"RunMode: Continuous operation error: {str(e)}", exc_info=True)
            await self._emit_event({
                "type": "error",
                "source": "runmode_continuous",
                "message": f"Continuous operation error: {str(e)}",
                "details": {"traceback": traceback.format_exc()}
            })
            raise
        finally:
            logger.debug("RunMode: Entering graceful shutdown for continuous mode.")
            await self._graceful_shutdown()

    async def _get_next_task_data(
        self, 
        specified_task_name: Optional[str], 
        task_description: Optional[str]
    ) -> Optional[Dict[str, Any]]:
        """
        Helper to prepare task data for execution.
        
        Args:
            specified_task_name: Optional name of specific task
            task_description: Optional description for task
            
        Returns:
            Dictionary with task data or None if no task available
        """
        if specified_task_name:
            # Check if it's an existing task
            try:
                task = self.core.project_manager.get_task_by_title(specified_task_name)
                if task:
                    # Return data from existing task
                    return {
                        "name": task.title,
                        "description": task.description if task_description is None else task_description,
                        "context": {
                            "id": task.id,
                            "project_id": task.project_id,
                            "priority": task.priority,
                            "metadata": task.metadata if hasattr(task, "metadata") else {},
                            "status": task.status.value,
                            "progress": getattr(task, "progress", 0),
                            "due_date": task.due_date,
                        }
                    }
            except Exception as e:
                logger.debug(f"Could not find task '{specified_task_name}': {e}")
            else:
                # Return data for user-specified task
                return {
                    "name": specified_task_name,
                    "description": task_description or f"Complete the task: {specified_task_name}",
                    "context": {
                        "id": "user_specified",
                        "project_id": None,
                        "priority": 1,
                        "metadata": {},
                        "status": "active",
                        "progress": 0,
                        "due_date": None,
                    }
                }
        
        # Get next task from project manager
        try:
            next_task = await self.core.project_manager.get_next_task_async()
            if next_task:
                return {
                    "name": next_task.title,
                    "description": next_task.description,
                    "context": {
                        "id": next_task.id,
                        "project_id": next_task.project_id,
                        "priority": next_task.priority,
                        "metadata": getattr(next_task, "metadata", {}),
                        "status": next_task.status.value,
                        "progress": getattr(next_task, "progress", 0),
                        "due_date": next_task.due_date,
                    }
                }
        except Exception as e:
            logger.debug(f"Error getting next task: {e}")
            
        return None

    async def _health_check(self) -> None:
        """Perform periodic health checks of system resources."""
        current_time = datetime.now()
        if current_time - self.last_health_check >= self.health_check_interval:
            try:
                logger.debug(f"Running health check at {current_time}")
                # Check system resources if available
                memory_usage = 0
                cpu_usage = 0
                
                if hasattr(self.core, "diagnostics"):
                    memory_usage = getattr(self.core.diagnostics, "get_memory_usage", lambda: 0)()
                    cpu_usage = getattr(self.core.diagnostics, "get_cpu_usage", lambda: 0)()

                if memory_usage > 90 or cpu_usage > 90:
                    msg_content = f"RunMode Warning: High resource usage - Memory {memory_usage}%, CPU {cpu_usage}%"
                    await self._emit_event({
                        "type": "message",
                        "role": "system",
                        "content": msg_content,
                        "category": MessageCategory.ERROR
                    })
                    await self._emit_event({
                        "type": "status",
                        "status_type": "health_check_warning",
                        "data": {"memory_usage": memory_usage, "cpu_usage": cpu_usage}
                    })

                self.last_health_check = current_time

            except Exception as e:
                logger.error(f"Health check error: {str(e)}")
                await self._emit_event({
                    "type": "error",
                    "source": "health_check",
                    "message": str(e)
                })

    async def _graceful_shutdown(self) -> None:
        """Perform graceful shutdown of RunMode."""
        logger.debug("Starting graceful shutdown")
        await self._emit_event({
            "type": "message",
            "role": "system",
            "content": "RunMode: Starting graceful shutdown.",
            "category": MessageCategory.SYSTEM
        })
        await self._emit_event({
            "type": "message",
            "role": "system",
            "content": "RunMode: Completing current tasks before shutdown...",
            "category": MessageCategory.SYSTEM
        })

        # Clean up state
        await self._cleanup()
        
        # Reset continuous mode flag explicitly
        self.continuous_mode = False
        
        logger.debug("Graceful shutdown completed")
        await self._emit_event({
            "type": "message",
            "role": "system",
            "content": "RunMode: Graceful shutdown completed.",
            "category": MessageCategory.SYSTEM
        })
        await self._emit_event({
            "type": "status", 
            "status_type": "shutdown_completed", 
            "data": {}
        })

    async def _execute_task(
        self,
        name: str,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a task using the Engine's run_task method.
        
        This method delegates the actual task execution to Engine.run_task,
        which handles all LLM interaction, action parsing, and execution.
        
        Args:
            name: Name of the task
            description: Task description
            context: Optional task context
            
        Returns:
            Dictionary with task execution results
        """
        # Set current task name for external reference
        self.current_task_name = name
        
        # Log task details
        logger.debug(f"Executing task: {name}")
        logger.debug(f"Description: {description}")
        
        # Prepare task prompt
        task_prompt = (
            f"Execute task: {name}\n"
            f"Description: {description or f'Complete the task: {name}'}\n"
            f"Respond with {self.TASK_COMPLETION_PHRASE} when finished."
        )
        
        # Add context as formatted text if provided
        if context:
            context_str = "\n".join(f"{k}: {v}" for k, v in context.items() if k not in ["metadata"])
            if context_str:
                task_prompt += f"\nContext: {context_str}"
            
            # Add metadata as a separate section if it exists
            if "metadata" in context and context["metadata"]:
                metadata_str = "\n".join(f"{k}: {v}" for k, v in context["metadata"].items())
                if metadata_str:
                    task_prompt += f"\nMetadata: {metadata_str}"
        
        try:
            # Check if Engine is available
            if not hasattr(self.core, "engine") or not self.core.engine:
                error_msg = "Engine not available. Cannot execute task without Engine."
                logger.error(error_msg)
                await self._emit_event({
                    "type": "error",
                    "source": "runmode_task_execution",
                    "message": error_msg
                })
                return {
                    "status": "error",
                    "message": error_msg,
                    "completion_type": "error"
                }
            
            # Track the last assistant buffer so we can forward *only* new text when
            # providers send cumulative chunks (e.g. some Gemini / Llama endpoints).
            last_assistant_chunk: str = ""

            async def message_callback(message: str, message_type: str, action_name: Optional[str] = None) -> None:
                """Unified callback invoked by Engine during run_task for **all** message types."""

                # ------------------------------------------------------------------
                # 1. Live assistant streaming – forward to Core streaming handler
                # ------------------------------------------------------------------
                if message_type == "assistant":
                    nonlocal last_assistant_chunk

                    # Compute delta if backend sends the full buffer each time.
                    new_part = message
                    if message.startswith(last_assistant_chunk):
                        new_part = message[len(last_assistant_chunk):]
                    last_assistant_chunk = message

                    if new_part:
                        # Forward the *new* part to Core so that the UI receives a
                        # single, de-duplicated stream of text chunks. Use the
                        # standard "assistant" message_type so downstream renderers
                        # (TUI/web) treat this as primary assistant content rather
                        # than an opaque "text" subtype.
                        try:
                            await self.core._handle_stream_chunk(new_part, message_type="assistant", role="assistant")
                        except Exception:
                            pass  # Never break RunMode on UI errors
                    return  # Assistant handled – skip further processing

                # ------------------------------------------------------------------
                # 1b. Reasoning stream – route via Core so TUI renders sidebar
                # ------------------------------------------------------------------
                if message_type == "reasoning":
                    try:
                        await self.core._handle_stream_chunk(message, message_type="reasoning", role="assistant")
                    except Exception:
                        pass
                    return

                # ------------------------------------------------------------------
                # 2. Tool output, errors, system notes – emit as regular events
                # ------------------------------------------------------------------
                
                # Determine role & category
                role = "system"
                category = MessageCategory.SYSTEM

                if message_type in ["tool_result", "tool_error", "tool_output", "tool_input"]:
                    is_error = message_type == "tool_error"
                    category = MessageCategory.ERROR if is_error else MessageCategory.SYSTEM_OUTPUT

                    tool_type = message_type.replace("_", " ").title()
                    if action_name:
                        message = f"{tool_type} ({action_name}):\n{message}"
                    else:
                        message = f"{tool_type}:\n{message}"

                elif message_type == "error":
                    category = MessageCategory.ERROR

                await self._emit_event({
                    "type": "message",
                    "role": role,
                    "content": message,
                    "category": category,
                    "metadata": {"tool_name": action_name} if action_name else {}
                })
            
            logger.debug("Using Engine.run_task method")
            
            # Set up custom completion phrases to check for
            completion_phrases = [
                self.TASK_COMPLETION_PHRASE,
                "TASK_COMPLETE",  # Common variation
                self.CONTINUOUS_COMPLETION_PHRASE,
                self.NEED_USER_CLARIFICATION_PHRASE,
                self.EMERGENCY_STOP_PHRASE
            ]
            
            # Extract task_id from context if available
            task_id = context.get("id") if context else None
            if task_id == "user_specified":
                task_id = f"user_task_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
            
            # ------------------------------------------------------------------
            # Call Engine.run_task – streaming enabled via Engine.settings;
            # assistant chunks arrive through *message_callback* above.
            # ------------------------------------------------------------------
            result = await self.core.engine.run_task(
                task_prompt=task_prompt,
                max_iterations=self.max_iterations,
                task_context=context,
                task_id=task_id,
                task_name=name,
                completion_phrases=completion_phrases,
                enable_events=True,
                message_callback=message_callback
            )
            
            # Ensure any active streaming message is finalised so UI gets a single completed panel
            try:
                finalized_msg = self.core.finalize_streaming_message()
                if finalized_msg:
                    logger.debug(f"Finalized streaming message: {finalized_msg.get('content', '')[:50]}...")
            except Exception as e:
                logger.warning(f"Error finalizing streaming message: {e}")  # Log the error instead of silently passing
            
            # Log completion
            logger.info(f"Task '{name}' finished with Engine - status: {result.get('status')}")
            
            # Determine completion type
            completion_type = self._determine_completion_type(name, context, result)
            
            # Create standardized return format
            return {
                "status": result.get("status", "unknown"),
                "message": result.get("assistant_response", ""),
                "completion_type": completion_type,
                "metadata": context.get("metadata", {}) if context else {},
                "iterations": result.get("iterations", 0),
                "execution_time": result.get("execution_time", 0),
            }
                
        except Exception as e:
            # Handle execution errors
            error_msg = f"Error executing task: {str(e)}"
            logger.error(error_msg)
            logger.exception("Traceback for task execution error:")
            
            await self._emit_event({
                "type": "error",
                "source": "execute_task",
                "message": error_msg,
                "details": {"traceback": traceback.format_exc()}
            })
            
            return {
                "status": "error",
                "message": error_msg,
                "completion_type": "error"
            }

    def _determine_completion_type(self, name: str, context: Optional[Dict[str, Any]], result: Dict[str, Any]) -> str:
        """
        Determine the completion type based on the task and result.
        
        Args:
            name: Task name
            context: Task context
            result: Task execution result
            
        Returns:
            Completion type string
        """
        # Check for user-specified tasks
        if name == "user_specified_task" or name == "determine_next_step":
            return "user_specified"
        
        if context and context.get("id") == "user_specified":
            return "user_specified"
        
        # Check special completion phrases in response
        response = result.get("assistant_response", "")
        
        if self.EMERGENCY_STOP_PHRASE in response:
            return "emergency_stop"
            
        if self.NEED_USER_CLARIFICATION_PHRASE in response:
            return "clarification_needed"
            
        if self.CONTINUOUS_COMPLETION_PHRASE in response:
            return "continuous"
            
        # Standard task completion
        return "task" 