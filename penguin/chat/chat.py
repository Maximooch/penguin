from typing import Optional, Tuple, List, Dict, Any
from core import PenguinCore
from utils.logs import penguin_logger, log_event
from chat.prompt_ui import PromptUI
from utils.parser import ActionExecutor, parse_action
import os

# Constants
EXIT_COMMAND = 'exit'
IMAGE_COMMAND = 'image'
TASK_COMMAND = 'task'
PROJECT_COMMAND = 'project'
RESUME_COMMAND = 'resume'

class ChatManager:
    def __init__(self, core: PenguinCore, ui: PromptUI):
        self.core = core
        self.ui = ui
        self.action_executor = core.action_executor
        self.logger = penguin_logger

    def chat_with_penguin(self, user_input: str, message_count: int, image_path: Optional[str] = None, 
                          current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[Dict[str, Any], bool]:
        try:
            response_dict, exit_continuation = self.core.get_response(user_input, image_path, current_iteration, max_iterations)
            log_event(self.logger, "assistant", f"Assistant response: {response_dict}")
            
            if not isinstance(response_dict, dict):
                response_dict = {"assistant_response": str(response_dict), "action_results": []}
            
            assistant_response = response_dict.get("assistant_response", "")
            actions = parse_action(assistant_response)
            
            action_results = []
            for action in actions:
                result = self.core.action_executor.execute_action(action)
                if result is not None:
                    action_results.append({
                        "action": action["name"] if isinstance(action, dict) and "name" in action else "unknown",
                        "result": str(result)
                    })
            
            response_dict["action_results"] = response_dict.get("action_results", []) + action_results
            
            if not current_iteration:
                log_event(self.logger, "user", f"User input: {user_input}")
                log_event(self.logger, "assistant", f"Assistant response: {response_dict}")
            
            return response_dict, exit_continuation
            
        except Exception as e:
            error_message = f"An error occurred: {str(e)}"
            log_event(self.logger, "error", error_message)
            error_response = {"assistant_response": error_message, "action_results": []}
            if not current_iteration:
                log_event(self.logger, "system", f"Error: {str(e)}")
            return error_response, False

    def run_chat(self) -> None:
        self.logger.info("Starting Penguin AI")
        self.ui.print_welcome_message()
        
        message_count = 0
        
        while True:
            message_count += 1
            try:
                user_input = self.ui.get_user_input(message_count)
                
                if user_input.lower() == EXIT_COMMAND:
                    self.handle_exit(message_count)
                    break
                
                if user_input.lower() == IMAGE_COMMAND:
                    self.handle_image_input(message_count)
                elif user_input.lower().startswith(TASK_COMMAND):
                    self.core.action_executor.handle_task_command(user_input, message_count)
                elif user_input.lower().startswith(PROJECT_COMMAND):
                    self.core.action_executor.handle_project_command(user_input, message_count)
                elif user_input.lower() == RESUME_COMMAND:
                    self.handle_resume(message_count)
                else:
                    response, _ = self.chat_with_penguin(user_input, message_count)
                    self.ui.process_and_display_response(response)
            except Exception as e:
                self.handle_error(str(e), message_count)

    def handle_exit(self, message_count: int) -> None:
        log_event(self.logger, "system", "Exiting chat session")
        self.ui.print_bordered_message(
            "Thank you for chatting. Goodbye!", 
            self.ui.PENGUIN_COLOR, 
            "system", 
            message_count
        )

    def handle_image_input(self, message_count: int) -> None:
        image_path = self.ui.get_image_path()
        if os.path.isfile(image_path):
            user_input = self.ui.get_image_prompt()
            response, _ = self.chat_with_penguin(user_input, message_count, image_path)
            log_event(self.logger, "assistant", f"Assistant response (with image): {response}")
            self.ui.print_bordered_message(f"Assistant response (with image):\n{response}", self.ui.PENGUIN_COLOR, "system", message_count)
            self.ui.print_code(response, "json")
        else:
            self.ui.print_bordered_message("Invalid image path. Please try again.", self.ui.PENGUIN_COLOR, "system", message_count)

    def handle_resume(self, message_count: int) -> None:
        latest_log = self.get_latest_log_file()
        if latest_log:
            with open(latest_log, 'r', encoding='utf-8') as f:
                content = f.read()
            self.ui.print_bordered_message("Resuming previous conversation:", self.ui.PENGUIN_COLOR, "system", message_count)
            
            messages = self.parse_log_content(content)
            
            for message in messages:
                self.core.add_message(message['role'], message['content'])
            
            if messages:
                last_message = messages[-1]
                response = f"I've loaded the previous conversation. The last message was from {last_message['role']} and it was about: {last_message['content'][:100]}... How would you like to continue?"
            else:
                response = "I've loaded the previous conversation, but it seems to be empty. How would you like to start?"
            
            log_event(self.logger, "assistant", f"Assistant response: {response}")
            self.ui.print_bordered_message(f"Assistant response:\n{response}", self.ui.PENGUIN_COLOR, "system", message_count)
            self.ui.print_code(response, "json")
        else:
            self.ui.print_bordered_message("No previous conversation found.", self.ui.PENGUIN_COLOR, "system", message_count)

    def handle_error(self, error_message: str, message_count: int) -> None:
        log_event(self.logger, "error", error_message)
        self.ui.print_bordered_message(f"An error occurred: {error_message}", self.ui.TOOL_COLOR, "system", message_count)
        self.core.reset_state()

    def get_latest_log_file(self) -> Optional[str]:
        # Implementation remains the same
        pass

    def parse_log_content(self, content: str) -> List[Dict[str, str]]:
        # Implementation remains the same
        pass
