"""
Core state management classes for Penguin conversation system.

This module defines the fundamental data structures used to represent and
manage conversation state, including messages, sessions, and categories.
"""

import json
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union, Callable
import logging

logger = logging.getLogger(__name__)


class SystemState(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    CHAT = "chat"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class TaskState(Enum):
    """State machine for tasks in the Penguin system."""
    PENDING = "pending"     # Task is created but not started
    ACTIVE = "active"       # Task is currently in progress
    PAUSED = "paused"       # Task execution is temporarily paused, can be resumed
    COMPLETED = "completed" # Task is successfully completed
    FAILED = "failed"       # Task execution failed
    BLOCKED = "blocked"     # Task is blocked by dependencies
    
    @classmethod
    def get_valid_transitions(cls, current_state):
        """Returns valid state transitions from the current state."""
        transitions = {
            cls.PENDING: [cls.ACTIVE, cls.FAILED, cls.BLOCKED],
            cls.ACTIVE: [cls.PAUSED, cls.COMPLETED, cls.FAILED, cls.BLOCKED],
            cls.PAUSED: [cls.ACTIVE, cls.FAILED, cls.BLOCKED],
            cls.COMPLETED: [],  # Terminal state
            cls.FAILED: [cls.PENDING],  # Allow retry from failed
            cls.BLOCKED: [cls.PENDING, cls.ACTIVE] # When dependencies resolved
        }
        return transitions.get(current_state, [])


class MessageCategory(Enum):
    """Categories of messages for priority-based handling in the context window."""
    SYSTEM = 1    # System instructions, never truncated
    CONTEXT = 2   # Important reference information. Declarative notes, context folders, etc.
    DIALOG = 3    # Main conversation between user and assistant
    SYSTEM_OUTPUT = 4   # Results from tool executions, system outputs, etc.
    ERROR = 5           # Error messages from the system or tools
    INTERNAL = "internal" # For core's internal thoughts/plans if exposed
    UNKNOWN = "unknown" # Added to handle cases where category might not be set
    
    # TODO: Consider ERROR as a category? 
    
@dataclass
class Message:
    """
    Represents a single message in a conversation.
    
    Messages have a role (user, assistant, system), content, and a category
    that determines its importance for context window management.
    
    The content field can be any type, supporting:
    - Plain text (str)
    - Structured content for multi-modal messages (list/dict)
    
    And later supports:

    - Images (via OpenAI format {"type": "image_url", "image_url": {...}})
    - Audio (via adapter-specific format)
    - File attachments (via adapter-specific format)
    """
    role: str
    content: Any
    category: MessageCategory
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert message to a dictionary for serialization."""
        result = asdict(self)
        # Convert enum to string for serialization
        result["category"] = self.category.name
        return result
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Message":
        """Create a Message instance from a dictionary."""
        # Convert category string back to enum
        if "category" in data and isinstance(data["category"], str):
            try:
                data["category"] = MessageCategory[data["category"]]
            except KeyError:
                # Default to DIALOG if category is invalid
                data["category"] = MessageCategory.DIALOG
        
        return cls(**data)
    
    def to_api_format(self) -> Dict[str, Any]:
        """Format message for API consumption."""
        return {
            "role": self.role,
            "content": self.content
        }
    
    def fallback_estimate_tokens(self) -> int:
        """
        Last-resort fallback for estimating token count when provider tokenizer 
        and tiktoken are unavailable.
        
        This is a rough approximation and should only be used when proper tokenizers
        cannot be accessed.
        """
        if self.tokens > 0:
            return self.tokens
            
        # Simple approximation: ~4 characters per token
        if isinstance(self.content, str):
            return len(self.content) // 4 + 1
        elif isinstance(self.content, list):
            # Handle OpenAI-style content list with text/image parts
            total_chars = 0
            for item in self.content:
                if isinstance(item, dict):
                    if item.get("type") == "text":
                        total_chars += len(str(item.get("text", "")))
                    elif item.get("type") in ["image_url", "image"]:
                        # Images typically count as ~1000 tokens
                        total_chars += 4000
                    elif item.get("type") == "audio":
                        # Audio typically counts as ~500 tokens
                        total_chars += 2000
                    elif item.get("type") == "file":
                        # Files depend on content, estimate based on metadata
                        total_chars += 1000
                else:
                    total_chars += len(str(item))
            return total_chars // 4 + 1
        else:
            # General fallback
            return len(str(self.content)) // 4 + 1


@dataclass
class Session:
    """
    Represents a conversation session containing multiple messages.
    
    Sessions have their own identity and metadata, and manage a collection
    of messages that belong to the conversation.
    """
    id: str = field(default_factory=lambda: f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}")
    messages: List[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    @property
    def message_count(self) -> int:
        """Get the number of messages in this session."""
        return len(self.messages)
    
    @property
    def total_tokens(self) -> int:
        """Get total token count for all messages in this session."""
        return sum(msg.tokens for msg in self.messages)
    
    def get_messages_by_category(self, category: MessageCategory) -> List[Message]:
        """Get all messages of a specific category."""
        return [msg for msg in self.messages if msg.category == category]
    
    def get_formatted_history(self) -> List[Dict[str, Any]]:
        """Get messages formatted for API consumption."""
        return [msg.to_api_format() for msg in self.messages]
    
    def add_message(self, message: Message) -> None:
        """Add a message to the session."""
        self.messages.append(message)
        self.last_active = datetime.now().isoformat()
        self.metadata["message_count"] = len(self.messages)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert session to a dictionary for serialization."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "metadata": self.metadata,
            "messages": [msg.to_dict() for msg in self.messages]
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create a Session instance from a dictionary."""
        # Handle the messages separately
        messages_data = data.pop("messages", [])
        session = cls(**data)
        
        # Add the messages
        session.messages = [Message.from_dict(msg) for msg in messages_data]
        return session
    
    def to_json(self) -> str:
        """Convert session to JSON string."""
        return json.dumps(self.to_dict(), indent=2)
    
    @classmethod
    def from_json(cls, json_str: str) -> "Session":
        """Create a Session instance from a JSON string."""
        try:
            data = json.loads(json_str)
            return cls.from_dict(data)
        except json.JSONDecodeError as e:
            raise ValueError(f"Invalid JSON format: {e}")
    
    def validate(self) -> bool:
        """Validate session data integrity."""
        # Check for required fields
        if not self.id or not isinstance(self.id, str):
            logger.warning(f"Session validation failed: Invalid or missing ID. Got: {self.id!r}")
            return False
        
        # Validate timestamps
        try:
            datetime.fromisoformat(self.created_at)
            datetime.fromisoformat(self.last_active)
        except (ValueError, TypeError) as e:
            logger.warning(f"Session validation failed: Invalid timestamp. Created: {self.created_at!r}, Last Active: {self.last_active!r}. Error: {e}")
            return False
        
        # Validate messages
        for i, msg in enumerate(self.messages):
            if not isinstance(msg, Message):
                logger.warning(f"Session validation failed: Message at index {i} is not a valid Message object. Type: {type(msg)}")
                return False
            if not msg.role or not isinstance(msg.role, str):
                logger.warning(f"Session validation failed: Message at index {i} has an invalid or missing role. Role: {msg.role!r}")
                return False
                
        return True
    
    def update_token_counts(self, counter_function: Callable[[Any], int]) -> None:
        """
        Update token counts for all messages using the provided counter function.
        
        Args:
            counter_function: Function that takes content and returns token count
        """
        total_tokens = 0
        for msg in self.messages:
            try:
                # Always recalculate for consistency
                msg.tokens = counter_function(msg.content)
                total_tokens += msg.tokens
            except Exception as e:
                # Use fallback estimation in case of failure
                msg.tokens = msg.fallback_estimate_tokens()
                total_tokens += msg.tokens
                logger.warning(f"Using fallback token estimation for message {msg.id}: {e}")
        
        # Update session metadata
        self.metadata["token_count"] = total_tokens
        
        return total_tokens


def create_message(
    role: str, 
    content: Any, 
    category: MessageCategory,
    metadata: Optional[Dict[str, Any]] = None,
    tokens: int = 0
) -> Message:
    """
    Helper function to create a new message.
    
    Args:
        role: Message role (user, assistant, system)
        content: Message content (text or structured data)
        category: Message category for priority handling
        metadata: Optional metadata for the message
        tokens: Optional pre-calculated token count
        
    Returns:
        Message object
    """
    return Message(
        role=role,
        content=content,
        category=category,
        metadata=metadata or {},
        tokens=tokens
    )


def create_session() -> Session:
    """
    Helper function to create a new empty session.
    
    Returns:
        Session object
    """
    return Session(
        metadata={
            "created_at": datetime.now().isoformat(),
            "message_count": 0
        }
    )


class PenguinState:
    """Central state management for all systems"""

    def __init__(self):
        self.system_states: Dict[str, SystemState] = {}
        self.global_state: SystemState = SystemState.IDLE
        self.state_history: List[SystemState] = []
        self._previous_state: Optional[SystemState] = None

    async def update_system_state(self, system: str, state: SystemState):
        """Update individual system state"""
        self._previous_state = self.system_states.get(system)
        self.system_states[system] = state
        self.state_history.append(state)
        await self._check_global_state()

    async def resume_previous_state(self, system: str) -> None:
        """Resume previous state after interruption"""
        if self._previous_state:
            await self.update_system_state(system, self._previous_state)

    async def _check_global_state(self):
        """Update global state based on system states"""
        if any(state == SystemState.ERROR for state in self.system_states.values()):
            self.global_state = SystemState.ERROR
        elif any(state == SystemState.CHAT for state in self.system_states.values()):
            self.global_state = SystemState.CHAT
        elif all(state == SystemState.IDLE for state in self.system_states.values()):
            self.global_state = SystemState.IDLE
        else:
            self.global_state = SystemState.PROCESSING


def parse_iso_datetime(iso_string: str) -> datetime:
    """Parse an ISO format datetime string into a datetime object."""
    try:
        return datetime.fromisoformat(iso_string)
    except (ValueError, TypeError):
        # Return current time as fallback
        return datetime.now()
