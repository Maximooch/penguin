from typing import Optional, Tuple
from core import PenguinCore
from agent.automode import Automode
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE
from utils.logs import setup_logger, log_event, logger
from chat.ui import (
    print_bordered_message, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, PENGUIN_COLOR
)
from colorama import init
import os

# Constants
EXIT_COMMAND = 'exit'
IMAGE_COMMAND = 'image'
AUTOMODE_COMMAND = 'automode'
AUTOMODE_CONTINUE_PROMPT = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."

class ChatManager:
    def __init__(self, core: PenguinCore):
        self.core = core
        self.automode = False

    def chat_with_penguin(self, user_input: str, message_count: int, image_path: Optional[str] = None, 
        current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
        
        try:
            response = self.core.get_response(user_input, image_path, current_iteration, max_iterations)
            logger.debug(f"Response from core: {response}")  # Add this debug log
            if isinstance(response, tuple) and len(response) == 2:
                return response
            else:
                return str(response), False
        except Exception as e:
            logger.error(f"Error in chat_with_penguin: {str(e)}")
            return f"An error occurred: {str(e)}", False

    def run_automode(self, user_input: str, message_count: int) -> None:
        self.automode = True
        self.core.automode = True
        self.core.run_automode(user_input, message_count, self.chat_with_penguin)

    def reset_state(self) -> None:
        self.automode = False
        self.core.reset_state()

    def handle_image_input(self, message_count: int, log_file: str) -> None:
        image_path = get_image_path()
        if os.path.isfile(image_path):
            user_input = get_image_prompt()
            response, _ = self.chat_with_penguin(user_input, message_count, image_path)
            log_event(log_file, "assistant", f"Assistant response (with image): {response}")
            process_and_display_response(response, message_count)
        else:
            print_bordered_message("Invalid image path. Please try again.", PENGUIN_COLOR, "system", message_count)

    def handle_automode(self, user_input: str, message_count: int) -> None:
        try:
            self.run_automode(user_input, message_count)
        except KeyboardInterrupt:
            self.handle_automode_interruption(message_count)
        finally:
            self.reset_state()

    def handle_automode_interruption(self, message_count: int) -> None:
        log_event("system", "Automode interrupted by user")
        print_bordered_message("\nAutomode interrupted by user. Exiting automode.", TOOL_COLOR, "system", message_count)
        self.automode = False
        self.core.add_message("assistant", "Automode interrupted. How can I assist you further?")

    def run_chat(self) -> None:
        log_file = setup_logger()
        log_event(log_file, "system", "Starting Penguin AI")
        print_welcome_message()
        
        message_count = 0
        
        while True:
            message_count += 1
            user_input = get_user_input(message_count)
            log_event(log_file, "user", f"User input: {user_input}")
            
            if user_input.lower() == EXIT_COMMAND:
                log_event(log_file, "system", "Exiting chat session")
                print_bordered_message("Thank you for chatting. Goodbye!", PENGUIN_COLOR, "system", message_count)
                break
            
            try:
                if user_input.lower() == IMAGE_COMMAND:
                    self.handle_image_input(message_count, log_file)
                elif user_input.lower().startswith(AUTOMODE_COMMAND):
                    self.handle_automode(user_input, message_count)
                else:
                    response, exit_continuation = self.chat_with_penguin(user_input, message_count)
                    log_event(log_file, "assistant", f"Assistant response: {response}")
                    process_and_display_response(response, message_count)
            except Exception as e:
                error_message = f"An error occurred: {str(e)}"
                logger.error(error_message)
                log_event(log_file, "error", error_message)
                print_bordered_message(error_message, TOOL_COLOR, "system", message_count)
                self.reset_state()

init()