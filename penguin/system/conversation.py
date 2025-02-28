import glob
import json
import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from penguin.config import CONVERSATION_CONFIG, WORKSPACE_PATH

logger = logging.getLogger(__name__)


def parse_iso_datetime(date_str: str) -> str:
    """Parse ISO format date string and return formatted display string"""
    try:
        # Split into date and time parts
        if "T" in date_str:
            date_str = (
                date_str.split("T")[0] + " " + date_str.split("T")[1].split(".")[0]
            )
        elif " " in date_str:
            date_str = date_str.split(".")[0]

        # Basic format check
        if len(date_str) < 16:  # Minimum "YYYY-MM-DD HH:MM"
            return date_str

        # Manual parsing
        year = date_str[0:4]
        month = date_str[5:7]
        day = date_str[8:10]
        hour = date_str[11:13]
        minute = date_str[14:16]

        return f"{year}-{month}-{day} {hour}:{minute}"
    except (IndexError, ValueError):
        return date_str


@dataclass
class ConversationMetadata:
    """Metadata for a conversation session"""

    created_at: str
    last_active: str
    message_count: int
    session_id: str
    title: Optional[str] = None
    tags: List[str] = field(default_factory=list)

    @property
    def display_date(self) -> str:
        """Get formatted display date"""
        return parse_iso_datetime(self.last_active)

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
    """Handles loading and managing conversation history."""

    def __init__(self, conversations_path: str = None):
        """Initialize the conversation loader with configurable path."""
        self.conversations_path = conversations_path or os.path.join(
            WORKSPACE_PATH, "conversations"
        )
        os.makedirs(self.conversations_path, exist_ok=True)

        # Load conversation config
        self.max_history = CONVERSATION_CONFIG.get("max_history", 1000000)
        self.auto_save = CONVERSATION_CONFIG.get("auto_save", True)
        self.save_format = CONVERSATION_CONFIG.get("save_format", "json")

    def load_conversation(
        self, conversation_id: str
    ) -> Tuple[List[Dict[str, Any]], ConversationMetadata]:
        """Load a conversation by ID with error handling and validation."""
        try:
            file_path = os.path.join(
                self.conversations_path, f"{conversation_id}.{self.save_format}"
            )

            if not os.path.exists(file_path):
                return [], ConversationMetadata(
                    created_at=datetime.now().isoformat(),
                    last_active=datetime.now().isoformat(),
                    message_count=0,
                    session_id=conversation_id,
                )

            with open(file_path, encoding="utf-8") as f:
                data = json.load(f)

            # Handle both old and new format
            if isinstance(data, dict) and "messages" in data:
                messages = data["messages"]
                metadata = data.get("metadata", {})
            else:
                messages = data
                metadata = {}

            # Create metadata object
            metadata = ConversationMetadata(
                session_id=conversation_id,
                created_at=metadata.get("created_at", datetime.now().isoformat()),
                last_active=metadata.get("last_active", datetime.now().isoformat()),
                message_count=len(messages),
                title=metadata.get("title", None),
            )

            # Update title if not set
            if not metadata.title:
                metadata.update_title_from_messages(messages)

            return messages, metadata

        except Exception as e:
            logger.error(f"Error loading conversation {conversation_id}: {str(e)}")
            raise

    def save_conversation(
        self,
        conversation_id: str,
        messages: List[Dict[str, Any]],
        metadata: Optional[ConversationMetadata] = None,
    ) -> bool:
        """Save conversation with proper error handling and validation."""
        if not self.auto_save:
            return False

        try:
            # Ensure conversation ID has proper prefix
            if not conversation_id.startswith("conversation_"):
                conversation_id = f"conversation_{conversation_id}"

            file_path = os.path.join(
                self.conversations_path, f"{conversation_id}.{self.save_format}"
            )

            # Sanitize messages to ensure they're serializable
            sanitized_messages = [
                {
                    "role": msg.get("role", ""),
                    "content": msg.get("content", ""),
                    "timestamp": msg.get("timestamp", datetime.now().isoformat()),
                }
                for msg in messages
                if isinstance(msg, dict) and msg.get("content")
            ]

            # Add metadata if provided
            data_to_save = {"messages": sanitized_messages}
            if metadata:
                data_to_save["metadata"] = asdict(metadata)

            with open(file_path, "w", encoding="utf-8") as f:
                json.dump(data_to_save, f, indent=2, ensure_ascii=False)
            return True

        except OSError as e:
            logger.error(f"Error saving conversation {conversation_id}: {str(e)}")
            return False

    def list_conversations(self) -> List[ConversationMetadata]:
        """List all available conversations with metadata."""
        try:
            # Only look for conversation_* files in the conversations directory
            pattern = os.path.join(self.conversations_path, "conversation_*.json")
            conversations = []

            for file_path in glob.glob(pattern):
                try:
                    with open(file_path, encoding="utf-8") as f:
                        data = json.load(f)

                        # Handle both old and new format
                        messages = data.get(
                            "messages", data
                        )  # If data is dict, get messages, else use data
                        metadata = data.get("metadata", {})

                        session_id = os.path.splitext(os.path.basename(file_path))[0]

                        # Parse ISO format dates manually if needed
                        created_at = metadata.get(
                            "created_at", datetime.now().isoformat()
                        )
                        last_active = metadata.get(
                            "last_active", datetime.now().isoformat()
                        )

                        metadata = ConversationMetadata(
                            session_id=session_id,
                            created_at=created_at,
                            last_active=last_active,
                            message_count=len(messages),
                            title=metadata.get("title", None),
                        )

                        # Try to extract title from messages if not in metadata
                        if not metadata.title:
                            metadata.update_title_from_messages(messages)

                        conversations.append(metadata)

                except Exception as e:
                    logger.error(f"Error reading conversation {file_path}: {str(e)}")
                    continue

            return sorted(conversations, key=lambda x: x.last_active, reverse=True)

        except Exception as e:
            logger.error(f"Error listing conversations: {str(e)}")
            return []


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
            session_id=self.session_id,
        )
        conversations_path = os.path.join(base_path, "conversations")
        self.loader = ConversationLoader(conversations_path)

    def _generate_session_id(self) -> str:
        """Generate a unique session ID"""
        return f"session_{datetime.now().strftime('%Y%m%d_%H%M%S')}"

    def save(self) -> None:
        """Save current conversation state"""
        # Update metadata
        self.metadata.last_active = datetime.now().isoformat()
        self.metadata.message_count = len(self.messages)

        # Ensure session ID has proper prefix and is in conversations directory
        if not self.session_id.startswith("conversation_"):
            self.session_id = f"conversation_{self.session_id}"

        # Save to conversations directory
        self.loader.save_conversation(self.session_id, self.messages, self.metadata)

    def load(self, session_id: str) -> None:
        """Load a saved conversation"""
        try:
            messages, metadata = self.loader.load_conversation(session_id)
            self.messages = messages
            self.metadata = metadata
            self.session_id = session_id
            self.system_prompt_sent = any(m["role"] == "system" for m in messages)
        except Exception as e:
            logger.error(f"Error loading conversation: {str(e)}")
            raise

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
            formatted_content = content  # Assume it's already a list of content parts
        else:
            formatted_content = [{"type": "text", "text": str(content)}]

        message = {"role": role, "content": formatted_content}
        self.messages.append(message)

        # Update title if this is the first user message
        if (
            role == "user"
            and len([m for m in self.messages if m["role"] == "user"]) == 1
        ):
            self.metadata.update_title_from_messages(self.messages)

        # Truncate history if it exceeds max length
        if len(self.messages) > self.max_history_length:
            # Keep system messages and trim others
            system_messages = [m for m in self.messages if m["role"] == "system"]
            other_messages = [m for m in self.messages if m["role"] != "system"]
            other_messages = other_messages[
                -self.max_history_length + len(system_messages) :
            ]
            self.messages = system_messages + other_messages

    def prepare_conversation(
        self, user_input: str, image_path: Optional[str] = None
    ) -> None:
        """Prepare the conversation by adding necessary messages."""
        if self.get_history() and self.get_last_message()["role"] == "user":
            self.add_message("assistant", "Continuing the conversation...")

        if not self.system_prompt_sent and self.system_prompt:
            system_tokens = self.diagnostics.count_tokens(self.system_prompt)
            self.diagnostics.update_tokens("system_prompt", system_tokens, 0)
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
                    "image_url": {"url": f"data:image/jpeg;base64,{base64_image}"},
                },
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
        self.add_message(
            "system",
            {
                "type": "summary_note",
                "category": category,
                "content": content,
                "timestamp": datetime.now().isoformat(),
            },
        )

    def reset(self):
        """Reset the conversation state"""
        self.messages = []
        self.system_prompt_sent = False

    def add_iteration_marker(self, iteration: int, max_iterations: int) -> None:
        """Add a marker for the start of a new iteration in the multi-step process."""
        self.add_message(
            "system",
            f"--- Beginning iteration {iteration}/{max_iterations} ---"
        )
