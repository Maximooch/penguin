import glob
import json
import logging
import os
import yaml # type: ignore
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from penguin.config import CONVERSATION_CONFIG, WORKSPACE_PATH

# Optional - can be replaced with approximation method for multiple providers
try:
    import tiktoken # type: ignore
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False

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
class ConversationSummary:
    """Summary information for a conversation - used in menus"""
    
    session_id: str
    title: str
    message_count: int
    last_active: str
    
    @property
    def display_date(self) -> str:
        """Get formatted display date"""
        return self.last_active
        
    @property
    def display_title(self) -> str:
        """Get display-friendly title"""
        return self.title if self.title else f"Conversation {self.session_id[-6:]}"

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
                
    def to_summary(self) -> ConversationSummary:
        """Convert to a ConversationSummary"""
        return ConversationSummary(
            session_id=self.session_id,
            title=self.title or f"Conversation {self.session_id[-6:]}",
            message_count=self.message_count,
            last_active=parse_iso_datetime(self.last_active)
        )


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
                    "category": msg.get("category", "CONVERSATION"),
                    "metadata": msg.get("metadata", {})
                }
                for msg in messages
                if isinstance(msg, dict) and "content" in msg
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


class MessageCategory(Enum):
    """Categories of messages for prioritization"""
    SYSTEM_PROMPT = 1        # Highest priority - never truncated
    DECLARATIVE_NOTES = 2    # Important context
    WORKING_MEMORY = 3       # Documents and references
    CONVERSATION = 4         # User/assistant exchanges
    ACTION_RESULTS = 5       # Action result outputs


@dataclass
class TokenBudget:
    """Token budget for a message category"""
    # Minimum tokens guaranteed for this category
    min_tokens: int
    # Maximum tokens this category can consume
    max_tokens: int
    # Current tokens used by this category
    current_tokens: int = 0


class SimpleContextLoader:
    """
    Minimal context folder loader with basic configuration.
    
    Loads files from a context folder based on user configuration.
    Users specify 'core_files' that should always be loaded.
    Additional files can be loaded on demand.
    """
    
    def __init__(
        self, 
        conversation_system,
        context_folder: str = "context"
    ):
        """
        Initialize the SimpleContextLoader.
        
        Args:
            conversation_system: The conversation system instance to add content to
            context_folder: Path to the context folder within the workspace
        """
        self.conversation_system = conversation_system
        # Use the workspace path from config with the context subfolder
        self.context_folder = os.path.join(WORKSPACE_PATH, context_folder)
        self.config_file = os.path.join(self.context_folder, "context_config.yml")
        self.core_files: List[str] = []  # List of essential files to always load
        
        # Create context folder if it doesn't exist
        if not os.path.exists(self.context_folder):
            os.makedirs(self.context_folder)
        
        # Create a sample config file if it doesn't exist
        if not os.path.exists(self.config_file):
            self._create_sample_config()
        
        self._load_config()
        
    def _create_sample_config(self):
        """Create a sample configuration file if none exists"""
        try:
            sample_config = {
                "core_files": [
                    # Example files that will be loaded at startup
                    # "project_overview.md",
                    # "api_reference.md"
                ],
                "notes": "Add paths to files that should always be loaded as context"
            }
            
            with open(self.config_file, 'w') as f:
                yaml.dump(sample_config, f, default_flow_style=False)
                
            logger.info(f"Created sample context configuration at {self.config_file}")
        except Exception as e:
            logger.warning(f"Failed to create sample config: {e}")
    
    def _load_config(self):
        """Load core file list from config if available"""
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r') as f:
                    config = yaml.safe_load(f) or {}
                self.core_files = config.get('core_files', [])
                logger.info(f"Loaded context configuration with {len(self.core_files)} core files")
            except Exception as e:
                # Fall back to empty list if config can't be loaded
                logger.warning(f"Failed to load context configuration: {e}")
                self.core_files = []
    
    def load_core_context(self) -> List[str]:
        """
        Load core context files defined by the user.
        
        Returns:
            List of successfully loaded file paths
        """
        loaded = []
        
        for file_path in self.core_files:
            full_path = os.path.join(self.context_folder, file_path)
            if os.path.exists(full_path) and os.path.isfile(full_path):
                try:
                    with open(full_path, 'r', encoding='utf-8') as f:
                        content = f.read()
                    
                    # Add to conversation system working memory
                    self.conversation_system.add_working_memory(
                        content=content,
                        source=f"context/{file_path}"
                    )
                    loaded.append(file_path)
                    logger.debug(f"Loaded core context file: {file_path}")
                except Exception as e:
                    logger.warning(f"Failed to load core context file {file_path}: {e}")
            else:
                logger.warning(f"Core context file not found: {file_path}")
        
        return loaded
    
    def load_file(self, file_path: str) -> bool:
        """
        Load a specific file from the context folder on demand.
        
        Args:
            file_path: Relative path to the file within the context folder
            
        Returns:
            True if loaded successfully, False otherwise
        """
        full_path = os.path.join(self.context_folder, file_path)
        if not os.path.exists(full_path) or not os.path.isfile(full_path):
            logger.warning(f"Context file not found: {file_path}")
            return False
            
        try:
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
            
            # Add to conversation system working memory
            self.conversation_system.add_working_memory(
                content=content,
                source=f"context/{file_path}"
            )
            logger.debug(f"Loaded context file on demand: {file_path}")
            return True
        except Exception as e:
            logger.warning(f"Failed to load context file {file_path}: {e}")
            return False
    
    def list_available_files(self) -> List[Dict[str, Any]]:
        """
        List all available files in the context folder.
        
        Returns:
            List of file information dictionaries with path and metadata
        """
        available_files = []
        
        if not os.path.exists(self.context_folder):
            return available_files
            
        for root, _, files in os.walk(self.context_folder):
            for file in files:
                # Skip config file and hidden files
                if file == os.path.basename(self.config_file) or file.startswith('.'):
                    continue
                    
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.context_folder)
                
                # Get basic file stats
                stats = os.stat(full_path)
                
                # Categorize by file type
                file_type = "text"
                if file.endswith(('.md', '.markdown')):
                    file_type = "markdown"
                elif file.endswith(('.yml', '.yaml')):
                    file_type = "yaml"
                elif file.endswith(('.txt')):
                    file_type = "text"
                
                available_files.append({
                    'path': rel_path,
                    'size': stats.st_size,
                    'modified': stats.st_mtime,
                    'is_core': rel_path in self.core_files,
                    'type': file_type
                })
        
        return available_files


class ConversationSystem:
    """
    Manages conversation state, history, and message preparation.

    Responsibilities:
    - Conversation history management
    - Message preparation and formatting
    - System prompt management
    - Image message handling
    - Token budget management for context window
    - Context loading from files
    """

    def __init__(self, tool_manager, diagnostics, base_path: Path, model_config=None, api_client=None):
        self.tool_manager = tool_manager
        self.diagnostics = diagnostics
        self.messages = []
        self.system_prompt = ""
        self.system_prompt_sent = False
        self.session_id = self._generate_session_id()
        self.metadata = ConversationMetadata(
            created_at=datetime.now().isoformat(),
            last_active=datetime.now().isoformat(),
            message_count=0,
            session_id=self.session_id,
        )
        conversations_path = os.path.join(base_path, "conversations")
        self.loader = ConversationLoader(conversations_path)
        self.max_history_length = 1000000

        # Import workspace path from config for context loading
        from penguin.config import WORKSPACE_PATH
        self.workspace_path = WORKSPACE_PATH

        # Token budgeting configuration
        self.max_tokens = 128000  # Default
        if model_config and hasattr(model_config, 'max_tokens') and model_config.max_tokens:
            self.max_tokens = model_config.max_tokens
            
        # Default allocation percentages for each category
        self.category_allocations = {
            MessageCategory.SYSTEM_PROMPT: 0.15,     # 15% of context - never truncated
            MessageCategory.DECLARATIVE_NOTES: 0.20, # 20% of context
            MessageCategory.WORKING_MEMORY: 0.20,    # 20% of context
            MessageCategory.CONVERSATION: 0.30,      # 30% of context
            MessageCategory.ACTION_RESULTS: 0.15     # 15% of context
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
                
        # Initialize token budgets for categories
        self._initialize_token_budgets()
        
        # Message storage by category
        self.categorized_messages = {
            MessageCategory.SYSTEM_PROMPT: [],
            MessageCategory.DECLARATIVE_NOTES: [],
            MessageCategory.WORKING_MEMORY: [],
            MessageCategory.CONVERSATION: [],
            MessageCategory.ACTION_RESULTS: []
        }
        
        # Initialize context loader
        self.context_loader = SimpleContextLoader(self)
        
        # Load core context files
        try:
            self.load_core_context()
        except Exception as e:
            logger.warning(f"Failed to load core context: {e}")

        # Add API client reference
        self.api_client = api_client

    def _initialize_token_budgets(self):
        """Initialize token budgets for each category based on allocations"""
        self.token_budgets = {}
        
        # Calculate base allocations from percentages
        for category, percentage in self.category_allocations.items():
            # System prompt has special handling - must be preserved
            if category == MessageCategory.SYSTEM_PROMPT:
                # For system prompts, min and max are the same (guaranteed allocation)
                max_tokens = int(self.available_tokens * percentage)
                self.token_budgets[category] = TokenBudget(
                    min_tokens=max_tokens,
                    max_tokens=max_tokens
                )
            else:
                # For other categories:
                # - minimum is 25% of their allocation (guaranteed)
                # - maximum is 200% of their allocation (can expand)
                base_tokens = int(self.available_tokens * percentage)
                min_tokens = int(base_tokens * 0.25)
                max_tokens = int(base_tokens * 2.0)
                
                self.token_budgets[category] = TokenBudget(
                    min_tokens=min_tokens,
                    max_tokens=max_tokens
                )
        
        logger.debug(f"Initialized token budgets: {self.token_budgets}")
        
        # Calculate minimum and maximum possible token usage
        self.min_required_tokens = sum(budget.min_tokens for budget in self.token_budgets.values())
        self.max_possible_tokens = sum(budget.max_tokens for budget in self.token_budgets.values())
        
        logger.debug(f"Token budgets - Min required: {self.min_required_tokens}, " 
                    f"Max possible: {self.max_possible_tokens}, "
                    f"Available: {self.available_tokens}")

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
            self.reset()  # Clear existing state
            self.metadata = metadata
            self.session_id = session_id
            
            # Process each message and add to categorized storage
            for msg in messages:
                role = msg.get("role", "")
                content = msg.get("content", "")
                category_str = msg.get("category", None)
                metadata = msg.get("metadata", {})
                timestamp = msg.get("timestamp", datetime.now().isoformat())
                
                # Determine category
                category = None
                if category_str:
                    try:
                        category = MessageCategory[category_str]
                    except (KeyError, ValueError):
                        category = None
                
                if category is None:
                    # Default category based on role and content
                    if role == "system":
                        if self.system_prompt and content == self.system_prompt:
                            category = MessageCategory.SYSTEM_PROMPT
                        elif "Action executed: " in str(content) or "Code saved to: " in str(content):
                            category = MessageCategory.ACTION_RESULTS
                        else:
                            category = MessageCategory.DECLARATIVE_NOTES
                    elif role == "user" or role == "assistant":
                        category = MessageCategory.CONVERSATION
                    else:
                        category = MessageCategory.CONVERSATION  # Default fallback
                
                # Create internal representation
                tokens = self.count_tokens(content)
                message = {
                    "role": role,
                    "content": content,
                    "category": category.name,
                    "timestamp": timestamp,
                    "tokens": tokens,
                    "metadata": metadata or {}
                }
                
                # Add to appropriate category and messages list
                self.categorized_messages[category].append(message)
                self.messages.append(message)
                
                # Update token counts
                self.current_token_count += tokens
                self.token_budgets[category].current_tokens += tokens
            
            # Check if system prompt is present in loaded conversation
            self.system_prompt_sent = any(
                msg.get("category") == MessageCategory.SYSTEM_PROMPT.name 
                for msg in self.messages
            )
            
        except Exception as e:
            logger.error(f"Error loading conversation: {str(e)}")
            raise

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt and mark it as not sent."""
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def count_tokens(self, text: Union[str, List, Dict]) -> int:
        """Count tokens using API client's tokenizer or fallback methods"""
        try:
            # Handle empty or None input
            if not text:
                return 0
            
            # Convert structured content to string for token counting
            if isinstance(text, (list, dict)):
                # Handle structured content (e.g., for OpenAI format with images)
                if isinstance(text, list) and all(isinstance(item, dict) for item in text):
                    # This is likely a message content array with text/image parts
                    combined_text = ""
                    for item in text:
                        if isinstance(item, dict):
                            if item.get("type") == "text":
                                combined_text += item.get("text", "")
                            elif item.get("type") == "image_url":
                                # Images typically count as ~85 tokens in Claude
                                return 85
                    text = combined_text
                else:
                    # For other structured content, convert to string
                    text = str(text)
                
            # Try using API client's token counter first
            if self.api_client:
                try:
                    # Create a temporary message to count tokens
                    message = {"role": "user", "content": text}
                    counts = self.api_client.count_message_tokens([message])
                    return counts["total_tokens"] - counts["format_tokens"]  # Return only content tokens
                except Exception as e:
                    logger.warning(f"API client token counting failed: {e}, falling back to local methods")
            
            # Try using tiktoken if available
            if self.tokenizer:
                try:
                    return len(self.tokenizer.encode(text))
                except Exception as e:
                    logger.warning(f"Tiktoken counting failed: {e}, falling back to approximation")
            
            # Fallback to character-based approximation
            # This is a very rough approximation - about 4 characters per token
            return len(text) // 4 + 1
            
        except Exception as e:
            logger.error(f"Error counting tokens: {e}")
            # Return a conservative estimate to prevent issues
            return len(str(text)) // 3  # Even more conservative fallback

    def add_message(
        self, 
        role: str, 
        content: Any,
        category: Optional[MessageCategory] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> None:
        """
        Add a message to the conversation history with category-based organization.
        
        Args:
            role: The message role (system, user, assistant)
            content: The message content (text or structured content)
            category: Optional category for the message (auto-determined if not provided)
            metadata: Optional metadata for the message
        """
        # Normalize content format
        if isinstance(content, str) and not content:
            formatted_content = ""  # Empty string is allowed
        elif isinstance(content, list) and not content:
            formatted_content = []  # Empty list is allowed
        else:
            # Format based on what we receive
            if isinstance(content, (list, dict)):
                # Keep structured content as is
                formatted_content = content
            else:
                # Convert anything else to string
                formatted_content = str(content)
        
        # Determine category if not provided
        if category is None:
            if role == "system":
                # Check content to determine system message type
                content_str = str(content).lower()
                if self.system_prompt and content == self.system_prompt:
                    category = MessageCategory.SYSTEM_PROMPT
                elif "action executed: " in content_str or "code saved to: " in content_str:
                    category = MessageCategory.ACTION_RESULTS
                else:
                    category = MessageCategory.DECLARATIVE_NOTES
            else:
                category = MessageCategory.CONVERSATION
        
        # Count tokens for the message
        tokens = self.count_tokens(formatted_content)
        
        # Create the message
        timestamp = datetime.now().isoformat()
        message = {
            "role": role, 
            "content": formatted_content, 
            "timestamp": timestamp,
            "category": category.name,
            "metadata": metadata or {},
            "tokens": tokens
        }
        
        # Add to the appropriate category and the main messages list
        self.categorized_messages[category].append(message)
        self.messages.append(message)
        
        # Update token counts
        self.current_token_count += tokens
        self.token_budgets[category].current_tokens += tokens
        
        # Update title if this is the first user message
        if (
            role == "user"
            and len([m for m in self.messages if m["role"] == "user"]) == 1
        ):
            self.metadata.update_title_from_messages(self.messages)
        
        # Trim context if needed
        if self.current_token_count > self.available_tokens:
            self.trim_context()

    def prepare_conversation(
        self, user_input: str, image_path: Optional[str] = None
    ) -> None:
        """Prepare the conversation by adding necessary messages."""
        if not self.system_prompt_sent and self.system_prompt:
            system_tokens = self.count_tokens(self.system_prompt)
            self.diagnostics.update_tokens("system_prompt", system_tokens, 0)
            self.add_message(
                "system", 
                self.system_prompt, 
                MessageCategory.SYSTEM_PROMPT, 
                {"type": "system_prompt", "permanent": True}
            )
            self.system_prompt_sent = True

        if image_path:
            self._add_image_message(user_input, image_path)
        else:
            self.add_message("user", user_input, MessageCategory.CONVERSATION)

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
            self.add_message("user", image_message, MessageCategory.CONVERSATION)
            logger.info("Image message added to conversation history")
        except Exception as e:
            logger.error(f"Error adding image message: {str(e)}")
            raise

    def add_action_result(self, action_type: str, result: str, status: str = "completed") -> None:
        """Add an action result with proper formatting"""
        content = f"Action executed: {action_type}\nResult: {result}\nStatus: {status}"
        self.add_message(
            "system", 
            content, 
            MessageCategory.ACTION_RESULTS, 
            {"action_type": action_type, "status": status}
        )

    def trim_context(self) -> None:
        """
        Trim context using token budgeting approach.
        
        This method implements a sophisticated token budgeting strategy:
        1. Never truncate system prompts
        2. Ensure each category gets at least its minimum allocation
        3. Allow categories to exceed their base allocation if others use less
        4. When trimming, remove oldest messages first within each category
        """
        if self.current_token_count <= self.available_tokens:
            return
        
        logger.info(f"Trimming context: {self.current_token_count}/{self.available_tokens}")
        print(f"Trimming context: {self.current_token_count}/{self.available_tokens}")
        
        # Step 1: Calculate excess tokens that need to be removed
        excess_tokens = self.current_token_count - self.available_tokens
        logger.debug(f"Need to remove {excess_tokens} tokens")
        print(f"Need to remove {excess_tokens} tokens")
        
        # Step 2: Determine which categories exceed their budget and by how much
        category_excess = {}
        for category in self.token_budgets:
            if category == MessageCategory.SYSTEM_PROMPT:
                # Skip system prompts - they're never trimmed
                continue
                
            budget = self.token_budgets[category]
            current = budget.current_tokens
            
            # If current usage is below minimum, there's no excess
            if current <= budget.min_tokens:
                category_excess[category] = 0
            else:
                # Otherwise, calculate excess as anything above minimum guarantee
                # This is the amount we can potentially reduce
                category_excess[category] = current - budget.min_tokens
        
        # Total excess across all categories
        total_excess = sum(category_excess.values())
        logger.debug(f"Total excess across categories: {total_excess}")
        print(f"Total excess across categories: {total_excess}")
        
        # If we can't trim enough, we'll need to go below minimums for some categories
        if total_excess < excess_tokens:
            logger.warning(f"Insufficient excess ({total_excess}) to trim required tokens ({excess_tokens})")
            print(f"Insufficient excess ({total_excess}) to trim required tokens ({excess_tokens})")
            # Calculate how much we need to take from minimums
            minimum_reduction_needed = excess_tokens - total_excess
            
            # Proportionally reduce minimum guarantees for non-system categories
            # Calculate total of minimum guarantees for non-system categories
            total_non_system_min = sum(
                self.token_budgets[cat].min_tokens for cat in self.token_budgets
                if cat != MessageCategory.SYSTEM_PROMPT
            )
            
            # Adjust category excess based on proportional minimum reduction
            for category in category_excess:
                if category != MessageCategory.SYSTEM_PROMPT:
                    proportion = self.token_budgets[category].min_tokens / total_non_system_min
                    additional_reduction = int(minimum_reduction_needed * proportion)
                    category_excess[category] += additional_reduction
                    logger.debug(f"Adding {additional_reduction} tokens to {category.name} reduction target")
                    print(f"Adding {additional_reduction} tokens to {category.name} reduction target")
        # Step 3: For each category, trim messages if they exceed their allocation
        tokens_removed = 0
        
        # Process categories in specific order (least important first)
        for category in [
            MessageCategory.ACTION_RESULTS,
            MessageCategory.CONVERSATION,  
            MessageCategory.WORKING_MEMORY,
            MessageCategory.DECLARATIVE_NOTES,
            # System prompt is preserved
        ]:
            # Skip system prompts entirely
            if category == MessageCategory.SYSTEM_PROMPT:
                continue
                
            # Skip if no excess to trim in this category
            if category_excess.get(category, 0) <= 0:
                continue
            
            # Calculate this category's proportion of the excess
            if total_excess > 0:
                proportion = category_excess[category] / total_excess
                target_reduction = min(int(excess_tokens * proportion), category_excess[category])
            else:
                # Fallback if total_excess is 0 (shouldn't happen)
                target_reduction = 0
            
            # Don't try to remove more than what exists
            target_reduction = min(target_reduction, self.token_budgets[category].current_tokens)
            
            if target_reduction <= 0:
                continue
                
            logger.debug(f"Target reduction for {category.name}: {target_reduction} tokens")
            
            # Identify messages to remove (excluding permanent ones)
            # Sort by timestamp (oldest first)
            sorted_msgs = sorted(
                [msg for msg in self.categorized_messages[category] 
                if not msg.get("metadata", {}).get("permanent", False)],
                key=lambda x: x.get("timestamp", "")
            )
            
            # Remove oldest messages until we reach target reduction
            removed_from_category = 0
            removal_msgs = []
            
            for msg in sorted_msgs:
                if removed_from_category >= target_reduction:
                    break
                removal_msgs.append(msg)
                msg_tokens = msg.get("tokens", 0)
                removed_from_category += msg_tokens
                logger.debug(f"Removing {category.name} message: {msg_tokens} tokens")
            
            # Update lists and counters
            for msg in removal_msgs:
                self.categorized_messages[category].remove(msg)
                if msg in self.messages:
                    self.messages.remove(msg)
            
            # Update token counts
            self.token_budgets[category].current_tokens -= removed_from_category
            tokens_removed += removed_from_category
            
            # If we've removed enough tokens across all categories, stop
            if tokens_removed >= excess_tokens:
                break
        
        # Recalculate token count to ensure accuracy
        self.current_token_count -= tokens_removed
        logger.info(f"After trimming: {self.current_token_count}/{self.available_tokens} tokens")

    def get_current_allocations(self) -> Dict[MessageCategory, float]:
        """Get current percentage allocations for each category"""
        if self.current_token_count == 0:
            return {category: 0.0 for category in self.token_budgets}
            
        return {
            category: self.token_budgets[category].current_tokens / self.current_token_count 
            for category in self.token_budgets
        }

    def clear_category(self, category: MessageCategory) -> None:
        """Clear all messages in a specific category (except permanent ones)"""
        # Identify messages to remove (non-permanent only)
        msgs_to_remove = [
            msg for msg in self.categorized_messages[category]
            if not msg.get("metadata", {}).get("permanent", False)
        ]
        
        # Calculate tokens to remove
        tokens_to_remove = sum(msg.get("tokens", 0) for msg in msgs_to_remove)
        
        # Update the category's message list
        self.categorized_messages[category] = [
            msg for msg in self.categorized_messages[category]
            if msg.get("metadata", {}).get("permanent", False)
        ]
        
        # Update main messages list
        for msg in msgs_to_remove:
            if msg in self.messages:
                self.messages.remove(msg)
        
        # Update token counts
        self.current_token_count -= tokens_to_remove
        self.token_budgets[category].current_tokens -= tokens_to_remove

    def get_history(self) -> List[Dict[str, Any]]:
        """Get the full conversation history."""
        # Format for API consumption (remove extra fields)
        return [
            {"role": msg["role"], "content": msg["content"]}
            for msg in self.messages
        ]

    def get_formatted_history(self) -> List[Dict[str, Any]]:
        """Get conversation history arranged by category priority."""
        formatted_messages = []
        
        # Add system messages first (never truncated)
        for msg in self.categorized_messages[MessageCategory.SYSTEM_PROMPT]:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add declarative notes next
        for msg in self.categorized_messages[MessageCategory.DECLARATIVE_NOTES]:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add working memory
        for msg in self.categorized_messages[MessageCategory.WORKING_MEMORY]:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})
        
        # Add conversation and action results in chronological order
        other_messages = sorted(
            self.categorized_messages[MessageCategory.CONVERSATION] + 
            self.categorized_messages[MessageCategory.ACTION_RESULTS],
            key=lambda x: x.get("timestamp", "")
        )
        
        for msg in other_messages:
            formatted_messages.append({"role": msg["role"], "content": msg["content"]})
        
        return formatted_messages

    def get_last_message(self) -> Optional[Dict[str, Any]]:
        """Get the last message in the conversation history."""
        return self.messages[-1] if self.messages else None

    def add_summary_note(self, category: str, content: str) -> None:
        """Add a summary note as a system message."""
        metadata = {
            "type": "summary_note",
            "category": category,
            "timestamp": datetime.now().isoformat()
        }
        self.add_message(
            "system",
            content,
            MessageCategory.DECLARATIVE_NOTES,
            metadata
        )

    def reset(self):
        """Reset the conversation state"""
        self.messages = []
        self.categorized_messages = {
            MessageCategory.SYSTEM_PROMPT: [],
            MessageCategory.DECLARATIVE_NOTES: [],
            MessageCategory.WORKING_MEMORY: [],
            MessageCategory.CONVERSATION: [],
            MessageCategory.ACTION_RESULTS: []
        }
        self.current_token_count = 0
        for category in self.token_budgets:
            self.token_budgets[category].current_tokens = 0
        self.system_prompt_sent = False

    def add_iteration_marker(self, iteration: int, max_iterations: int) -> None:
        """Add a marker for the start of a new iteration in the multi-step process."""
        content = f"--- Beginning iteration {iteration}/{max_iterations} ---"
        metadata = {"type": "iteration_marker", "iteration": iteration}
        self.add_message(
            "system",
            content,
            MessageCategory.ACTION_RESULTS,  # Changed from DECLARATIVE_NOTES
            metadata
        )
        
    def add_working_memory(self, content: str, source=None) -> None:
        """Add content to working memory"""
        metadata = {"source": source} if source else {}
        self.add_message(
            "system",
            content,
            MessageCategory.WORKING_MEMORY,
            metadata
        )
        
    def load_core_context(self):
        """Load core context files from the context folder"""
        return self.context_loader.load_core_context()
        
    def load_context_file(self, file_path: str) -> bool:
        """
        Load a specific context file on demand
        
        Args:
            file_path: Path to file (relative to context folder)
            
        Returns:
            True if loaded successfully, False otherwise
        """
        return self.context_loader.load_file(file_path)
        
    def list_context_files(self) -> List[Dict[str, Any]]:
        """
        List all available context files
        
        Returns:
            List of file information dictionaries
        """
        return self.context_loader.list_available_files()
    
    async def request_summary(self, api_client, messages, max_tokens=2500, temperature=0.3):
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

    def get_current_token_usage(self) -> Dict[str, int]:
        """Get current token usage including formatting"""
        # Calculate prompt tokens (system + user messages)
        prompt_tokens = (
            self.token_budgets[MessageCategory.SYSTEM_PROMPT].current_tokens +
            sum(msg.get("tokens", 0) for msg in self.messages 
                if msg["role"] == "user")
        )
        
        # Calculate completion tokens (assistant messages)
        completion_tokens = sum(msg.get("tokens", 0) for msg in self.messages 
                              if msg["role"] == "assistant")
        
        return {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": self.current_token_count,
            "max_tokens": self.max_tokens
        }