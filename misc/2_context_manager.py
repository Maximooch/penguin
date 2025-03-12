"""
ContextManager for Penguin AI Assistant.

Manages context window by prioritizing different message types:
1. System messages (system prompts, declarative notes) - never truncated
2. Working memory (documents and context)
3. Conversational memory (user/assistant exchanges)
4. Tool memory (tool calls and results)
"""

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional, Union

# Optional - can be replaced with approximation method for multiple providers
try:
    import tiktoken # type: ignore
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False

logger = logging.getLogger(__name__)


class MessageCategory(Enum):
    """Categories of messages for prioritization"""
    SYSTEM_PROMPT = 1        # Highest priority - never truncated
    DECLARATIVE_NOTES = 2    # Important context
    WORKING_MEMORY = 3       # Documents and references
    CONVERSATION = 4         # User/assistant exchanges
    TOOL_MEMORY = 5          # Tool calls and results


@dataclass
class Message:
    """Message with category and metadata for prioritization"""
    role: str
    content: Union[str, List[Dict[str, Any]]]
    category: MessageCategory
    created_at: datetime
    tokens: int = 0
    metadata: Optional[Dict[str, Any]] = None
    
    def to_dict(self):
        """Convert to API format"""
        return {
            "role": self.role,
            "content": self.content
        }


class ContextManager:
    """
    Manages conversation context with category-based prioritization.
    
    Maintains different categories of messages and prioritizes them when
    token limits are exceeded, keeping the most important context.
    """
    
    def __init__(
        self,
        model_config=None,
        default_category_allocations=None
    ):
        # Determine max tokens from model config or use default
        self.max_tokens = 128000  # Default
        if model_config:
            self.max_tokens = model_config.max_tokens or self.max_tokens
        
        # Default allocation percentages for each category
        self.category_allocations = default_category_allocations or {
            MessageCategory.SYSTEM_PROMPT: 0.15,     # 15% of context - never truncated
            MessageCategory.DECLARATIVE_NOTES: 0.20, # 20% of context
            MessageCategory.WORKING_MEMORY: 0.20,    # 20% of context
            MessageCategory.CONVERSATION: 0.30,      # 30% of context
            MessageCategory.TOOL_MEMORY: 0.15        # 15% of context
        }
        
        # Calculate tokens reserved for response (10% of max)
        self.reserved_tokens = int(self.max_tokens * 0.1)
        self.available_tokens = self.max_tokens - self.reserved_tokens
        self.current_token_count = 0
        
        # Initialize tokenizer if available
        self.tokenizer = None
        if TOKENIZER_AVAILABLE:
            try:
                self.tokenizer = tiktoken.get_encoding("cl100k_base")
            except Exception as e:
                logger.warning(f"Could not load tokenizer: {e}")
        
        # Message storage by category
        self.messages = {
            MessageCategory.SYSTEM_PROMPT: [],
            MessageCategory.DECLARATIVE_NOTES: [],
            MessageCategory.WORKING_MEMORY: [],
            MessageCategory.CONVERSATION: [],
            MessageCategory.TOOL_MEMORY: []
        }
        
        # All messages in chronological order
        self.all_messages = []
    
    def count_tokens(self, text: Union[str, List, Dict]) -> int:
        """Count tokens in text using tokenizer or approximation"""
        if text is None:
            return 0
            
        # Convert structured content to string
        if isinstance(text, (list, dict)):
            text = str(text)
        
        # Use tokenizer if available
        if self.tokenizer and isinstance(text, str):
            try:
                return len(self.tokenizer.encode(text))
            except Exception:
                pass
        
        # Fallback approximation (4 chars per token)
        if isinstance(text, str):
            return len(text) // 4 + 1
        
        return 50  # Default estimate
    
    def add_message(
        self,
        role: str,
        content: Union[str, List[Dict[str, Any]]],
        category: MessageCategory,
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """Add a message with specified category"""
        tokens = self.count_tokens(content)
        
        message = Message(
            role=role,
            content=content,
            category=category,
            created_at=datetime.now(),
            tokens=tokens,
            metadata=metadata or {}
        )
        
        # Add to category and all messages
        self.messages[category].append(message)
        self.all_messages.append(message)
        
        # Update token count
        self.current_token_count += tokens
        
        # Check if need to trim context
        if self.current_token_count > self.available_tokens:
            self.trim_context()
        
        return message
    
    def set_system_prompt(self, prompt: str) -> Message:
        """Set or update the system prompt"""
        # Remove any existing system prompts
        self.messages[MessageCategory.SYSTEM_PROMPT] = [
            msg for msg in self.messages[MessageCategory.SYSTEM_PROMPT]
            if msg.metadata and msg.metadata.get("type") != "system_prompt"
        ]
        
        # Update all_messages list
        self.all_messages = [
            msg for msg in self.all_messages
            if not (msg.category == MessageCategory.SYSTEM_PROMPT and 
                   msg.metadata and msg.metadata.get("type") == "system_prompt")
        ]
        
        # Create new system prompt message
        return self.add_message(
            role="system",
            content=prompt,
            category=MessageCategory.SYSTEM_PROMPT,
            metadata={"type": "system_prompt", "permanent": True}
        )
    
    def add_declarative_note(self, content: str, metadata=None) -> Message:
        """Add a declarative note"""
        meta = metadata or {}
        meta["type"] = "declarative_note"
        return self.add_message(
            role="system",
            content=content,
            category=MessageCategory.DECLARATIVE_NOTES,
            metadata=meta
        )
    
    def add_working_memory(self, content: str, source=None) -> Message:
        """Add content to working memory"""
        metadata = {"source": source} if source else {}
        return self.add_message(
            role="system",
            content=content,
            category=MessageCategory.WORKING_MEMORY,
            metadata=metadata
        )
    
    def add_user_message(self, content: Union[str, List[Dict[str, Any]]]) -> Message:
        """Add a user message"""
        return self.add_message(
            role="user",
            content=content,
            category=MessageCategory.CONVERSATION
        )
    
    def add_assistant_message(self, content: Union[str, List[Dict[str, Any]]]) -> Message:
        """Add an assistant message"""
        return self.add_message(
            role="assistant",
            content=content,
            category=MessageCategory.CONVERSATION
        )
    
    def add_tool_message(self, content: Union[str, List[Dict[str, Any]]], tool_name=None) -> Message:
        """Add a tool result message"""
        metadata = {"tool_name": tool_name} if tool_name else {}
        return self.add_message(
            role="tool",
            content=content,
            category=MessageCategory.TOOL_MEMORY,
            metadata=metadata
        )
    
    def trim_context(self) -> None:
        """
        Trim context based on category allocations.
        Preserves system prompt and prioritizes other categories by allocation.
        """
        if self.current_token_count <= self.available_tokens:
            return
        
        logger.info(f"Trimming context: {self.current_token_count}/{self.available_tokens}")
        
        # Calculate total tokens used by system prompts (which we never truncate)
        system_prompt_tokens = sum(msg.tokens for msg in self.messages[MessageCategory.SYSTEM_PROMPT])
        
        # Calculate tokens that can be allocated to other categories
        remaining_tokens = self.available_tokens - system_prompt_tokens
        
        # If remaining tokens are negative, we can't fit everything
        if remaining_tokens <= 0:
            logger.warning("System prompts exceed available token limit!")
            remaining_tokens = max(remaining_tokens, 0)
        
        # Calculate target tokens for each category based on allocations
        total_non_system_allocation = sum(
            self.category_allocations[cat] for cat in self.category_allocations
            if cat != MessageCategory.SYSTEM_PROMPT
        )
        
        target_tokens = {}
        for category in self.category_allocations:
            if category == MessageCategory.SYSTEM_PROMPT:
                # System prompts are never truncated
                target_tokens[category] = system_prompt_tokens
            else:
                # Calculate proportional allocation for this category
                proportion = self.category_allocations[category] / total_non_system_allocation
                target_tokens[category] = int(remaining_tokens * proportion)
        
        # For each category, trim messages if they exceed their allocation
        for category in [
            MessageCategory.TOOL_MEMORY,
            MessageCategory.CONVERSATION,  
            MessageCategory.WORKING_MEMORY,
            MessageCategory.DECLARATIVE_NOTES,
            # System prompt is preserved
        ]:
            current_category_tokens = sum(msg.tokens for msg in self.messages[category])
            
            # Skip if under target or no messages
            if current_category_tokens <= target_tokens[category] or not self.messages[category]:
                continue
                
            # Sort messages by creation time (oldest first)
            sorted_msgs = sorted(self.messages[category], key=lambda x: x.created_at)
            
            # Remove oldest messages until under target
            tokens_to_remove = current_category_tokens - target_tokens[category]
            tokens_removed = 0
            removal_msgs = []
            
            for msg in sorted_msgs:
                if tokens_removed >= tokens_to_remove:
                    break
                removal_msgs.append(msg)
                tokens_removed += msg.tokens
                logger.debug(f"Removing {category.name} message: {tokens_removed}/{tokens_to_remove}")
            
            # Update lists
            for msg in removal_msgs:
                self.messages[category].remove(msg)
                if msg in self.all_messages:
                    self.all_messages.remove(msg)
        
        # Recalculate token count
        self.current_token_count = sum(msg.tokens for msg in self.all_messages)
    
    def get_messages_for_api(self) -> List[Dict[str, Any]]:
        """Get formatted messages for API request"""
        api_messages = []
        
        # Add system messages first (never truncated)
        for msg in self.messages[MessageCategory.SYSTEM_PROMPT]:
            api_messages.append(msg.to_dict())
        
        # Add declarative notes next
        for msg in self.messages[MessageCategory.DECLARATIVE_NOTES]:
            api_messages.append(msg.to_dict())
        
        # Add working memory
        for msg in self.messages[MessageCategory.WORKING_MEMORY]:
            api_messages.append(msg.to_dict())
        
        # Add conversation and tool messages in chronological order
        conversation_messages = sorted(
            self.messages[MessageCategory.CONVERSATION] + 
            self.messages[MessageCategory.TOOL_MEMORY],
            key=lambda x: x.created_at
        )
        
        for msg in conversation_messages:
            api_messages.append(msg.to_dict())
        
        return api_messages
    
    async def request_summary(self, api_client, messages, max_tokens=500, temperature=0.3):
        """
        Request a summary of messages using the API client.
        
        Args:
            api_client: The API client to use
            messages: Messages to summarize
            max_tokens: Maximum tokens for summary
            temperature: Temperature setting for generation
            
        Returns:
            Summary text string
        """
        # Construct a summary request prompt
        summary_prompt = (
            "Summarize the key points of the following conversation. "
            "Focus on important facts, decisions, and context that would be "
            "needed to continue the conversation effectively:"
        )
        
        # Format message content for summarization
        message_content = "\n\n".join([
            f"{msg['role']}: {msg['content']}" 
            for msg in messages
        ])
        
        # Create summary request messages
        summary_request = [
            {"role": "system", "content": summary_prompt},
            {"role": "user", "content": message_content}
        ]
        
        # Get summary from API
        response = await api_client.create_message(
            messages=summary_request,
            max_tokens=max_tokens,
            temperature=temperature
        )
        
        # Process response to extract summary
        summary_text, _ = api_client.process_response(response)
        return summary_text