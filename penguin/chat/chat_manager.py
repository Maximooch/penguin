from typing import Optional, Tuple, List, Dict, Any
# from .ui import process_and_display_response
from core import PenguinCore

class ChatManager:
    def __init__(self, core: PenguinCore):
        self.core = core
        self.automode = False

    def chat_with_penguin(self, user_input: str, message_count: int, image_path: Optional[str] = None, 
        current_iteration: Optional[int] = None, max_iterations: Optional[int] = None) -> Tuple[str, bool]:
        
        return self.core.get_response(user_input, image_path, current_iteration, max_iterations)

    def handle_automode(self, automode_goal: str, max_iterations: int) -> None:
        self.automode = True
        self.core.automode = True
        # Implementation of automode logic

    def reset_state(self) -> None:
        self.automode = False
        self.core.reset_state()

    # Other chat-specific methods...
    # Like what?
