"""
ChatManager is a class that manages the conversation with the Claude AI model.

It handles tasks such as:
- Maintaining the conversation history
- Sending messages to the Claude API and processing the responses
- Managing system prompts and automode iterations
- Handling tool usage and image inputs
- Providing diagnostic logging and token usage tracking

Attributes:
    api_client (ClaudeAPIClient): The API client for interacting with the Claude API.
    automode (bool): Flag indicating whether automode is enabled.
    system_prompt (str): The system prompt to be sent to Claude.
    tools (List[Dict[str, Any]]): A list of available tools.
    execute_tool (callable): A function to execute a tool.
    system_prompt_sent (bool): Flag indicating whether the system prompt has been sent.
    max_history_length (int): The maximum length of the conversation history to keep.
    conversation_history (List[Dict[str, Any]]): The conversation history.

Methods:
    get_system_message(current_iteration, max_iterations): Returns the system message for the current automode iteration.
    _update_system_prompt(current_iteration, max_iterations): Updates the system prompt with automode and iteration information.
    _get_dynamic_updates(current_iteration, max_iterations): Returns dynamic updates for the system message based on automode and iteration.
    add_message(role, content): Adds a message to the conversation history.
    get_history(): Returns the conversation history.
    clear_history(): Clears the conversation history.
    get_last_message(): Returns the last message in the conversation history.
    chat_with_claude(user_input, message_count, image_path, current_iteration, max_iterations): Sends a message to Claude and processes the response.
    _prepare_conversation(user_input, image_path): Prepares the conversation history for the next message.
    _add_image_message(user_input, image_path): Adds an image message to the conversation history.
    _get_claude_response(current_iteration, max_iterations): Sends a request to the Claude API and returns the response.
    _process_response(response, message_count): Processes the response from Claude, handling tool usage and continuation.
    _handle_tool_use(content_block, message_count): Handles a tool use by executing the tool and updating the conversation history.
    _get_final_response(message_count): Gets the final response from Claude after processing tool results.
    set_system_prompt(prompt): Sets the system prompt.
    set_tools(tools): Sets the list of available tools.
    set_execute_tool(execute_tool_function): Sets the function to execute a tool.
    enable_diagnostics(): Enables diagnostic logging.
    disable_diagnostics(): Disables diagnostic logging.
    reset_state(): Resets the state of the ChatManager.
    print_colored(text, color): Prints text with the specified color.
"""

from typing import List, Optional, Tuple, Dict, Any
from colorama import Fore, Style
from llm.api_client import ClaudeAPIClient
# from memory import ConversationMemory
from config import CONTINUATION_EXIT_PHRASE, TOOL_COLOR
from .ui import process_and_display_response
from tools.support import encode_image_to_base64
from .diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
import logging

logger = logging.getLogger(__name__)

class ChatManager:
    def __init__(self, api_client: ClaudeAPIClient):
        self.api_client = api_client
        # self.memory = memory
        self.automode = False
        self.system_prompt = ""
        self.tools: List[Dict[str, Any]] = []
        self.execute_tool = None
        self.system_prompt_sent = False
        self.max_history_length = 1000
        self.conversation_history: List[Dict[str, Any]] = []

    # System Prompts
    def get_system_message(self, current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> str:
        if not self.system_prompt_sent:
            full_prompt = self._update_system_prompt(current_iteration, max_iterations)
            self.system_prompt_sent = True
            return full_prompt
        else:
            return self._get_dynamic_updates(current_iteration, max_iterations)

    def _update_system_prompt(self, current_iteration: Optional[int], max_iterations: Optional[int]) -> str:
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        return self.system_prompt.format(automode_status=automode_status, iteration_info=iteration_info)

    def _get_dynamic_updates(self, current_iteration: Optional[int], max_iterations: Optional[int]) -> str:
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        return f"{automode_status} {iteration_info}".strip()

    # Conversation History
    def add_message(self, role: str, content: Any) -> None:
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
        return self.conversation_history
    
    def clear_history(self) -> None:
        self.conversation_history = []

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        return self.conversation_history[-1] if self.conversation_history else None

    # Chatting with Claude
    def chat_with_claude(self, user_input: str, message_count: int, image_path: Optional[str] = None, 
        current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
        try:
            self._prepare_conversation(user_input, image_path)
            response = self._get_claude_response(current_iteration, max_iterations)
            return self._process_response(response, message_count)
        except Exception as e:
            logger.error(f"Error in chat_with_claude: {str(e)}")
            return "I'm sorry, an error occurred. Please try again.", False

    def _prepare_conversation(self, user_input: str, image_path: Optional[str]) -> None:
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
        logger.info(f"Processing image at path: {image_path}")
        image_base64 = encode_image_to_base64(image_path)
        
        if image_base64.startswith("Error"):
            logger.error(f"Error encoding image: {image_base64}")
            raise ValueError("Error processing image")
        
        image_message = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": image_base64
                }
            },
            {
                "type": "text",
                "text": user_input
            }
        ]
        self.add_message("user", image_message)
        logger.info("Image message added to conversation history")

    def _get_claude_response(self, current_iteration: Optional[int], max_iterations: Optional[int]) -> Any:
        try:
            response = self.api_client.create_message(
                model=self.api_client.model_config.model,
                max_tokens=self.api_client.model_config.max_tokens,
                system=self.get_system_message(current_iteration, max_iterations),
                messages=self.get_history(),
                tools=self.tools,
                tool_choice={"type": "auto"}
            )
            diagnostics.update_tokens('main_model', response.usage.input_tokens, response.usage.output_tokens)
            return response
        except Exception as e:
            logger.error(f"Error calling Claude API: {str(e)}")
            raise

    def _process_response(self, response: Any, message_count: int) -> Tuple[str, bool]:
        assistant_response = ""
        exit_continuation = False
        
        for content_block in response.content:
            if content_block.type == "text":
                assistant_response += content_block.text
                if CONTINUATION_EXIT_PHRASE in content_block.text:
                    exit_continuation = True
            elif content_block.type == "tool_use":
                self._handle_tool_use(content_block, message_count)
        
        if any(content_block.type == "tool_use" for content_block in response.content):
            assistant_response = self._get_final_response(message_count)
        
        if assistant_response:
            self.add_message("assistant", assistant_response)
        
        diagnostics.log_token_usage()
        return assistant_response, exit_continuation

    def _handle_tool_use(self, content_block: Any, message_count: int) -> None:
        tool_name = content_block.name
        tool_input = content_block.input
        tool_use_id = content_block.id
        
        result = self.execute_tool(tool_name, tool_input)
        
        tool_output = f"Tool Used: {tool_name}\nTool Input: {tool_input}\nTool Result: {result}"
        process_and_display_response(tool_output, message_count)
        
        self.add_message("assistant", [content_block])
        self.add_message("user", [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result
            }
        ])

    def _get_final_response(self, message_count: int) -> str:
        try:
            final_response = self.api_client.create_message(
                model=self.api_client.model_config.model,
                max_tokens=self.api_client.model_config.max_tokens,
                system=self.get_system_message(),
                messages=self.get_history(),
                tools=self.tools,
                tool_choice={"type": "auto"}
            )
            diagnostics.update_tokens('tool_checker', final_response.usage.input_tokens, final_response.usage.output_tokens)
            return "".join(block.text for block in final_response.content if block.type == "text")
        except Exception as e:
            logger.error(f"Error in final response: {str(e)}")
            return "\nI encountered an error while processing the tool results. Please try again."

    # Utilities
    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt 
        self.system_prompt_sent = False

    def set_tools(self, tools: List[Dict[str, Any]]) -> None:
        self.tools = tools

    def set_execute_tool(self, execute_tool_function: callable) -> None:
        self.execute_tool = execute_tool_function

    def enable_diagnostics(self) -> None:
        enable_diagnostics()

    def disable_diagnostics(self) -> None:
        disable_diagnostics()

    def reset_state(self) -> None:
        self.automode = False
        self.system_prompt_sent = False
        self.clear_history()
        logger.info("ChatManager state reset")

    def print_colored(self, text: str, color: str) -> None:
        print(f"{color}{text}{Style.RESET_ALL}")

