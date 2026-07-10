"""
Core state management classes for Penguin conversation system.

This module defines the fundamental data structures used to represent and
manage conversation state, including messages, sessions, and categories.
"""

import json
import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_PERSISTED_LLM_REQUEST_LIFECYCLES = 256
MAX_PERSISTED_TOOL_RECORDS = 512


def _default_session_id() -> str:
    """Create Penguin's timestamped session id."""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    return f"session_{timestamp}_{uuid.uuid4().hex[:8]}"


class SystemState(Enum):
    IDLE = "idle"
    PROCESSING = "processing"
    CHAT = "chat"
    ERROR = "error"
    SHUTDOWN = "shutdown"


class TaskState(Enum):
    """State machine for tasks in the Penguin system."""

    PENDING = "pending"  # Task is created but not started
    ACTIVE = "active"  # Task is currently in progress
    PAUSED = "paused"  # Task execution is temporarily paused, can be resumed
    COMPLETED = "completed"  # Task is successfully completed
    FAILED = "failed"  # Task execution failed
    BLOCKED = "blocked"  # Task is blocked by dependencies

    @classmethod
    def get_valid_transitions(cls, current_state):
        """Returns valid state transitions from the current state."""
        transitions = {
            cls.PENDING: [cls.ACTIVE, cls.FAILED, cls.BLOCKED],
            cls.ACTIVE: [cls.PAUSED, cls.COMPLETED, cls.FAILED, cls.BLOCKED],
            cls.PAUSED: [cls.ACTIVE, cls.FAILED, cls.BLOCKED],
            cls.COMPLETED: [],  # Terminal state
            cls.FAILED: [cls.PENDING],  # Allow retry from failed
            cls.BLOCKED: [cls.PENDING, cls.ACTIVE],  # When dependencies resolved
        }
        return transitions.get(current_state, [])


class MessageCategory(Enum):
    """Categories of messages for priority-based handling in the context window."""

    SYSTEM = 1  # System instructions, never truncated
    # Important reference information: declarative notes, context folders, etc.
    CONTEXT = 2
    DIALOG = 3  # Main conversation between user and assistant
    SYSTEM_OUTPUT = 4  # Results from tool executions, system outputs, etc.
    ERROR = 5  # Error messages from the system or tools
    INTERNAL = "internal"  # For core's internal thoughts/plans if exposed
    UNKNOWN = "unknown"  # Added to handle cases where category might not be set

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
    - Video (via adapter-specific format)
    - Other structured content as needed
    """

    role: str
    content: Any
    category: MessageCategory
    id: str = field(default_factory=lambda: f"msg_{uuid.uuid4().hex[:8]}")
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    tokens: int = 0
    # Phase 3 envelope fields
    agent_id: Optional[str] = None
    recipient_id: Optional[str] = None
    message_type: str = "message"  # message|action|status

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
        # Backward compatibility: envelope fields may be absent
        data.setdefault("agent_id", None)
        data.setdefault("recipient_id", None)
        data.setdefault("message_type", "message")

        return cls(**data)

    def to_api_format(self) -> Dict[str, Any]:
        """Format message for API consumption."""
        return {"role": self.role, "content": self.content}

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

    id: str = field(default_factory=_default_session_id)
    messages: List[Message] = field(default_factory=list)
    created_at: str = field(default_factory=lambda: datetime.now().isoformat())
    last_active: str = field(default_factory=lambda: datetime.now().isoformat())
    metadata: Dict[str, Any] = field(default_factory=dict)
    llm_request_lifecycles: List[Dict[str, Any]] = field(default_factory=list)
    tool_call_records: List[Dict[str, Any]] = field(default_factory=list)
    tool_result_records: List[Dict[str, Any]] = field(default_factory=list)

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

    def add_llm_request_lifecycle(self, lifecycle: Any) -> None:
        """Persist one provider request lifecycle record on this session."""

        if hasattr(lifecycle, "to_dict") and callable(lifecycle.to_dict):
            record = lifecycle.to_dict()
        elif isinstance(lifecycle, dict):
            record = dict(lifecycle)
        else:
            raise TypeError("lifecycle must be a dictionary or to_dict object")

        if not isinstance(record, dict):
            raise TypeError("lifecycle.to_dict() must return a dictionary")

        record = dict(record)
        request_id = str(record.get("request_id") or "").strip()
        if request_id:
            self.llm_request_lifecycles = [
                existing_record
                for existing_record in self.llm_request_lifecycles
                if str(existing_record.get("request_id") or "").strip() != request_id
            ]
        self.llm_request_lifecycles.append(record)
        self.llm_request_lifecycles = self.llm_request_lifecycles[
            -MAX_PERSISTED_LLM_REQUEST_LIFECYCLES:
        ]
        self.last_active = datetime.now().isoformat()
        self.metadata["llm_request_lifecycle_count"] = len(self.llm_request_lifecycles)

    def _coerce_record(self, record: Any, *, record_name: str) -> Dict[str, Any]:
        """Convert a record-like object into a dictionary."""

        if hasattr(record, "to_dict") and callable(record.to_dict):
            resolved = record.to_dict()
        elif isinstance(record, dict):
            resolved = dict(record)
        else:
            raise TypeError(f"{record_name} must be a dictionary or to_dict object")

        if not isinstance(resolved, dict):
            raise TypeError(f"{record_name}.to_dict() must return a dictionary")
        return dict(resolved)

    def _replace_record_by_call_id(
        self,
        records: List[Dict[str, Any]],
        record: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Replace an existing call-id record while preserving older fields."""

        call_id = str(record.get("call_id") or "").strip()
        if not call_id:
            return [*records, record]

        merged_records: List[Dict[str, Any]] = []
        replaced = False
        for existing in records:
            existing_call_id = str(existing.get("call_id") or "").strip()
            if existing_call_id == call_id:
                merged = dict(existing)
                merged.update(record)
                merged_records.append(merged)
                replaced = True
            else:
                merged_records.append(existing)
        if not replaced:
            merged_records.append(record)
        return merged_records[-MAX_PERSISTED_TOOL_RECORDS:]

    def add_tool_call_record(self, record: Any) -> None:
        """Persist or update one lightweight tool-call record."""

        resolved = self._coerce_record(record, record_name="tool_call_record")
        self.tool_call_records = self._replace_record_by_call_id(
            self.tool_call_records,
            resolved,
        )
        self.last_active = datetime.now().isoformat()
        self.metadata["tool_call_record_count"] = len(self.tool_call_records)

    def add_tool_result_record(self, record: Any) -> None:
        """Persist or update one lightweight tool-result record."""

        resolved = self._coerce_record(record, record_name="tool_result_record")
        self.tool_result_records = self._replace_record_by_call_id(
            self.tool_result_records,
            resolved,
        )
        self.last_active = datetime.now().isoformat()
        self.metadata["tool_result_record_count"] = len(self.tool_result_records)

    def to_dict(self) -> Dict[str, Any]:
        """Convert session to a dictionary for serialization."""
        return {
            "id": self.id,
            "created_at": self.created_at,
            "last_active": self.last_active,
            "metadata": self.metadata,
            "messages": [msg.to_dict() for msg in self.messages],
            "llm_request_lifecycles": [
                dict(record) for record in self.llm_request_lifecycles
            ],
            "tool_call_records": [dict(record) for record in self.tool_call_records],
            "tool_result_records": [
                dict(record) for record in self.tool_result_records
            ],
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Session":
        """Create a Session instance from a dictionary."""
        data = dict(data)
        # Handle the messages separately
        messages_data = data.pop("messages", [])
        lifecycles_data = data.pop("llm_request_lifecycles", [])
        tool_call_records_data = data.pop("tool_call_records", [])
        tool_result_records_data = data.pop("tool_result_records", [])
        session = cls(**data)

        # Add the messages
        session.messages = [Message.from_dict(msg) for msg in messages_data]
        session.llm_request_lifecycles = [
            dict(record) for record in lifecycles_data if isinstance(record, dict)
        ][-MAX_PERSISTED_LLM_REQUEST_LIFECYCLES:]
        session.tool_call_records = [
            dict(record)
            for record in tool_call_records_data
            if isinstance(record, dict)
        ][-MAX_PERSISTED_TOOL_RECORDS:]
        session.tool_result_records = [
            dict(record)
            for record in tool_result_records_data
            if isinstance(record, dict)
        ][-MAX_PERSISTED_TOOL_RECORDS:]
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
            logger.warning(
                f"Session validation failed: Invalid or missing ID. Got: {self.id!r}"
            )
            return False

        # Validate timestamps
        try:
            datetime.fromisoformat(self.created_at)
            datetime.fromisoformat(self.last_active)
        except (ValueError, TypeError) as e:
            logger.warning(
                f"Session validation failed: Invalid timestamp. Created: {self.created_at!r}, Last Active: {self.last_active!r}. Error: {e}"
            )
            return False

        # Validate messages
        for i, msg in enumerate(self.messages):
            if not isinstance(msg, Message):
                logger.warning(
                    f"Session validation failed: Message at index {i} is not a valid Message object. Type: {type(msg)}"
                )
                return False
            if not msg.role or not isinstance(msg.role, str):
                logger.warning(
                    f"Session validation failed: Message at index {i} has an invalid or missing role. Role: {msg.role!r}"
                )
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
                logger.warning(
                    f"Using fallback token estimation for message {msg.id}: {e}"
                )

        # Update session metadata
        self.metadata["token_count"] = total_tokens

        return total_tokens


def create_message(
    role: str,
    content: Any,
    category: MessageCategory,
    metadata: Optional[Dict[str, Any]] = None,
    tokens: int = 0,
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
        tokens=tokens,
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
            "message_count": 0,
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
