from typing import Optional, Tuple, List, Dict
from core import PenguinCore
from agent.automode import Automode
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE
from utils.logs import setup_logger, log_event, logger
from chat.ui import (
    print_bordered_message, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, PENGUIN_COLOR
)
from colorama import init # type: ignore
import os

# Constants
EXIT_COMMAND = 'exit'
IMAGE_COMMAND = 'image'
AUTOMODE_COMMAND = 'automode'
AUTOMODE_CONTINUE_PROMPT = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."
RESUME_COMMAND = 'resume'

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

    def handle_resume(self, message_count: int, log_file: str) -> None:
        latest_log = self.get_latest_log_file()
        if latest_log:
            with open(latest_log, 'r', encoding='utf-8') as f:
                content = f.read()
            print_bordered_message("Resuming previous conversation:", PENGUIN_COLOR, "system", message_count)
            
            # Parse the content (assuming it's Markdown for this example)
            messages = self.parse_log_content(content)
            
            # Instead of clearing history, we'll append the loaded messages
            for message in messages:
                self.core.add_message(message['role'], message['content'])
            
            if messages:
                last_message = messages[-1]
                response = f"I've loaded the previous conversation. The last message was from {last_message['role']} and it was about: {last_message['content'][:100]}... How would you like to continue?"
            else:
                response = "I've loaded the previous conversation, but it seems to be empty. How would you like to start?"
            
            log_event(log_file, "assistant", f"Assistant response: {response}")
            process_and_display_response(response, message_count)
        else:
            print_bordered_message("No previous conversation found.", PENGUIN_COLOR, "system", message_count)

    def get_latest_log_file(self) -> Optional[str]:
        log_dir = os.path.join(os.getcwd(), 'logs')
        log_files = [f for f in os.listdir(log_dir) if f.startswith('chat_') and f.endswith('.md')]
        if log_files:
            # Sort files based on the timestamp in the filename
            latest_file = max(log_files, key=lambda x: x.split('_')[1].split('.')[0])
            return os.path.join(log_dir, latest_file)
        return None

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
                elif user_input.lower() == RESUME_COMMAND:
                    self.handle_resume(message_count, log_file)
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

    def parse_log_content(self, content: str) -> List[Dict[str, str]]:
        messages = []
        current_message = {'role': '', 'content': ''}
        for line in content.split('\n'):
            if line.startswith('### 🐧 Penguin AI'):
                if current_message['role']:
                    messages.append(current_message)
                current_message = {'role': 'assistant', 'content': ''}
            elif line.startswith('### 👤 User'):
                if current_message['role']:
                    messages.append(current_message)
                current_message = {'role': 'user', 'content': ''}
            elif line.startswith('Assistant response:') or line.startswith('User input:'):
                current_message['content'] += line.split(':', 1)[1].strip() + ' '
        if current_message['role']:
            messages.append(current_message)
        return messages

init()