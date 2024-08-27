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

Attributes:
    api_client (ClaudeAPIClient): The API client for interacting with the Claude API.
    tool_manager (ToolManager): The manager for available tools and declarative memory.
    automode (bool): Flag indicating whether automode is enabled.
    system_prompt (str): The system prompt to be sent to Claude.
    system_prompt_sent (bool): Flag indicating whether the system prompt has been sent.
    max_history_length (int): The maximum length of the conversation history to keep.
    conversation_history (List[Dict[str, Any]]): The conversation history.
    logger (logging.Logger): Logger for the class.

Methods:
    set_system_prompt(prompt: str) -> None: Sets the system prompt.
    get_system_message(current_iteration: Optional[int], max_iterations: Optional[int]) -> str: Returns the system message for the current automode iteration.
    add_message(role: str, content: Any) -> None: Adds a message to the conversation history.
    get_history() -> List[Dict[str, Any]]: Returns the conversation history.
    clear_history() -> None: Clears the conversation history.
    get_last_message() -> Optional[Dict[str, Any]]: Returns the last message in the conversation history.
    get_response(user_input: str, image_path: Optional[str], current_iteration: Optional[int], max_iterations: Optional[int]) -> Tuple[str, bool]: Sends a message to Claude and processes the response.
    execute_tool(tool_name: str, tool_input: Any) -> Any: Executes a tool using the tool manager.
    run_automode(user_input: str, message_count: int, chat_function: Callable) -> None: Runs the automode functionality.
    disable_diagnostics() -> None: Disables diagnostic logging.
    reset_state() -> None: Resets the state of PenguinCore.
"""

# Import necessary modules and types
from typing import List, Optional, Tuple, Dict, Any, Callable
from llm.api_client import ClaudeAPIClient
from tools.tool_manager import ToolManager
from utils.parser import parse_action, ActionExecutor

from config import CONTINUATION_EXIT_PHRASE, MAX_CONTINUATION_ITERATIONS
from utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
from agent.automode import Automode
import logging

# Set up logging
logger = logging.getLogger(__name__)

class PenguinCore:
    def __init__(self, api_client: ClaudeAPIClient, tool_manager: ToolManager):
        # Initialize PenguinCore with API client and tool manager
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.automode = False
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.max_history_length = 1000
        self.conversation_history: List[Dict[str, Any]] = []
        self.logger = logger
        self.action_executor = ActionExecutor(self.tool_manager)

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
        
        declarative_notes = self.tool_manager.declarative_memory_tool.get_notes()
        notes_str = "\n".join([f"{note['category']}: {note['content']}" for note in declarative_notes])
        
        return f"{self.system_prompt}\n\nDeclarative Notes:\n{notes_str}\n\n{automode_status}\n{iteration_info}"

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
        # High-level method to get a response from the AI model
        # This method orchestrates the entire response process, including:
        # 1. Preparing the conversation
        # 2. Getting the AI response
        # 3. Processing the response (including handling tool use and CodeAct actions)
        # 4. Handling any errors that occur during the process
        try:
            self._prepare_conversation(user_input, image_path)
            response = self._get_ai_response(current_iteration, max_iterations)
            return self._process_response(response)
        except Exception as e:
            logger.error(f"Error in get_response: {str(e)}")
            if "declarative memory" in str(e).lower():
                return "I encountered an issue with my memory. I'll do my best to continue our conversation without it.", False
            return "I'm sorry, an error occurred. Please try again.", False
    
        
    
    def _prepare_conversation(self, user_input: str, image_path: Optional[str]) -> None:
        # Prepare the conversation by adding necessary messages
        if self.get_history() and self.get_last_message()["role"] == "user":
            self.add_message("assistant", {"type": "text", "text": "Continuing the conversation..."})

        if not self.system_prompt_sent:
            system_message = self.get_system_message()
            system_tokens = self.api_client.count_tokens(system_message)
            diagnostics.update_tokens('system_prompt', system_tokens, 0)
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

    def _get_ai_response(self, current_iteration: Optional[int], max_iterations: Optional[int]) -> Any:
        # Low-level method to directly interact with the AI model
        # This method is responsible for:
        # 1. Constructing the API request with the current conversation state
        # 2. Sending the request to the AI model
        # 3. Receiving and returning the raw response from the model
        try:
            response = self.api_client.create_message(
                model=self.api_client.model_config.model,
                max_tokens=self.api_client.model_config.max_tokens,
                system=self.get_system_message(current_iteration, max_iterations),
                messages=self.get_history(),
                tools=self.tool_manager.get_tools(),
                tool_choice={"type": "auto"}
            )
            diagnostics.update_tokens('main_model', response.usage.input_tokens, response.usage.output_tokens)
            return response
        except Exception as e:
            logger.error(f"Error calling LLM API: {str(e)}")
            raise

    def _process_response(self, response: Any) -> Tuple[str, bool]:
        # Process the AI model's response
        # This method handles:
        # 1. Extracting text content from the response
        # 2. Checking for continuation exit phrases
        # 3. Parsing and executing CodeAct actions
        # 4. Handling tool use requests
        # 5. Compiling the final assistant response
        assistant_response = ""
        exit_continuation = False
        actions_to_execute = []
        
        try:
            for content_block in response.content:
                if content_block.type == "text":
                    assistant_response += content_block.text
                    if CONTINUATION_EXIT_PHRASE in content_block.text:
                        exit_continuation = True
                    
                    # Parse CodeAct actions
                    actions = parse_action(content_block.text)
                    actions_to_execute.extend(actions)
                
                elif content_block.type == "tool_use":
                    # Handle tool use directly
                    tool_result = self._handle_tool_use(content_block)
                    assistant_response += f"\n{tool_result}"
            
            # Execute all CodeAct actions
            for action in actions_to_execute:
                result = self.action_executor.execute_action(action)
                assistant_response += f"\n{result}"
            
            if assistant_response:
                self.add_message("assistant", assistant_response)
            
            diagnostics.log_token_usage()
            return assistant_response, exit_continuation
        except Exception as e:
            logger.error(f"Error processing response: {str(e)}")
            return f"An error occurred while processing the response: {str(e)}", False

    def _handle_tool_use(self, content_block: Any) -> str:
        # Handle tool use requests from the AI model
        tool_name = content_block.name
        tool_input = content_block.input
        tool_use_id = content_block.id
        
        try:
            result = self.tool_manager.execute_tool(tool_name, tool_input)
            self.add_message("assistant", [content_block])
            self.add_message("user", [
                {
                    "type": "tool_result",
                    "tool_use_id": tool_use_id,
                    "content": result if isinstance(result, list) else [{"type": "text", "text": str(result)}]
                }
            ])
            return f"Tool Used: {tool_name}\nTool Input: {tool_input}\nTool Result: {result}"
        except Exception as e:
            error_message = f"Error handling tool use '{tool_name}': {str(e)}"
            logger.error(error_message)
            return error_message


    def _get_final_response(self) -> str:
        # Get a final response from the AI model after tool use
        # This method is similar to _get_ai_response, but is specifically used
        # after tool use to get a final, summarized response from the model
        try:
            final_response = self.api_client.create_message(
                model=self.api_client.model_config.model,
                max_tokens=self.api_client.model_config.max_tokens,
                system=self.get_system_message(),
                messages=self.get_history(),
                tools=self.tool_manager.get_tools(),
                tool_choice={"type": "auto"}
            )
            diagnostics.update_tokens('tool_checker', final_response.usage.input_tokens, final_response.usage.output_tokens)
            return "".join(block.text for block in final_response.content if block.type == "text")
        except Exception as e:
            logger.error(f"Error in final response: {str(e)}")
            return "\nI encountered an error while processing the tool results. Please try again."

    def execute_tool(self, tool_name: str, tool_input: Any) -> Any:
        # Execute a tool using the tool manager
        # This is a public method that allows direct tool execution
        return self.tool_manager.execute_tool(tool_name, tool_input)

    def run_automode(self, user_input: str, message_count: int, chat_function: Callable) -> None:
        # Run the automode functionality
        # This method initiates the automode process, which allows for
        # multiple iterations of conversation without user intervention
        automode = Automode(self.logger, MAX_CONTINUATION_ITERATIONS)
        automode.start(user_input, message_count, chat_function)
        self.reset_state()


    # def enable_diagnostics(self) -> None:
    #     enable_diagnostics()

    def disable_diagnostics(self) -> None:
        # Disable diagnostic logging
        disable_diagnostics()

    def reset_state(self) -> None:
        # Reset the state of PenguinCore
        # This method is typically called after automode or when a fresh start is needed
        self.automode = False
        self.system_prompt_sent = False
        self.clear_history()
        logger.info("PenguinCore state reset")