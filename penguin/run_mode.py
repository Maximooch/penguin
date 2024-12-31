"""
RunMode provides autonomous operation capabilities for the Penguin AI assistant.
It allows the core to switch from interactive conversation to autonomous execution
while maintaining the existing conversation context and tool capabilities.
"""

from typing import Optional, Dict, Any, List
import logging
from datetime import datetime

from rich.console import Console # type: ignore
from rich.panel import Panel # type: ignore
from rich.markdown import Markdown # type: ignore

from config import MAX_TASK_ITERATIONS, TASK_COMPLETION_PHRASE

logger = logging.getLogger(__name__)
console = Console()

class RunMode:
    """
    Manages autonomous operation mode for PenguinCore sessions.
    Allows switching between interactive and autonomous execution
    while preserving conversation context and tool access.
    """
    
    def __init__(self, core, max_iterations: int = MAX_TASK_ITERATIONS):
        self.core = core
        self.max_iterations = max_iterations
        self._interrupted = False
        
        # Display settings
        self.SYSTEM_COLOR = "yellow"
        self.OUTPUT_COLOR = "green"
        self.ERROR_COLOR = "red"
        
        # Task completion settings
        self.TASK_COMPLETION_PHRASE = TASK_COMPLETION_PHRASE
        
    def _display_message(self, message: str, message_type: str = "system") -> None:
        """Display formatted message with consistent styling"""
        if not message:
            return
            
        color = {
            "output": self.OUTPUT_COLOR,
            "error": self.ERROR_COLOR,
            "system": self.SYSTEM_COLOR
        }.get(message_type, self.SYSTEM_COLOR)
        
        panel = Panel(
            Markdown(message),
            title=f"🐧 RunMode ({message_type})",
            title_align="left",
            border_style=color
        )
        console.print(panel)

    async def start(self, name: str, description: Optional[str] = None, context: Optional[Dict[str, Any]] = None) -> None:
        """
        Start autonomous execution mode with specified task details
        
        Args:
            name: Name of the task
            description: Optional description (will be fetched from task if not provided)
            context: Optional additional context or parameters for the task
        """
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

    async def _execute_run_loop(self, name: str, description: str, context: Optional[Dict[str, Any]] = None) -> None:
        """Execute the autonomous run loop"""
        current_task = {
            "name": name,
            "description": description,
            "context": context or {}
        }
        
        for iteration in range(self.max_iterations):
            if self._interrupted:
                break
                
            try:
                # Process current task
                task_prompt = (
                    f"Execute task: {current_task['name']}\n"
                    f"Description: {current_task['description']}\n"
                    f"Respond with {self.TASK_COMPLETION_PHRASE} when finished."
                )
                
                await self.core.process_input({"text": task_prompt})
                response, exit_flag = await self.core.get_response(
                    current_iteration=iteration + 1,
                    max_iterations=self.max_iterations
                )
                
                # Display results
                if isinstance(response, dict):
                    if response.get("assistant_response"):
                        self._display_message(
                            response["assistant_response"], 
                            "output"
                        )
                    
                    for result in response.get("action_results", []):
                        if result.get("status") == "error":
                            self._display_message(
                                f"Action error: {result.get('result')}", 
                                "error"
                            )
                        else:
                            self._display_message(
                                f"Action result: {result.get('result')}", 
                                "output"
                            )
                
                # Check for completion
                if exit_flag or self.TASK_COMPLETION_PHRASE in str(response):
                    self._display_message("Task completed successfully")
                    break
                    
                # Update for next iteration if needed
                current_task["description"] = (
                    "Continue with the next step toward completing the task. "
                    "Say 'TASK_COMPLETE' when finished."
                )
                
            except Exception as e:
                logger.error(f"Error in iteration {iteration + 1}: {str(e)}")
                self._display_message(
                    f"Error in iteration {iteration + 1}: {str(e)}", 
                    "error"
                )
                if not self._should_continue():
                    break

    def _should_continue(self) -> bool:
        """Check if execution should continue after error"""
        try:
            response = console.input(
                "[yellow]Continue execution? (y/n):[/yellow] "
            ).lower()
            return response.startswith('y')
        except (KeyboardInterrupt, EOFError):
            return False

    def _cleanup(self) -> None:
        """Cleanup run mode state"""
        self._interrupted = False
        self._display_message("Exiting run mode")