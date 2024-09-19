"""
PenguinCore is a class that manages the core functionality of the Penguin AI assistant.

It handles tasks such as:
- Maintaining the conversation history
- Sending messages to the LLM API and processing the responses
- Managing system prompts and automode iterations
- Handling tool usage and image inputs
- Providing diagnostic logging and token usage tracking
- Parsing and executing CodeAct actions
- Managing declarative memory
- Error logging and handling

Attributes:
    api_client (APIClient): The API client for interacting with the AI model.
    tool_manager (ToolManager): The manager for available tools and declarative memory.
    automode (bool): Flag indicating whether automode is enabled.
    system_prompt (str): The system prompt to be sent to the AI model.
    system_prompt_sent (bool): Flag indicating whether the system prompt has been sent.
    max_history_length (int): The maximum length of the conversation history to keep.
    conversation_history (List[Dict[str, Any]]): The conversation history.
    logger (logging.Logger): Logger for the class.
    action_executor (ActionExecutor): Executor for CodeAct actions.
    diagnostics (Diagnostics): Diagnostics utility for token tracking and logging.

Methods:
    set_system_prompt(prompt: str) -> None: Sets the system prompt.
    get_system_message(current_iteration: Optional[int], max_iterations: Optional[int]) -> str: Returns the system message for the current automode iteration.
    add_message(role: str, content: Any) -> None: Adds a message to the conversation history.
    get_history() -> List[Dict[str, Any]]: Returns the conversation history.
    clear_history() -> None: Clears the conversation history.
    get_last_message() -> Optional[Dict[str, Any]]: Returns the last message in the conversation history.
    get_response(user_input: str, image_path: Optional[str], current_iteration: Optional[int], max_iterations: Optional[int]) -> Tuple[str, bool]: Sends a message to the AI model and processes the response.
    log_error(error: Exception, context: str) -> None: Logs detailed error information to a file.
    execute_tool(tool_name: str, tool_input: Any) -> Any: Executes a tool using the tool manager.
    run_automode(user_input: str, message_count: int, chat_function: Callable) -> None: Runs the automode functionality.
    enable_diagnostics() -> None: Enables diagnostic logging.
    disable_diagnostics() -> None: Disables diagnostic logging.
    reset_state() -> None: Resets the state of PenguinCore.

Private Methods:
    _prepare_conversation(user_input: str, image_path: Optional[str]) -> None: Prepares the conversation by adding necessary messages.
    _add_image_message(user_input: str, image_path: str) -> None: Adds an image message to the conversation.
    _handle_tool_use(tool_call: Any) -> str: Handles tool use requests from the AI model.
    _get_final_response() -> str: Gets a final response from the AI model after tool use.
"""


# Import necessary modules and types
from typing import List, Optional, Tuple, Dict, Any, Callable
from llm import APIClient
from llm.model_config import ModelConfig

from tools.tool_manager import ToolManager
from utils.parser import parse_action, ActionExecutor


from config import TASK_COMPLETION_PHRASE, MAX_TASK_ITERATIONS
from utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
# from agent.automode import Automode
from agent.task_manager import TaskManager
from agent.task import Task, TaskStatus
from agent.project import Project, ProjectStatus
from system.file_manager import FileManager
import logging
import os
import traceback
from datetime import datetime
from config import Config
import json
import re
from workspace import get_workspace_path, write_workspace_file
from agent.task_utils import create_project, get_project_details

# Set up logging
logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)

class PenguinCore:
    def __init__(self, api_client: APIClient, tool_manager: ToolManager):
        # Initialize PenguinCore with API client and tool manager
        self.os_name = os.name
        # print(f"OS Name: {self.os_name}")  # Add this line for debugging
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.automode = False
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.max_history_length = 1000
        self.conversation_history: List[Dict[str, Any]] = []
        self.logger = logger
        self.task_manager = TaskManager(self.logger)
        self.action_executor = ActionExecutor(self.tool_manager, self.task_manager)
        self.diagnostics = diagnostics  # Initialize diagnostics
        self.file_manager = FileManager()
        self.current_project: Optional[Project] = None
        

    def set_system_prompt(self, prompt: str) -> None:
        # Set the system prompt and mark it as not sent
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def get_system_message(self, current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> str:
        # Generate the system message including automode status and declarative notes
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        
        self.logger.debug("Fetching declarative notes...")
        declarative_notes = self.tool_manager.declarative_memory_tool.get_notes()
        self.logger.debug(f"Fetched declarative notes: {declarative_notes}")
        
        notes_str = "\n".join([f"{note['category']}: {note['content']}" for note in declarative_notes])
        self.logger.debug(f"Formatted notes string: {notes_str}")
        
        os_info = f"You are running on {self.os_name}, use the appropriate commands for your OS."
        # print(f"Debug - OS Info: {os_info}")  # Add this line for debugging
        
        system_message = f"{self.system_prompt}\n\n{os_info}\n\nDeclarative Notes:\n{notes_str}\n\n{automode_status}\n{iteration_info}"
        self.logger.debug(f"Generated system message: {system_message}")
        
        # print(f"Debug - Full System Message:\n{system_message}")  # Add this line for debugging
        
        current_task = self.task_manager.get_current_task()
        if current_task:
            task_info = f"Current Task: {current_task.description} - Status: {current_task.status.value} - Progress: {current_task.progress}%"
            system_message += f"\n\n{task_info}"
        else:
            system_message += "\n\nNo current task."

        current_project = self.task_manager.get_current_project()
        if current_project:
            project_info = f"Current Project: {current_project.name} - Status: {current_project.status.value} - Progress: {current_project.progress:.2f}%"
        else:
            project_info = "No current project."
        system_message += f"\n\nCurrent Project Information:\n{project_info}"

        return system_message

    def add_message(self, role: str, content: Any) -> None:
        # Add a message to the conversation history
        if isinstance(content, dict):
            message = {"role": role, "content": [content]}
        elif isinstance(content, list):
            message = {"role": role, "content": content}
        else:
            message = {"role": role, "content": [{"type": "text", "text": str(content)}]}
        self.conversation_history.append(message)
        if len(self.conversation_history) > self.max_history_length:
            self.conversation_history.pop(0)

    def get_history(self) -> List[Dict[str, Any]]:
        # Return the conversation history
        return self.conversation_history

    def clear_history(self) -> None:
        # Clear the conversation history
        self.conversation_history = []

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        # Return the last message in the conversation history
        return self.conversation_history[-1] if self.conversation_history else None

    def get_response(self, user_input: str, image_path: Optional[str] = None, 
                    current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
        try:
            self._prepare_conversation(user_input, image_path)
            
            # Add this line to include OS info in each API call
            self.add_message("system", f"You are running on {self.os_name}, use the appropriate commands for your OS.")
            
            # Construct and send API request
            response = self.api_client.create_message(
                messages=self.get_history(),
                max_tokens=None,
                temperature=None
            )
            
            # Process the response
            assistant_response = response.choices[0].message.content
            exit_continuation = TASK_COMPLETION_PHRASE in assistant_response
            
            # Parse and execute CodeAct actions
            actions = parse_action(assistant_response)
            for action in actions:
                result = self.action_executor.execute_action(action)
                assistant_response += f"\n{result}"
            
            # Handle tool use if present in the response
            if hasattr(response.choices[0].message, 'tool_calls'):
                for tool_call in response.choices[0].message.tool_calls:
                    tool_result = self._handle_tool_use(tool_call)
                    assistant_response += f"\n{tool_result}"
                
                # Get final response after tool use
                final_response = self._get_final_response()
                assistant_response += f"\n{final_response}"
            
            if assistant_response:
                self.add_message("assistant", assistant_response)
            
            self.diagnostics.log_token_usage()
            
            current_task = self.task_manager.get_current_task()
            if current_task and current_task.status == TaskStatus.IN_PROGRESS:
                # Update task progress based on the response
                # This is a simple implementation and can be improved
                if "task completed" in assistant_response.lower():
                    current_task.update_progress(100)
                elif "progress" in assistant_response.lower():
                    # Extract progress percentage from the response
                    # This is a naive implementation and should be improved
                    progress = int(re.search(r'\d+', assistant_response).group())
                    current_task.update_progress(progress)
            
            current_project = self.task_manager.get_current_project()
            if current_project and current_project.status == TaskStatus.IN_PROGRESS:
                # Update project progress based on the response
                if "project completed" in assistant_response.lower():
                    current_project.update_progress(100)
                elif "project progress" in assistant_response.lower():
                    # Extract progress percentage from the response
                    progress = int(re.search(r'\d+', assistant_response).group())
                    current_project.update_progress(progress)
            
            return assistant_response, exit_continuation
        
        except AttributeError as e:
            error_context = f"Error in response structure: {str(e)}"
            self.log_error(e, error_context)
            return "I'm having trouble understanding the AI's response. This issue has been logged for investigation. Could you please rephrase your question?", False
        except Exception as e:
            error_context = f"Error in get_response. User input: {user_input}, Image path: {image_path}, Iteration: {current_iteration}/{max_iterations}"
            self.log_error(e, error_context)
            return "I'm sorry, an unexpected error occurred. The error has been logged for further investigation. Please try again.", False

    def log_error(self, error: Exception, context: str):
        error_log_dir = get_workspace_path('errors_log')
        os.makedirs(error_log_dir, exist_ok=True)
        
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        error_file = get_workspace_path('errors_log', f"error_{timestamp}.log")
        
        content = f"Error occurred at: {datetime.now()}\n"
        content += f"Context: {context}\n\n"
        content += f"Error type: {type(error).__name__}\n"
        content += f"Error message: {str(error)}\n\n"
        content += "Traceback:\n"
        content += traceback.format_exc()
        
        write_workspace_file(error_file, content)
        
        self.logger.error(f"Detailed error log saved to: {error_file}")
        
    
    def _prepare_conversation(self, user_input: str, image_path: Optional[str]) -> None:
        # Prepare the conversation by adding necessary messages
        if self.get_history() and self.get_last_message()["role"] == "user":
            self.add_message("assistant", {"type": "text", "text": "Continuing the conversation..."})

        if not self.system_prompt_sent:
            system_message = self.get_system_message()
            system_tokens = self.diagnostics.count_tokens(system_message)  # Use diagnostics to count tokens
            self.diagnostics.update_tokens('system_prompt', system_tokens, 0)
            self.system_prompt_sent = True

        if image_path:
            self._add_image_message(user_input, image_path)
        else:
            self.add_message("user", {"type": "text", "text": user_input})

    def _add_image_message(self, user_input: str, image_path: str) -> None:
        # Add an image message to the conversation
        try:
            base64_image = self.tool_manager.encode_image(image_path)
            image_message = [
                {"type": "text", "text": user_input},
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": "image/jpeg",
                        "data": base64_image
                    }
                }
            ]
            self.add_message("user", image_message)
            logger.info("Image message added to conversation history")
        except Exception as e:
            logger.error(f"Error adding image message: {str(e)}")
            raise

    def _handle_tool_use(self, tool_call: Any) -> str:
        tool_name = tool_call.function.name
        tool_input = tool_call.function.arguments
        tool_use_id = tool_call.id
        
        try:
            result = self.tool_manager.execute_tool(tool_name, tool_input)
            self.add_message("assistant", [{"type": "function", "function": tool_call.function}])
            
            if isinstance(result, dict):
                result_content = [{"type": "text", "text": json.dumps(result, indent=2)}]
            elif isinstance(result, list):
                result_content = [{"type": "text", "text": json.dumps(item) if isinstance(item, dict) else str(item)} for item in result]
            else:
                result_content = [{"type": "text", "text": str(result)}]
            
            self.add_message("user", [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result_content
                }
            ])
            return f"Tool Used: {tool_name}\nTool Input: {tool_input}\nTool Result: {json.dumps(result, indent=2)}"
        except Exception as e:
            error_message = f"Error handling tool use '{tool_name}': {str(e)}"
            self.logger.error(error_message)
            return error_message

    def _get_final_response(self) -> str:
        try:
            final_response = self.api_client.create_message(
                messages=self.get_history(),
                max_tokens=None,
                temperature=None
            )
            return final_response.choices[0].message.content
        except Exception as e:
            self.logger.error(f"Error in final response: {str(e)}")
            return "\nI encountered an error while processing the tool results. Please try again."

    def execute_tool(self, tool_name: str, tool_input: Any) -> Any:
        if tool_name == "execute_command":
            return self.file_manager.execute_command(tool_input)
        return self.tool_manager.execute_tool(tool_name, tool_input)

    def create_task(self, description: str) -> Task:
        return self.task_manager.create_task(description)

    def run_task(self, task: Task) -> None:
        self.task_manager.run_task(task, self.get_response)

    def get_task_board(self) -> str:
        return self.task_manager.get_task_board()

    def get_task_by_description(self, description: str) -> Optional[Task]:
        return self.task_manager.get_task_by_description(description)

    def create_project(self, name: str, description: str) -> Project:
        return self.task_manager.create_project(name, description)

    def run_project(self, project: Project) -> None:
        self.task_manager.run_project(project, self.get_response)

    def complete_project(self, project_name: str) -> str:
        return self.task_manager.complete_project(project_name)

    def get_project_board(self) -> str:
        return self.task_manager.get_project_board()

    def get_project_by_name(self, name: str) -> Optional[Project]:
        return self.task_manager.get_project_by_name(name)

    def enable_diagnostics(self) -> None:
        from config import Config
        Config.enable_feature('DIAGNOSTICS_ENABLED')
        enable_diagnostics()
        self.logger.info("Diagnostics enabled")

    def disable_diagnostics(self) -> None:
        from config import Config
        Config.disable_feature('DIAGNOSTICS_ENABLED')
        disable_diagnostics()
        self.logger.info("Diagnostics disabled")

    def reset_state(self) -> None:
        # Reset the state of PenguinCore
        # This method is typically called after automode or when a fresh start is needed
        self.automode = False
        self.system_prompt_sent = False
        self.clear_history()
        self.task_manager = TaskManager(self.logger)
        self.file_manager = FileManager()
        logger.info("PenguinCore state reset")