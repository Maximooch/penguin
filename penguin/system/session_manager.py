"""
Session management for Penguin conversation system.

This module handles session lifecycle operations including:
- Creating and loading sessions
- Saving sessions with transaction safety
- Managing session boundaries and transitions
- Creating continuation sessions for long-running conversations
"""

import json
import logging
import os
import shutil
import threading
import time
from collections import OrderedDict
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple, Any

# ------------------------------------------------------------------
# Ensure builtins.open is always available (some libraries may delete
# or monkey-patch it which breaks file operations).
# ------------------------------------------------------------------
import builtins  # noqa: E402
import io  # noqa: E402
if not hasattr(builtins, "open") or builtins.open is None:  # type: ignore[attr-defined]
    builtins.open = io.open  # type: ignore[attr-defined]

# ------------------------------------------------------------------
# Capture a stable reference to the open function to avoid issues if
# third-party libraries later delete or monkey-patch builtins.open.
# ------------------------------------------------------------------
_safe_open = builtins.open  # type: ignore[assignment]
# Ensure the builtins namespace retains a valid open function even if
# external libraries attempt to remove or overwrite it later.
builtins.open = _safe_open  # type: ignore[attr-defined]

from penguin.config import CONVERSATIONS_PATH
from penguin.system.state import Message, MessageCategory, Session, create_message

logger = logging.getLogger(__name__)


class SessionManager:
    """
    Manages conversation sessions including creation, persistence, and boundaries.
    
    Handles session lifecycle operations such as:
    - Creating and loading sessions from storage
    - Saving sessions with transaction safety
    - Detecting when to create a new session
    - Creating continuation sessions for long-running conversations
    - Maintaining a lightweight index of all sessions
    """

    def __init__(
        self, 
        base_path: str = CONVERSATIONS_PATH,
        max_messages_per_session: int = 5000,  # Increased from 500 to 5000
        max_sessions_in_memory: int = 20,
        format: str = "json",
        auto_save_interval: int = 60  # seconds
    ):
        """
        Initialize the session manager.
        
        Args:
            base_path: Directory for storing session files
            max_messages_per_session: Maximum messages before creating a new session
            max_sessions_in_memory: Maximum number of sessions to keep in memory
            format: File format for session storage (json only for now)
            auto_save_interval: Seconds between auto-saves of modified sessions
        """
        self.base_path = Path(base_path)
        self.max_messages_per_session = max_messages_per_session
        self.max_sessions_in_memory = max_sessions_in_memory
        self.format = format
        self.current_session: Optional[Session] = None
        
        # Use OrderedDict as an LRU cache for sessions
        self.sessions: OrderedDict[str, Tuple[Session, bool]] = OrderedDict()  # (session, is_modified)
        
        # Create directory if it doesn't exist
        os.makedirs(self.base_path, exist_ok=True)
        
        # Initialize the session index
        self.index_path = self.base_path / "session_index.json"
        self.session_index = self._load_or_create_index()
        
        # Setup auto-save thread if interval > 0
        self.auto_save_interval = auto_save_interval
        if auto_save_interval > 0:
            self._stop_auto_save = threading.Event()
            self._auto_save_thread = threading.Thread(
                target=self._auto_save_loop, 
                daemon=True
            )
            self._auto_save_thread.start()
    
    def _load_or_create_index(self) -> Dict[str, Dict[str, Any]]:
        """Load the session index or create it if it doesn't exist."""
        if not self.index_path.exists():
            # Create an empty index
            index = {}
            self._save_index(index)
            return index
            
        try:
            with _safe_open(self.index_path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"Error loading session index: {str(e)}")
            # Create a new index by scanning the directory
            return self._rebuild_index()
    
    def _rebuild_index(self) -> Dict[str, Dict[str, Any]]:
        """Rebuild the session index by scanning session files."""
        logger.info("Rebuilding session index from files")
        index = {}
        
        # Scan for session files
        for path in self.base_path.glob(f"*.{self.format}"):
            if path.name == f"session_index.{self.format}":
                continue
                
            session_id = path.stem
            try:
                # Load minimal metadata without loading all messages
                with _safe_open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Extract key metadata
                metadata = data.get("metadata", {})
                created_at = data.get("created_at", "")
                last_active = data.get("last_active", "")
                
                index[session_id] = {
                    "created_at": created_at,
                    "last_active": last_active,
                    "message_count": metadata.get("message_count", 0),
                    "title": metadata.get("title", f"Session {session_id[-8:]}")
                }
            except Exception as e:
                logger.error(f"Error reading session metadata from {path}: {str(e)}")
        
        # Save the rebuilt index
        self._save_index(index)
        return index
    
    def _save_index(self, index: Dict[str, Dict[str, Any]]) -> None:
        """Save the session index to disk."""
        try:
            # Write to temp file first - fix the suffix
            temp_path = Path(f"{self.index_path}.temp")  # Fix: Use explicit Path constructor
            with _safe_open(temp_path, 'w', encoding='utf-8') as f:
                json.dump(index, f, indent=2)
                
            # Atomic rename
            os.replace(temp_path, self.index_path)
        except Exception as e:
            logger.error(f"Error saving session index: {str(e)}")
    
    def _auto_save_loop(self) -> None:
        """Background thread that auto-saves modified sessions."""
        while not self._stop_auto_save.is_set():
            try:
                self._auto_save_sessions()
            except Exception as e:
                logger.error(f"Error in auto-save loop: {str(e)}")
                
            # Sleep for the configured interval
            self._stop_auto_save.wait(self.auto_save_interval)
    
    def _auto_save_sessions(self) -> None:
        """Save all modified sessions."""
        modified_sessions = []
        
        # Find all modified sessions
        for session_id, (session, is_modified) in list(self.sessions.items()):
            if is_modified:
                modified_sessions.append(session)
                
        # Save each modified session
        for session in modified_sessions:
            self.save_session(session)
            # Mark as not modified in the cache
            if session.id in self.sessions:
                self.sessions[session.id] = (session, False)
                
        # If current session is modified, save it too
        if self.current_session and self.current_session.id not in self.sessions:
            self.save_session(self.current_session)
    
    def create_session(self) -> Session:
        """
        Create a new empty session.
        
        Returns:
            New Session object
        """
        session = Session()
        # Initialize message count
        session.metadata["message_count"] = 0
        self.sessions[session.id] = (session, True)  # True = modified
        self.current_session = session
        
        # Update the index
        self.session_index[session.id] = {
            "created_at": session.created_at,
            "last_active": session.last_active,
            "message_count": 0,
            "title": f"Session {session.id[-8:]}"
        }
        self._save_index(self.session_index)
        
        logger.debug(f"Created new session: {session.id}")
        return session
    
    def load_session(self, session_id: str) -> Optional[Session]:
        """
        Load a session by ID with error recovery.
        
        Args:
            session_id: ID of the session to load
            
        Returns:
            Session object if found, None if not found or unrecoverable
        """
        # Check if already loaded
        if session_id in self.sessions:
            # Move to end of OrderedDict to mark as most recently used
            session, is_modified = self.sessions.pop(session_id)
            self.sessions[session_id] = (session, is_modified)
            self.current_session = session
            return session
            
        # Try primary file
        primary_path = self.base_path / f"{session_id}.{self.format}"
        backup_path = self.base_path / f"{session_id}.{self.format}.bak"
        primary_error: Optional[Exception] = None
        
        try:
            # Try loading from primary file
            session = self._load_from_file(primary_path)
            if session and session.validate():
                self._add_to_session_cache(session_id, session)
                self.current_session = session
                logger.debug(f"Loaded session from primary file: {session_id}")
                return session
        except Exception as e:
            primary_error = e
            logger.error(f"Error loading session {session_id} from primary file: {str(e)}", exc_info=True)
            
            # Try backup file
            try:
                if backup_path.exists():
                    session = self._load_from_file(backup_path)
                    if session and session.validate():
                        self._add_to_session_cache(session_id, session)
                        self.current_session = session
                        
                        # Restore from backup
                        shutil.copy2(backup_path, primary_path)
                        logger.warning(f"Restored session {session_id} from backup")
                        return session
            except Exception as backup_error:
                logger.error(f"Error loading backup for session {session_id}: {str(backup_error)}", exc_info=True)
        
        # If we get here, both primary and backup loading failed
        logger.warning(f"Could not load session {session_id}, creating recovery session. Primary error: {primary_error!r}", exc_info=True)
        return self._create_recovery_session(session_id)
    
    def _add_to_session_cache(self, session_id: str, session: Session) -> None:
        """Add a session to the cache, managing the LRU behavior."""
        # Add to sessions cache
        self.sessions[session_id] = (session, False)  # False = not modified
        
        # If we've exceeded max_sessions_in_memory, remove oldest
        if len(self.sessions) > self.max_sessions_in_memory:
            # Get oldest (first) item from OrderedDict
            oldest_id, (oldest_session, is_modified) = next(iter(self.sessions.items()))
            
            # If modified, save before removing
            if is_modified:
                self.save_session(oldest_session)
                
            # Remove from cache
            del self.sessions[oldest_id]
            logger.debug(f"Evicted session {oldest_id} from cache (LRU policy)")
    
    def _load_from_file(self, file_path: Path) -> Optional[Session]:
        """
        Load a session from a file.
        
        Args:
            file_path: Path to the session file
            
        Returns:
            Session object or None if file doesn't exist
        """
        if not file_path.exists():
            return None
            
        with _safe_open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        session = Session.from_dict(data)
        
        # Ensure message_count exists in metadata
        if "message_count" not in session.metadata:
            session.metadata["message_count"] = len(session.messages)
            
        return session
    
    def _create_recovery_session(self, failed_session_id: str) -> Session:
        """
        Create a recovery session when loading fails.
        
        Args:
            failed_session_id: ID of the session that failed to load
            
        Returns:
            New Session object with recovery notice
        """
        # Extract original ID if possible, otherwise use as is
        if failed_session_id.startswith("session_"):
            original_id = failed_session_id
        else:
            original_id = f"session_{failed_session_id}"
            
        # Create new session with recovery notice
        session = Session(
            id=f"recovery_{datetime.now().strftime('%Y%m%d_%H%M%S')}",
            metadata={
                "recovered_from": original_id,
                "recovery_time": datetime.now().isoformat(),
                "message_count": 1
            }
        )
        
        # Add recovery notice message
        recovery_message = create_message(
            role="system",
            content=f"This is a recovery session. The original session '{original_id}' could not be loaded due to file corruption or other errors.",
            category=MessageCategory.SYSTEM, 
            metadata={"type": "recovery_notice"}
        )
        session.add_message(recovery_message)
        
        # Store in sessions dict and update index
        self._add_to_session_cache(session.id, session)
        self.session_index[session.id] = {
            "created_at": session.created_at,
            "last_active": session.last_active,
            "message_count": 1,
            "title": f"Recovery of {original_id[-8:]}",
            "recovered_from": original_id
        }
        self._save_index(self.session_index)
        
        self.current_session = session
        logger.info(f"Created recovery session {session.id} for failed session {original_id}")
        
        return session
        
    def save_session(self, session: Optional[Session] = None) -> bool:
        """
        Save a session with transaction safety.
        
        Args:
            session: Session to save (defaults to current_session)
            
        Returns:
            True if saved successfully, False otherwise
        """
        # Guard against external tampering with the built-in open during runtime.
        import builtins as _blt
        if getattr(_blt, "open", None) is not _safe_open:
            _blt.open = _safe_open  # type: ignore[attr-defined]
        session = session or self.current_session
        if not session:
            logger.error("No session to save")
            return False
            
        try:
            temp_path = self.base_path / f"{session.id}.{self.format}.temp"
            backup_path = self.base_path / f"{session.id}.{self.format}.bak"
            target_path = self.base_path / f"{session.id}.{self.format}"
            
            # Update session metadata
            session.metadata["message_count"] = len(session.messages)
            session.last_active = datetime.now().isoformat()
            
            # Add token count to metadata - ensure it's calculated from the current state
            token_count = session.total_tokens
            session.metadata["token_count"] = token_count
            
            # Write to temp file first
            with _safe_open(temp_path, 'w', encoding='utf-8') as f:
                f.write(session.to_json())
                
            # Create backup of current file if it exists
            if target_path.exists():
                shutil.copy2(target_path, backup_path)
                
            # Atomic rename of temp to target
            os.replace(temp_path, target_path)
            
            # Update the session index with consistent token information
            self.session_index[session.id] = {
                "created_at": session.created_at,
                "last_active": session.last_active,
                "message_count": session.metadata.get("message_count", 0),
                "token_count": token_count,  # Always include token count
                "title": session.metadata.get("title", f"Session {session.id[-8:]}")
            }
            
            # Add link fields and token information for continuation sessions
            if "continued_from" in session.metadata:
                source_id = session.metadata["continued_from"]
                source_tokens = session.metadata.get("source_session_tokens", 0)
                
                self.session_index[session.id]["continued_from"] = source_id
                self.session_index[session.id]["source_session_tokens"] = source_tokens
                self.session_index[session.id]["total_chain_tokens"] = token_count + source_tokens
                
            if "continued_to" in session.metadata:
                self.session_index[session.id]["continued_to"] = session.metadata["continued_to"]
            
            self._save_index(self.session_index)
            
            # Update cache status
            if session.id in self.sessions:
                self.sessions[session.id] = (session, False)  # Mark as not modified
            
            logger.debug(f"Saved session {session.id} with {token_count} tokens")
            return True
            
        except Exception as e:
            logger.error(f"Error saving session {session.id}: {str(e)}")
            return False
    
    def check_session_boundary(self, session: Optional[Session] = None) -> bool:
        """
        Check if a session has reached its boundary and should transition.
        
        Args:
            session: Session to check (defaults to current_session)
            
        Returns:
            True if session should transition, False otherwise
        """
        session = session or self.current_session
        if not session:
            return False
            
        # Simple boundary check based on total message count only
        # Token budget concerns are handled by ContextWindowManager
        return len(session.messages) >= self.max_messages_per_session
    
    def create_continuation_session(self, source_session: Optional[Session] = None) -> Session:
        """
        Create a new session that continues from an existing one.
        
        This transfers system and context messages to maintain conversation continuity.
        
        Args:
            source_session: Source session to continue from (defaults to current_session)
            
        Returns:
            New continuation Session object
        """
        source_session = source_session or self.current_session
        if not source_session:
            raise ValueError("No source session provided for continuation")
        
        # Ensure source session has accurate token count
        source_token_count = source_session.total_tokens
        source_session.metadata["token_count"] = source_token_count
        
        # Create new session with proper metadata
        continuation = Session(
            metadata={
                "continued_from": source_session.id,
                "original_created_at": source_session.created_at,
                "continuation_index": self._get_continuation_index(source_session.id),
                "message_count": 0,
                "source_session_tokens": source_token_count,
                "token_count": 0  # Will be updated after adding messages
            }
        )
        
        # Transfer all SYSTEM and CONTEXT messages
        token_counter = getattr(self, 'token_counter', None)
        
        for category in [MessageCategory.SYSTEM, MessageCategory.CONTEXT]:
            for msg in source_session.get_messages_by_category(category):
                transferred_msg = Message(
                    role=msg.role,
                    content=msg.content,
                    category=msg.category,
                    metadata=msg.metadata.copy(),
                    tokens=msg.tokens  # Preserve token counts
                )
                continuation.add_message(transferred_msg)
        
        # Add transition marker
        transition_message = create_message(
            role="system",
            content=f"Continuing from session {source_session.id}",
            category=MessageCategory.SYSTEM,
            metadata={
                "type": "session_transition", 
                "previous_session": source_session.id,
                "previous_session_tokens": source_token_count
            }
        )
        continuation.add_message(transition_message)
        
        # Update source session metadata with link to continuation
        source_session.metadata["continued_to"] = continuation.id
        source_session.metadata["continuation_time"] = datetime.now().isoformat()
        source_session.metadata["token_count"] = source_token_count
        
        # Calculate token count for continuation session
        continuation_token_count = continuation.total_tokens
        continuation.metadata["token_count"] = continuation_token_count
        
        # Update session index with comprehensive token tracking
        self.session_index[continuation.id] = {
            "created_at": continuation.created_at,
            "last_active": continuation.last_active,
            "message_count": len(continuation.messages),
            "title": f"Continuation of {source_session.id[-8:]}",
            "continued_from": source_session.id,
            "token_count": continuation_token_count,
            "source_session_tokens": source_token_count,
            "total_chain_tokens": continuation_token_count + source_token_count
        }
        
        # Update source session index entry
        if source_session.id in self.session_index:
            self.session_index[source_session.id]["token_count"] = source_token_count
            self.session_index[source_session.id]["continued_to"] = continuation.id
        
        self._save_index(self.session_index)
        
        # Add to session cache
        self._add_to_session_cache(continuation.id, continuation)
        self.current_session = continuation
        
        # Log creation with token information
        logger.info(f"Created continuation session {continuation.id} from {source_session.id} " +
                    f"(source tokens: {source_token_count}, continuation tokens: {continuation_token_count})")
        
        # Save both sessions
        self.save_session(source_session)
        self.save_session(continuation)
        
        return continuation
    
    def _get_continuation_index(self, session_id: str) -> int:
        """
        Get the continuation index for a session using the index.
        
        Args:
            session_id: ID of the session to check
            
        Returns:
            Continuation index (1 for first continuation, etc.)
        """
        # Use the index to find continuation sessions
        continuation_count = 0
        for metadata in self.session_index.values():
            if metadata.get("continued_from") == session_id:
                continuation_count += 1
                
        return continuation_count + 1
    
    def list_sessions(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        List available sessions with metadata using the index.
        
        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination
            
        Returns:
            List of session metadata dictionaries
        """
        # Use the index for efficient listing
        sorted_sessions = sorted(
            self.session_index.items(),
            key=lambda x: x[1].get("last_active", ""),
            reverse=True
        )
        
        # Apply pagination
        paginated = sorted_sessions[offset:offset+limit]
        
        # Format the results with titles from first user messages
        result = []
        for session_id, metadata in paginated:
            session_data = {
                "id": session_id,
                **metadata
            }
            
            # Try to extract a title from the first user message if not already set
            if not session_data.get("title"):
                try:
                    # Check if session is in memory cache first
                    if session_id in self.sessions:
                        session = self.sessions[session_id][0]
                        # Find first user message
                        for msg in session.messages:
                            if msg.role == "user":
                                # Use content as title
                                content = msg.content
                                if isinstance(content, str):
                                    first_line = content.split('\n', 1)[0]
                                    session_data["title"] = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                    break
                                elif isinstance(content, list) and len(content) > 0:
                                    # Try to extract text from structured content
                                    for item in content:
                                        if isinstance(item, dict) and item.get("type") == "text":
                                            text = item.get("text", "")
                                            first_line = text.split('\n', 1)[0]
                                            session_data["title"] = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                            break
                                    break
                    else:
                        # If not in memory, check the file (but don't load fully)
                        session_path = self.base_path / f"{session_id}.{self.format}"
                        if not session_path.exists():
                            session_data["title"] = f"Session {session_id[-8:]}"
                            result.append(session_data)
                            continue
                            
                        with _safe_open(session_path, 'r', encoding='utf-8') as f:
                            try:
                                # Load only part of the file to find first user message
                                data = json.load(f)
                                # Look for first user message
                                if "messages" in data:
                                    for msg in data["messages"]:
                                        if msg.get("role") == "user":
                                            content = msg.get("content", "")
                                            if isinstance(content, str):
                                                first_line = content.split('\n', 1)[0]
                                                session_data["title"] = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                                break
                                            elif isinstance(content, list) and len(content) > 0:
                                                # Try to extract text from structured content
                                                for item in content:
                                                    if isinstance(item, dict) and item.get("type") == "text":
                                                        text = item.get("text", "")
                                                        first_line = text.split('\n', 1)[0]
                                                        session_data["title"] = (first_line[:37] + '...') if len(first_line) > 40 else first_line
                                                        break
                                                break
                            except json.JSONDecodeError:
                                pass
                except Exception as e:
                    logger.debug(f"Error extracting title for session {session_id}: {e}")
                
                # Fallback if we couldn't extract a title
                if not session_data.get("title"):
                    session_data["title"] = f"Session {session_id[-8:]}"
                    
            result.append(session_data)
        
        return result
    
    def delete_session(self, session_id: str) -> bool:
        """
        Delete a session and its files.
        
        Args:
            session_id: ID of the session to delete
            
        Returns:
            True if deleted successfully, False otherwise
        """
        try:
            # Remove from memory
            if session_id in self.sessions:
                del self.sessions[session_id]
                
            # Clear current session if it matches
            if self.current_session and self.current_session.id == session_id:
                self.current_session = None
                
            # Remove from index
            if session_id in self.session_index:
                del self.session_index[session_id]
                self._save_index(self.session_index)
                
            # Remove files
            for suffix in [f".{self.format}", f".{self.format}.bak", f".{self.format}.temp"]:
                path = self.base_path / f"{session_id}{suffix}"
                if path.exists():
                    path.unlink()
                    
            logger.info(f"Deleted session {session_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {str(e)}")
            return False
    
    def mark_session_modified(self, session_id: str) -> None:
        """Mark a session as modified in the cache."""
        if session_id in self.sessions:
            session, _ = self.sessions[session_id]
            self.sessions[session_id] = (session, True)
    
    def __del__(self):
        """Clean up resources."""
        if hasattr(self, '_stop_auto_save') and hasattr(self, '_auto_save_thread'):
            self._stop_auto_save.set()
            if self._auto_save_thread.is_alive():
                self._auto_save_thread.join(timeout=1.0)
        
        # Auto-save any modified sessions
        try:
            self._auto_save_sessions()
        except Exception as e:
            logger.error(f"Error during cleanup: {str(e)}") 