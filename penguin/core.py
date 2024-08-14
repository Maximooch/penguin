"""
PenguinCore is a class that manages the core functionality of the Penguin AI assistant.

It handles tasks such as:
- Maintaining the conversation history
- Sending messages to the Claude API and processing the responses
- Managing system prompts and automode iterations
- Handling tool usage and image inputs
- Providing diagnostic logging and token usage tracking

Attributes:
    api_client (ClaudeAPIClient): The API client for interacting with the Claude API.
    tool_manager (ToolManager): The manager for available tools.
    automode (bool): Flag indicating whether automode is enabled.
    system_prompt (str): The system prompt to be sent to Claude.
    system_prompt_sent (bool): Flag indicating whether the system prompt has been sent.
    max_history_length (int): The maximum length of the conversation history to keep.
    conversation_history (List[Dict[str, Any]]): The conversation history.

Methods:
    set_system_prompt(prompt): Sets the system prompt.
    get_system_message(current_iteration, max_iterations): Returns the system message for the current automode iteration.
    add_message(role, content): Adds a message to the conversation history.
    get_history(): Returns the conversation history.
    clear_history(): Clears the conversation history.
    get_last_message(): Returns the last message in the conversation history.
    get_response(user_input, image_path, current_iteration, max_iterations): Sends a message to Claude and processes the response.
    execute_tool(tool_name, tool_input): Executes a tool using the tool manager.
    enable_diagnostics(): Enables diagnostic logging.
    disable_diagnostics(): Disables diagnostic logging.
    reset_state(): Resets the state of PenguinCore.
"""

from typing import List, Optional, Tuple, Dict, Any
from llm.api_client import ClaudeAPIClient
from tools.tool_manager import ToolManager
from config import CONTINUATION_EXIT_PHRASE
from utils.diagnostics import diagnostics, enable_diagnostics, disable_diagnostics
# from tools.support import encode_image_to_base64
# from memory.declarative_memory import DeclarativeMemory
import logging

logger = logging.getLogger(__name__)

class PenguinCore:
    def __init__(self, api_client: ClaudeAPIClient, tool_manager: ToolManager):
        self.api_client = api_client
        self.tool_manager = tool_manager
        self.automode = False
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.max_history_length = 1000
        self.conversation_history: List[Dict[str, Any]] = []
        # Ensure we're using the declarative memory from the tool manager
        # self.declarative_memory = self.tool_manager.declarative_memory

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def get_system_message(self, current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> str:
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        
        declarative_notes = self.tool_manager.declarative_memory_tool.get_notes()
        notes_str = "\n".join([f"{note['category']}: {note['content']}" for note in declarative_notes])
        
        return f"{self.system_prompt}\n\nDeclarative Notes:\n{notes_str}\n\n{automode_status}\n{iteration_info}"
        
    # def add_declarative_note(self, category: str, content: str) -> None:
    #         result = self.tool_manager.add_declarative_note(category, content)
    #         logger.info(f"Declarative note addition result: {result}")

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

    def get_response(self, user_input: str, image_path: Optional[str] = None, 
                 current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
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
        assistant_response = ""
        exit_continuation = False
        
        for content_block in response.content:
            if content_block.type == "text":
                assistant_response += content_block.text
                if CONTINUATION_EXIT_PHRASE in content_block.text:
                    exit_continuation = True
            elif content_block.type == "tool_use":
                self._handle_tool_use(content_block)
        
        if any(content_block.type == "tool_use" for content_block in response.content):
            assistant_response = self._get_final_response()
        
        if assistant_response:
            self.add_message("assistant", assistant_response)
        
        diagnostics.log_token_usage()
        return assistant_response, exit_continuation
    
    # def set_tools(self, tools: List[Dict[str, Any]]) -> None:
    #     self.tool_manager.get_tools(tools)  

    # def set_execute_tool(self, execute_tool_function: callable) -> None:
    #     self.tool_manager.set_execute_tool(execute_tool_function)

    def _handle_tool_use(self, content_block: Any) -> None:
        tool_name = content_block.name
        tool_input = content_block.input
        tool_use_id = content_block.id
        
        result = self.execute_tool(tool_name, tool_input)
        
        self.add_message("assistant", [content_block])
        self.add_message("user", [
            {
                "type": "tool_result",
                "tool_use_id": tool_use_id,
                "content": result if isinstance(result, list) else [{"type": "text", "text": str(result)}]
            }
        ])

    def _get_final_response(self) -> str:
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
        return self.tool_manager.execute_tool(tool_name, tool_input)

    def enable_diagnostics(self) -> None:
        enable_diagnostics()

    # def disable_diagnostics(self) -> None:
    #     disable_diagnostics()

    def reset_state(self) -> None:
        self.automode = False
        self.system_prompt_sent = False
        self.clear_history()
        logger.info("PenguinCore state reset")