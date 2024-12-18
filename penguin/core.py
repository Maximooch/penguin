"""
PenguinCore acts as the central nervous system for the Penguin AI assistant.

This class orchestrates the interaction between various systems:
- Cognition System: Handles reasoning and response generation
- Conversation System: Manages message history and formatting
- Memory System: Handles context and knowledge persistence
- Processor System: Manages available tools and actions
- Task System: Handles task and project management
- Diagnostic System: Monitors performance and usage

The core acts primarily as a coordinator, delegating specific functionality
to specialized systems while maintaining overall state and flow control.
"""

from typing import Dict, List, Optional, Tuple, Any, Callable, Generator, AsyncGenerator
import logging
import os
import traceback
from datetime import datetime
import json
import re
from pathlib import Path
from rich.console import Console # type: ignore
from rich.tree import Tree # type: ignore

# LLM and API
from llm import APIClient
from llm.model_config import ModelConfig

# Core systems
from system.conversation import ConversationSystem
from cognition.cognition import CognitionSystem
from system.file_manager import FileManager

# Tools and Processing
from utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
from tools.tool_manager import ToolManager
from utils.parser import parse_action, ActionExecutor

# Task Management
# from agent.task_manager import TaskManager
# from agent.task import Task, TaskStatus
# from agent.project import Project, ProjectStatus
# from agent.task_utils import create_project, get_project_details

# Configuration
# from .config import Config
from config import (
    TASK_COMPLETION_PHRASE, 
    MAX_TASK_ITERATIONS,
    Config,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER
)

# Workspace
from workspace import get_workspace_path, write_workspace_file

# RunMode
from run_mode import RunMode

from utils.errors import error_logger

logger = logging.getLogger(__name__)
console = Console()

class PenguinCore:
    def __init__(
        self,
        config: Optional[Config] = None,
        api_client: Optional[APIClient] = None,
        tool_manager: Optional[ToolManager] = None,
        # task_manager: Optional[TaskManager] = None
    ):
        """Initialize PenguinCore with required components."""
        self.config = config or Config.load_config()
        
        # Initialize project manager
        from local_task.manager import ProjectManager
        self.project_manager = ProjectManager(workspace_root=get_workspace_path())
        
        # Initialize diagnostics based on config
        if not self.config.diagnostics.enabled:
            disable_diagnostics()
        
        self.api_client = api_client
        self.tool_manager = tool_manager
        # self.task_manager = task_manager
        self.action_executor = ActionExecutor(tool_manager) 
        self.messages = []
        
        # Initialize core systems
        self.conversation = ConversationSystem(self.tool_manager, diagnostics)
        self.cognition = CognitionSystem(
            api_client=self.api_client,
            diagnostics=diagnostics
        )
        
        # State
        self.system_prompt = ""
        self.initialized = True
        self._interrupted = False
        logger.info("PenguinCore initialized successfully")

    def _setup_diagnostics(self):
        """Initialize diagnostics based on config"""
        if self.config.diagnostics.enabled:
            enable_diagnostics()
            if self.config.diagnostics.log_to_file and self.config.diagnostics.log_path:
                # Setup file logging if configured
                log_path = Path(self.config.diagnostics.log_path)
                log_path.parent.mkdir(parents=True, exist_ok=True)
                logging.basicConfig(
                    filename=str(log_path),
                    level=logging.WARNING,
                    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
                )
        else:
            disable_diagnostics()

    def reset_context(self):
        """Reset context and diagnostics"""
        diagnostics.reset()
        self.messages = []
        self._interrupted = False
        self.conversation.reset()
        if self.tool_manager:
            self.tool_manager.reset()
        if self.action_executor:
            self.action_executor.reset()
        
    @property
    def total_tokens_used(self) -> int:
        """Get total tokens used in current session"""
        return diagnostics.get_total_tokens()
        
    def get_token_usage(self) -> Dict[str, Dict[str, int]]:
        """Get detailed token usage statistics"""
        return {
            name: tracker.tokens.copy()
            for name, tracker in diagnostics.token_trackers.items()
        }

    def prepare_conversation(self, message: str, tool_outputs: Optional[List[Dict[str, Any]]] = None):
        """Prepare conversation context with tool outputs"""
        self.add_message("user", message)
        if tool_outputs:
            tool_output_text = "\n".join(
                f"{output['action']}: {output['result']}" 
                for output in tool_outputs
            )
            self.add_message("system", f"Tool outputs:\n{tool_output_text}")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.system_prompt = prompt
        if self.api_client:
            self.api_client.set_system_prompt(prompt)

    def get_system_message(self, current_iteration: Optional[int] = None, 
                          max_iterations: Optional[int] = None) -> str:
        """Get the system message including iteration info if provided."""
        message = self.system_prompt
        if current_iteration is not None and max_iterations is not None:
            message += f"\n\nCurrent iteration: {current_iteration}/{max_iterations}"
        return message

    def _check_interrupt(self) -> bool:
        """Check if execution has been interrupted"""
        return self._interrupted
    
    async def process_message(self, message: str, context: Optional[Dict[str, Any]] = None) -> str:
        """Process a message with token tracking"""
        try:
            # Track input tokens
            diagnostics.update_tokens('main_model', message)
            
            # Process message through conversation system
            self.conversation.prepare_conversation(message)
            
            # Get response with tool execution results
            response_data, _ = await self.get_response()
            
            # Format final response including tool outputs
            if isinstance(response_data, dict):
                response = response_data.get("assistant_response", "")
                action_results = response_data.get("action_results", [])
                
                # Format response with tool outputs
                formatted_response = response + "\n\n"
                if action_results:
                    formatted_response += "Tool outputs:\n"
                    for result in action_results:
                        formatted_response += f"- {result['action']}: {result['result']}\n"
            else:
                formatted_response = str(response_data)
            
            # Track output tokens
            diagnostics.update_tokens('main_model', "", formatted_response)
            
            # Log usage if enabled
            diagnostics.log_token_usage()
            
            return formatted_response
            
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "process_message", 
                "message": message,
                "context": context
            })
            raise

    async def process_input(self, input_data: Dict[str, Any]) -> None:
        """Process user input and update token count"""
        try:
            # Count input tokens
            if "text" in input_data:
                diagnostics.update_tokens('main_model', input_data["text"])
            
            # Extract input parameters
            user_input = input_data.get("text", "")
            image_path = input_data.get("image_path")
            
            # Prepare conversation context
            self.conversation.prepare_conversation(user_input, image_path)
            
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "process_input",
                "input_data": input_data
            })
            raise

    async def process_input_with_image(self, input_data: Dict) -> None:
        try:
            user_input = input_data.get("text", "")
            image_path = input_data.get("image_path")
            
            if image_path:
                base64_image = self.tool_manager.encode_image(image_path)
                message_content = [
                    {"type": "text", "text": user_input},
                    {
                        "type": "image_url",
                        "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"}
                    }
                ]
            else:
                message_content = user_input

            response = self.api_client.create_message(
                messages=[{"role": "user", "content": message_content}]
            )
            
            # Process the response...
            
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "process_input_with_image",
                "input_data": input_data
            })
            raise

    async def get_response(
        self, 
        current_iteration: Optional[int] = None, 
        max_iterations: Optional[int] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate a response using the current conversation context.
        
        This method handles the LLM interaction and response processing,
        ensuring that tool execution is properly isolated.
        
        Returns:
            Tuple[Dict[str, Any], bool]: Response data and continuation flag
        """
        try:
            # Get raw response through API
            response = await self.api_client.create_message(
                messages=self.conversation.get_history(),
                max_tokens=None,
                temperature=None
            )
            logger.debug(f"Raw API response: {response}")

            # Process response format
            if self.api_client.model_config.use_assistants_api:
                if isinstance(response, dict):
                    assistant_response = response.get("assistant_response", "") or str(response)
                else:
                    assistant_response = str(response)
            else:
                assistant_response = response.choices[0].message.content

            # Count output tokens
            diagnostics.update_tokens('main_model', "", assistant_response)
                
            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in str(assistant_response)
            
            # Parse actions without executing
            actions = parse_action(assistant_response)
            
            # Execute actions with interrupt checking
            action_results = []
            for action in actions:
                if self._check_interrupt():
                    action_results.append({
                        "action": action.action_type.value,
                        "result": "Action skipped due to interrupt",
                        "status": "interrupted"
                    })
                    continue
                    
                try:
                    result = await self.action_executor.execute_action(action)
                    if result is not None:
                        action_results.append({
                            "action": action.action_type.value,
                            "result": str(result),
                            "status": "completed"
                        })
                except Exception as e:
                    action_results.append({
                        "action": action.action_type.value,
                        "result": f"Error executing action: {str(e)}",
                        "status": "error"
                    })
                    logger.error(f"Action execution error: {str(e)}")
            
            # Check for interrupt after actions
            if self._check_interrupt():
                return {
                    "assistant_response": "Operation interrupted during action execution",
                    "action_results": action_results,
                    "metadata": {
                        "interrupted": True,
                        "completed_actions": len([a for a in action_results if a["status"] == "completed"])
                    }
                }, True
            
            # Construct response
            full_response = {
                "assistant_response": assistant_response,
                "action_results": action_results,
                "metadata": {
                    "iteration": current_iteration,
                    "max_iterations": max_iterations
                }
            }
            
            # Update conversation
            self.conversation.add_message("assistant", assistant_response)
            
            # Log diagnostics
            diagnostics.log_token_usage()
            
            # Update task progress
            # await self._update_task_progress(assistant_response)
            
            return full_response , exit_continuation
            
        except Exception as e:
            error_data = error_logger.log_error(e, context={
                "component": "core",
                "method": "get_response",
                "iteration": current_iteration,
                "max_iterations": max_iterations
            })
            return {
                "assistant_response": "I apologize, but an error occurred. It has been logged for investigation.",
                "action_results": []
            }, False

    async def execute_action(self, action) -> Dict[str, Any]:
        """Execute an action and return structured result"""
        try:
            result = await super().execute_action(action)
            return {
                "action": action.action_type.value,
                "result": str(result) if result is not None else "",
                "status": "completed"
            }
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "execute_action",
                "action": action.action_type.value
            })
            return {
                "action": action.action_type.value,
                "result": f"Error: {str(e)}",
                "status": "error"
            }

    def reset_state(self):
        """Reset the core state"""
        self.messages = []
        self._interrupted = False
        self.conversation.reset()
        self.tool_manager.reset()
        self.action_executor.reset()

    async def display_all(self) -> str:
        """
        Display all projects and tasks in a unified view.
        Returns formatted string output.
        """
        from io import StringIO
        import sys
        
        # Capture console output
        old_stdout = sys.stdout
        string_buffer = StringIO()
        sys.stdout = string_buffer
        
        try:
            # Use project manager's display function instead
            self.project_manager._display_all()
            
            # Get the captured output
            output = string_buffer.getvalue()
            return output
            
        finally:
            sys.stdout = old_stdout
            string_buffer.close()

    async def process_list_command(self) -> Dict[str, Any]:
        """Process the /list command and return formatted output"""
        try:
            output = await self.display_all()
            return {
                "assistant_response": "Here's the current workspace overview:",
                "action_results": [{
                    "action": "list",
                    "result": output,
                    "status": "completed"
                }]
            }
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "process_list_command"
            })
            return {
                "assistant_response": f"Error displaying workspace: {str(e)}",
                "action_results": []
            }

    async def create_task(self, name: str, description: str) -> Dict[str, Any]:
        """Create a new independent task"""
        try:
            task = self.project_manager._create_independent_task(name, description)
            return {
                "action": "task_create",
                "result": f"Created task: {task.title}",
                "status": "completed"
            }
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "create_task",
                "name": name,
                "description": description
            })
            return {
                "action": "task_create",
                "result": f"Error creating task: {str(e)}",
                "status": "error"
            }

    async def complete_task(self, name: str) -> Dict[str, Any]:
        """Complete a task by name"""
        try:
            self.project_manager.complete(name)
            return {
                "action": "task_complete",
                "result": f"Completed task: {name}",
                "status": "completed"
            }
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "complete_task",
                "name": name
            })
            return {
                "action": "task_complete",
                "result": f"Error completing task: {str(e)}",
                "status": "error"
            }

    async def create_project(self, name: str, description: str) -> Dict[str, Any]:
        """Create a new project"""
        try:
            project = self.project_manager.create(name, description)
            return {
                "action": "project_create",
                "result": f"Created project: {project.name}",
                "status": "completed"
            }
        except Exception as e:
            return {
                "action": "project_create",
                "result": f"Error creating project: {str(e)}",
                "status": "error"
            }

    async def get_project_status(self, name: str) -> Dict[str, Any]:
        """Get status of a project"""
        try:
            project = self.project_manager._find_project_by_name(name)
            if not project:
                raise ValueError(f"Project not found: {name}")
            
            # Format project status
            active_tasks = [t for t in project.tasks.values() if t.status == "active"]
            completed_tasks = [t for t in project.tasks.values() if t.status == "completed"]
            
            result = (
                f"Project: {project.name}\n"
                f"Description: {project.description}\n"
                f"Tasks: active: {len(active_tasks)}, completed: {len(completed_tasks)}\n"
                f"Created: {project.created_at}\n"
                f"Last Updated: {project.updated_at}"
            )
            
            return {
                "action": "project_status",
                "result": result,
                "status": "completed"
            }
        except Exception as e:
            return {
                "action": "project_status",
                "result": f"Error getting project status: {str(e)}",
                "status": "error"
            }

    async def get_task_status(self, name: str) -> Dict[str, Any]:
        """Get status of a task"""
        try:
            task = self.project_manager._find_task_by_name(name)
            if not task:
                raise ValueError(f"Task not found: {name}")
            
            # Format task status
            result = (
                f"Task: {task.title}\n"
                f"Status: {task.status}\n"
                f"Progress: {task.progress}%\n"
                f"Priority: {task.priority}\n"
            )
            
            if task.due_date:
                result += f"Due Date: {task.due_date}\n"
            if task.tags:
                result += f"Tags: {', '.join(task.tags)}\n"
            if task.project_id:
                project = self.project_manager.projects[task.project_id]
                result += f"Project: {project.name}\n"
            
            return {
                "action": "task_status",
                "result": result,
                "status": "completed"
            }
        except Exception as e:
            return {
                "action": "task_status",
                "result": f"Error getting task status: {str(e)}",
                "status": "error"
            }

    async def start_run_mode(
        self, 
        name: str, 
        description: Optional[str] = None, 
        context: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Start autonomous run mode for executing a task.
        
        Args:
            name: Name of the task (existing or new)
            description: Optional description if creating a new task
            context: Optional additional context or parameters
        """
        try:
            # Initialize and start run mode
            run_mode = RunMode(self)
            await run_mode.start(name, description, context)
            
            # Mark task as complete if run mode finished successfully
            if not run_mode._interrupted:
                await self.complete_task(name)
                
        except Exception as e:
            error_logger.log_error(e, context={
                "component": "core",
                "method": "start_run_mode",
                "task_name": name,
                "description": description,
                "context": context
            })
            raise
