from typing import Optional, Tuple, List, Dict, Any
from core import PenguinCore
from utils.logs import penguin_logger, log_event
from chat.prompt_ui import PromptUI
from utils.parser import ActionExecutor, parse_action
import os
import logging
import time
import asyncio

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
        self.logger = logging.getLogger(__name__)
        self._is_processing = False
        self._interrupt_requested = False
        
    async def run_chat(self):
        """Main chat loop with async support"""
        self.ui.print_welcome_message()
        message_count = 1
        
        while True:
            try:
                user_input = await self.ui.get_user_input(message_count)
                
                if user_input.lower() == EXIT_COMMAND:
                    break
                    
                response_dict, exit_flag = await self.chat_with_penguin(
                    user_input=user_input,
                    message_count=message_count
                )
                
                if exit_flag:
                    break
                    
                self.ui.process_and_display_response(response_dict)
                message_count += 1
                
            except KeyboardInterrupt:
                if self._is_processing:
                    self._interrupt_requested = True
                    print("\nInterrupting current operation...")
                else:
                    print("\nUse 'exit' to close Penguin")
            except Exception as e:
                await self.handle_error({"message": str(e)}, message_count)

    async def chat_with_penguin(
        self, 
        user_input: str, 
        message_count: int, 
        image_path: Optional[str] = None,
        current_iteration: Optional[int] = None, 
        max_iterations: Optional[int] = None
    ) -> Tuple[Dict[str, Any], bool]:
        try:
            self._is_processing = True
            self._interrupt_requested = False
            
            # Process input with interrupt check
            try:
                await self.core.process_input({
                    "text": user_input,
                    "image_path": image_path
                })
            except KeyboardInterrupt:
                self._interrupt_requested = True
            
            if self._interrupt_requested:
                return self._create_interrupt_response("Processing interrupted")
            
            # Get response with interrupt check
            try:
                response_dict, exit_continuation = await self.core.get_response(
                    current_iteration=current_iteration, 
                    max_iterations=max_iterations
                )
            except KeyboardInterrupt:
                self._interrupt_requested = True
                
            if self._interrupt_requested:
                return self._create_interrupt_response("Response generation interrupted")
            
            # Process response
            if not isinstance(response_dict, dict):
                response_dict = {"assistant_response": str(response_dict), "action_results": []}
            
            log_event(self.logger, "user", f"User input: {user_input}")
            log_event(self.logger, "assistant", f"Assistant response: {response_dict}")
            
            return response_dict, exit_continuation
            
        except Exception as e:
            error_info = await self.core._handle_error(e, {
                "method": "chat_with_penguin",
                "user_input": user_input,
                "image_path": image_path,
                "iteration": current_iteration,
                "max_iterations": max_iterations
            })
            await self.handle_error(error_info, message_count)
            return {"assistant_response": error_info["message"], "action_results": []}, False
        finally:
            self._is_processing = False
            
    def _create_interrupt_response(self, message: str) -> Tuple[Dict[str, Any], bool]:
        """Create a standardized interrupt response"""
        return {
            "assistant_response": f"{message}. How can I help?",
            "action_results": [],
            "metadata": {
                "interrupted": True,
                "timestamp": time.time()
            }
        }, True

    async def handle_exit(self, message_count: int) -> None:
        log_event(self.logger, "system", "Exiting chat session")
        print("Exiting chat session")
        self.ui.print_bordered_message(
            "Thank you for chatting. Goodbye!", 
            self.ui.PENGUIN_COLOR, 
            "system", 
            message_count
        )

    async def handle_image_input(self, message_count: int) -> None:
        image_path = self.ui.get_image_path()
        if os.path.isfile(image_path):
            user_input = self.ui.get_image_prompt()
            response, _ = await self.chat_with_penguin(user_input, message_count, image_path)
            log_event(self.logger, "assistant", f"Assistant response (with image): {response}")
            print(f"Assistant response (with image): {response}")
            self.ui.print_bordered_message(f"Assistant response (with image):\n{response}", self.ui.PENGUIN_COLOR, "system", message_count)
            self.ui.print_code(response, "json")
        else:
            self.ui.print_bordered_message("Invalid image path. Please try again.", self.ui.PENGUIN_COLOR, "system", message_count)

    async def handle_resume(self, message_count: int) -> None:
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
            print(f"Assistant response: {response}")
            self.ui.print_bordered_message(f"Assistant response:\n{response}", self.ui.PENGUIN_COLOR, "system", message_count)
            self.ui.print_code(response, "json")
        else:
            self.ui.print_bordered_message("No previous conversation found.", self.ui.PENGUIN_COLOR, "system", message_count)

    async def handle_error(self, error_info: Dict[str, str], message_count: int) -> None:
        error_message = error_info["message"]
        log_path = error_info.get("log_path")
        
        log_event(self.logger, "error", error_message)
        print(f"Error: {error_message}")
        
        error_display = f"An error occurred: {error_message}"
        if log_path:
            error_display += f"\nError details logged to: {log_path}"
        
        self.ui.print_bordered_message(error_display, self.ui.TOOL_COLOR, "system", message_count)
        self.core.reset_state()

    def get_latest_log_file(self) -> Optional[str]:
        # Implementation remains the same
        pass

    def parse_log_content(self, content: str) -> List[Dict[str, str]]:
        # Implementation remains the same
        pass