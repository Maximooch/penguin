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
from penguin.config import config as global_config
from penguin.system.context_loader import SimpleContextLoader
from penguin.system.context_window import ContextWindowManager
from penguin.system.conversation import ConversationSystem
from penguin.system.session_manager import SessionManager
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.checkpoint_manager import CheckpointManager, CheckpointConfig, CheckpointType
from penguin.constants import DEFAULT_MAX_MESSAGES_PER_SESSION

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
        max_messages_per_session: int = DEFAULT_MAX_MESSAGES_PER_SESSION,
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
        logger.info(f"Context window initialized with max tokens: {self.context_window.max_context_window_tokens}")
        
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
        
        # Initialize conversation system (default agent)
        self.conversation = ConversationSystem(
            context_window_manager=self.context_window,
            session_manager=self.session_manager,
            system_prompt=system_prompt,
            checkpoint_manager=self.checkpoint_manager
        )
        # Ensure the default agent is tagged on the initial session so
        # envelope fields (agent_id) are present for all messages.
        try:
            self.conversation.session.metadata.setdefault("agent_id", "default")
        except Exception:
            pass
        
        # Initialize context loader
        self.context_loader = SimpleContextLoader(
            context_manager=self.conversation
        )

        # Load core context files if configured
        try:
            loaded_files = self.context_loader.load_core_context()
            if loaded_files:
                logger.info(f"Loaded {len(loaded_files)} core context files")
        except Exception as e:
            logger.warning(f"Failed loading core context files: {e}")

        # Auto-load project docs (PENGUIN.md/AGENTS.md/README.md) into CONTEXT if enabled
        try:
            autoload = bool(global_config.get('context', {}).get('autoload_project_docs', True))
        except Exception:
            autoload = True
        if autoload and self.context_window:
            try:
                content, info = self.context_window.load_project_instructions(str(self.workspace_path))
                if content:
                    # Add project docs content as a CONTEXT message
                    self.conversation.add_context(content, source="project_docs")
                    logger.info(f"Project docs autoloaded: {', '.join(info.get('loaded_files', []))}")
            except Exception as e:
                logger.debug(f"Project docs autoload skipped due to error: {e}")

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

        # ---------------------------
        # Multi-agent scaffolding (Phase 2)
        # ---------------------------
        # Keep a registry of per-agent ConversationSystem and SessionManager.
        # Backward-compat: the "default" agent is the one used above and exposed
        # via `self.conversation` and `self.session_manager`.
        self.current_agent_id: str = "default"
        self.agent_sessions: Dict[str, ConversationSystem] = {"default": self.conversation}
        self.agent_session_managers: Dict[str, SessionManager] = {"default": self.session_manager}
        # Namespace checkpoint managers per agent (optional; default agent uses the prebuilt one).
        self.agent_checkpoint_managers: Dict[str, Optional[CheckpointManager]] = {"default": self.checkpoint_manager}
        # Separate context windows per agent (default shares existing)
        self.agent_context_windows: Dict[str, ContextWindowManager] = {"default": self.context_window}
        # Track parent/sub-agent relationships
        self.sub_agent_parent: Dict[str, str] = {}
        self.parent_sub_agents: Dict[str, List[str]] = {}

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
        
    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.conversation.set_system_prompt(prompt)

    # ------------------------------------------------------------------
    # Multi-agent helpers
    # ------------------------------------------------------------------

    def _ensure_agent(self, agent_id: str) -> None:
        """Ensure internal structures for `agent_id` exist.

        Creates a dedicated SessionManager under `conversations/<agent_id>/` and
        a separate ConversationSystem bound to it. Checkpoints are stored under
        `<workspace>/agents/<agent_id>/checkpoints` to keep them isolated.
        """
        if agent_id in self.agent_sessions:
            return

        # Create namespaced paths
        conversations_root = Path(self.workspace_path) / "conversations"
        agent_conv_path = conversations_root / agent_id
        agent_conv_path.mkdir(parents=True, exist_ok=True)

        # Dedicated SessionManager per agent
        agent_sm = SessionManager(
            base_path=str(agent_conv_path),
            max_messages_per_session=self.session_manager.max_messages_per_session,
            max_sessions_in_memory=self.session_manager.max_sessions_in_memory,
            auto_save_interval=self.session_manager.auto_save_interval,
        )

        # Dedicated ContextWindowManager per agent (isolation by default)
        agent_cw = ContextWindowManager(
            model_config=self.model_config,
            api_client=self.api_client,
            config_obj=self._get_live_config(),
        )

        # Dedicated CheckpointManager per agent (separate folder tree)
        agent_workspace = Path(self.workspace_path) / "agents" / agent_id
        agent_workspace.mkdir(parents=True, exist_ok=True)
        agent_cp: Optional[CheckpointManager] = None
        if self.checkpoint_manager is not None:
            try:
                agent_cp = CheckpointManager(
                    workspace_path=agent_workspace,
                    session_manager=agent_sm,
                    config=self.checkpoint_manager.config,
                )
            except Exception as e:
                logger.warning(f"Failed to init agent checkpoint manager for '{agent_id}': {e}")
                agent_cp = None

        # ConversationSystem for this agent (uses its own ContextWindowManager)
        agent_conv = ConversationSystem(
            context_window_manager=agent_cw,
            session_manager=agent_sm,
            system_prompt=self.conversation.system_prompt,
            checkpoint_manager=agent_cp,
        )
        # Ensure the new agent's session is tagged with its owner for envelope routing
        try:
            agent_conv.session.metadata.setdefault("agent_id", agent_id)
        except Exception:
            pass

        # Register
        self.agent_session_managers[agent_id] = agent_sm
        self.agent_checkpoint_managers[agent_id] = agent_cp
        self.agent_sessions[agent_id] = agent_conv
        self.agent_context_windows[agent_id] = agent_cw

    def set_current_agent(self, agent_id: str) -> None:
        """Switch active agent for backward-compatible APIs.

        Updates `self.conversation`, `self.session_manager`, and context loader
        bindings to the agent's instances.
        """
        self._ensure_agent(agent_id)
        self.current_agent_id = agent_id
        self.conversation = self.agent_sessions[agent_id]
        self.session_manager = self.agent_session_managers[agent_id]
        # Keep checkpoint_manager reference in sync (optional)
        self.checkpoint_manager = self.agent_checkpoint_managers.get(agent_id)
        # Update current context window reference
        try:
            self.context_window = self.agent_context_windows[agent_id]
        except Exception:
            pass
        # Update context loader target
        if getattr(self, "context_loader", None):
            self.context_loader.context_manager = self.conversation

    def get_current_context_window(self) -> Optional[ContextWindowManager]:
        """Return the active agent's ContextWindowManager."""
        try:
            return self.agent_context_windows.get(self.current_agent_id, self.context_window)
        except Exception:
            return self.context_window

    def get_agent_conversation(self, agent_id: str, *, create_if_missing: bool = True) -> ConversationSystem:
        if create_if_missing:
            self._ensure_agent(agent_id)
        conv = self.agent_sessions.get(agent_id)
        if conv is None:
            raise KeyError(f"Agent conversation not found for '{agent_id}'")
        return conv

    def create_agent_conversation(self, agent_id: str) -> str:
        """Create a new conversation for a specific agent and return its ID."""
        self._ensure_agent(agent_id)
        sm = self.agent_session_managers[agent_id]
        conv = self.agent_sessions[agent_id]
        session = sm.create_session()
        # Tag session with agent ownership for Phase 3 compatibility
        try:
            session.metadata["agent_id"] = agent_id
        except Exception:
            pass
        conv.session = session
        conv.system_prompt_sent = False
        conv._modified = True
        # If switching to this agent is desired, caller should invoke set_current_agent
        return session.id

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        share_session: bool = True,
        share_context_window: bool = True,
        shared_context_window_max_tokens: Optional[int] = None,
    ) -> None:
        """Create a sub-agent, honoring session/context-window sharing preferences."""
        self._ensure_agent(parent_agent_id)

        if share_session and not share_context_window:
            logger.warning(
                "Sub-agent '%s' requested share_session without share_context_window; forcing context window sharing.",
                agent_id,
            )
            share_context_window = True

        if share_session:
            parent_conv = self.agent_sessions[parent_agent_id]
            self.agent_sessions[agent_id] = parent_conv
            self.agent_session_managers[agent_id] = self.agent_session_managers[parent_agent_id]
            self.agent_checkpoint_managers[agent_id] = self.agent_checkpoint_managers.get(parent_agent_id)
        else:
            self._ensure_agent(agent_id)

        if share_context_window:
            self.agent_context_windows[agent_id] = self.agent_context_windows[parent_agent_id]

        # Configure child's CWM max_context_window_tokens from parent (optionally clamp) when not sharing the object
        if not share_context_window:
            try:
                parent_cw = self.agent_context_windows[parent_agent_id]
                child_cw = self.agent_context_windows[agent_id]
                if parent_cw and child_cw and hasattr(parent_cw, "max_context_window_tokens") and hasattr(child_cw, "max_context_window_tokens"):
                    desired = parent_cw.max_context_window_tokens
                    if shared_context_window_max_tokens is not None:
                        desired = min(desired, int(shared_context_window_max_tokens))
                    child_cw.max_context_window_tokens = desired
                    if shared_context_window_max_tokens is not None:
                        note = (
                            f"Note: Sub-agent '{agent_id}' uses isolated CWM with max_context_window_tokens={desired} (parent={parent_cw.max_context_window_tokens})."
                        )
                        meta = {
                            "type": "cw_clamp_notice",
                            "sub_agent": agent_id,
                            "child_max": desired,
                            "parent_max": parent_cw.max_context_window_tokens,
                            "clamped": bool(desired < parent_cw.max_context_window_tokens),
                        }
                        # Record on parent and mirror to child for easier discovery
                        self.add_system_note(parent_agent_id, content=note, metadata=dict(meta))
                        self.add_system_note(agent_id, content=note, metadata={**meta, "audience": "child"})
            except Exception as e:  # pragma: no cover - defensive logging
                logger.warning(f"Failed to configure sub-agent CWM: {e}")

        # When session is isolated, copy SYSTEM/CONTEXT messages for initial state
        if not share_session:
            try:
                self.partial_share_context(
                    parent_agent_id,
                    agent_id,
                    categories=[MessageCategory.SYSTEM, MessageCategory.CONTEXT],
                    replace_child_context=False,
                )
            except Exception as e:
                logger.warning(f"Failed partial context share to '{agent_id}': {e}")

        # Track relationships
        self.sub_agent_parent[agent_id] = parent_agent_id
        subs = self.parent_sub_agents.setdefault(parent_agent_id, [])
        if agent_id not in subs:
            subs.append(agent_id)

        # Ensure conversation metadata reflects agent_id
        try:
            conv = self.agent_sessions[agent_id]
            conv.session.metadata.setdefault("agent_id", agent_id)
        except Exception:  # pragma: no cover - defensive
            pass

    def save_all(self) -> int:
        """Save all agent conversations. Returns count of successful saves."""
        saved = 0
        for aid, conv in self.agent_sessions.items():
            try:
                if conv.save():
                    saved += 1
            except Exception as e:
                logger.warning(f"Failed to save conversation for agent '{aid}': {e}")
        return saved

    def partial_share_context(
        self,
        parent_agent_id: str,
        child_agent_id: str,
        *,
        categories: Optional[List[MessageCategory]] = None,
        replace_child_context: bool = False,
    ) -> None:
        """Copy selected categories (default: SYSTEM + CONTEXT) from parent to child.

        On replace_child_context=True, clears existing messages in those categories in the child first.
        """
        self._ensure_agent(parent_agent_id)
        self._ensure_agent(child_agent_id)

        cats = categories or [MessageCategory.SYSTEM, MessageCategory.CONTEXT]
        parent_conv = self.agent_sessions[parent_agent_id]
        child_conv = self.agent_sessions[child_agent_id]

        if replace_child_context:
            try:
                child_conv.session.messages = [m for m in child_conv.session.messages if m.category not in cats]
                child_conv._modified = True
            except Exception:
                pass

        for msg in parent_conv.session.messages:
            if msg.category in cats:
                try:
                    child_conv.add_message(role=msg.role, content=msg.content, category=msg.category, metadata=msg.metadata)
                except Exception:
                    continue

        # Recompute usage under child's CWM
        try:
            if child_conv.context_window:
                child_conv.session = child_conv.context_window.process_session(child_conv.session)
        except Exception:
            pass

    def list_all_conversations(self, *, limit_per_agent: int = 1000, offset: int = 0) -> List[Dict[str, Any]]:
        """List conversations across all agents with agent_id included."""
        results: List[Dict[str, Any]] = []
        for aid, sm in self.agent_session_managers.items():
            try:
                lst = sm.list_sessions(limit=limit_per_agent, offset=offset)
                for item in lst:
                    item = dict(item)
                    item["agent_id"] = aid
                    results.append(item)
            except Exception as e:
                logger.warning(f"Failed listing sessions for agent '{aid}': {e}")
        return results

    def load_agent_conversation(self, agent_id: str, conversation_id: str, *, activate: bool = True) -> bool:
        """Load a specific conversation for a given agent. Optionally activate the agent."""
        self._ensure_agent(agent_id)
        conv = self.agent_sessions[agent_id]
        ok = conv.load(conversation_id)
        if ok and activate:
            self.set_current_agent(agent_id)
        return ok

    def delete_agent_conversation(self, agent_id: str, conversation_id: str) -> bool:
        """Delete a specific conversation for a given agent."""
        self._ensure_agent(agent_id)
        sm = self.agent_session_managers[agent_id]
        success = sm.delete_session(conversation_id)
        if success:
            try:
                conv = self.agent_sessions[agent_id]
                if conv.session and conv.session.id == conversation_id:
                    conv.reset()
            except Exception:
                pass
        return success

    def add_system_note(self, agent_id: str, content: str, *, metadata: Optional[Dict[str, Any]] = None) -> None:
        """Add a system-level note to an agent's conversation and save it."""
        try:
            conv = self.get_agent_conversation(agent_id)
            conv.add_message(
                role="system",
                content=content,
                category=MessageCategory.SYSTEM,
                metadata=metadata or {"type": "agent_notice"},
            )
            self.save()
        except Exception as e:
            logger.warning(f"Failed to add system note to agent '{agent_id}': {e}")

    def log_delegation_event(
        self,
        *,
        delegation_id: str,
        parent_agent_id: str,
        child_agent_id: str,
        event: str,
        message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        mirror_to_child: bool = True,
    ) -> None:
        """Record a delegation lifecycle event in the relevant conversations."""

        base_meta = {
            "type": "delegation_event",
            "delegation_id": delegation_id,
            "parent_agent_id": parent_agent_id,
            "child_agent_id": child_agent_id,
            "event": event,
        }
        if metadata:
            base_meta.update(metadata)

        content = message or f"Delegation {delegation_id} ({parent_agent_id} → {child_agent_id}): {event}"
        self.add_system_note(parent_agent_id, content, metadata=dict(base_meta))

        if mirror_to_child:
            try:
                meta_child = dict(base_meta)
                meta_child["audience"] = "child"
                self.add_system_note(
                    child_agent_id,
                    content,
                    metadata=meta_child,
                )
            except Exception:
                logger.debug("Failed to mirror delegation event to child '%s'", child_agent_id)

    def agents_sharing_session(self, agent_id: str) -> List[str]:
        """Return agent IDs that share the same ConversationSystem as agent_id (including itself).

        Useful to warn before deleting sessions that are shared across agents.
        """
        self._ensure_agent(agent_id)
        target_conv = self.agent_sessions[agent_id]
        shared = [aid for aid, conv in self.agent_sessions.items() if conv is target_conv]
        return shared
        
    async def process_message(
        self,
        message: str,
        conversation_id: Optional[str] = None,
        image_paths: Optional[List[str]] = None,
        streaming: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        context_files: Optional[List[str]] = None
    ) -> Union[str, AsyncGenerator[str, None]]:
        """
        Process a user message and get AI response.

        Args:
            message: User input message
            conversation_id: Optional ID to load specific conversation
            image_paths: Optional list of image paths for multi-modal input
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
            self.conversation.prepare_conversation(message, image_paths=image_paths)
            
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
                        # add_assistant_message automatically strips action tags
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
                    metadata={"error": True, "type": "processing_error"},
                    message_type="status",
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
        return self.conversation.list_context_files()
        
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
                "max_tokens": <int>,            # model context limit (legacy key, deprecated)
                "max_context_window_tokens": <int>,
                "available_tokens": <int>,      # remaining budget
                "percentage": <float>,          # current_total / max_context_window_tokens * 100
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

        # Get truncation stats from context window manager
        truncation_tracker = self.context_window.truncation_tracker
        truncation_stats = {
            "total_truncations": truncation_tracker.session_total_truncations,
            "messages_removed": truncation_tracker.session_total_messages_removed,
            "tokens_freed": truncation_tracker.session_total_tokens_freed,
            "by_category": {
                cat.name: truncation_tracker.get_category_truncations(cat)
                for cat in MessageCategory
            },
            "recent_events": [
                {
                    "category": event.category.name,
                    "messages_removed": event.messages_removed,
                    "tokens_freed": event.tokens_freed,
                    "timestamp": event.timestamp
                }
                for event in truncation_tracker.get_recent_events(limit=5)
            ]
        }

        standardized_usage: Dict[str, Any] = {
            "current_total_tokens": cw_usage.get("total", 0),
            "max_tokens": cw_usage.get("max", self.context_window.max_context_window_tokens),  # Legacy key for backward compat
            "max_context_window_tokens": cw_usage.get(
                "max", self.context_window.max_context_window_tokens
            ),
            "available_tokens": cw_usage.get("available", self.context_window.available_tokens),
            "percentage": cw_usage.get("usage_percentage", 0),
            "categories": categories_current,
            "truncations": truncation_stats,
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
        # Preserve agent context on new session
        try:
            self.conversation.session.metadata["agent_id"] = getattr(self, "current_agent_id", "default")
        except Exception:
            pass
        
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
        limit: int = 100,
        offset: int = 0,
        search_term: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
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
        conversations = self.session_manager.list_sessions(limit=limit, offset=offset)
        
        # Enhance with meaningful titles
        for conversation in conversations:
            session_id = conversation.get("id")
            if session_id:
                conversation.setdefault("agent_id", conversation.get("agent_id") or conversation.get("metadata", {}).get("agent_id"))
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

            # Ensure agent_id is populated even if index metadata lacked it
            if session_id and not conversation.get("agent_id"):
                try:
                    session = self.session_manager.load_session(session_id)
                    if session and session.metadata.get("agent_id"):
                        conversation["agent_id"] = session.metadata.get("agent_id")
                except Exception as e:
                    logger.debug(f"Unable to load agent metadata for {session_id}: {e}")
        
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

    def get_conversation_history(
        self,
        session_id: str,
        *,
        include_system: bool = True,
        limit: Optional[int] = None,
    ) -> List[Dict[str, Any]]:
        """Return conversation messages annotated with agent metadata."""

        session = self.session_manager.load_session(session_id)
        if session is None:
            return []

        messages: List[Dict[str, Any]] = []
        for message in session.messages:
            if not include_system and message.role == "system":
                continue
            entry = {
                "id": message.id,
                "role": message.role,
                "content": message.content,
                "category": message.category.name if hasattr(message.category, "name") else message.category,
                "timestamp": message.timestamp,
                "agent_id": message.agent_id,
                "recipient_id": message.recipient_id,
                "message_type": message.message_type,
                "metadata": message.metadata,
            }
            messages.append(entry)

        if limit is not None and limit > 0:
            messages = messages[-limit:]

        return messages
        
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
        try:
            session.metadata["agent_id"] = getattr(self, "current_agent_id", "default")
        except Exception:
            pass
        
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

    def list_agents(self) -> List[str]:
        """Return all registered agent identifiers."""
        return sorted(self.agent_sessions.keys())

    def list_sub_agents(self, parent_agent_id: Optional[str] = None) -> Dict[str, List[str]]:
        """Return mapping of parent agents to their sub-agents.

        If ``parent_agent_id`` is provided, the mapping is filtered to that parent.
        """
        if parent_agent_id:
            subs = self.parent_sub_agents.get(parent_agent_id, [])
            return {parent_agent_id: list(subs)}
        return {parent: list(children) for parent, children in self.parent_sub_agents.items()}

    # ------------------------------------------------------------------
    # Shared Context Window Management
    # ------------------------------------------------------------------
    def shares_context_window(self, agent_id_1: str, agent_id_2: str) -> bool:
        """Check if two agents share the same context window object.

        Args:
            agent_id_1: First agent ID
            agent_id_2: Second agent ID

        Returns:
            True if both agents point to the same ContextWindowManager object
        """
        cw1 = self.agent_context_windows.get(agent_id_1)
        cw2 = self.agent_context_windows.get(agent_id_2)
        if cw1 is None or cw2 is None:
            return False
        return cw1 is cw2

    def get_context_sharing_info(self, agent_id: str) -> Dict[str, Any]:
        """Get information about an agent's context sharing relationships.

        Args:
            agent_id: The agent to query

        Returns:
            Dict with:
                - has_context_window: Whether agent has a CWM
                - parent: Parent agent ID (if sub-agent)
                - shares_with_parent: Whether shares CWM with parent
                - children: List of child agent IDs
                - shares_with_children: List of children that share CWM
        """
        result: Dict[str, Any] = {
            "agent_id": agent_id,
            "has_context_window": agent_id in self.agent_context_windows,
            "parent": None,
            "shares_with_parent": False,
            "children": [],
            "shares_with_children": [],
        }

        # Check parent relationship
        parent = self.sub_agent_parent.get(agent_id)
        if parent:
            result["parent"] = parent
            result["shares_with_parent"] = self.shares_context_window(agent_id, parent)

        # Check children relationships
        children = self.parent_sub_agents.get(agent_id, [])
        result["children"] = list(children)
        result["shares_with_children"] = [
            child for child in children
            if self.shares_context_window(agent_id, child)
        ]

        return result

    def get_context_window_stats(self, agent_id: str) -> Optional[Dict[str, Any]]:
        """Get token usage statistics for an agent's context window.

        Args:
            agent_id: The agent to query

        Returns:
            Dict with token counts and limits, or None if no CWM
        """
        cw = self.agent_context_windows.get(agent_id)
        if cw is None:
            return None

        return {
            "agent_id": agent_id,
            "max_context_window_tokens": getattr(cw, "max_context_window_tokens", None),
            "current_tokens": getattr(cw, "current_tokens", None),
            "reserved_tokens": getattr(cw, "reserved_tokens", None),
        }

    def sync_context_to_child(
        self,
        parent_agent_id: str,
        child_agent_id: str,
        *,
        categories: Optional[List[MessageCategory]] = None,
        replace_existing: bool = False,
    ) -> bool:
        """Synchronize context from parent to child agent.

        This is useful for agents with isolated context windows that need
        to receive updates from their parent.

        Args:
            parent_agent_id: Source agent
            child_agent_id: Destination agent
            categories: Message categories to sync (default: SYSTEM, CONTEXT)
            replace_existing: If True, replace child's messages in those categories

        Returns:
            True if sync succeeded
        """
        try:
            self.partial_share_context(
                parent_agent_id,
                child_agent_id,
                categories=categories,
                replace_child_context=replace_existing,
            )
            return True
        except Exception as e:
            logger.warning(f"Failed to sync context from '{parent_agent_id}' to '{child_agent_id}': {e}")
            return False

    def get_shared_context_agents(self, agent_id: str) -> List[str]:
        """Get all agents that share the same context window as the given agent.

        Args:
            agent_id: The agent to query

        Returns:
            List of agent IDs that share the same CWM object
        """
        cw = self.agent_context_windows.get(agent_id)
        if cw is None:
            return []

        return [
            aid for aid, other_cw in self.agent_context_windows.items()
            if other_cw is cw and aid != agent_id
        ]

    def remove_agent(self, agent_id: str) -> bool:
        """Remove an agent and associated structures.

        Returns True if the agent was removed, False when no action was taken.
        """
        if agent_id == "default":
            raise ValueError("Cannot remove the default agent")

        if agent_id not in self.agent_sessions:
            return False

        # Prevent removal when parent still has active sub-agents
        children = self.parent_sub_agents.get(agent_id, [])
        if children:
            raise ValueError(f"Agent '{agent_id}' has active sub-agents: {children}")

        parent = self.sub_agent_parent.pop(agent_id, None)
        if parent:
            subs = self.parent_sub_agents.get(parent)
            if subs and agent_id in subs:
                subs.remove(agent_id)
                if not subs:
                    self.parent_sub_agents.pop(parent, None)

        self.agent_sessions.pop(agent_id, None)
        self.agent_session_managers.pop(agent_id, None)
        self.agent_checkpoint_managers.pop(agent_id, None)
        self.agent_context_windows.pop(agent_id, None)
        if getattr(self, "context_loader", None) and getattr(self.context_loader, "context_manager", None) is self.conversation:
            # Ensure context loader still references active conversation
            try:
                self.context_loader.context_manager = self.conversation
            except Exception:
                pass
        if self.current_agent_id == agent_id:
            self.current_agent_id = "default"
            self.conversation = self.agent_sessions["default"]
        return True

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
