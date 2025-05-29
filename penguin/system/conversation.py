import glob
import json
import logging
import os
import uuid
import yaml # type: ignore
from dataclasses import asdict, dataclass, field
from datetime import datetime
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Union

from penguin.config import CONVERSATION_CONFIG
from penguin.system.state import Message, MessageCategory, Session
from penguin.utils.diagnostics import diagnostics

# Optional - can be replaced with approximation method for multiple providers
try:
    import tiktoken # type: ignore
    TOKENIZER_AVAILABLE = True
except ImportError:
    TOKENIZER_AVAILABLE = False

logger = logging.getLogger(__name__)

class ConversationSystem:
    """
    Manages conversation state and message preparation.
    
    Handles message categorization, history management, and API formatting.
    Uses external systems for token budgeting and context management.
    """
    
    def __init__(
        self, 
        context_window_manager=None,
        session_manager=None,
        system_prompt: str = "",
        checkpoint_manager=None,
    ):
        """
        Initialize the conversation system.
        
        Args:
            context_window_manager: Manager for token budgeting and context trimming
            session_manager: Manager for session persistence and boundaries
            system_prompt: Initial system prompt
            checkpoint_manager: Manager for conversation checkpointing (optional)
        """
        self.context_window = context_window_manager
        self.session_manager = session_manager
        self.checkpoint_manager = checkpoint_manager
        self.system_prompt = system_prompt
        self.system_prompt_sent = False
        
        # Create or load initial session
        if session_manager and session_manager.current_session:
            self.session = session_manager.current_session
        else:
            self.session = Session()
            if session_manager:
                session_manager.current_session = self.session
        
        # Track if save is needed
        self._modified = False

    def set_system_prompt(self, prompt: str) -> None:
        """Set system prompt and mark for sending on next interaction."""
        self.system_prompt = prompt
        self.system_prompt_sent = False

    def add_message(
        self, 
        role: str, 
        content: Any,
        category: MessageCategory = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> Message:
        """
        Add a message to the current session.
        
        Args:
            role: Message role (system, user, assistant)
            content: Message content (string, list, or dict)
            category: Message category for token budgeting
            metadata: Optional metadata for the message
            
        Returns:
            The created Message object
        """
        # Set default category based on role if not specified
        if category is None:
            if role == "system":
                if content == self.system_prompt:
                    category = MessageCategory.SYSTEM
                elif any(marker in str(content).lower() for marker in 
                        ["action executed:", "code saved to:", "result:", "status:"]):
                    category = MessageCategory.SYSTEM_OUTPUT
                else:
                    category = MessageCategory.CONTEXT
            else:
                category = MessageCategory.DIALOG
        
        # Create the message
        message = Message(
            role=role,
            content=content,
            category=category,
            id=f"msg_{uuid.uuid4().hex[:8]}",
            timestamp=datetime.now().isoformat(),
            metadata=metadata or {},
        )
        
        # Add to current session
        self.session.messages.append(message)
        self._modified = True
        
        # NEW: Auto-checkpoint integration
        if self.checkpoint_manager and self.checkpoint_manager.should_checkpoint(message):
            # Create checkpoint asynchronously to avoid blocking
            import asyncio
            try:
                # Try to get the current event loop
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # If we're in an async context, create a task
                    asyncio.create_task(
                        self.checkpoint_manager.create_checkpoint(self.session, message)
                    )
                else:
                    # If no loop is running, run the checkpoint creation
                    asyncio.run(
                        self.checkpoint_manager.create_checkpoint(self.session, message)
                    )
            except RuntimeError:
                # If we can't get a loop, try to run it
                try:
                    asyncio.run(
                        self.checkpoint_manager.create_checkpoint(self.session, message)
                    )
                except Exception as e:
                    logger.warning(f"Failed to create checkpoint: {e}")
        
        # Process session through context window manager if available
        if self.context_window:
            self.session = self.context_window.process_session(self.session)
        
        # Check session boundaries and handle transitions automatically
        if self.session_manager and self.session_manager.check_session_boundary(self.session):
            logger.info(f"Session {self.session.id} reached boundary, creating continuation")
            
            # Save current session before transitioning
            self.save()
            
            # Create continuation session and switch to it
            new_session = self.session_manager.create_continuation_session(self.session)
            self.session = new_session
            self._modified = True
            
            # Log transition for debugging
            logger.info(f"Transitioned to continuation session {new_session.id}")
        
        return message

    def prepare_conversation(
        self, 
        user_input: str, 
        image_path: Optional[str] = None
    ) -> None:
        """
        Prepare conversation with user input and optional image.
        
        Adds system prompt if needed, then adds the user message.
        
        Args:
            user_input: User message text
            image_path: Optional path to an image file
        """
        # Send system prompt if not sent yet
        if not self.system_prompt_sent and self.system_prompt:
            self.add_message(
                "system", 
                self.system_prompt, 
                MessageCategory.SYSTEM,
                {"type": "system_prompt"}
            )
            self.system_prompt_sent = True

        # Handle image content if provided
        if image_path:
            # Create multimodal content with text and image
            content = [
                {"type": "text", "text": user_input},
                {"type": "image_url", "image_path": image_path}  # Use standardized format for adapters
            ]
            self.add_message("user", content)
        else:
            # Simple text content
            self.add_message("user", user_input)
            
    def add_assistant_message(self, content: str) -> Message:
        """Add a message from the assistant."""
        return self.add_message("assistant", content)
        
    def add_action_result(
        self, 
        action_type: str, 
        result: str, 
        status: str = "completed"
    ) -> Message:
        """
        Add an action result message.
        
        Args:
            action_type: Type of action executed
            result: Result of the action
            status: Status of execution (completed, error, etc.)
            
        Returns:
            The created Message object
        """
        content = f"Action executed: {action_type}\nResult: {result}\nStatus: {status}"
        return self.add_message(
            "system", 
            content, 
            MessageCategory.SYSTEM_OUTPUT,
            {"action_type": action_type, "status": status}
        )

    def add_context(
        self, 
        content: str, 
        source: Optional[str] = None
    ) -> Message:
        """
        Add context information to the conversation.
        
        Args:
            content: Context content (documentation, files, etc.)
            source: Optional source identifier
            
        Returns:
            The created Message object
        """
        return self.add_message(
            "system", 
            content, 
            MessageCategory.CONTEXT,
            {"source": source} if source else {}
        )
        
    def add_iteration_marker(
        self, 
        iteration: int, 
        max_iterations: int
    ) -> Message:
        """
        Add an iteration marker for multi-step processing.
        
        Args:
            iteration: Current iteration number
            max_iterations: Maximum number of iterations
            
        Returns:
            The created Message object
        """
        content = f"--- Beginning iteration {iteration}/{max_iterations} ---"
        return self.add_message(
            "system",
            content,
            MessageCategory.SYSTEM_OUTPUT,
            {"type": "iteration_marker", "iteration": iteration}
        )

    def get_history(self) -> List[Dict[str, Any]]:
        """
        Get formatted conversation history for API consumption.
        
        Returns:
            List of messages in API-compatible format
        """
        # Format for API consumption (remove extra fields)
        return [
            {"role": msg.role, "content": msg.content}
            for msg in self.session.messages
        ]
        
    def get_formatted_messages(self) -> List[Dict[str, Any]]:
        """
        Get formatted messages optimized for API consumption.
        
        Organizes messages by category priority and formats for the AI model.
        Returns:
            List of formatted message dictionaries
        """
        # Group by category
        categorized = {
            MessageCategory.SYSTEM: [],
            MessageCategory.CONTEXT: [],
            MessageCategory.DIALOG: [],
            MessageCategory.SYSTEM_OUTPUT: []
        }
        
        # Populate categories
        for msg in self.session.messages:
            categorized[msg.category].append(msg)
            
        # Create ordered list with proper priority
        messages = []
        
        # System messages first (highest priority)
        messages.extend([{"role": msg.role, "content": msg.content} 
                        for msg in categorized[MessageCategory.SYSTEM]])
        
        # Context information next
        messages.extend([{"role": msg.role, "content": msg.content} 
                        for msg in categorized[MessageCategory.CONTEXT]])
        
        # Merge dialogue and system output by timestamp
        dialog_and_output = (
            categorized[MessageCategory.DIALOG] + 
            categorized[MessageCategory.SYSTEM_OUTPUT]
        )
        dialog_and_output.sort(key=lambda msg: msg.timestamp)
        
        # Add merged messages
        messages.extend([{"role": msg.role, "content": msg.content} 
                        for msg in dialog_and_output])
        
        # If no messages, add a default user message to prevent API errors
        if not messages:
            messages.append({"role": "user", "content": "Placeholder message to prevent API errors"})
                
        # --- Add logging here ---
        # try:
        #     # Use json.dumps for potentially complex content structures
        #     messages_json = json.dumps(messages, indent=2)
        #     logger.debug(f"Formatted messages being sent to LLM:\n{messages_json}")
        # except Exception as e:
        #     logger.error(f"Error logging formatted messages: {e}") # Log formatting errors too
        # --- End logging ---
        
        return messages
        
    def save(self) -> bool:
        """
        Save the current session through session manager.
        
        Returns:
            True if successful, False otherwise
        """
        if not self._modified:
            return True
            
        if self.session_manager:
            success = self.session_manager.save_session(self.session)
            if success:
                self._modified = False
            return success
        return False
        
    def load(self, session_id: str) -> bool:
        """
        Load a session by ID via session manager.
        
        Args:
            session_id: ID of the session to load
            
        Returns:
            True if successful, False otherwise
        """
        if not self.session_manager:
            logger.error("Cannot load: No session manager available")
            return False
            
        loaded_session = self.session_manager.load_session(session_id)
        if loaded_session:
            self.session = loaded_session
            self._modified = False
            # Update sent status
            self.system_prompt_sent = any(
                msg.category == MessageCategory.SYSTEM 
                for msg in self.session.messages
            )
            return True
            
        return False
        
    def load_context_file(self, file_path: str) -> bool:
        """
        Load a context file into the conversation.
        
        Args:
            file_path: Path to the file to load
            
        Returns:
            True if successful, False otherwise
        """
        try:
            from penguin.config import WORKSPACE_PATH
            full_path = os.path.join(WORKSPACE_PATH, file_path)
            if not os.path.exists(full_path):
                logger.warning(f"Context file not found: {full_path}")
                return False
                
            with open(full_path, 'r', encoding='utf-8') as f:
                content = f.read()
                
            self.add_context(content, source=file_path)
            logger.info(f"Loaded context file: {file_path}")
            return True
        except Exception as e:
            logger.error(f"Error loading context file {file_path}: {str(e)}")
            return False
        
    def list_context_files(self) -> List[Dict[str, Any]]:
        """
        List available context files in workspace.
        
        Returns:
            List of file information dictionaries
        """
        from penguin.config import WORKSPACE_PATH
        context_dir = os.path.join(WORKSPACE_PATH, "context")
        if not os.path.exists(context_dir):
            return []
            
        files = []
        for entry in os.scandir(context_dir):
            if entry.is_file() and not entry.name.startswith('.'):
                files.append({
                    'path': f"context/{entry.name}",
                    'name': entry.name,
                    'size': entry.stat().st_size,
                    'modified': datetime.fromtimestamp(entry.stat().st_mtime).isoformat()
                })
                
        return files
        
    def reset(self) -> None:
        """Reset the conversation state with a new empty session."""
        self.session = Session()
        self.system_prompt_sent = False
        self._modified = True
        
        if self.session_manager:
            self.session_manager.current_session = self.session