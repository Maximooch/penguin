from typing import List, Dict, Any, Optional, Tuple
from datetime import datetime
# import diagnostics
# maybe logging

class ConversationSystem:

    """
    Manages conversation state, history, message flow, and prepartion.
    
    Responsibilities:
    - Conversation history management
    - Message preparation and formatting
    - System prompt management
    - Image message handling
    - Task completion handling
    - Asynchronous message handling
    - Asynchronous task execution? (maybe handled by another system) 
    """

    def __init__(self):
        self.messages = []
        self.system_prompt = None
        self.system_prompt_sent = False

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt and mark it as not sent."""
        self.system_prompt = prompt
        self.system_prompt_sent = False

    # prepare conversation

    # add message (user, penguin, system, maybe image included)
    
    # probably a base function/class, then something for user, penguin, system, and maybe image.

    # get last message (for penguin's response). Why?

    # clear history

