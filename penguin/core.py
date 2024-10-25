"""
PenguinCore is the central class that manages the core functionality of the Penguin AI assistant.

This class handles various tasks including:
- Conversation history management
- Interaction with LLM API
- System prompt and automode management
- Tool usage and image input processing
- Diagnostic logging and token usage tracking
- CodeAct action parsing and execution
- Declarative memory management
- Error logging and handling
- Task and project management

Attributes:
    api_client (APIClient): Client for interacting with the AI model.
    tool_manager (ToolManager): Manager for available tools and declarative memory.
    automode (bool): Flag indicating whether automode is enabled.
    system_prompt (str): The system prompt to be sent to the AI model.
    system_prompt_sent (bool): Flag indicating whether the system prompt has been sent.
    max_history_length (int): Maximum length of the conversation history to keep.
    conversation_history (List[Dict[str, Any]]): The conversation history.
    logger (logging.Logger): Logger for the class.
    action_executor (ActionExecutor): Executor for CodeAct actions.
    diagnostics (Diagnostics): Diagnostics utility for token tracking and logging.
    file_manager (FileManager): Manager for file operations.
    current_project (Optional[Project]): The currently active project.

Methods:
    set_system_prompt(prompt: str) -> None
    get_system_message(current_iteration: Optional[int], max_iterations: Optional[int]) -> str
    add_message(role: str, content: Any) -> None
    get_history() -> List[Dict[str, Any]]
    clear_history() -> None
    get_last_message() -> Optional[Dict[str, Any]]
    get_response(user_input: str, image_path: Optional[str], current_iteration: Optional[int], max_iterations: Optional[int]) -> Tuple[str, bool]
    log_error(error: Exception, context: str) -> None
    execute_tool(tool_name: str, tool_input: Any) -> Any
    create_task(description: str) -> Task
    run_task(task: Task) -> None
    get_task_board() -> str
    get_task_by_description(description: str) -> Optional[Task]
    create_project(name: str, description: str) -> Project
    run_project(project: Project) -> None
    complete_project(project_name: str) -> str
    get_project_board() -> str
    get_project_by_name(name: str) -> Optional[Project]
    enable_diagnostics() -> None
    disable_diagnostics() -> None
    reset_state() -> None
"""

# Import necessary modules and types
from typing import List, Optional, Tuple, Dict, Any, Callable
from llm import APIClient
from llm.model_config import ModelConfig

from tools.tool_manager import ToolManager
from utils.parser import parse_action, ActionExecutor

from config import TASK_COMPLETION_PHRASE, MAX_TASK_ITERATIONS
from utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
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
        """
        Initialize PenguinCore with API client and tool manager.
        
        This constructor sets up the core components of the Penguin AI assistant,
        including the API client, tool manager, task manager, and various other
        attributes necessary for its operation.
        
        Args:
            api_client (APIClient): The client used to interact with the AI model.
            tool_manager (ToolManager): The manager for available tools and declarative memory.
        """
        self.os_name = os.name
        # print(f"OS Name: {self.os_name}")  # Add this line for debugging
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.automode = False
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.max_history_length = 1000000
        self.conversation_history: List[Dict[str, Any]] = []
        self.logger = logger
        self.task_manager = TaskManager(self.logger)
        self.action_executor = ActionExecutor(self.tool_manager, self.task_manager)
        self.diagnostics = diagnostics  # Initialize diagnostics
        self.file_manager = FileManager()
        self.current_project: Optional[Project] = None

    def set_system_prompt(self, prompt: str) -> None:
        """
        Set the system prompt and mark it as not sent.
        
        This method updates the system prompt that will be used in conversations
        with the AI model. It also resets the system_prompt_sent flag to ensure
        the new prompt will be sent in the next interaction.
        
        Args:
            prompt (str): The new system prompt to be set.
        """
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def get_system_message(self, current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> str:
        """
        Generate the system message including automode status and declarative notes.
        
        This method constructs a comprehensive system message that includes:
        - The current system prompt
        - Information about the operating system
        - The workspace file structure
        - Declarative notes from memory
        - Automode status
        - Current iteration information (if in automode)
        - Current task and project information
        
        Args:
            current_iteration (Optional[int]): The current iteration number if in automode.
            max_iterations (Optional[int]): The maximum number of iterations if in automode.
        
        Returns:
            str: The complete system message to be sent to the AI model.
        """
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
        
        # Generate file map
        self.logger.debug("Generating file map...")
        file_map = self.tool_manager.file_map.get_formatted_file_map(max_files=50)  # Limit to 50 files for brevity
        self.logger.debug(f"Generated file map: {file_map}")
        system_message = f"{self.system_prompt}\n\n{os_info}\n\nWorkspace Structure:\n{file_map}\n\nDeclarative Notes:\n{notes_str}\n\n{automode_status}\n{iteration_info}"

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
        """
        Add a message to the conversation history.
        
        This method adds a new message to the conversation history. It handles
        different types of content (dict, list, or other) and formats them
        appropriately. If the conversation history exceeds the maximum length,
        the oldest message is removed.
        
        Args:
            role (str): The role of the message sender (e.g., "user", "assistant", "system").
            content (Any): The content of the message, which can be a dict, list, or string.
        """
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
        """
        Return the conversation history.
        
        This method provides access to the full conversation history.
        
        Returns:
            List[Dict[str, Any]]: The complete conversation history.
        """
        return self.conversation_history

    def clear_history(self) -> None:
        """
        Clear the conversation history.
        
        This method resets the conversation history to an empty list.
        """
        self.conversation_history = []

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        """
        Return the last message in the conversation history.
        
        This method retrieves the most recent message from the conversation history.
        If the history is empty, it returns None.
        
        Returns:
            Optional[Dict[str, Any]]: The last message in the conversation history, or None if empty.
        """
        return self.conversation_history[-1] if self.conversation_history else None

    def get_response(self, user_input: str, image_path: Optional[str], 
        current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
        """
        Generate a response to the user input, potentially using an image.
        
        This method is the core interaction point with the AI model. It prepares the conversation,
        sends the request to the API, processes the response including any tool calls or actions,
        and handles task and project progress updates.
        
        Args:
            user_input (str): The input from the user.
            image_path (Optional[str]): Path to an image file, if any.
            current_iteration (Optional[int]): Current iteration number if in automode.
            max_iterations (Optional[int]): Maximum number of iterations if in automode.
        
        Returns:
            Tuple[Dict[str, Any], bool]: A tuple containing the assistant's response and a boolean indicating
                              whether to exit the continuation (True if task completion phrase is present).
        """
        self.logger.debug(f"Entering get_response. User input: {user_input}, Image path: {image_path}")
        try:
            self._prepare_conversation(user_input, image_path)
            
            response = self.api_client.create_message(
                messages=self.get_history(),
                max_tokens=None,
                temperature=None
            )
            self.logger.debug(f"Raw API response: {response}")

            assistant_response = response.choices[0].message.content
            exit_continuation = TASK_COMPLETION_PHRASE in assistant_response
            
            self.logger.debug(f"Parsed assistant response: {assistant_response}")
            self.logger.debug(f"Exit continuation: {exit_continuation}")

            actions = parse_action(assistant_response)
            self.logger.debug(f"Parsed actions: {actions}")

            action_results = []
            for action in actions:
                result = self.action_executor.execute_action(action)
                self.logger.debug(f"Action executed: {action.action_type.value}, Result: {result}")
                if result is not None:
                    action_results.append({"action": action.action_type.value, "result": str(result)})
            
            full_response = {
                "assistant_response": assistant_response,
                "action_results": action_results
            }
            
            self.logger.debug(f"Full response: {full_response}")

            if full_response:
                self.add_message("assistant", assistant_response)
            
            self.diagnostics.log_token_usage()
            
            self._update_task_and_project_progress(assistant_response)
            
            return full_response, exit_continuation
        
        except Exception as e:
            error_context = f"Error in get_response. User input: {user_input}, Image path: {image_path}, Iteration: {current_iteration}/{max_iterations}"
            self.log_error(e, error_context)
            return {"assistant_response": "I'm sorry, an unexpected error occurred. The error has been logged for further investigation. Please try again.", "action_results": []}, False

    def _update_task_and_project_progress(self, assistant_response: str):
        """
        Update the progress of the current task and project based on the assistant's response.
        
        This method parses the assistant's response for indications of task or project completion
        or progress updates, and updates the corresponding task or project accordingly.
        
        Args:
            assistant_response (str): The response from the assistant to analyze for progress indicators.
        """
        current_task = self.task_manager.get_current_task()
        if current_task and current_task.status == TaskStatus.IN_PROGRESS:
            if "task completed" in assistant_response.lower():
                current_task.update_progress(100)
            elif "progress" in assistant_response.lower():
                progress = int(re.search(r'\d+', assistant_response).group())
                current_task.update_progress(progress)
        
        current_project = self.task_manager.get_current_project()
        if current_project and current_project.status == TaskStatus.IN_PROGRESS:
            if "project completed" in assistant_response.lower():
                current_project.update_progress(100)
            elif "project progress" in assistant_response.lower():
                progress = int(re.search(r'\d+', assistant_response).group())
                current_project.update_progress(progress)

    def log_error(self, error: Exception, context: str):
        """
        Log an error with detailed information to a file.
        
        This method creates a detailed error log including the error type, message,
        traceback, and the context in which the error occurred. The log is saved
        to a file in the errors_log directory within the workspace.
        
        Args:
            error (Exception): The exception that occurred.
            context (str): Additional context information about when/where the error occurred.
        """
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


