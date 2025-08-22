# It could use some improvements, but it's a good start.

"""
Context window management for managing token budgets and content trimming.

This module provides tools to:
1. Track token usage across different message categories
2. Manage trimming strategies based on content types
3. Handle special content types like images
4. Ensure context windows don't exceed model limits
"""

# TODO: 
# - Add a function to get the total token usage for a session
# - Add a function to get the token usage for a specific category
# - Add a function to get the token usage as a percentage of the total budget
# - Add a function to get the token usage for a specific message
# - Add a function to get the token usage for a specific message category
# - Add a function to get the token usage for a specific message role

# TODO:
# - Don't hardcode the categories, make them configurable. Which means here it deals with the budgets of categories based on the priority they're infered from the config.
# - Make the budgets dynamic based on the content of the messages. Maybe?


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
        token_counter: Optional[Callable[[Any], int]] = None,
        api_client=None,
        config_obj: Optional[Any] = None,
    ):
        """
        Initialize the context window manager.
        
        Args:
            model_config: Optional model configuration with max_tokens
            token_counter: Function to count tokens for content
            api_client: API client for token counting
        """
        # Get max_tokens from model_config / config context_window when available
        self.max_tokens = 150000  # Default fallback
        
        if model_config and hasattr(model_config, 'max_tokens') and model_config.max_tokens:
            self.max_tokens = model_config.max_tokens
            logger.info(f"Using model's max_tokens: {self.max_tokens}")
        
        # Prefer values coming from the live Config instance when provided
        if config_obj is not None:
            try:
                cw_from_config = None
                # Prefer a dedicated max_history_tokens (context capacity) when present
                if hasattr(config_obj, 'model_config') and hasattr(config_obj.model_config, 'max_history_tokens'):
                    cw_from_config = config_obj.model_config.max_history_tokens
                # Upgrade only if larger
                if cw_from_config and cw_from_config > self.max_tokens:
                    self.max_tokens = cw_from_config
                    logger.info(f"Using live Config max_history_tokens: {self.max_tokens}")
            except Exception as e:
                logger.warning(f"Failed to read context window from live Config: {e}")

        # Try to load from module-level config as a last resort (legacy path)
        try:
            from penguin.config import config
            if 'model_configs' in config:
                model_name = model_config.model if model_config and hasattr(model_config, 'model') else None
                if model_name and model_name in config['model_configs'] and 'max_tokens' in config['model_configs'][model_name]:
                    config_max_tokens = config['model_configs'][model_name]['max_tokens']
                    if config_max_tokens:
                        self.max_tokens = config_max_tokens
                        logger.info(f"Using config.yml max_tokens for {model_name}: {self.max_tokens}")
            # Prefer global model.context_window if present. Do not downgrade the
            # window if model_config already provides a larger, authoritative value
            # (e.g., fetched from model specs). Use the larger of the two.
            if 'model' in config and isinstance(config['model'], dict):
                cw = config['model'].get('context_window')
                if cw:
                    if self.max_tokens and cw > self.max_tokens:
                        self.max_tokens = cw
                        logger.info(f"Using global context_window from config.yml (upgraded): {self.max_tokens}")
                    else:
                        logger.info(f"Retaining model's max_tokens ({self.max_tokens}); global context_window={cw} not larger")
        except (ImportError, AttributeError) as e:
            logger.warning(f"Could not load config.yml for max_tokens: {e}")

        # Try to get token counter with clearer logging
        if token_counter:
            logger.info("Using explicit token counter")
            self.token_counter = token_counter
        elif api_client and hasattr(api_client, 'count_tokens'):
            logger.info(f"Using API client token counter from {getattr(api_client.client_handler, 'provider', 'unknown') if hasattr(api_client, 'client_handler') else 'unknown'}")
            self.token_counter = api_client.count_tokens
        elif model_config and hasattr(model_config, 'api_client') and model_config.api_client:
            logger.info(f"Using model_config.api_client token counter")
            self.token_counter = model_config.api_client.count_tokens
        else:
            # No API client, make a best effort
            try:
                from penguin.utils.diagnostics import diagnostics
                self.token_counter = diagnostics.count_tokens
                logger.info("Using tiktoken via diagnostics for token counting")
            except (ImportError, AttributeError):
                # Last resort: Use fallback counter
                self.token_counter = self._default_token_counter
                logger.warning("Using fallback token counter - counts may be inaccurate")
            
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
            
            # Set minimum tokens to a reasonable value but never higher than the budget itself
            if category == MessageCategory.SYSTEM:
                min_tokens = min(1000, budget)  # Use 1000 or budget, whichever is smaller
            else:
                min_tokens = 0
            
            self._budgets[category] = TokenBudget(
                min_tokens=min_tokens,
                max_tokens=budget,
                current_tokens=0
            )
        
        # ------------------------------------------------------------------
        # Ensure **all** MessageCategory values have a budget entry.
        # Some categories (e.g. ERROR, INTERNAL, UNKNOWN) were previously
        # missing which caused AttributeError crashes when later code
        # attempted to access attributes on a `None` budget.  Assign a small
        # default budget so they are at least tracked safely.
        # ------------------------------------------------------------------
        default_max = int(total_budget * 0.05)  # 5 % fallback per uncategorised
        for category in MessageCategory:
            if category not in self._budgets:
                self._budgets[category] = TokenBudget(
                    min_tokens=0,
                    max_tokens=default_max,
                    current_tokens=0,
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
                (if False, messages would be selected arbitrarily for removal)
            
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
        
        # Special handling for images - they consume many tokens
        if stats["image_count"] > 1:
            # First pass: handle images separately
            session_with_image_placeholders = self._handle_image_trimming(session) 
            
            # why use session_with_image_placeholders? Isn't that approximate character count instead of using a real tokenizer?
            
            # Re-analyze after image trimming
            stats = self.analyze_session(session_with_image_placeholders)
            session = session_with_image_placeholders
        
        # Group messages by category
        categorized = {}
        for category in MessageCategory:
            categorized[category] = [
                msg for msg in session.messages 
                if msg.category == category
            ]
            
        # Get the order for trimming based on our priority (from lowest to highest priority)
        # SYSTEM_OUTPUT (4) trimmed first, then DIALOG (3), then CONTEXT (2), then SYSTEM (1)
        trim_order = [
            MessageCategory.SYSTEM_OUTPUT,   # Trim first - lowest priority
            MessageCategory.DIALOG,          # Trim second
            MessageCategory.CONTEXT,         # Trim third
        ]
            
        # Check if total is over budget
        total_over_budget = stats["total_tokens"] > self.max_tokens
        tokens_to_trim = max(0, stats["total_tokens"] - self.max_tokens) if total_over_budget else 0
        
        # Trim categories in priority order
        for category in trim_order:
            budget = self._budgets.get(category)
            category_msgs = categorized[category]
            category_tokens = stats["per_category"].get(category, 0)
            
            # If this category is over its individual budget, trim it regardless of total
            if category_tokens > budget.max_tokens:
                # Determine how much to trim
                category_excess = category_tokens - budget.max_tokens
                
                # If the overall budget is also exceeded, we might need to trim even more
                if total_over_budget:
                    category_excess = max(category_excess, min(tokens_to_trim, category_tokens - budget.min_tokens))
                    
                # Always preserve recency by sorting oldest first for trimming
                # This is now a required behavior for coherent trimming
                category_msgs.sort(key=lambda m: m.timestamp)
                
                # Strictly chronological trimming - remove oldest messages first
                remaining_msgs = []
                tokens_removed = 0
                
                # First pass: Remove oldest messages until we reach our token target
                msgs_to_keep = []
                for msg in category_msgs:
                    msg_tokens = msg.tokens or self.token_counter(msg.content)
                    
                    if tokens_removed < category_excess:
                        # Remove this message (oldest first)
                        tokens_removed += msg_tokens
                        # Update the overall token trimming target
                        tokens_to_trim = max(0, tokens_to_trim - msg_tokens)
                        # Log the removed message
                        logger.debug(f"Trimmed {category.name} message: {msg.id} ({msg_tokens} tokens)")
                    else:
                        # Keep this message
                        msgs_to_keep.append(msg)
                
                # Replace the category's messages with trimmed version
                categorized[category] = msgs_to_keep
                
                # Update statistics for next category
                stats["per_category"][category] = category_tokens - tokens_removed
                stats["total_tokens"] -= tokens_removed
                
                # Log the trimming operation
                logger.debug(f"Trimmed {category.name}: removed {tokens_removed} tokens " + 
                            f"({len(category_msgs) - len(msgs_to_keep)} messages)")
                
                # Check if we've trimmed enough overall
                if tokens_to_trim <= 0:
                    total_over_budget = False
        
        # Add SYSTEM messages without any trimming (preserve all of them)
        system_messages = categorized.get(MessageCategory.SYSTEM, [])
        
        # Reconstruct the message list preserving original order
        # We'll use a dictionary to track which messages to keep
        kept_messages = {}
        
        # First add ALL system messages (guaranteed to be kept)
        for msg in system_messages:
            kept_messages[msg.id] = msg
        
        # Then add messages from other categories that survived trimming
        for category in [MessageCategory.CONTEXT, MessageCategory.DIALOG, MessageCategory.SYSTEM_OUTPUT]:
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
        
        # Reset budgets to match the actual session content
        self.reset_usage()
        
        # Update budget tracking
        for msg in session.messages:
            self.update_usage(msg.category, msg.tokens)
        
        # Check if any categories exceed their individual budgets
        # Start with lowest priority first (SYSTEM_OUTPUT)
        categories_over_budget = []
        for category in reversed(list(MessageCategory)):  # Reversed to start with lowest priority
            # Skip SYSTEM messages - NEVER consider them for trimming
            if category == MessageCategory.SYSTEM:
                continue
                
            budget = self._budgets.get(category)
            # Skip categories that do not have an explicit budget (safety)
            if budget is None:
                continue
            category_tokens = stats["per_category"].get(category, 0)
            if category_tokens > budget.max_tokens:
                categories_over_budget.append(category)
                logger.info(
                    f"Category {category.name} is over budget: {category_tokens} tokens " +
                    f"(exceeds by {category_tokens - budget.max_tokens})"
                )
        
        # If total is over budget or any non-SYSTEM categories are over budget, trim
        # For total budget, subtract SYSTEM tokens as those are never trimmed
        system_tokens = stats["per_category"].get(MessageCategory.SYSTEM, 0)
        adjusted_total = stats["total_tokens"] - system_tokens
        adjusted_budget = self.max_tokens - system_tokens
        total_over_budget = adjusted_total > adjusted_budget
        
        if total_over_budget or categories_over_budget:
            # Perform trimming
            if total_over_budget:
                logger.info(
                    f"Trimming session {session.id}: {adjusted_total} tokens " +
                    f"(over adjusted budget by {adjusted_total - adjusted_budget})"
                )
            else:
                logger.info(
                    f"Trimming session {session.id} categories: {[c.name for c in categories_over_budget]}"
                )
            
            trimmed_session = self.trim_session(session)
            
            # Calculate how many messages were removed
            messages_removed = len(session.messages) - len(trimmed_session.messages)
            logger.info(f"Removed {messages_removed} messages during trimming")
            
            # Double-check that SYSTEM messages were preserved
            original_system_count = len([msg for msg in session.messages 
                                         if msg.category == MessageCategory.SYSTEM])
            trimmed_system_count = len([msg for msg in trimmed_session.messages 
                                        if msg.category == MessageCategory.SYSTEM])
            
            if original_system_count != trimmed_system_count:
                logger.error(f"SYSTEM messages were incorrectly trimmed! Before: {original_system_count}, After: {trimmed_system_count}")
                # Fix by restoring all SYSTEM messages
                system_msgs = [msg for msg in session.messages if msg.category == MessageCategory.SYSTEM]
                
                # Create a new session with SYSTEM messages preserved
                fixed_session = Session(
                    id=trimmed_session.id,
                    created_at=trimmed_session.created_at,
                    last_active=trimmed_session.last_active,
                    metadata=trimmed_session.metadata.copy(),
                    messages=system_msgs + [msg for msg in trimmed_session.messages 
                                           if msg.category != MessageCategory.SYSTEM]
                )
                
                # Use fixed session instead
                trimmed_session = fixed_session
                logger.info("Restored all SYSTEM messages after trimming")
            
            # Update budget tracking for trimmed session
            self.reset_usage()
            for msg in trimmed_session.messages:
                self.update_usage(msg.category, msg.tokens)
            
            return trimmed_session
        
        # If we get here, no trimming needed
        return session
    
    def format_token_usage(self) -> str:
        """
        Format token usage in a human-readable format for CLI display.
        
        Returns:
            String representation of token usage by category
        """
        usage = self.get_token_usage()
        total = usage.get("total", 0)
        available = usage.get("available", 0)
        max_tokens = usage.get("max", 0)
        
        # Calculate percentage of total budget used
        percentage = (total / max_tokens * 100) if max_tokens > 0 else 0
        
        output = [
            f"Token Usage: {total:,}/{max_tokens:,} ({percentage:.1f}%)",
            f"Available: {available:,} tokens",
            "\nBy Category:"
        ]
        
        # Add category breakdowns
        for category in MessageCategory:
            category_tokens = usage.get(str(category), 0)
            category_max = self._budgets[category].max_tokens if category in self._budgets else 0
            category_pct = (category_tokens / category_max * 100) if category_max > 0 else 0
            
            output.append(f"  {category.name}: {category_tokens:,}/{category_max:,} ({category_pct:.1f}%)")
        
        return "\n".join(output)
    
    def format_token_usage_rich(self) -> str:
        """
        Format token usage with rich for prettier CLI output.
        
        Returns:
            Rich console markup for token usage
        """
        try:
            from rich.console import Console # type: ignore
            from rich.table import Table # type: ignore
            from rich.text import Text # type: ignore
            from rich.box import Box, SIMPLE  # Import Box objects # type: ignore
            
            usage = self.get_token_usage()
            total = usage.get("total", 0)
            available = usage.get("available", 0)
            max_tokens = usage.get("max", 0)
            
            # Create rich table with proper Box object
            table = Table(
                title=f"Token Usage: {total:,}/{max_tokens:,} ({total/max_tokens*100:.1f}%)",
                expand=False,
                box=SIMPLE,  # Use SIMPLE box instead of boolean
                safe_box=True  # Prevents rendering issues
            )
            
            # Add columns with fixed width
            table.add_column("Category", style="cyan", width=15)
            table.add_column("Tokens", style="green", width=8, justify="right")
            table.add_column("Allocation", style="yellow", width=12)
            table.add_column("Budget", style="blue", width=7, justify="right")
            table.add_column("Usage", style="magenta", width=30)
            
            # Add rows for each category
            for category in MessageCategory:
                category_tokens = usage.get(str(category), 0)
                category_budget = self._budgets.get(category)
                
                if category_budget:
                    # Create progress bar with clean rendering
                    max_tokens = category_budget.max_tokens
                    if max_tokens > 0:
                        usage_pct = min(100, category_tokens / max_tokens * 100)
                        bar_width = 20
                        filled = int(usage_pct / 100 * bar_width)
                        
                        # Create a simple string for the progress bar
                        progress_bar = f"[{'█' * filled}{' ' * (bar_width - filled)}] {usage_pct:.1f}%"
                        
                        # Add row as simple strings
                        table.add_row(
                            category.name,
                            f"{category_tokens:,}",
                            f"{category_budget.min_tokens:,}-{max_tokens:,}",
                            f"{max_tokens/self.max_tokens*100:.1f}%",
                            progress_bar
                        )
                    else:
                        # Handle zero case
                        table.add_row(
                            category.name,
                            f"{category_tokens:,}",
                            f"{category_budget.min_tokens:,}-{max_tokens:,}",
                            f"{max_tokens/self.max_tokens*100:.1f}%",
                            "[" + " " * 20 + "] 0.0%"
                        )
                
            # Add summary row with simple string progress bar
            total_progress_bar = f"[{'█' * int(total/self.max_tokens*20)}{' ' * (20 - int(total/self.max_tokens*20))}] {total/self.max_tokens*100:.1f}%"
            
            table.add_row(
                "TOTAL", 
                f"{total:,}",
                f"0-{self.max_tokens:,}",
                "100.0%",
                total_progress_bar,
                style="bold"
            )
            
            # Render table to string
            console = Console(width=80, record=True)
            console.print(table)
            return console.export_text()
            
        except ImportError:
            # Fallback if rich is not installed
            return self.format_token_usage_simple()
        
    def format_token_usage_simple(self) -> str:
        """Simple token usage formatting without dependencies"""
        usage = self.get_token_usage()
        total = usage.get("total", 0)
        available = usage.get("available", 0)
        max_tokens = usage.get("max", 0)
        
        # Calculate percentage of total budget used
        percentage = (total / max_tokens * 100) if max_tokens else 0
        
        output = [
            f"Token Usage: {total:,}/{max_tokens:,} ({percentage:.1f}%)",
            f"Available: {available:,} tokens",
            "\nBy Category:"
        ]
        
        # Add category breakdowns
        for category in MessageCategory:
            category_tokens = usage.get(str(category), 0)
            budget = self._budgets.get(category)
            if budget:
                category_pct = (category_tokens / budget.max_tokens * 100) if budget.max_tokens else 0
                output.append(f"  {category.name}: {category_tokens:,}/{budget.max_tokens:,} ({category_pct:.1f}%)")
        
        return "\n".join(output)
    
    def get_usage(self, category: MessageCategory) -> int:
        """Get current token usage for a specific category."""
        budget = self._budgets.get(category)
        return budget.current_tokens if budget else 0 