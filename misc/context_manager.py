"""
ContextManager for Penguin AI Assistant.

This module provides context window management to prevent token limits from being exceeded
during conversations with LLM models. It includes intelligent message truncation,
summarization, and priority-based retention to maintain the most important context
within token limits.
"""

import logging
import re
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Set, Tuple, Union

import tiktoken  # For token counting

logger = logging.getLogger(__name__)


class MessageRole(Enum):
    """Enum representing different message roles in a conversation."""
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"  # For tool outputs/results


class MessagePriority(Enum):
    """Priority levels for messages in the context window."""
    CRITICAL = 100  # System prompts, current user query
    HIGH = 80       # Recent interactions, important context
    MEDIUM = 50     # Regular conversation turns
    LOW = 20        # Older messages, less relevant context
    VERY_LOW = 10   # Candidates for early removal


@dataclass
class Message:
    """Represents a message in the context with metadata for management."""
    role: MessageRole
    content: Union[str, List[Dict[str, Any]]]
    priority: MessagePriority
    created_at: datetime
    tokens: int = 0
    metadata: Optional[Dict[str, Any]] = None
    iteration: Optional[int] = None
    message_id: Optional[str] = None
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dict format for LLM API."""
        return {
            "role": self.role.value,
            "content": self.content
        }


class ContextManager:
    """
    Manages conversation context to stay within token limits.
    
    This class handles the maintenance of conversation history,
    ensuring it stays within the token limits of the model while
    preserving the most important context.
    """
    
    def __init__(
        self,
        max_tokens: int = 200000,
        reserved_tokens: int = 4000,  # Reserve space for model response
        encoding_name: str = "cl100k_base",  # Claude/GPT-4 encoding
        system_prompt: str = "",
    ):
        """
        Initialize the ContextManager.
        
        Args:
            max_tokens: Maximum tokens allowed in context window
            reserved_tokens: Tokens to reserve for model response
            encoding_name: The name of the tokenizer encoding to use
            system_prompt: The system prompt to use for the conversation
        """
        self.max_tokens = max_tokens
        self.reserved_tokens = reserved_tokens
        self.available_tokens = max_tokens - reserved_tokens
        self.current_token_count = 0
        
        # Setup tokenizer
        try:
            self.tokenizer = tiktoken.get_encoding(encoding_name)
        except Exception as e:
            logger.warning(f"Could not load {encoding_name} tokenizer: {e}")
            # Fallback to approximate token counting
            self.tokenizer = None
        
        # Initialize message store with sections
        self.all_messages: List[Message] = []
        self.system_messages: List[Message] = []
        self.user_messages: List[Message] = []
        self.assistant_messages: List[Message] = []
        self.tool_messages: List[Message] = []
        
        # Track iteration boundaries
        self.iteration_markers: Dict[int, int] = {}
        
        # Set system prompt if provided
        if system_prompt:
            self.set_system_prompt(system_prompt)
    
    def count_tokens(self, text: Union[str, List, Dict]) -> int:
        """
        Count tokens in text using the tokenizer or approximation.
        
        Args:
            text: Text or structured content to count tokens for
            
        Returns:
            Number of tokens in the text
        """
        if text is None:
            return 0
            
        # Convert to string for token counting if needed
        if isinstance(text, (list, dict)):
            # Handle structured content (e.g., for Claude/OpenAI format)
            if isinstance(text, list) and all(isinstance(item, dict) for item in text):
                # This is likely a message content array with text/image parts
                combined_text = ""
                for item in text:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            combined_text += item.get("text", "")
                        # Images typically have fixed token counts, could add estimates
                text = combined_text
            else:
                # For other structured content, convert to string
                text = str(text)
        
        # Use tiktoken if available
        if self.tokenizer and isinstance(text, str):
            try:
                tokens = len(self.tokenizer.encode(text))
                return tokens
            except Exception as e:
                logger.warning(f"Error counting tokens with tokenizer: {e}")
        
        # Fallback approximate count (4 chars per token is rough approximation)
        if isinstance(text, str):
            return len(text) // 4 + 1
        
        # For unknown types
        return 50  # Default estimate
    
    def set_system_prompt(self, prompt: str) -> None:
        """
        Set or update the system prompt with highest priority.
        
        Args:
            prompt: The system prompt text
        """
        # Remove any existing system prompts
        self.system_messages = [msg for msg in self.system_messages 
                               if msg.metadata and msg.metadata.get("type") != "system_prompt"]
        
        # Count tokens
        tokens = self.count_tokens(prompt)
        
        # Create new system prompt message
        system_prompt_msg = Message(
            role=MessageRole.SYSTEM,
            content=prompt,
            priority=MessagePriority.CRITICAL,
            created_at=datetime.now(),
            tokens=tokens,
            metadata={"type": "system_prompt", "permanent": True}
        )
        
        # Add to system messages
        self.system_messages.append(system_prompt_msg)
        
        # Update token count
        self.recalculate_token_count()
    
    def add_message(
        self,
        role: Union[str, MessageRole],
        content: Union[str, List[Dict[str, Any]]],
        priority: Union[str, MessagePriority] = MessagePriority.MEDIUM,
        metadata: Optional[Dict[str, Any]] = None,
        iteration: Optional[int] = None
    ) -> Message:
        """
        Add a message to the context.
        
        Args:
            role: The role of the message sender
            content: The message content
            priority: Priority level for this message
            metadata: Additional metadata for the message
            iteration: Which multi-step iteration this belongs to
            
        Returns:
            The created Message object
        """
        # Convert string role to enum if needed
        if isinstance(role, str):
            try:
                role = MessageRole(role)
            except ValueError:
                # Default to system if invalid role
                role = MessageRole.SYSTEM
        
        # Convert string priority to enum if needed
        if isinstance(priority, str):
            try:
                priority = MessagePriority[priority.upper()]
            except KeyError:
                # Default to medium priority
                priority = MessagePriority.MEDIUM
        
        # Count tokens
        tokens = self.count_tokens(content)
        
        # Create message
        message = Message(
            role=role,
            content=content,
            priority=priority,
            created_at=datetime.now(),
            tokens=tokens,
            metadata=metadata or {},
            iteration=iteration,
            message_id=f"msg_{datetime.now().timestamp()}"
        )
        
        # Add to appropriate message list
        if role == MessageRole.SYSTEM:
            self.system_messages.append(message)
        elif role == MessageRole.USER:
            self.user_messages.append(message)
        elif role == MessageRole.ASSISTANT:
            self.assistant_messages.append(message)
        elif role == MessageRole.TOOL:
            self.tool_messages.append(message)
        
        # Update all messages list and token count
        self.all_messages.append(message)
        self.current_token_count += tokens
        
        # Check if we need to trim context
        if self.current_token_count > self.available_tokens:
            self.trim_context()
        
        return message
    
    def add_user_message(
        self, 
        content: Union[str, List[Dict[str, Any]]],
        priority: MessagePriority = MessagePriority.HIGH
    ) -> Message:
        """Add a user message with preset priority."""
        return self.add_message(MessageRole.USER, content, priority)
    
    def add_assistant_message(
        self, 
        content: Union[str, List[Dict[str, Any]]],
        priority: MessagePriority = MessagePriority.MEDIUM
    ) -> Message:
        """Add an assistant message with preset priority."""
        return self.add_message(MessageRole.ASSISTANT, content, priority)
    
    def add_tool_message(
        self, 
        content: Union[str, List[Dict[str, Any]]],
        priority: MessagePriority = MessagePriority.MEDIUM,
        tool_name: Optional[str] = None
    ) -> Message:
        """Add a tool result message with preset priority."""
        metadata = {"tool_name": tool_name} if tool_name else {}
        return self.add_message(MessageRole.TOOL, content, priority, metadata)
    
    def add_system_message(
        self, 
        content: str,
        priority: MessagePriority = MessagePriority.HIGH,
        permanent: bool = False,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """Add a system message with preset priority."""
        # Create metadata dict with permanent flag
        meta = metadata or {}
        meta["permanent"] = permanent
        return self.add_message(MessageRole.SYSTEM, content, priority, meta)
    
    def add_iteration_marker(self, iteration: int, max_iterations: int) -> Message:
        """
        Add a marker message for a new iteration in multi-step reasoning.
        
        Args:
            iteration: The iteration number
            max_iterations: The maximum number of iterations
            
        Returns:
            The marker message
        """
        # Create marker message
        content = f"--- Beginning iteration {iteration}/{max_iterations} ---"
        
        # Create metadata dictionary
        meta = {"type": "iteration_marker", "iteration": iteration}
        
        # Add the system message
        marker = self.add_system_message(
            content=content,
            priority=MessagePriority.HIGH,
            metadata=meta
        )
        
        # Store the index of this marker in our iteration tracking
        self.iteration_markers[iteration] = len(self.get_messages_for_llm()) - 1
        
        return marker
    
    def add_action_result(
        self, 
        action_type: str, 
        result: str,
        status: str,
        iteration: Optional[int] = None
    ) -> Message:
        """
        Add an action result with appropriate formatting.
        
        Args:
            action_type: The type of action that was executed
            result: The result of the action
            status: Status of the action (completed, error, etc.)
            iteration: Which iteration this action belongs to
            
        Returns:
            The created Message object
        """
        content = f"Action: {action_type}\nResult: {result}\nStatus: {status}"
        return self.add_message(
            role=MessageRole.TOOL,
            content=content,
            priority=MessagePriority.HIGH,
            metadata={"action_type": action_type, "status": status},
            iteration=iteration
        )
    
    def get_messages_for_llm(self) -> List[Dict[str, Any]]:
        """
        Get all messages formatted for the LLM API.
        
        Returns:
            List of message dictionaries in LLM API format
        """
        all_messages = []
        
        # Add messages in correct order (system, then chronological user/assistant/tool)
        # First add system messages
        for msg in self.system_messages:
            all_messages.append(msg.to_dict())
        
        # Then add other messages in chronological order
        other_messages = sorted(
            self.user_messages + self.assistant_messages + self.tool_messages,
            key=lambda x: x.created_at
        )
        
        for msg in other_messages:
            all_messages.append(msg.to_dict())
        
        return all_messages
    
    def get_iteration_context(self, iteration: int) -> List[Dict[str, Any]]:
        """
        Get messages specific to a particular iteration.
        
        Args:
            iteration: The iteration number to get context for
            
        Returns:
            List of messages for that iteration in LLM API format
        """
        if iteration not in self.iteration_markers:
            # If we don't have this iteration marked, return all messages
            return self.get_messages_for_llm()
        
        # Get start index for this iteration
        start_idx = self.iteration_markers[iteration]
        
        # Get end index (next iteration or end of messages)
        end_idx = None
        for i in range(iteration + 1, max(self.iteration_markers.keys()) + 1):
            if i in self.iteration_markers:
                end_idx = self.iteration_markers[i]
                break
        
        # Get all messages
        all_messages = self.get_messages_for_llm()
        
        # Always include system messages (they're already at the beginning)
        system_count = len(self.system_messages)
        
        # Get slice of messages for this iteration, ensuring system messages are included
        if end_idx is not None:
            return all_messages[:system_count] + all_messages[start_idx:end_idx]
        else:
            return all_messages[:system_count] + all_messages[start_idx:]
    
    def recalculate_token_count(self) -> int:
        """
        Recalculate the total token count for all messages.
        
        Returns:
            Updated token count
        """
        total = 0
        for message in self.all_messages:
            # Recalculate tokens if needed
            if message.tokens == 0:
                message.tokens = self.count_tokens(message.content)
            total += message.tokens
        
        self.current_token_count = total
        return total
    
    def trim_context(self) -> None:
        """
        Trim the context to fit within token limits using priority-based removal.
        
        This method removes messages based on priority, keeping high-priority
        messages and removing low-priority ones until we're under the token limit.
        """
        if self.current_token_count <= self.available_tokens:
            return
        
        logger.info(f"Trimming context: current={self.current_token_count}, limit={self.available_tokens}")
        
        # Sort messages by priority (lowest first) and then by creation time (oldest first)
        # Exclude permanent messages
        messages_to_consider = [
            msg for msg in self.all_messages 
            if not (msg.metadata and msg.metadata.get("permanent", False))
        ]
        
        messages_to_consider.sort(
            key=lambda x: (x.priority.value, x.created_at.timestamp())
        )
        
        tokens_to_remove = self.current_token_count - self.available_tokens
        tokens_removed = 0
        messages_to_remove = set()
        
        # Remove messages until we're under the limit
        for msg in messages_to_consider:
            if tokens_removed >= tokens_to_remove:
                break
                
            messages_to_remove.add(msg.message_id)
            tokens_removed += msg.tokens
            
            logger.debug(f"Removing message: priority={msg.priority.name}, tokens={msg.tokens}")
        
        # Actually remove the messages from our lists
        self._remove_messages(messages_to_remove)
        
        # Recalculate token count
        self.recalculate_token_count()
        
        logger.info(f"After trimming: messages={len(self.all_messages)}, tokens={self.current_token_count}")
    
    def _remove_messages(self, message_ids: Set[str]) -> None:
        """
        Remove messages with the given IDs from all message lists.
        
        Args:
            message_ids: Set of message IDs to remove
        """
        self.all_messages = [msg for msg in self.all_messages if msg.message_id not in message_ids]
        self.system_messages = [msg for msg in self.system_messages if msg.message_id not in message_ids]
        self.user_messages = [msg for msg in self.user_messages if msg.message_id not in message_ids]
        self.assistant_messages = [msg for msg in self.assistant_messages if msg.message_id not in message_ids]
        self.tool_messages = [msg for msg in self.tool_messages if msg.message_id not in message_ids]
    
    def clear(self) -> None:
        """Clear all messages except permanent ones (like system prompt)."""
        permanent_messages = [
            msg for msg in self.all_messages 
            if msg.metadata and msg.metadata.get("permanent", False)
        ]
        
        self.all_messages = permanent_messages
        self.system_messages = [msg for msg in permanent_messages if msg.role == MessageRole.SYSTEM]
        self.user_messages = []
        self.assistant_messages = []
        self.tool_messages = []
        self.iteration_markers = {}
        
        self.recalculate_token_count()
    
    def summarize_conversation(self) -> str:
        """
        Generate a summary of the current conversation.
        
        Returns:
            String summary of the conversation state
        """
        summary = []
        summary.append(f"Context Stats:")
        summary.append(f"- Total messages: {len(self.all_messages)}")
        summary.append(f"- System messages: {len(self.system_messages)}")
        summary.append(f"- User messages: {len(self.user_messages)}")
        summary.append(f"- Assistant messages: {len(self.assistant_messages)}")
        summary.append(f"- Tool messages: {len(self.tool_messages)}")
        summary.append(f"- Token count: {self.current_token_count}/{self.available_tokens}")
        
        if self.iteration_markers:
            summary.append(f"- Iterations: {len(self.iteration_markers)}")
            summary.append(f"- Current iteration: {max(self.iteration_markers.keys())}")
        
        return "\n".join(summary)