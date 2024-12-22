from typing import List, Dict, Any, Optional, Tuple
import json
import logging
from datetime import datetime
from pathlib import Path
from dataclasses import dataclass, asdict, field
from utils.diagnostics import Diagnostics

logger = logging.getLogger(__name__)

@dataclass
class ConversationMetadata:
    """Metadata for a conversation session"""
    created_at: str
    last_active: str
    message_count: int
    session_id: str
    title: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    def update_title_from_messages(self, messages: List[Dict]) -> None:
        """Set title from first user message"""
        for message in messages:
            if message["role"] == "user":
                content = message["content"]
                # Handle both string and list content formats
                if isinstance(content, list):
                    text = next((c["text"] for c in content if c["type"] == "text"), "")
                else:
                    text = str(content)
                # Truncate long titles
                self.title = (text[:37] + "...") if len(text) > 40 else text
                break

class ConversationLoader:
    """Handles saving and loading conversations"""
    
    def __init__(self, base_path: Path):
        self.base_path = Path(base_path) / "conversations"
        self.base_path.mkdir(parents=True, exist_ok=True)
        
    def save_conversation(self, session_id: str, messages: List[Dict], metadata: ConversationMetadata) -> None:
        """Save conversation to disk"""
        session_path = self.base_path / session_id
        session_path.mkdir(exist_ok=True)
        
        # Save messages
        messages_path = session_path / "messages.json"
        with messages_path.open('w', encoding='utf-8') as f:
            json.dump(messages, f, indent=2, ensure_ascii=False)
            
        # Save metadata
        metadata_path = session_path / "metadata.json"
        with metadata_path.open('w', encoding='utf-8') as f:
            json.dump(asdict(metadata), f, indent=2)
            
    def load_conversation(self, session_id: str) -> Tuple[List[Dict], ConversationMetadata]:
        """Load conversation from disk"""
        session_path = self.base_path / session_id
        
        if not session_path.exists():
            raise ValueError(f"Session {session_id} not found")
            
        try:
            # Load messages
            messages_path = session_path / "messages.json"
            with messages_path.open('r', encoding='utf-8') as f:
                messages = json.load(f)
                
            # Load metadata
            metadata_path = session_path / "metadata.json"
            with metadata_path.open('r', encoding='utf-8') as f:
                metadata_dict = json.load(f)
                metadata = ConversationMetadata(**metadata_dict)
                
            return messages, metadata
            
        except Exception as e:
            logger.error(f"Error loading conversation {session_id}: {str(e)}")
            raise
            
    def list_conversations(self) -> List[ConversationMetadata]:
        """List all saved conversations"""
        conversations = []
        
        for session_path in self.base_path.iterdir():
            if session_path.is_dir():
                try:
                    metadata_path = session_path / "metadata.json"
                    if metadata_path.exists():
                        with metadata_path.open('r', encoding='utf-8') as f:
                            metadata_dict = json.load(f)
                            conversations.append(ConversationMetadata(**metadata_dict))
                except Exception as e:
                    logger.error(f"Error loading metadata for {session_path}: {str(e)}")
                    continue
                    
        return sorted(conversations, key=lambda x: x.last_active, reverse=True)

class ConversationSystem:
    """
    Manages conversation state, history, and message preparation.
    
    Responsibilities:
    - Conversation history management
    - Message preparation and formatting
    - System prompt management
    - Image message handling
    """
    
    def __init__(self, tool_manager, diagnostics, base_path: Path):
        self.tool_manager = tool_manager
        self.diagnostics = diagnostics
        self.messages = []
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.max_history_length = 1000000
        self.session_id = self._generate_session_id()
        self.metadata = ConversationMetadata(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            message_count=0,
            session_id=self.session_id
        )
        self.loader = ConversationLoader(base_path)

    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def save(self) -> None:
        """Save current conversation state"""
        self.metadata.last_active = datetime.now().isoformat()
        self.metadata.message_count = len(self.messages)
        self.loader.save_conversation(self.session_id, self.messages, self.metadata)
        
    def load(self, session_id: str) -> None:
        """Load a saved conversation"""
        messages, metadata = self.loader.load_conversation(session_id)
        self.messages = messages
        self.metadata = metadata
        self.session_id = session_id
        self.system_prompt_sent = any(m["role"] == "system" for m in messages)
        
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
        self.messages.append(message)
        
        # Update title if this is the first user message
        if role == "user" and len([m for m in self.messages if m["role"] == "user"]) == 1:
            self.metadata.update_title_from_messages(self.messages)
        
        # Truncate history if it exceeds max length
        if len(self.messages) > self.max_history_length:
            # Keep system messages and trim others
            system_messages = [m for m in self.messages if m["role"] == "system"]
            other_messages = [m for m in self.messages if m["role"] != "system"]
            other_messages = other_messages[-self.max_history_length + len(system_messages):]
            self.messages = system_messages + other_messages
            
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
                {
                    "type": "text",
                    "text": user_input
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
            # Add as properly structured content
            self.add_message("user", image_message)
            logger.info("Image message added to conversation history")
        except Exception as e:
            logger.error(f"Error adding image message: {str(e)}")
            raise
            
    def get_history(self) -> List[Dict[str, Any]]:
        """Get the full conversation history."""
        return self.messages
        
    def get_last_message(self) -> Optional[Dict[str, Any]]:
        """Get the last message in the conversation history."""
        return self.messages[-1] if self.messages else None
        
    def clear_history(self) -> None:
        """Clear the conversation history."""
        self.messages = []
        self.system_prompt_sent = False
        
    def add_summary_note(self, category: str, content: str) -> None:
        """Add a summary note as a system message."""
        self.add_message("system", {
            "type": "summary_note",
            "category": category,
            "content": content,
            "timestamp": datetime.now().isoformat()
        })

    def reset(self):
        """Reset the conversation state"""
        self.messages = []
        self.system_prompt_sent = False