# This code is not yet implemented, just a placeholder for now

"""
Context window management for managing token budgets and content trimming.

This module provides tools to:
1. Track token usage across different message categories
2. Manage trimming strategies based on content types
3. Handle special content types like images
4. Ensure context windows don't exceed model limits
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Union, Any, Callable, Tuple

from penguin.system.state import Message, MessageCategory, Session

logger = logging.getLogger(__name__)

@dataclass
class TokenBudget:
    """Token budget for a message category"""
    # Minimum tokens guaranteed for this category
    min_tokens: int
    # Maximum tokens this category can consume
    max_tokens: int
    # Current tokens used by this category
    current_tokens: int = 0
    
    def __post_init__(self):
        # Ensure min_tokens <= max_tokens
        if self.min_tokens > self.max_tokens:
            logger.warning(f"min_tokens ({self.min_tokens}) > max_tokens ({self.max_tokens}). Setting min_tokens = max_tokens")
            self.min_tokens = self.max_tokens

class ContextWindowManager:
    """Manages token budgeting and content trimming for conversation context"""
    
    def __init__(
        self,
        model_config = None,
        token_counter: Optional[Callable[[Any], int]] = None
    ):
        """
        Initialize the context window manager.
        
        Args:
            model_config: Optional model configuration with max_tokens
            token_counter: Function to count tokens for content
        """
        # Get max_tokens from model_config if available
        self.max_tokens = 100000  # Default fallback
        
        if model_config and hasattr(model_config, 'max_tokens') and model_config.max_tokens:
            self.max_tokens = model_config.max_tokens
            logger.info(f"Using model's max_tokens: {self.max_tokens}")
        
        # Try to load from config.yml if available
        try:
            from penguin.config import config
            if 'model_configs' in config:
                model_name = model_config.model if model_config and hasattr(model_config, 'model') else None
                if model_name and model_name in config['model_configs'] and 'max_tokens' in config['model_configs'][model_name]:
                    config_max_tokens = config['model_configs'][model_name]['max_tokens']
                    if config_max_tokens:
                        self.max_tokens = config_max_tokens
                        logger.info(f"Using config.yml max_tokens for {model_name}: {self.max_tokens}")
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not load config.yml for max_tokens: {e}")
            
        self.token_counter = token_counter or self._default_token_counter
        self._budgets = {}
        self._initialize_token_budgets()
        
    def _default_token_counter(self, content: Any) -> int:
        """Default token counter when none is provided"""
        # This is a very simplistic fallback that should rarely be used
        if isinstance(content, str):
            return len(content) // 4
        elif isinstance(content, list):
            # Handle potential image content with more realistic estimates
            total = 0
            for item in content:
                if isinstance(item, dict) and item.get("type") in ["image", "image_url"]:
                    # Much more realistic image token estimates - Claude models use ~4000 tokens per image
                    total += 4000  # Higher default for safety
                elif isinstance(item, dict) and "text" in item:
                    total += len(item["text"]) // 4
                else:
                    total += len(str(item)) // 4
            return total
        else:
            return len(str(content)) // 4
        
    def _initialize_token_budgets(self):
        """Initialize default token budgets for different message categories"""
        total_budget = self.max_tokens
        
        # Default allocation percentages (can be made configurable)
        allocations = {
            MessageCategory.SYSTEM: 0.10,     # 10% - highest priority (only system prompt)
            MessageCategory.CONTEXT: 0.35,    # 35% - high priority
            MessageCategory.DIALOG: 0.50,     # 50% - medium priority
            MessageCategory.SYSTEM_OUTPUT: 0.05  # 5% - lowest priority (renamed from ACTIONS)
        }
        # This needs room for large messages, like images, audio, and files. 
        # It also needs to be dynamic based on letting some categories have more budget than others until they are full?
        
        # Create token budgets based on percentages
        for category, percentage in allocations.items():
            budget = int(total_budget * percentage)
            
            # Only system messages need a minimum guarantee
            min_tokens = 1000 if category == MessageCategory.SYSTEM else 0
            
            self._budgets[category] = TokenBudget(
                min_tokens=min_tokens,
                max_tokens=budget,
                current_tokens=0
            )
    
    @property
    def total_budget(self) -> int:
        """Get the total token budget"""
        return self.max_tokens
    
    @property
    def available_tokens(self) -> int:
        """Get the number of available tokens"""
        used_tokens = sum(budget.current_tokens for budget in self._budgets.values())
        return max(0, self.max_tokens - used_tokens)
    
    def get_budget(self, category: MessageCategory) -> TokenBudget:
        """Get the token budget for a specific category"""
        return self._budgets.get(category)
    
    def update_usage(self, category: MessageCategory, tokens: int) -> None:
        """Update token usage for a category"""
        if category in self._budgets:
            self._budgets[category].current_tokens += tokens
            
    def reset_usage(self, category: Optional[MessageCategory] = None) -> None:
        """Reset token usage for a category or all categories"""
        if category:
            if category in self._budgets:
                self._budgets[category].current_tokens = 0
        else:
            for budget in self._budgets.values():
                budget.current_tokens = 0
                
    def is_over_budget(self, category: Optional[MessageCategory] = None) -> bool:
        """Check if a category or the entire context is over budget"""
        if category:
            return self._budgets[category].current_tokens > self._budgets[category].max_tokens
        
        return sum(budget.current_tokens for budget in self._budgets.values()) > self.max_tokens
    
    def analyze_session(self, session: Session) -> Dict[str, Any]:
        """
        Analyze a session for token usage statistics and multimodal content.
        
        Args:
            session: Session object containing messages
            
        Returns:
            Dict with token counts, image counts, and other statistics
        """
        total_tokens = 0
        per_category_tokens = {category: 0 for category in MessageCategory}
        image_count = 0
        
        for msg in session.messages:
            category = msg.category
            content = msg.content
            
            # Use existing token count or calculate new one
            token_count = msg.tokens
            if token_count == 0:
                token_count = self.token_counter(content)
                # Update message token count for future reference
                msg.tokens = token_count
                
            total_tokens += token_count
            
            # Count images in multimodal content
            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict) and part.get("type") in ["image", "image_url"]:
                        image_count += 1
            
            # Update per-category counts
            if category in per_category_tokens:
                per_category_tokens[category] += token_count
                
        # Add a warning log if there are multiple images
        if image_count > 1:
            logger.warning(f"Multiple images detected ({image_count}). This may consume significant token budget.")
        
        return {
            "total_tokens": total_tokens,
            "per_category": per_category_tokens,
            "image_count": image_count,
            "over_budget": total_tokens > self.max_tokens,
            "message_count": len(session.messages)
        }
    
    def trim_session(self, session: Session, preserve_recency: bool = True) -> Session:
        """
        Trim session messages to fit within token budget.
        
        Args:
            session: Session object to trim
            preserve_recency: Whether to prioritize keeping recent messages
            
        Returns:
            New Session object with trimmed messages
        """
        if not session.messages:
            return session
            
        # Create a new session to avoid modifying the original
        # This maintains immutability principles
        result_session = Session(
            id=session.id,
            created_at=session.created_at,
            last_active=session.last_active,
            metadata=session.metadata.copy()
        )
            
        # Analyze current message state
        stats = self.analyze_session(session)
        
        # If we're under budget, no trimming needed
        if not stats["over_budget"]:
            result_session.messages = [msg for msg in session.messages]
            return result_session
            
        # Special handling for images - they consume many tokens
        if stats["image_count"] > 1:
            # First pass: handle images separately
            session_with_image_placeholders = self._handle_image_trimming(session)
            
            # Re-analyze after image trimming
            stats = self.analyze_session(session_with_image_placeholders)
            if not stats["over_budget"]:
                return session_with_image_placeholders
                
            # Continue with the image-trimmed session
            session = session_with_image_placeholders
        
        # Group messages by category
        categorized = {}
        for category in MessageCategory:
            categorized[category] = [
                msg for msg in session.messages 
                if msg.category == category
            ]
            
        # Get the order for trimming based on our priority (from lowest to highest priority)
        # ACTIONS (4) trimmed first, then DIALOG (3), then CONTEXT (2), then SYSTEM (1)
        trim_order = [
            MessageCategory.SYSTEM_OUTPUT,   # Trim first - lowest priority
            MessageCategory.DIALOG,    # Trim second
            MessageCategory.CONTEXT,   # Trim third
            MessageCategory.SYSTEM     # NEVER TRIM SYSTEM PROMPT- highest priority
        ]
            
        # Trim categories in priority order
        for category in trim_order:
            budget = self._budgets.get(category)
            category_msgs = categorized[category]
            category_tokens = stats["per_category"].get(category, 0)
            
            # If this category is over its budget, trim it
            if category_tokens > budget.max_tokens:
                excess = category_tokens - budget.min_tokens
                
                if preserve_recency:
                    # Sort oldest first for trimming
                    category_msgs.sort(key=lambda m: m.timestamp)
                    
                # Trim messages until we're under budget
                remaining_msgs = []
                tokens_to_remove = excess
                for msg in category_msgs:
                    msg_tokens = msg.tokens or self.token_counter(msg.content)
                    
                    if tokens_to_remove > 0 and msg_tokens <= tokens_to_remove:
                        # Skip this message (trim it)
                        tokens_to_remove -= msg_tokens
                    else:
                        remaining_msgs.append(msg)
                        
                # Replace the category's messages with trimmed version
                categorized[category] = remaining_msgs
        
        # Reconstruct the message list preserving original order
        # We'll use a dictionary to track which messages to keep
        kept_messages = {}
        for category in MessageCategory:
            for msg in categorized[category]:
                kept_messages[msg.id] = msg
                
        # Build the result session maintaining original order
        result_session.messages = [msg for msg in session.messages if msg.id in kept_messages]
        
        # Update message counts in metadata
        result_session.metadata["message_count"] = len(result_session.messages)
        dialog_count = sum(1 for msg in result_session.messages 
                          if msg.category == MessageCategory.DIALOG)
        result_session.metadata["dialog_message_count"] = dialog_count
                
        return result_session
    
    def _contains_image(self, content: Any) -> bool:
        """Check if content contains an image."""
        if not isinstance(content, list):
            return False
        return any(isinstance(part, dict) and 
                  (part.get("type") in ["image", "image_url"] or 
                   "image_path" in part)
                  for part in content)
                
    def _create_placeholder_message(self, msg: Message) -> Message:
        """Create a message with image replaced by placeholder text."""
        if not isinstance(msg.content, list):
            return msg
            
        new_content = []
        for part in msg.content:
            if isinstance(part, dict) and part.get("type") in ["image", "image_url"]:
                url_ref = part.get("image_url") or part.get("image_path")
                new_part = {"type": "text", "text": "[Image removed to save tokens]"}
                if url_ref:
                    new_part["metadata"] = {"original_image_reference": url_ref}
                new_content.append(new_part)
            else:
                new_content.append(part)
        
        return Message(
            role=msg.role,
            content=new_content,
            category=msg.category,
            id=msg.id,
            timestamp=msg.timestamp,
            metadata={**msg.metadata, "image_replaced": True},
            tokens=self.token_counter(new_content)
        )
    
    def _handle_image_trimming(self, session: Session) -> Session:
        """
        Replace all but the most recent image with placeholders.
        
        Args:
            session: Session object with messages
            
        Returns:
            New Session with image content trimmed
        """
        if not session.messages:
            return session
            
        # Find messages with images
        image_messages = [(i, msg) for i, msg in enumerate(session.messages) 
                          if self._contains_image(msg.content)]
        
        # Nothing to trim if 0-1 images
        if len(image_messages) <= 1:
            return Session(
                id=session.id,
                created_at=session.created_at,
                last_active=session.last_active,
                metadata=session.metadata.copy(),
                messages=[msg for msg in session.messages]
            )
        
        # Keep most recent image intact
        image_messages.sort(key=lambda x: x[1].timestamp)
        most_recent_msg = image_messages[-1][1]
        
        # Create result with replaced images
        result = Session(
            id=session.id,
            created_at=session.created_at,
            last_active=session.last_active,
            metadata=session.metadata.copy()
        )
        
        # Process each message
        for msg in session.messages:
            if msg.id != most_recent_msg.id and self._contains_image(msg.content):
                # Replace image with placeholder
                result.messages.append(self._create_placeholder_message(msg))
            else:
                # Keep message as is
                result.messages.append(msg)
        
        return result
    
    def get_current_allocations(self) -> Dict[MessageCategory, float]:
        """Get the current token allocations as percentages"""
        total_used = sum(budget.current_tokens for budget in self._budgets.values())
        if total_used == 0:
            return {category: 0.0 for category in self._budgets}
            
        return {
            category: budget.current_tokens / total_used 
            for category, budget in self._budgets.items()
        }
    
    def get_token_usage(self) -> Dict[str, int]:
        """Get token usage dictionary for tracking"""
        # Get base usage stats
        usage = {
            "total": sum(budget.current_tokens for budget in self._budgets.values()),
            "available": self.available_tokens,
            "max": self.max_tokens,
            **{str(category): budget.current_tokens for category, budget in self._budgets.items()}
        }
        
        # Add extra debug info
        usage["usage_percentage"] = (usage["total"] / self.max_tokens) * 100 if self.max_tokens else 0
        
        return usage
        
    def process_session(self, session: Session) -> Session:
        """
        Process a session through token budgeting and trimming.
        Main entry point for integration with conversation system.
        
        Args:
            session: Session object to process
            
        Returns:
            Processed session (trimmed if needed)
        """
        # Analyze token usage
        stats = self.analyze_session(session)
        
        # If under budget, no changes needed
        if not stats["over_budget"]:
            return session
            
        # Log trimming activity
        logger.info(
            f"Trimming session {session.id}: {stats['total_tokens']} tokens " +
            f"(over budget by {stats['total_tokens'] - self.max_tokens})"
        )
        
        # Perform trimming
        trimmed_session = self.trim_session(session)
        
        # Calculate how many messages were removed
        messages_removed = len(session.messages) - len(trimmed_session.messages)
        logger.info(f"Removed {messages_removed} messages during trimming")
        
        return trimmed_session 