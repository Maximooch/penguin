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

from typing import Dict, List, Optional, Tuple, Any, Callable
import logging
import os
import traceback
from datetime import datetime
import json
import re

# LLM and API
from llm import APIClient
from llm.model_config import ModelConfig

# Core systems
# from hub import PenguinHub
from system.conversation import ConversationSystem
from cognition.cognition import CognitionSystem
from system.file_manager import FileManager

# Tools and Processing
from utils.diagnostics import Diagnostics
from tools.tool_manager import ToolManager
from utils.parser import parse_action, ActionExecutor

# Task Management
from agent.task_manager import TaskManager
from agent.task import Task, TaskStatus
from agent.project import Project, ProjectStatus
from agent.task_utils import create_project, get_project_details

# Configuration
from config import (
    TASK_COMPLETION_PHRASE, 
    MAX_TASK_ITERATIONS,
    config,
    DEFAULT_MODEL,
    DEFAULT_PROVIDER
)

# Workspace
from workspace import get_workspace_path, write_workspace_file

logger = logging.getLogger(__name__)

class PenguinCore:
    def __init__(
        self,
        api_client: APIClient,
        tool_manager: ToolManager,
        task_manager: TaskManager
    ):
        """Initialize PenguinCore with required components."""
        print("Initializing PenguinCore...")
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.task_manager = task_manager
        print("Creating ActionExecutor...")
        self.action_executor = ActionExecutor(tool_manager, task_manager)
        print("ActionExecutor created successfully")
        self.messages = []
        
        # Initialize core systems
        self.diagnostics = Diagnostics()
        self.conversation = ConversationSystem(self.tool_manager, self.diagnostics)
        self.cognition = CognitionSystem(
            api_client=self.api_client,
            diagnostics=self.diagnostics
        )
        
        # State
        self.system_prompt = ""
        self.initialized = True
        logger.info("PenguinCore initialized successfully")

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.system_prompt = prompt
        self.api_client.set_system_prompt(prompt)

    def get_system_message(self, current_iteration: Optional[int] = None, 
                          max_iterations: Optional[int] = None) -> str:
        """Get the system message including iteration info if provided."""
        message = self.system_prompt
        if current_iteration is not None and max_iterations is not None:
            message += f"\n\nCurrent iteration: {current_iteration}/{max_iterations}"
        return message

    async def process_input(self, input_data: Dict) -> Tuple[Dict, bool]:
        """
        Process user input through the system pipeline.
        
        Args:
            input_data: Dict containing user input and optional parameters
            
        Returns:
            Tuple[Dict, bool]: Response data and continuation flag
        """
        try:
            # Extract input parameters
            user_input = input_data.get("text", "")
            image_path = input_data.get("image_path")
            current_iteration = input_data.get("iteration")
            max_iterations = input_data.get("max_iterations")
            
            # Prepare conversation context
            self.conversation.prepare_conversation(user_input, image_path)
            
            # Get response through cognition system
            response, exit_flag = await self.cognition.get_response(
                conversation_history=self.conversation.get_history(),
                user_input=user_input,
                image_path=image_path,
                current_iteration=current_iteration,
                max_iterations=max_iterations
            )
            
            # Update conversation with response
            if response.get("assistant_response"):
                self.conversation.add_message(
                    "assistant", 
                    response["assistant_response"]
                )
            
            # Handle any task/project updates
            await self._update_task_progress(response)
            
            return response, exit_flag
            
        except Exception as e:
            await self._handle_error(e, input_data)
            return {"error": str(e)}, True

    async def _handle_error(self, error: Exception, context: Dict):
        """
        Handle and log system errors with detailed information.
        
        Args:
            error (Exception): The exception that occurred
            context (Dict): Context information about when/where the error occurred
        """
        try:
            error_log_dir = get_workspace_path('errors_log')
            os.makedirs(error_log_dir, exist_ok=True)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            error_file = get_workspace_path('errors_log', f"error_{timestamp}.log")
            
            content = f"Error occurred at: {datetime.now()}\n"
            content += f"Context: {json.dumps(context, indent=2)}\n\n"
            content += f"Error type: {type(error).__name__}\n"
            content += f"Error message: {str(error)}\n\n"
            content += "Traceback:\n"
            content += traceback.format_exc()
            
            write_workspace_file(error_file, content)
            logger.error(f"Detailed error log saved to: {error_file}")
            logger.error(f"Error in core processing: {error}")
        except Exception as e:
            logger.error(f"Failed to log error: {str(e)}")

    async def _update_task_progress(self, response: Dict):
        """Update task and project progress based on response."""
        try:
            if "task_update" in response:
                await self.task_manager.update_task(response["task_update"])
            if "project_update" in response:
                await self.task_manager.update_project(response["project_update"])
        except Exception as e:
            logger.error(f"Error updating task progress: {str(e)}")

    # Task and Project Management Interface
    async def create_task(self, description: str):
        """Create a new task."""
        return await self.task_manager.create_task(description)

    async def create_project(self, name: str, description: str):
        """Create a new project."""
        return await self.task_manager.create_project(name, description)

    async def get_response(
        self, 
        user_input: str, 
        image_path: Optional[str] = None,
        current_iteration: Optional[int] = None, 
        max_iterations: Optional[int] = None
    ) -> Tuple[Dict[str, Any], bool]:
        """
        Generate a response to the user input, potentially using an image.
        
        This method is the core interaction point with the AI model. It prepares the conversation,
        sends the request to the API, processes the response including any tool calls or actions,
        and handles task and project progress updates.
        """
        logger.debug(f"Entering get_response. User input: {user_input}, Image path: {image_path}")
        
        try:
            # Prepare conversation context
            self.conversation.prepare_conversation(user_input, image_path)
            
            # Get raw response through cognition system
            response = self.api_client.create_message(
                messages=self.conversation.get_history(),
                max_tokens=None,
                temperature=None
            )
            logger.debug(f"Raw API response: {response}")

            # Handle different response formats based on API type
            if self.api_client.model_config.use_assistants_api:
                if isinstance(response, dict):
                    assistant_response = response.get("assistant_response", "") or str(response)
                else:
                    assistant_response = str(response)
            else:
                assistant_response = response.choices[0].message.content
                
            # Check for task completion
            exit_continuation = TASK_COMPLETION_PHRASE in str(assistant_response)
            
            logger.debug(f"Parsed assistant response: {assistant_response}")
            logger.debug(f"Exit continuation: {exit_continuation}")

            # Parse and execute actions
            actions = parse_action(assistant_response)
            logger.debug(f"Parsed actions: {actions}")

            action_results = []
            for action in actions:
                result = self.action_executor.execute_action(action)
                logger.debug(f"Action executed: {action.action_type.value}, Result: {result}")
                if result is not None:
                    action_results.append({"action": action.action_type.value, "result": str(result)})

            # Construct full response
            full_response = {
                "assistant_response": assistant_response,
                "action_results": action_results
            }
            
            logger.debug(f"Full response: {full_response}")

            # Update conversation with response
            if full_response:
                self.conversation.add_message("assistant", assistant_response)
            
            # Log diagnostics
            self.diagnostics.log_token_usage()
            
            # Update task progress
            await self._update_task_progress(assistant_response)
            
            return full_response, exit_continuation
            
        except Exception as e:
            error_context = f"Error in get_response. User input: {user_input}, Image path: {image_path}, Iteration: {current_iteration}/{max_iterations}"
            await self._handle_error(e, error_context)
            return {
                "assistant_response": "I apologize, but an error occurred. It has been logged for investigation.",
                "action_results": []
            }, False

    def reset_state(self):
        """Reset the conversation state"""
        self.messages = []
        self.api_client.reset()
        self.tool_manager.reset()