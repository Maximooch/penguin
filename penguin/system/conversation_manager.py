"""
High-level conversation management for Penguin AI Assistant.

This module coordinates between:
1. ConversationSystem - Core message handling
2. ContextWindowManager - Token budgeting
3. SessionManager - Session persistence and boundaries
4. ContextLoader - Context file management
5. CheckpointManager - Conversation checkpointing (NEW)
"""

import logging
import os
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Union, AsyncGenerator, Callable

from penguin.config import CONVERSATIONS_PATH, WORKSPACE_PATH
from penguin.system.context_loader import SimpleContextLoader
from penguin.system.context_window import ContextWindowManager
from penguin.system.conversation import ConversationSystem
from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.checkpoint_manager import CheckpointManager, CheckpointConfig, CheckpointType

logger = logging.getLogger(__name__)


class ConversationManager:
    """
    High-level coordinator for conversation management.
    
    Provides a simplified interface for PenguinCore while managing the complexity
    of token budgeting, session management, context loading, and checkpointing.
    """
    
    def __init__(
        self,
        model_config=None,
        api_client=None,
        workspace_path: Optional[Path] = None,
        system_prompt: str = "",
        max_messages_per_session: int = 5000,
        max_sessions_in_memory: int = 20,
        auto_save_interval: int = 60,
        checkpoint_config: Optional[CheckpointConfig] = None
    ):
        """
        Initialize the conversation manager.
        
        Args:
            model_config: Configuration for the AI model
            api_client: Client for API interactions
            workspace_path: Path to workspace directory
            system_prompt: Initial system prompt
            max_messages_per_session: Maximum messages before creating a new session
            max_sessions_in_memory: Maximum sessions to keep in memory cache
            auto_save_interval: Seconds between auto-saves (0 to disable)
            checkpoint_config: Configuration for checkpointing system
        """
        self.model_config = model_config
        self.api_client = api_client
        self.workspace_path = Path(workspace_path or WORKSPACE_PATH)
        
        # Initialize component paths
        conversations_path = os.path.join(self.workspace_path, "conversations")
        context_path = os.path.join(self.workspace_path, "context")
        
        # Create directories if they don't exist
        os.makedirs(conversations_path, exist_ok=True)
        os.makedirs(context_path, exist_ok=True)
        
        # Initialize components with proper configuration
        logger.info("Initializing conversation components...")
        
        # Token window manager for content trimming
        self.context_window = ContextWindowManager(
            model_config=model_config,
            api_client=api_client,
            config_obj=self._get_live_config()
        )
        logger.info(f"Context window initialized with max tokens: {self.context_window.max_tokens}")
        
        # Session manager for persistence and caching
        self.session_manager = SessionManager(
            base_path=conversations_path,
            max_messages_per_session=max_messages_per_session,
            max_sessions_in_memory=max_sessions_in_memory,
            auto_save_interval=auto_save_interval
        )
        logger.info(f"Session manager initialized with {len(self.session_manager.session_index)} sessions")
        
        # Initialize checkpoint manager
        self.checkpoint_manager = None
        if checkpoint_config is None:
            checkpoint_config = CheckpointConfig()
        
        if checkpoint_config.enabled:
            try:
                self.checkpoint_manager = CheckpointManager(
                    workspace_path=self.workspace_path,
                    session_manager=self.session_manager,
                    config=checkpoint_config
                )
                logger.info(f"Checkpoint manager initialized with {len(self.checkpoint_manager.checkpoint_index)} checkpoints")
                
                # Workers will start lazily when first checkpoint is created
                    
            except Exception as e:
                logger.warning(f"Failed to initialize checkpoint manager: {e}")
                self.checkpoint_manager = None
        
        # Initialize conversation system
        self.conversation = ConversationSystem(
            context_window_manager=self.context_window,
            session_manager=self.session_manager,
            system_prompt=system_prompt,
            checkpoint_manager=self.checkpoint_manager
        )
        
        # Initialize context loader
        self.context_loader = SimpleContextLoader(
            context_manager=self.conversation
        )

    def _get_live_config(self):
        """Best-effort accessor for the live Config instance used by Core.
        Falls back to None if unavailable (e.g., tests).
        """
        try:
            # PenguinCore passes a Config instance to ConversationManager via the core
            # but not directly stored here; when available through the backref, use it.
            if hasattr(self, 'core') and getattr(self, 'core') and hasattr(self.core, 'config'):
                return self.core.config
        except Exception:
            pass
        return None
        
        # Load core context files
        loaded_files = self.context_loader.load_core_context()
        if loaded_files:
            logger.info(f"Loaded {len(loaded_files)} core context files")
        
        # -----------------------------------------------------------
        # Snapshot / Restore support (Phase 3)
        # -----------------------------------------------------------
        try:
            from penguin.system.snapshot_manager import SnapshotManager  # local import to avoid circulars
            snapshots_path = Path(self.workspace_path) / "snapshots" / "snapshots.db"
            self.snapshot_manager: Optional[SnapshotManager] = SnapshotManager(snapshots_path)
        except Exception as e:
            logger.warning(f"Failed to initialise SnapshotManager – snapshot/restore disabled: {e}")
            self.snapshot_manager = None
        
    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.conversation.set_system_prompt(prompt)
        
    async def process_message(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        image_path: Optional[str] = None,
        streaming: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        context_files: Optional[List[str]] = None
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Process a user message and get AI response.
        
        Args:
            message: User input message
            conversation_id: Optional ID to load specific conversation
            image_path: Optional path to image for multi-modal input
            streaming: Whether to stream the response
            stream_callback: Callback for streaming chunks
            context_files: Optional list of context files to load
            
        Returns:
            AI assistant's response or streaming generator
        """
        try:
            # Load conversation if ID provided
            if conversation_id:
                if not self.load(conversation_id):
                    logger.warning(f"Failed to load conversation {conversation_id}, creating new one")
                    self.create_new_conversation()
                
            # Load context files if specified
            if context_files:
                for file_path in context_files:
                    self.load_context_file(file_path)
                
            # Make sure we have a valid session
            if not self.conversation or not self.conversation.session:
                self.create_new_conversation()
            
            # Prepare conversation with user input
            self.conversation.prepare_conversation(message, image_path)
            
            # Get formatted messages for API and ensure they're not empty
            messages = self.conversation.get_formatted_messages()
            if not messages:
                logger.error("No messages to send to API - this should never happen")
                # Add a fallback message 
                messages = [{"role": "user", "content": message}]
            
            # Get response from API
            if streaming and self.api_client:
                if hasattr(self.api_client, 'get_streaming_response'):
                    async def stream_generator():
                        async for chunk in self.api_client.get_streaming_response(
                            messages=messages, 
                            stream_callback=stream_callback
                        ):
                            yield chunk
                            last_chunk = chunk
                            
                        # After streaming completes, add the full response to conversation
                        self.conversation.add_assistant_message(last_chunk)
                        self.save()
                    
                    return stream_generator()
                else:
                    logger.warning("API client doesn't support streaming, falling back to non-streaming")
                    streaming = False
            else:
                # Non-streaming path
                if self.api_client:
                    response = await self.api_client.get_response(messages)
                    # Add assistant's response to conversation
                    self.conversation.add_assistant_message(response)
                    
                    # Save conversation state and update token counts
                    self.save()
                    
                    # Update session token counts in the index
                    session = self.conversation.session
                    session_id = session.id
                    if session_id in self.session_manager.session_index:
                        self.session_manager.session_index[session_id]["token_count"] = session.total_tokens
                        self.session_manager._save_index(self.session_manager.session_index)
                    
                    return response
                else:
                    error_msg = "No API client available"
                    logger.error(error_msg)
                    return error_msg
                
        except Exception as e:
            error_msg = f"Error processing message: {str(e)}"
            logger.error(error_msg, exc_info=True)
            
            # Add error message to conversation if possible
            try:
                self.conversation.add_message(
                    role="system",
                    content=f"Error: {str(e)}",
                    category=MessageCategory.SYSTEM_OUTPUT,
                    metadata={"error": True, "type": "processing_error"}
                )
                self.save()
            except Exception:
                pass
                
            return error_msg
            
    def add_context(self, content: str, source: Optional[str] = None) -> Message:
        """
        Add context information to conversation.
        
        Args:
            content: Context content (documentation, files, etc.)
            source: Optional source identifier
            
        Returns:
            The created Message object
        """
        return self.conversation.add_context(content, source)
        
    def load_context_file(self, file_path: str) -> bool:
        """
        Load a context file into conversation.
        
        Args:
            file_path: Path to the file to load
            
        Returns:
            True if successful, False otherwise
        """
        return self.conversation.load_context_file(file_path)
        
    def list_context_files(self) -> List[Dict[str, Any]]:
        """
        List available context files.
        
        Returns:
            List of file information dictionaries
        """
        return self.context_loader.list_available_files()
        
    def add_action_result(
        self, 
        action_type: str, 
        result: str, 
        status: str = "completed"
    ) -> Message:
        """
        Add an action result to conversation.
        
        Args:
            action_type: Type of action executed
            result: Result of the action
            status: Status of execution (completed, error, etc.)
            
        Returns:
            The created Message object
        """
        return self.conversation.add_action_result(action_type, result, status)
        
    def get_token_usage(self) -> Dict[str, Any]:
        """
        Get token usage statistics for the current conversation across all sessions.

        Returns:
            Dictionary with token usage by category, session, and total.  In
            addition to the historical/legacy keys this now includes a
            forward-compatible structure preferred by the CLI:

            {
                "current_total_tokens": <int>,   # tokens currently loaded in context window
                "max_tokens": <int>,            # model context limit
                "available_tokens": <int>,      # remaining budget
                "percentage": <float>,          # current_total / max_tokens * 100
                "categories": {
                    "SYSTEM": <int>,
                    "CONTEXT": <int>,
                    ...
                },
                # --- legacy keys kept for backwards compatibility ---
                "total": <int>,
                "MessageCategory.SYSTEM": <int>,
                ...
            }
        """
        # ---------------------------
        # Always expose **current** window usage first so real-time UI can use
        # it without digging through historic sessions.
        # ---------------------------
        cw_usage = self.context_window.get_token_usage()
        categories_current = {
            cat.name: self.context_window.get_usage(cat) for cat in MessageCategory
        }

        standardized_usage: Dict[str, Any] = {
            "current_total_tokens": cw_usage.get("total", 0),
            "max_tokens": cw_usage.get("max", self.context_window.max_tokens),
            "available_tokens": cw_usage.get("available", self.context_window.available_tokens),
            "percentage": cw_usage.get("usage_percentage", 0),
            "categories": categories_current,
        }

        # ------------------------------------------------------------------
        # Build legacy / historical data so existing callers do not break.
        # ------------------------------------------------------------------
        if not self.conversation or not self.conversation.session:
            # Even if there is no active session we still return the
            # standardized structure (filled with zeros) so callers relying on
            # the new keys continue to work.
            return {
                **standardized_usage,
                "total": 0,
            }

        # The block below replicates the previous behaviour (session-chain
        # aggregation) while re-using the *standardized_usage* dict so we
        # avoid code duplication.
        current_session = self.conversation.session
        session_manager = self.session_manager

        legacy_usage: Dict[str, Any] = {
            "total": 0,
            "sessions": {},
        }

        # Per-category counts (legacy keys like "MessageCategory.SYSTEM")
        for category in MessageCategory:
            token_count = categories_current.get(category.name, 0)
            legacy_usage[str(category)] = token_count
            legacy_usage["total"] += token_count

        visited_sessions = set()

        def _add_session_tokens(session_id: str, is_current: bool = False):
            if session_id in visited_sessions:
                return 0
            visited_sessions.add(session_id)

            session_tokens = 0
            if is_current:
                session_tokens = legacy_usage["total"]
            else:
                idx_data = session_manager.session_index.get(session_id, {})
                if "token_count" in idx_data:
                    session_tokens = idx_data["token_count"]
                elif session_id in session_manager.sessions:
                    session_obj = session_manager.sessions[session_id][0]
                    session_tokens = session_obj.total_tokens

            legacy_usage["sessions"][session_id] = {"total": session_tokens}

            idx_entry = session_manager.session_index.get(session_id, {})
            if "continued_from" in idx_entry and not is_current:
                _add_session_tokens(idx_entry["continued_from"])
            if "continued_to" in idx_entry and not is_current:
                _add_session_tokens(idx_entry["continued_to"])

            return session_tokens

        # Seed with current session tokens
        _ = _add_session_tokens(current_session.id, is_current=True)

        # Chain total calculation (legacy)
        chain_total = sum(v["total"] for k, v in legacy_usage["sessions"].items())
        legacy_usage["chain_total"] = chain_total
        # Keep legacy total as the larger of current window or chain
        legacy_usage["total"] = max(legacy_usage["total"], chain_total)

        # ------------------------------------------------------------------
        # Merge legacy keys into the standardized structure (do not override
        # the new ones).
        # ------------------------------------------------------------------
        merged_usage = {**legacy_usage, **standardized_usage}
        return merged_usage
        
    def reset(self) -> None:
        """Reset conversation state."""
        self.conversation.reset()
        
    def save(self) -> bool:
        """
        Save current conversation state.
        
        Returns:
            True if successful, False otherwise
        """
        return self.conversation.save()
        
    def load(self, conversation_id: str) -> bool:
        """
        Load a specific conversation.
        
        Args:
            conversation_id: ID of the conversation to load
            
        Returns:
            True if successful, False otherwise
        """
        return self.conversation.load(conversation_id)
        
    def list_conversations(
        self, 
        limit: int = 100, # Why a limit of 100? Is it per page? 
        offset: int = 0,
        search_term: Optional[str] = None
    ) -> List[Dict]:
        """
        List available conversations with optional search.
        
        Args:
            limit: Maximum number of conversations to return
            offset: Offset for pagination
            search_term: Optional search term to filter by title
            
        Returns:
            List of conversation metadata dictionaries
        """
        # Get basic conversation listing from session manager
        conversations = self.session_manager.list_sessions(limit=100000, offset=0)
        
        # Enhance with meaningful titles
        for conversation in conversations:
            session_id = conversation.get("id")
            if session_id and not conversation.get("title"):
                # Try to load just enough of the session to extract a title
                try:
                    # Check if session is already in memory cache
                    if session_id in self.session_manager.sessions:
                        session = self.session_manager.sessions[session_id][0]
                    else:
                        # Load session file but only scan for title
                        session_path = self.session_manager.base_path / f"{session_id}.{self.session_manager.format}"
                        if session_path.exists():
                            with open(session_path, 'r', encoding='utf-8') as f:
                                data = json.load(f)
                                # Find first user message
                                title = None
                                if "messages" in data:
                                    for msg in data["messages"]:
                                        if msg.get("role") == "user":
                                            content = msg.get("content", "")
                                            if isinstance(content, str):
                                                # Use first line or first few words
                                                first_line = content.split('\n', 1)[0]
                                                title = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                                break
                                            elif isinstance(content, list) and content:
                                                # Handle structured content (like with images)
                                                for part in content:
                                                    if isinstance(part, dict) and part.get("type") == "text":
                                                        text = part.get("text", "")
                                                        first_line = text.split('\n', 1)[0]
                                                        title = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                                        break
                            
                                if title:
                                    conversation["title"] = title
                except Exception as e:
                    logger.warning(f"Error extracting title for session {session_id}: {e}")
                    # Keep default title if extraction fails
        
        # Filter by search term if provided
        if search_term and search_term.strip():
            search_lower = search_term.lower()
            conversations = [
                conv for conv in conversations
                if search_lower in (conv.get("title") or "").lower()
            ]
            
        # Apply pagination after filtering
        total_count = len(conversations)
        conversations = conversations[offset:offset+limit]
        
        # Add total count to first item as metadata if there are results
        if conversations:
            conversations[0]["_metadata"] = {"total_count": total_count}
            
        return conversations
        
    def get_current_session(self) -> Optional[Session]:
        """
        Get the current session.
        
        Returns:
            Current Session object or None
        """
        return self.conversation.session
        
    def get_conversation_id(self) -> Optional[str]:
        """
        Get current conversation ID.
        
        Returns:
            Current conversation ID or None
        """
        return self.conversation.session.id if self.conversation.session else None
        
    def create_new_conversation(self) -> str:
        """
        Create a new conversation.
        
        Returns:
            ID of the new conversation
        """
        # Create new session through session manager
        session = self.session_manager.create_session()
        
        # Update conversation system
        self.conversation.session = session
        self.conversation.system_prompt_sent = False
        self.conversation._modified = True
        
        # Return the new ID
        return session.id
        
    def delete_conversation(self, conversation_id: str) -> bool:
        """
        Delete a conversation.
        
        Args:
            conversation_id: ID of the conversation to delete
            
        Returns:
            True if successful, False otherwise
        """
        success = self.session_manager.delete_session(conversation_id)
        
        # If we deleted the current session, reset
        if self.conversation.session and self.conversation.session.id == conversation_id:
            self.reset()
            
        return success
        
    def get_session_stats(self) -> Dict[str, Any]:
        """
        Get statistics about sessions.
        
        Returns:
            Dictionary with session statistics
        """
        # Get counts from index and cache
        total_sessions = len(self.session_manager.session_index)
        cached_sessions = len(self.session_manager.sessions)
        
        # Get current session info
        current_session = self.conversation.session
        current_session_info = None
        if current_session:
            current_session_info = {
                "id": current_session.id,
                "message_count": len(current_session.messages),
                "created_at": current_session.created_at,
                "last_active": current_session.last_active
            }
            
        return {
            "total_sessions": total_sessions,
            "cached_sessions": cached_sessions,
            "current_session": current_session_info,
            "max_sessions_in_memory": self.session_manager.max_sessions_in_memory,
            "max_messages_per_session": self.session_manager.max_messages_per_session
        }
    
    def __del__(self):
        """Ensure resources are properly cleaned up."""
        # Save the current session if needed
        try:
            if hasattr(self, 'conversation') and self.conversation:
                self.save()
        except Exception:
            pass

    # ------------------------------------------------------------------
    # Snapshot / Branching API (delegates to SnapshotManager)
    # ------------------------------------------------------------------

    def create_snapshot(self, *, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Serialise current conversation + persist snapshot. Returns snapshot_id."""
        if not self.snapshot_manager:
            logger.warning("SnapshotManager unavailable – cannot snapshot")
            return None
        payload = json.dumps(self.conversation.session.to_dict(), ensure_ascii=False)
        parent_id = self.conversation.session.metadata.get("snapshot_parent")
        snap_id = self.snapshot_manager.snapshot(payload, parent_id=parent_id, meta=meta)
        # Track lineage inside session metadata so subsequent branches know where they came from
        self.conversation.session.metadata["snapshot_id"] = snap_id
        self.conversation.session.metadata["snapshot_parent"] = parent_id
        return snap_id

    def restore_snapshot(self, snapshot_id: str) -> bool:
        """Hydrate conversation from *snapshot_id*."""
        if not self.snapshot_manager:
            logger.warning("SnapshotManager unavailable – cannot restore snapshot")
            return False
        payload = self.snapshot_manager.restore(snapshot_id)
        if payload is None:
            return False
        try:
            data = json.loads(payload)
            session = Session.from_dict(data)
            self.conversation.session = session
            self.session_manager.current_session = session
            return True
        except Exception as e:
            logger.error(f"Failed to hydrate session from snapshot {snapshot_id}: {e}")
            return False

    def branch_from_snapshot(self, snapshot_id: str, *, meta: Optional[Dict[str, Any]] = None) -> Optional[str]:
        """Fork a snapshot & load the branched copy as current session."""
        if not self.snapshot_manager:
            logger.warning("SnapshotManager unavailable – cannot branch snapshot")
            return None
        try:
            new_id, payload = self.snapshot_manager.branch_from(snapshot_id, meta=meta)
            session = Session.from_dict(json.loads(payload))
            # Update lineage in new session so future branches chain correctly
            session.metadata["snapshot_parent"] = snapshot_id
            session.metadata["snapshot_id"] = new_id
            # Register new session with SessionManager so it persists separately on save()
            self.session_manager.current_session = session
            self.conversation.session = session
            self.conversation._modified = True
            return new_id
        except Exception as e:
            logger.error(f"Failed branching from snapshot {snapshot_id}: {e}")
            return None

    # ------------------------------------------------------------------
    # Checkpoint Management API (NEW)
    # ------------------------------------------------------------------

    async def create_manual_checkpoint(
        self,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a manual checkpoint with optional name and description.
        
        Args:
            name: Optional name for the checkpoint
            description: Optional description
            
        Returns:
            Checkpoint ID if successful, None otherwise
        """
        if not self.checkpoint_manager:
            logger.warning("Checkpoint manager not available")
            return None
            
        current_session = self.conversation.session
        if not current_session or not current_session.messages:
            logger.warning("No active session or messages to checkpoint")
            return None
            
        # Use the last message as the trigger
        last_message = current_session.messages[-1]
        
        return await self.checkpoint_manager.create_checkpoint(
            current_session,
            last_message,
            CheckpointType.MANUAL,
            name=name,
            description=description
        )
    
    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Rollback conversation to a specific checkpoint.
        
        Args:
            checkpoint_id: ID of the checkpoint to rollback to
            
        Returns:
            True if successful, False otherwise
        """
        if not self.checkpoint_manager:
            logger.warning("Checkpoint manager not available")
            return False
            
        success = await self.checkpoint_manager.rollback_to_checkpoint(checkpoint_id)
        
        if success:
            # Update conversation system with the restored session
            self.conversation.session = self.session_manager.current_session
            self.conversation._modified = True
            
        return success
    
    async def branch_from_checkpoint(
        self,
        checkpoint_id: str,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a new branch from a checkpoint.
        
        Args:
            checkpoint_id: ID of the checkpoint to branch from
            name: Optional name for the branch
            description: Optional description
            
        Returns:
            New branch checkpoint ID if successful, None otherwise
        """
        if not self.checkpoint_manager:
            logger.warning("Checkpoint manager not available")
            return None
            
        branch_id = await self.checkpoint_manager.branch_from_checkpoint(
            checkpoint_id,
            name=name,
            description=description
        )
        
        if branch_id:
            # Update conversation system with the new branch session
            self.conversation.session = self.session_manager.current_session
            self.conversation._modified = True
            
        return branch_id
    
    def list_checkpoints(
        self,
        session_id: Optional[str] = None,
        checkpoint_type: Optional[CheckpointType] = None,
        limit: int = 50
    ) -> List[Dict[str, Any]]:
        """
        List available checkpoints with optional filtering.
        
        Args:
            session_id: Filter by session ID
            checkpoint_type: Filter by checkpoint type
            limit: Maximum number of checkpoints to return
            
        Returns:
            List of checkpoint information
        """
        if not self.checkpoint_manager:
            return []
            
        return self.checkpoint_manager.list_checkpoints(
            session_id=session_id,
            checkpoint_type=checkpoint_type,
            limit=limit
        )
    
    async def cleanup_old_checkpoints(self) -> int:
        """
        Clean up old checkpoints according to retention policy.
        
        Returns:
            Number of checkpoints cleaned up
        """
        if not self.checkpoint_manager:
            return 0
            
        return await self.checkpoint_manager.cleanup_old_checkpoints()
