"""
RunMode provides autonomous operation capabilities for the Penguin AI assistant.
It allows the core to switch from interactive conversation to autonomous execution
while maintaining the existing conversation context and tool capabilities.
"""

import asyncio
import json
import logging
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Dict, Optional

from rich.console import Console  # type: ignore
from rich.panel import Panel  # type: ignore

from penguin.config import (
    CONTINUOUS_COMPLETION_PHRASE,
    EMERGENCY_STOP_PHRASE,
    MAX_TASK_ITERATIONS,
    TASK_COMPLETION_PHRASE,
)

logger = logging.getLogger(__name__)
console = Console()


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
    Allows switching between interactive and autonomous execution
    while preserving conversation context and tool access.
    """

    def __init__(
        self,
        core,
        max_iterations: int = MAX_TASK_ITERATIONS,
        time_limit: Optional[int] = None,
    ):
        self.core = core
        self.max_iterations = max_iterations
        self._interrupted = False
        self.continuous_mode = False

        # Initialize timing variables
        self.start_time = datetime.now()
        self.last_health_check = datetime.now()
        self.health_check_interval = timedelta(seconds=30)
        self.time_limit = timedelta(minutes=time_limit) if time_limit else None

        # Display settings
        self.SYSTEM_COLOR = "yellow"
        self.OUTPUT_COLOR = "green"
        self.ERROR_COLOR = "red"

        # Task completion settings
        self.TASK_COMPLETION_PHRASE = TASK_COMPLETION_PHRASE
        self.CONTINUOUS_COMPLETION_PHRASE = CONTINUOUS_COMPLETION_PHRASE
        self.EMERGENCY_STOP_PHRASE = EMERGENCY_STOP_PHRASE

        self._shutdown_requested = False

    def _display_message(self, message_text: str, message_type: str = "system") -> None:
        """Display formatted message with consistent styling"""
        if not message_text:
            return

        color = {
            "output": self.OUTPUT_COLOR,
            "error": self.ERROR_COLOR,
            "system": self.SYSTEM_COLOR,
        }.get(message_type, self.SYSTEM_COLOR)

        panel = Panel(
            message_text,
            title=f"🐧 RunMode ({message_type})",
            title_align="left",
            border_style=color,
        )
        console.print(panel)

        # New message logging logic
        role_mapping = {
            "system": "system",
            "output": "assistant",
            "error": "system",
            "debug": "system",
        }

        if hasattr(self.core, "run_mode_messages"):
            self.core.run_mode_messages.append(
                {
                    "role": role_mapping.get(message_type, "system"),
                    "content": f"[RunMode {message_type}] {message_text}",
                }
            )

    async def start(
        self,
        name: str,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Start autonomous execution mode with specified task details

        Args:
            name: Name of the task
            description: Optional description (will be fetched from task if not provided)
            context: Optional additional context or parameters for the task
        """
        if hasattr(self.core, "run_mode_messages"):
            self.core.run_mode_messages.clear()
        try:
            # Get task from project manager
            task = None
            project_manager = self.core.project_manager

            # Search in independent tasks first
            for t in project_manager.independent_tasks.values():
                if t.title.lower() == name.lower():
                    task = t
                    break

            # If not found, search in all projects
            if not task:
                for project in project_manager.projects.values():
                    for t in project.tasks.values():
                        if t.title.lower() == name.lower():
                            task = t
                            break
                    if task:
                        break

            if not task and not description:
                self._display_message(f"Task not found: {name}", "error")
                return

            # Use task description if found
            if task:
                description = task.description

            self._display_message(
                f"Starting task: {name}\n"
                f"Description: {description}\n"
                f"Context: {context or 'None'}\n\n"
                "Press Ctrl+C to interrupt execution"
            )

            await self._execute_run_loop(name, description, context)

        except KeyboardInterrupt:
            self._interrupted = True
            self._display_message("Run mode interrupted by user")
        except Exception as e:
            logger.error(f"Error in run mode: {str(e)}")
            self._display_message(f"Error: {str(e)}", "error")
        finally:
            self._cleanup()

    async def _execute_run_loop(
        self, name: str, description: str, context: Optional[Dict[str, Any]] = None
    ) -> None:
        """Execute the autonomous run loop"""
        current_task = {
            "name": name,
            "description": description,
            "context": context or {},
        }

        for iteration in range(self.max_iterations):
            if self._interrupted:
                break

            try:
                # Process current task
                task_prompt = (
                    f"Execute task: {current_task['name']}\n"
                    f"Description: {current_task['description']}\n"
                    f"Respond with {self.TASK_COMPLETION_PHRASE} ONLY when finished with the task, not the message!."
                )

                # Use the conversation system to prepare the message without executing anything yet
                self.core.conversation_manager.conversation.prepare_conversation(task_prompt)
                
                # Get response and execute actions in one step (no multi-step needed for run mode commands)
                response, exit_flag = await self.core.get_response(
                    current_iteration=iteration + 1, max_iterations=self.max_iterations
                )

                # Display results
                if isinstance(response, dict):
                    if response.get("assistant_response"):
                        self._display_message(response["assistant_response"], "output")

                    for result in response.get("action_results", []):
                        if result.get("status") == "error":
                            self._display_message(
                                f"Action error: {result.get('result')}", "error"
                            )
                        else:
                            self._display_message(
                                f"Action result: {result.get('result')}", "output"
                            )

                # Check for completion
                if not self.continuous_mode:
                    if exit_flag or self.TASK_COMPLETION_PHRASE in str(response):
                        self._display_message("Task completed")
                        break
                elif (
                    self.time_limit
                    and (datetime.now() - self.start_time) >= self.time_limit
                ):
                    self._display_message("Time limit reached")
                    break

                # Update for next iteration if needed
                current_task["description"] = (
                    "Continue with the next step toward completing the task. "
                    "Say 'TASK_COMPLETE' when finished."
                )

            except Exception as e:
                logger.error(f"Error in iteration {iteration + 1}: {str(e)}")
                self._display_message(
                    f"Error in iteration {iteration + 1}: {str(e)}", "error"
                )
                if not self._should_continue():
                    break

    def _should_continue(self) -> bool:
        """Check if execution should continue after error"""
        try:
            response = console.input(
                "[yellow]Continue execution? (y/n):[/yellow] "
            ).lower()
            return response.startswith("y")
        except (KeyboardInterrupt, EOFError):
            return False

    def _cleanup(self) -> None:
        """Cleanup run mode state"""
        self._interrupted = False
        self.continuous_mode = False
        logger.debug("Cleaning up run mode state")
        self._display_message(
            f"Exiting run mode\nDebug: {logger.getEffectiveLevel()}\nTraceback: {traceback.format_stack()}"
        )

    async def start_continuous(self) -> None:
        """Start continuous operation mode"""
        try:
            self.continuous_mode = True
            self._display_message("[DEBUG] Starting continuous operation mode")
            self._display_message(
                "Starting continuous operation mode\n"
                + (
                    f"Time limit: {self.time_limit.total_seconds() / 60:.1f} minutes\n"
                    if self.time_limit
                    else ""
                )
                + "Press Ctrl+C to initiate graceful shutdown"
            )

            self._shutdown_requested = False
            self.start_time = datetime.now()

            while not self._shutdown_requested:
                self._display_message(
                    f"[DEBUG] Continuous mode loop - shutdown_requested: {self._shutdown_requested}"
                )

                # Check time limit
                if (
                    self.time_limit
                    and (datetime.now() - self.start_time) >= self.time_limit
                ):
                    self._display_message("[DEBUG] Time limit reached")
                    self._display_message("Time limit reached, initiating shutdown...")
                    self._shutdown_requested = True
                    break

                # Check for interrupts using Core's state
                if getattr(self.core, "_interrupted", False):
                    logger.debug("Interrupt detected, waiting...")
                    self._display_message("Interrupt detected, waiting...")
                    await asyncio.sleep(0.1)
                    continue

                # I do wonder if it'll be more logical for the Penguin to just decide what's the next task to do from seeing the list.
                # Because it saves a lot of hassle about priority, scheduling, mostly DAGs.

                # Get next task from project manager
                next_task = await self.core.project_manager.get_next_task()
                if next_task:
                    self._display_message(
                        f"[DEBUG] Processing task: {next_task['title']}"
                    )
                    await self._execute_task(
                        next_task["title"],
                        next_task["description"],
                        {
                            "id": next_task["id"],
                            "project_id": next_task.get("project_id"),
                            "priority": next_task.get("priority"),
                            "metadata": next_task.get("metadata", {}),
                            "status": next_task.get("status"),
                            "progress": next_task.get("progress"),
                            "due_date": next_task.get("due_date"),
                        },
                    )
                else:
                    self._display_message("[DEBUG] No tasks available")
                    await asyncio.sleep(1 if not self.time_limit else 0.1)

                await self._health_check()

            self._display_message("[DEBUG] Exiting continuous mode main loop")

        except KeyboardInterrupt:
            self._display_message("[DEBUG] Keyboard interrupt received")
            self._shutdown_requested = True
            self._display_message("Initiating graceful shutdown...")
        except Exception as e:
            self._display_message(f"[DEBUG] Continuous operation error: {str(e)}")
            self._display_message(f"[DEBUG] Traceback:\n{traceback.format_exc()}")
            raise
        finally:
            self._display_message("[DEBUG] Entering graceful shutdown")
            await self._graceful_shutdown()

    async def _health_check(self) -> None:
        """Perform periodic health checks"""
        current_time = datetime.now()
        if current_time - self.last_health_check >= self.health_check_interval:
            try:
                logger.debug(f"Running health check at {current_time}")
                # Check system resources
                memory_usage = self.core.diagnostics.get_memory_usage()
                cpu_usage = self.core.diagnostics.get_cpu_usage()

                if memory_usage > 90 or cpu_usage > 90:
                    self._display_message(
                        f"High resource usage: Memory {memory_usage}%, CPU {cpu_usage}%",
                        "error",
                    )

                self.last_health_check = current_time

            except Exception as e:
                logger.error(f"Health check error: {str(e)}")

    async def _graceful_shutdown(self) -> None:
        """Perform graceful shutdown"""
        logger.debug("Starting graceful shutdown")
        self._display_message("Starting graceful shutdown")
        self._display_message("Completing current tasks before shutdown...")
        # Wait for current task to complete if any
        # Save state if needed
        self._cleanup()
        logger.debug("Graceful shutdown completed")
        self._display_message("Graceful shutdown completed")

    async def _execute_task(
        self,
        name: str,
        description: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """
        Execute a task with proper completion handling

        Args:
            name: Name of the task
            description: Task description
            context: Optional task context including:
                - id: Task ID
                - project_id: Optional project ID
                - priority: Task priority
                - metadata: Additional task metadata
                - status: Current task status
                - progress: Task progress (0-100)
                - due_date: Optional due date
        """
        try:
            iteration = 0
            self._display_message(f"Starting task: {name}")

            # Provide default description if none exists
            task_description = description or f"Complete the task: {name}"

            while iteration < self.max_iterations:
                if self._interrupted:
                    return {"status": "interrupted", "message": "Task execution interrupted by user"}

                # Create task prompt
                task_prompt = (
                    f"Execute task: {name}\n"
                    f"Description: {task_description}\n"
                    "Respond with TASK_COMPLETE when finished."
                )

                # Add context if available
                if context:
                    task_prompt += f"\nContext: {json.dumps(context, indent=2)}"

                # Use core.process directly with run_mode context
                # This will automatically use the optimized path
                response = await self.core.process(
                    task_prompt, 
                    context=context,
                    max_iterations=1  # Just one iteration needed here
                )

                # Enhanced error handling for empty responses
                if not response.get("assistant_response"):
                    error_info = {
                        "iteration": iteration,
                        "timestamp": datetime.now().isoformat(),
                        "response_data": response,
                    }
                    logger.error(f"Empty response in task execution", extra={"debug_info": error_info}) # TODO:Include traceback
                    response["assistant_response"] = (
                        "I apologize, but I encountered an issue generating a response. "
                        "Let me try to continue with the task."
                    )

                # Display Penguin's thoughts
                self._display_message(response["assistant_response"], "assistant")

                # Display action results
                for result in response.get("action_results", []):
                    self._display_message(
                        f"{result['action']}: {result['result']}",
                        "output" if result["status"] == "completed" else "error",
                    )

                # Check completion phrases
                response_text = str(response.get("assistant_response", ""))

                if self.EMERGENCY_STOP_PHRASE in response_text:
                    self._display_message("Emergency stop requested")
                    return {
                        "status": "error",
                        "message": "Emergency stop requested by task",
                    }

                if self.CONTINUOUS_COMPLETION_PHRASE in response_text:
                    self._display_message(
                        "[DEBUG] Continuous mode completion requested"
                    )
                    self.continuous_mode = False
                    self.core._continuous_mode = False
                    return {
                        "status": "completed",
                        "message": "Continuous mode session completed",
                        "completion_type": "continuous",
                    }

                if self.TASK_COMPLETION_PHRASE in response_text:
                    self._display_message(f"[DEBUG] Task completion detected: {name}")
                    result = self.core.project_manager.complete_task(name)

                    # Enhanced state checks and error handling
                    self._display_message("[DEBUG] Completion state check:")
                    self._display_message(
                        f"[DEBUG] - RunMode continuous_mode: {self.continuous_mode}"
                    )
                    self._display_message(
                        f"[DEBUG] - Core continuous_mode: {self.core._continuous_mode}"
                    )
                    self._display_message(
                        f"[DEBUG] - Result status: {result['status']}"
                    )
                    self._display_message(
                        f"[DEBUG] - Result metadata: {result.get('metadata', {})}"
                    )

                    if result["status"] == "completed":
                        self._display_message(f"Task completed: {name}", "output")
                        return {
                            "status": "completed",
                            "message": f"Task '{name}' completed successfully",
                            "completion_type": "task",
                            "metadata": result.get("metadata", {}),
                        }
                    else:
                        error_msg = f"Task completion error: {result.get('result', 'Unknown error')}"
                        self._display_message(f"[DEBUG] {error_msg}")
                        return {"status": "error", "message": error_msg}

                # Update iteration counter
                iteration += 1

                # Perform health check if needed
                if datetime.now() - self.last_health_check > self.health_check_interval:
                    self._display_message("[DEBUG] Performing health check")
                    self.last_health_check = datetime.now()

                # Check time limit if set
                if (
                    self.time_limit
                    and datetime.now() - self.start_time > self.time_limit
                ):
                    return {
                        "status": "error",
                        "message": "Task execution time limit exceeded",
                    }

            # Max iterations reached
            return {
                "status": "error",
                "message": f"Max iterations ({self.max_iterations}) reached without completion",
            }

        except Exception as e:
            self._display_message(f"[DEBUG] Error in task execution: {str(e)}")
            self._display_message(f"[DEBUG] Traceback:\n{traceback.format_exc()}")
            return {"status": "error", "message": str(e)}

    # def _request_shutdown(self, message: str = None):
    #     """Request graceful shutdown with optional message"""
    #     self._display_message(f"[DEBUG] Shutdown requested: {message}")
    #     if message:
    #         self._display_message(message)
    #     self._display_message(f"[DEBUG] Current continuous_mode state: {self.continuous_mode}")
    #     self._shutdown_requested = True
