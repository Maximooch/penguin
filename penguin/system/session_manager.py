"""
Session management for Penguin conversation system.

This module handles session lifecycle operations including:
- Creating and loading sessions
- Saving sessions with transaction safety
- Managing session boundaries and transitions
- Creating continuation sessions for long conversations
"""

import json
import logging
import os
import shutil
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

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
    """
    #TODO: fully implement dialog message count later

    def __init__(
        self, 
        base_path: str = CONVERSATIONS_PATH,
        max_messages_per_session: int = 500, #TODO: This should be configurable
        format: str = "json"
    ):
        """
        Initialize the session manager.
        
        Args:
            base_path: Directory for storing session files
            max_messages_per_session: Maximum messages before creating a new session
            format: File format for session storage (json only for now)
        """
        self.base_path = Path(base_path)
        self.max_messages_per_session = max_messages_per_session
        self.format = format
        self.current_session: Optional[Session] = None
        self.sessions: Dict[str, Session] = {}
        
        # Create directory if it doesn't exist
        os.makedirs(self.base_path, exist_ok=True)
    
    def create_session(self) -> Session:
        """
        Create a new empty session.
        
        Returns:
            New Session object
        """
        session = Session()
        # Initialize dialog message count
        session.metadata["dialog_message_count"] = 0
        self.sessions[session.id] = session
        self.current_session = session
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
            self.current_session = self.sessions[session_id]
            return self.current_session
            
        # Try primary file
        primary_path = self.base_path / f"{session_id}.{self.format}"
        backup_path = self.base_path / f"{session_id}.{self.format}.bak"
        
        try:
            # Try loading from primary file
            session = self._load_from_file(primary_path)
            if session and session.validate():
                self.sessions[session_id] = session
                self.current_session = session
                logger.debug(f"Loaded session from primary file: {session_id}")
                return session
        except Exception as e:
            logger.error(f"Error loading session {session_id} from primary file: {str(e)}")
            
            # Try backup file
            try:
                if backup_path.exists():
                    session = self._load_from_file(backup_path)
                    if session and session.validate():
                        self.sessions[session_id] = session
                        self.current_session = session
                        
                        # Restore from backup
                        shutil.copy2(backup_path, primary_path)
                        logger.warning(f"Restored session {session_id} from backup")
                        return session
            except Exception as backup_error:
                logger.error(f"Error loading backup for session {session_id}: {str(backup_error)}")
        
        # If we get here, both primary and backup loading failed
        logger.warning(f"Could not load session {session_id}, creating recovery session")
        return self._create_recovery_session(session_id)
    
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
            
        with open(file_path, 'r', encoding='utf-8') as f:
            data = json.load(f)

        session = Session.from_dict(data)
        
        # Ensure dialog_message_count exists in metadata
        if "dialog_message_count" not in session.metadata:
            # Count dialog messages if not present in metadata
            dialog_count = sum(1 for msg in session.messages 
                             if msg.category == MessageCategory.DIALOG)
            session.metadata["dialog_message_count"] = dialog_count
            
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
                "message_count": 1,
                "dialog_message_count": 0  # No dialog messages yet
            }
        )
        
        # Add recovery notice message
        recovery_message = create_message(
            role="system",
            content=f"This is a recovery session. The original session '{original_id}' could not be loaded due to file corruption or other errors.",
            category=MessageCategory.SYSTEM, # system as in system prompt? or system message? So in that case, ACTIONS? Although ACTIONS should probably be renamed to SYSTEM_OUTPUTS since that's what it is and include things much more than ACTIONS, which could be misleading
            metadata={"type": "recovery_notice"}
        )
        session.add_message(recovery_message)
        
        # Store in sessions dict
        self.sessions[session.id] = session
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
        session = session or self.current_session
        if not session:
            logger.error("No session to save")
            return False
            
        try:
            temp_path = self.base_path / f"{session.id}.{self.format}.temp"
            backup_path = self.base_path / f"{session.id}.{self.format}.bak"
            target_path = self.base_path / f"{session.id}.{self.format}"
            
            # Write to temp file first
            with open(temp_path, 'w', encoding='utf-8') as f:
                f.write(session.to_json())
                
            # Create backup of current file if it exists
            if target_path.exists():
                shutil.copy2(target_path, backup_path)
                
            # Atomic rename of temp to target
            os.replace(temp_path, target_path)
            
            logger.debug(f"Saved session {session.id}")
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
            
        # Check if message count exceeds limit
        return session.message_count >= self.max_messages_per_session
    
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
            
        # Create new session
        continuation = Session(
            metadata={
                "continued_from": source_session.id,
                "original_created_at": source_session.created_at,
                "continuation_index": self._get_continuation_index(source_session.id),
                "message_count": 0,
                "dialog_message_count": 0
            }
        )
        
        # Transfer all SYSTEM and CONTEXT messages
        for category in [MessageCategory.SYSTEM, MessageCategory.CONTEXT]:
            for msg in source_session.get_messages_by_category(category):
                continuation.add_message(Message(
                    role=msg.role,
                    content=msg.content,
                    category=msg.category,
                    metadata=msg.metadata.copy(),
                    tokens=msg.tokens
                ))
        
        # Add transition marker
        transition_message = create_message(
            role="system",
            content=f"Continuing from session {source_session.id}",
            category=MessageCategory.SYSTEM,
            metadata={
                "type": "session_transition", 
                "previous_session": source_session.id
            }
        )
        continuation.add_message(transition_message)
        
        # Update state
        self.sessions[continuation.id] = continuation
        self.current_session = continuation
        logger.info(f"Created continuation session {continuation.id} from {source_session.id}")
        
        # Save both sessions
        self.save_session(source_session)
        self.save_session(continuation)
        
        return continuation
    
    def _get_continuation_index(self, session_id: str) -> int:
        """
        Get the continuation index for a session.
        
        Args:
            session_id: ID of the session to check
            
        Returns:
            Continuation index (1 for first continuation, etc.)
        """
        base_sessions = []
        continuation_sessions = []
        
        # Find all related sessions
        for path in self.base_path.glob(f"*.{self.format}"):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Check if this is a continuation of our target
                if data.get("metadata", {}).get("continued_from") == session_id:
                    continuation_sessions.append(data)
                    
                # Check if this is the target
                if data.get("id") == session_id:
                    base_sessions.append(data)
            except Exception:
                pass
                
        # Return continuation count + 1
        return len(continuation_sessions) + 1
    
    def list_sessions(self, limit: int = 100, offset: int = 0) -> List[Dict]:
        """
        List available sessions with metadata.
        
        Args:
            limit: Maximum number of sessions to return
            offset: Offset for pagination
            
        Returns:
            List of session metadata dictionaries
        """
        sessions = []
        
        # Scan directory for session files
        for path in sorted(self.base_path.glob(f"*.{self.format}"), 
                          key=os.path.getmtime, reverse=True):
            if len(sessions) >= offset + limit:
                break
                
            if len(sessions) < offset:
                continue
                
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    
                # Extract metadata
                metadata = data.get("metadata", {})
                sessions.append({
                    "id": data.get("id", ""),
                    "created_at": data.get("created_at", ""),
                    "last_active": data.get("last_active", ""),
                    "message_count": metadata.get("message_count", 0),
                    "dialog_message_count": metadata.get("dialog_message_count", 0),
                    "title": metadata.get("title", f"Session {data.get('id', '')[-8:]}")
                })
            except Exception as e:
                logger.error(f"Error reading session from {path}: {str(e)}")
                
        return sessions[offset:offset+limit]
    
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