from typing import List, Dict, Any, Optional, Tuple
import logging
from datetime import datetime
from utils.diagnostics import Diagnostics

logger = logging.getLogger(__name__)

class ConversationSystem:
    """
    Manages conversation state, history, and message preparation.
    
    Responsibilities:
    - Conversation history management
    - Message preparation and formatting
    - System prompt management
    - Image message handling
    """
    
    def __init__(self, tool_manager, diagnostics):
        self.tool_manager = tool_manager
        self.diagnostics = diagnostics
        self.system_prompt = None
        self.system_prompt_sent = False
        self.history = []
        self.max_history_length = 1000000
        
    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt and mark it as not sent."""
        self.system_prompt = prompt
        self.system_prompt_sent = False
        
    def add_message(self, role: str, content: Any) -> None:
        """Add a message to the conversation history."""
        # Format content as per OpenAI's new API requirements
        if isinstance(content, str):
            formatted_content = [{"type": "text", "text": content}]
        elif isinstance(content, dict) and "type" in content:
            formatted_content = [content]  # Already properly formatted
        elif isinstance(content, list):
            formatted_content = content    # Assume it's already a list of content parts
        else:
            formatted_content = [{"type": "text", "text": str(content)}]
        
        message = {"role": role, "content": formatted_content}
        self.history.append(message)
        
        # Truncate history if it exceeds max length
        if len(self.history) > self.max_history_length:
            # Keep system messages and trim others
            system_messages = [m for m in self.history if m["role"] == "system"]
            other_messages = [m for m in self.history if m["role"] != "system"]
            other_messages = other_messages[-self.max_history_length + len(system_messages):]
            self.history = system_messages + other_messages
            
    def prepare_conversation(self, user_input: str, image_path: Optional[str] = None) -> None:
        """Prepare the conversation by adding necessary messages."""
        if self.get_history() and self.get_last_message()["role"] == "user":
            self.add_message("assistant", "Continuing the conversation...")

        if not self.system_prompt_sent and self.system_prompt:
            system_tokens = self.diagnostics.count_tokens(self.system_prompt)
            self.diagnostics.update_tokens('system_prompt', system_tokens, 0)
            self.add_message("system", self.system_prompt)
            self.system_prompt_sent = True

        if image_path:
            self._add_image_message(user_input, image_path)
        else:
            self.add_message("user", user_input)
            
    def _add_image_message(self, user_input: str, image_path: str) -> None:
        """Add an image message to the conversation."""
        try:
            base64_image = self.tool_manager.encode_image(image_path)
            image_message = [
                {"type": "text", "text": user_input},
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
            self.add_message("user", image_message)
            logger.info("Image message added to conversation history")
        except Exception as e:
            logger.error(f"Error adding image message: {str(e)}")
            raise
            
    def get_history(self) -> List[Dict[str, Any]]:
        """Get the full conversation history."""
        return self.history
        
    def get_last_message(self) -> Optional[Dict[str, Any]]:
        """Get the last message in the conversation history."""
        return self.history[-1] if self.history else None
        
    def clear_history(self) -> None:
        """Clear the conversation history."""
        self.history = []
        self.system_prompt_sent = False
        
    def add_summary_note(self, category: str, content: str) -> None:
        """Add a summary note as a system message."""
        self.add_message("system", {
            "type": "summary_note",
            "category": category,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

class ConversationSession:
    """Represents a single conversation session with its own state."""
    
    def __init__(self, session_id: str, tool_manager, diagnostics: Optional[Diagnostics] = None):
        self.session_id = session_id
        self.tool_manager = tool_manager
        self.diagnostics = diagnostics or Diagnostics()
        self.conversation_history: List[Dict[str, Any]] = []
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.metadata = {
            "created_at": datetime.now().isoformat(),
            "last_active": datetime.now().isoformat(),
            "message_count": 0
        }
        
    def to_dict(self) -> Dict[str, Any]:
        """Serialize session state to dictionary."""
        return {
            "session_id": self.session_id,
            "history": self.conversation_history,
            "system_prompt": self.system_prompt,
            "system_prompt_sent": self.system_prompt_sent,
            "metadata": self.metadata
        }
        
    @classmethod
    def from_dict(cls, data: Dict[str, Any], tool_manager, diagnostics=None) -> 'ConversationSession':
        """Create session from serialized state."""
        session = cls(data["session_id"], tool_manager, diagnostics)
        session.conversation_history = data["history"]
        session.system_prompt = data["system_prompt"]
        session.system_prompt_sent = data["system_prompt_sent"]
        session.metadata = data["metadata"]
        return session

# Later on something in CLI to have a sort of menu to select/create/delete sessions

# class ConversationSystem:
#     """Enhanced conversation system supporting multiple sessions."""
    
#     def __init__(self, tool_manager, diagnostics: Optional[Diagnostics] = None):
#         self.tool_manager = tool_manager
#         self.diagnostics = diagnostics
#         self.sessions: Dict[str, ConversationSession] = {}
#         self.active_session_id: Optional[str] = None
        
#     def create_session(self) -> str:
#         """Create a new conversation session."""
#         session_id = f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{os.getpid()}"
#         self.sessions[session_id] = ConversationSession(session_id, self.tool_manager, self.diagnostics)
#         self.active_session_id = session_id
#         return session_id
        
#     def load_session(self, session_id: str) -> None:
#         """Load and activate a saved session."""
#         if session_id in self.sessions:
#             self.active_session_id = session_id
#         else:
#             raise ValueError(f"Session {session_id} not found")
            
#     def get_active_session(self) -> ConversationSession:
#         """Get the currently active session."""
#         if not self.active_session_id:
#             self.create_session()
#         return self.sessions[self.active_session_id]