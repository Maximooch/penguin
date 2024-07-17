from colorama import Fore, Style
from llm.api_client import ClaudeAPIClient
from memory import ConversationMemory
from config import (
    CONTINUATION_EXIT_PHRASE,
    USER_COLOR,
    CLAUDE_COLOR,
    TOOL_COLOR,
    RESULT_COLOR
)
from .ui import process_and_display_response
from tools.support import encode_image_to_base64

class ChatManager:
    def __init__(self, api_client: ClaudeAPIClient, memory: ConversationMemory):
        self.api_client = api_client
        self.memory = memory
        self.automode = False
        self.system_prompt = ""
        self.tools = []
        self.execute_tool = None
        self.system_prompt_sent = False

    def get_system_message(self, current_iteration=None, max_iterations=None):
        if not self.system_prompt_sent:
            full_prompt = self.update_system_prompt(current_iteration, max_iterations)
            self.system_prompt_sent = True
            return full_prompt
        else:
            return self.get_dynamic_updates(current_iteration, max_iterations)

    def update_system_prompt(self, current_iteration=None, max_iterations=None):
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        return self.system_prompt.format(automode_status=automode_status, iteration_info=iteration_info)

    def get_dynamic_updates(self, current_iteration=None, max_iterations=None):
        automode_status = "You are currently in automode." if self.automode else "You are not in automode."
        iteration_info = ""
        if current_iteration is not None and max_iterations is not None:
            iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
        return f"{automode_status} {iteration_info}".strip()

    def print_colored(self, text, color):
        print(f"{color}{text}{Style.RESET_ALL}")

    def chat_with_claude(self, user_input, message_count, image_path=None, current_iteration=None, max_iterations=None):
        if self.memory.get_history() and self.memory.get_last_message()["role"] == "user":
            self.memory.add_assistant_message("Continuing the conversation...")

        if image_path:
            self.print_colored(f"Processing image at path: {image_path}", TOOL_COLOR)
            image_base64 = encode_image_to_base64(image_path)
            
            if image_base64.startswith("Error"):
                self.print_colored(f"Error encoding image: {image_base64}", TOOL_COLOR)
                return "I'm sorry, there was an error processing the image. Please try again.", False
            
            image_message = {
                "role": "user",
                "content": [
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
                        "text": f"User input for image: {user_input}"
                    }
                ]
            }
            self.memory.add_message(image_message)
            self.print_colored("Image message added to conversation history", TOOL_COLOR)
        else:
            self.memory.add_user_message(user_input)
            
        messages = self.memory.get_history()

        try:
            response = self.api_client.create_message(
                model=self.api_client.model_config.model,
                max_tokens=self.api_client.model_config.max_tokens,
                system=self.get_system_message(current_iteration, max_iterations),
                messages=messages,
                tools=self.tools,
                tool_choice={"type": "auto"}
            )
        except Exception as e:
            self.print_colored(f"Error calling Claude API: {str(e)}", TOOL_COLOR)
            return "I'm sorry, there was an error communicating with the AI. Please try again.", False
        
        assistant_response = ""
        exit_continuation = False
        
        for content_block in response.content:
            if content_block.type == "text":
                assistant_response += content_block.text
                if CONTINUATION_EXIT_PHRASE in content_block.text:
                    exit_continuation = True
            elif content_block.type == "tool_use":
                tool_name = content_block.name
                tool_input = content_block.input
                tool_use_id = content_block.id
                
                result = self.execute_tool(tool_name, tool_input)
                
                tool_output = f"Tool Used: {tool_name}\nTool Input: {tool_input}\nTool Result: {result}"
                process_and_display_response(tool_output, message_count)
                
                self.memory.add_assistant_message([content_block])
                self.memory.add_user_message([
                    {
                        "type": "tool_result",
                        "tool_use_id": tool_use_id,
                        "content": result
                    }
                ])
        
        if any(content_block.type == "tool_use" for content_block in response.content):
            try:
                final_response = self.api_client.create_message(
                    model=self.api_client.model_config.model,
                    max_tokens=self.api_client.model_config.max_tokens,
                    system=self.get_system_message(current_iteration, max_iterations),
                    messages=self.memory.get_history(),
                    tools=self.tools,
                    tool_choice={"type": "auto"}
                )
                assistant_response = "".join(block.text for block in final_response.content if block.type == "text")
            except Exception as e:
                self.print_colored(f"Error in final response: {str(e)}", TOOL_COLOR)
                assistant_response += "\nI encountered an error while processing the tool results. Please try again."
        
        if assistant_response:
            self.memory.add_assistant_message(assistant_response)
        
        return assistant_response, exit_continuation

    def set_system_prompt(self, prompt):
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def set_tools(self, tools):
        self.tools = tools

    def set_execute_tool(self, execute_tool_function):
        self.execute_tool = execute_tool_function


# from colorama import Fore, Style
# from llm.api_client import ClaudeAPIClient
# from memory import ConversationMemory
# from config import (
#     CONTINUATION_EXIT_PHRASE,
#     USER_COLOR,
#     CLAUDE_COLOR,
#     TOOL_COLOR,
#     RESULT_COLOR
# )
# from tools.support import encode_image_to_base64

# class ChatManager:
#     def __init__(self, api_client: ClaudeAPIClient, memory: ConversationMemory):
#         self.api_client = api_client
#         self.memory = memory
#         self.automode = False
#         self.system_prompt = ""
#         self.tools = []
#         self.execute_tool = None

#     def update_system_prompt(self, current_iteration=None, max_iterations=None):
#         automode_status = "You are currently in automode." if self.automode else "You are not in automode."
#         iteration_info = ""
#         if current_iteration is not None and max_iterations is not None:
#             iteration_info = f"You are currently on iteration {current_iteration} out of {max_iterations} in automode."
#         return self.system_prompt.format(automode_status=automode_status, iteration_info=iteration_info)

#     def print_colored(self, text, color):
#         print(f"{color}{text}{Style.RESET_ALL}")

#     def chat_with_claude(self, user_input, image_path=None, current_iteration=None, max_iterations=None):
#         # Ensure the last message in the history is from the assistant before adding a new user message
#         if self.memory.get_history() and self.memory.get_last_message()["role"] == "user":
#             self.memory.add_assistant_message("Continuing the conversation...")

#         if image_path:
#             self.print_colored(f"Processing image at path: {image_path}", TOOL_COLOR)
#             image_base64 = encode_image_to_base64(image_path)
            
#             if image_base64.startswith("Error"):
#                 self.print_colored(f"Error encoding image: {image_base64}", TOOL_COLOR)
#                 return "I'm sorry, there was an error processing the image. Please try again.", False
            
#             image_message = {
#                 "role": "user",
#                 "content": [
#                     {
#                         "type": "image",
#                         "source": {
#                             "type": "base64",
#                             "media_type": "image/jpeg",
#                             "data": image_base64
#                         }
#                     },
#                     {
#                         "type": "text",
#                         "text": f"User input for image: {user_input}"
#                     }
#                 ]
#             }
#             self.memory.add_message(image_message)
#             self.print_colored("Image message added to conversation history", TOOL_COLOR)
#         else:
#             self.memory.add_user_message(user_input)
            
#             messages = self.memory.get_history()

#             try:
#                 response = self.api_client.create_message(
#                     model=self.api_client.model_config.model,
#                     max_tokens=self.api_client.model_config.max_tokens,
#                     system=self.update_system_prompt(current_iteration, max_iterations),
#                     messages=messages,
#                     tools=self.tools,
#                     tool_choice={"type": "auto"}
#                 )
#             except Exception as e:
#                 self.print_colored(f"Error calling Claude API: {str(e)}", TOOL_COLOR)
#                 return "I'm sorry, there was an error communicating with the AI. Please try again.", False
            
#             assistant_response = ""
#             exit_continuation = False
            
#             for content_block in response.content:
#                 if content_block.type == "text":
#                     assistant_response += content_block.text
#                     if CONTINUATION_EXIT_PHRASE in content_block.text:
#                         exit_continuation = True
#                 elif content_block.type == "tool_use":
#                     tool_name = content_block.name
#                     tool_input = content_block.input
#                     tool_use_id = content_block.id
                    
#                     self.print_colored(f"\nTool Used: {tool_name}", TOOL_COLOR)
#                     self.print_colored(f"Tool Input: {tool_input}", TOOL_COLOR)
                    
#                     result = self.execute_tool(tool_name, tool_input)
#                     self.print_colored(f"Tool Result: {result}", RESULT_COLOR)
                    
#                     self.memory.add_assistant_message([content_block])
#                     self.memory.add_user_message([
#                         {
#                             "type": "tool_result",
#                             "tool_use_id": tool_use_id,
#                             "content": result
#                         }
#                     ])
            
#             if any(content_block.type == "tool_use" for content_block in response.content):
#                 try:
#                     final_response = self.api_client.create_message(
#                         model=self.api_client.model_config.model,
#                         max_tokens=self.api_client.model_config.max_tokens,
#                         system=self.update_system_prompt(current_iteration, max_iterations),
#                         messages=self.memory.get_history(),
#                         tools=self.tools,
#                         tool_choice={"type": "auto"}
#                     )
#                     assistant_response = "".join(block.text for block in final_response.content if block.type == "text")
#                 except Exception as e:
#                     self.print_colored(f"Error in final response: {str(e)}", TOOL_COLOR)
#                     assistant_response += "\nI encountered an error while processing the tool results. Please try again."
            
#             if assistant_response:
#                 self.memory.add_assistant_message(assistant_response)
            
#             return assistant_response, exit_continuation

#     def set_system_prompt(self, prompt):
#         self.system_prompt = prompt

#     def set_tools(self, tools):
#         self.tools = tools

#     def set_execute_tool(self, execute_tool_function):
#         self.execute_tool = execute_tool_function

