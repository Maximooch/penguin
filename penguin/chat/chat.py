from typing import Optional, Tuple, List, Dict, Any
from core import PenguinCore
# from agent.automode import Automode
from agent.task_manager import TaskManager
from config import MAX_CONTINUATION_ITERATIONS, CONTINUATION_EXIT_PHRASE
from utils.logs import setup_logger, log_event, logger
from chat.ui import (
    print_bordered_message, process_and_display_response, print_welcome_message,
    get_user_input, get_image_path, get_image_prompt,
    TOOL_COLOR, PENGUIN_COLOR
)
from colorama import init # type: ignore
import os
import re
from agent.task import TaskStatus
from utils.parser import parse_action, ActionExecutor
from agent.task_utils import create_task, update_task, complete_task, list_tasks

# Constants
EXIT_COMMAND = 'exit'
IMAGE_COMMAND = 'image'
# AUTOMODE_COMMAND = 'automode'
# AUTOMODE_CONTINUE_PROMPT = "Continue with the next step. Or STOP by saying 'AUTOMODE_COMPLETE' if you think you've achieved the results established in the original request."
TASK_COMMAND = 'task'
RESUME_COMMAND = 'resume'

class ChatManager:
    def __init__(self, core: PenguinCore):
        self.core = core
        self.task_manager = TaskManager(logger)
        self.action_executor = ActionExecutor(self.core.tool_manager, self.task_manager)

    def chat_with_penguin(self, user_input: str, message_count: int, image_path: Optional[str] = None, 
        current_iteration: Optional[int] = None, max_iterations: Optional[int] = None,
        conversation_history: Optional[List[Dict[str, Any]]] = None) -> Tuple[str, bool]:
        
        try:
            response, exit_continuation = self.core.get_response(user_input, image_path or None, current_iteration, max_iterations)
            logger.debug(f"Response from core: {response}")
            
            actions = parse_action(response)
            
            for action in actions:
                result = self.action_executor.execute_action(action)
                response += f"\n{result}"
            
            return response, exit_continuation
        except Exception as e:
            logger.error(f"Error in chat_with_penguin: {str(e)}")
            return f"An error occurred: {str(e)}", False

    def _update_task_progress(self, response: str) -> None:
        current_task = self.task_manager.get_current_task()
        if current_task and current_task.status == TaskStatus.IN_PROGRESS:
            if "task completed" in response.lower():
                current_task.update_progress(100)
            elif "progress" in response.lower():
                progress = int(re.search(r'\d+', response).group())
                current_task.update_progress(progress)

    def handle_task_command(self, user_input: str, message_count: int) -> None:
        parts = user_input.split(maxsplit=3)
        if len(parts) < 2:
            print_bordered_message("Invalid task command. Usage: task [create|run|list|status] [task_name] [task_description]", TOOL_COLOR, "system", message_count)
            return

        action = parts[1]

        if action == "list":
            task_board = list_tasks(self.task_manager)
            print_bordered_message(f"Task Board:\n{task_board}", TOOL_COLOR, "system", message_count)
            return

        if len(parts) < 3:
            print_bordered_message("Invalid task command. Usage: task [create|run|status] [task_name] [task_description]", TOOL_COLOR, "system", message_count)
            return

        task_name = parts[2]

        if action == "create":
            if len(parts) < 4:
                print_bordered_message("Invalid task command. Usage: task create [task_name] [task_description]", TOOL_COLOR, "system", message_count)
                return
            task_description = parts[3]
            task = create_task(self.task_manager, task_name, task_description)
            print_bordered_message(str(task), TOOL_COLOR, "system", message_count)
        elif action == "run":
            task = self.task_manager.get_task_by_name(task_name)
            if task:
                try:
                    for current_iteration, max_iterations, response in self.task_manager.run_task(task, self.chat_with_penguin, message_count):
                        print_bordered_message(f"Task Progress: Iteration {current_iteration}/{max_iterations}", TOOL_COLOR, "system", message_count)
                        print_bordered_message(f"AI Response:\n{response}", PENGUIN_COLOR, "system", message_count)
                    print_bordered_message(f"Task completed: {task}", TOOL_COLOR, "system", message_count)
                except Exception as e:
                    print_bordered_message(f"Error running task: {str(e)}", TOOL_COLOR, "system", message_count)
            else:
                print_bordered_message(f"Task not found: {task_name}", TOOL_COLOR, "system", message_count)
        elif action == "status":
            task = self.task_manager.get_task_by_name(task_name)
            if task:
                print_bordered_message(f"Task Status: {task}", TOOL_COLOR, "system", message_count)
            else:
                print_bordered_message(f"Task not found: {task_name}", TOOL_COLOR, "system", message_count)
        else:
            print_bordered_message(f"Unknown task action: {action}", TOOL_COLOR, "system", message_count)

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
                elif user_input.lower().startswith(TASK_COMMAND):
                    self.handle_task_command(user_input, message_count)
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

    def handle_image_input(self, message_count: int, log_file: str) -> None:
        image_path = get_image_path()
        if os.path.isfile(image_path):
            user_input = get_image_prompt()
            response, _ = self.chat_with_penguin(user_input, message_count, image_path)
            log_event(log_file, "assistant", f"Assistant response (with image): {response}")
            process_and_display_response(response, message_count)
        else:
            print_bordered_message("Invalid image path. Please try again.", PENGUIN_COLOR, "system", message_count)

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

    def reset_state(self) -> None:
        self.core.reset_state()
        self.task_manager = TaskManager(logger)

init()