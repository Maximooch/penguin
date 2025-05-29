"""
Checkpoint management for Penguin conversation system.

This module implements the conversation plane auto-checkpointing from V2.1 plan:
- Automatic checkpoint creation on every message
- Async worker pattern to prevent UI blocking
- Retention policies for storage management
- Rollback and branching functionality
"""

import asyncio
import gzip
import json
import logging
import os
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Callable
from enum import Enum

from penguin.system.state import Message, MessageCategory, Session

logger = logging.getLogger(__name__)


class CheckpointType(Enum):
    """Types of checkpoints that can be created."""
    AUTO = "auto"           # Automatic checkpoint every N messages
    MANUAL = "manual"       # User-created checkpoint with optional name
    BRANCH = "branch"       # Checkpoint created when branching
    ROLLBACK = "rollback"   # Checkpoint created before rollback


@dataclass
class CheckpointConfig:
    """Configuration for checkpoint behavior."""
    enabled: bool = True
    frequency: int = 1  # Checkpoint every N messages
    planes: Dict[str, bool] = field(default_factory=lambda: {
        "conversation": True,
        "tasks": False,      # Will be enabled in Phase 2
        "code": False        # Will be enabled in Phase 3
    })
    retention: Dict[str, int] = field(default_factory=lambda: {
        "keep_all_hours": 24,
        "keep_every_nth": 10,
        "max_age_days": 30
    })
    max_auto_checkpoints: int = 1000  # Hard limit on auto checkpoints


@dataclass
class CheckpointMetadata:
    """Metadata for a checkpoint."""
    id: str
    type: CheckpointType
    created_at: str
    session_id: str
    message_id: str
    message_count: int
    name: Optional[str] = None
    description: Optional[str] = None
    parent_checkpoint: Optional[str] = None
    branch_point: Optional[str] = None
    auto: bool = True


class CheckpointManager:
    """
    Manages conversation checkpoints with async worker pattern.
    
    Implements the V2.1 conversation plane checkpointing:
    - Auto-checkpoint every message (configurable frequency)
    - Async workers to prevent UI blocking
    - Retention policies for storage management
    - Rollback and branching functionality
    """
    
    def __init__(
        self,
        workspace_path: Path,
        session_manager,
        config: Optional[CheckpointConfig] = None
    ):
        """
        Initialize the checkpoint manager.
        
        Args:
            workspace_path: Base workspace directory
            session_manager: SessionManager instance for lineage operations
            config: Checkpoint configuration
        """
        self.workspace_path = Path(workspace_path)
        self.session_manager = session_manager
        self.config = config or CheckpointConfig()
        
        # Setup checkpoint storage
        self.checkpoints_path = self.workspace_path / "checkpoints"
        self.checkpoints_path.mkdir(exist_ok=True)
        
        # Checkpoint index for fast lookups
        self.index_path = self.checkpoints_path / "checkpoint_index.json"
        self.checkpoint_index: Dict[str, CheckpointMetadata] = {}
        self._load_checkpoint_index()
        
        # Async worker setup
        self.checkpoint_queue: asyncio.Queue = asyncio.Queue()
        self.cleanup_queue: asyncio.Queue = asyncio.Queue()
        self._workers_started = False
        self._worker_tasks: List[asyncio.Task] = []
        
        # Message counter for frequency control
        self._message_counter = 0
        
        logger.info(f"CheckpointManager initialized with {len(self.checkpoint_index)} existing checkpoints")
    
    async def start_workers(self) -> None:
        """Start the async worker tasks."""
        if self._workers_started:
            return
            
        # Start checkpoint worker
        checkpoint_worker = asyncio.create_task(self._checkpoint_worker())
        self._worker_tasks.append(checkpoint_worker)
        
        # Start cleanup worker
        cleanup_worker = asyncio.create_task(self._cleanup_worker())
        self._worker_tasks.append(cleanup_worker)
        
        self._workers_started = True
        logger.info("Checkpoint workers started")
    
    async def stop_workers(self) -> None:
        """Stop the async worker tasks."""
        if not self._workers_started:
            return
            
        # Cancel all worker tasks
        for task in self._worker_tasks:
            task.cancel()
            
        # Wait for tasks to complete
        await asyncio.gather(*self._worker_tasks, return_exceptions=True)
        
        self._worker_tasks.clear()
        self._workers_started = False
        logger.info("Checkpoint workers stopped")
    
    def should_checkpoint(self, message: Message) -> bool:
        """
        Determine if this message should trigger a checkpoint.
        
        Args:
            message: The message to evaluate
            
        Returns:
            True if a checkpoint should be created
        """
        if not self.config.enabled or not self.config.planes.get("conversation", True):
            return False
            
        # Start workers if not already started
        if not self._workers_started:
            try:
                import asyncio
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    asyncio.create_task(self.start_workers())
            except RuntimeError:
                # No event loop available, workers will start when checkpoint is created
                pass
            
        # Skip certain system messages
        if message.category == MessageCategory.SYSTEM:
            # Only checkpoint system messages that are action results or important markers
            important_markers = ["action executed", "session transition", "iteration marker"]
            if not any(marker in message.content.lower() for marker in important_markers):
                return False
        
        # Apply frequency filter
        self._message_counter += 1
        return (self._message_counter % self.config.frequency) == 0
    
    async def create_checkpoint(
        self,
        session: Session,
        message: Message,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        name: Optional[str] = None,
        description: Optional[str] = None
    ) -> Optional[str]:
        """
        Create a checkpoint for the current conversation state.
        
        Args:
            session: Current session to checkpoint
            message: The message that triggered the checkpoint
            checkpoint_type: Type of checkpoint being created
            name: Optional name for manual checkpoints
            description: Optional description
            
        Returns:
            Checkpoint ID if successful, None otherwise
        """
        if not self.config.enabled:
            return None
            
        # Ensure workers are started
        if not self._workers_started:
            await self.start_workers()
            
        # Generate checkpoint ID
        checkpoint_id = f"cp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        
        # Create checkpoint metadata
        metadata = CheckpointMetadata(
            id=checkpoint_id,
            type=checkpoint_type,
            created_at=datetime.now().isoformat(),
            session_id=session.id,
            message_id=message.id,
            message_count=len(session.messages),
            name=name,
            description=description,
            auto=(checkpoint_type == CheckpointType.AUTO)
        )
        
        # Enqueue for async processing
        await self.checkpoint_queue.put(('create', session, metadata))
        
        logger.debug(f"Enqueued checkpoint creation: {checkpoint_id}")
        return checkpoint_id
    
    async def rollback_to_checkpoint(self, checkpoint_id: str) -> bool:
        """
        Rollback conversation to a specific checkpoint.
        
        Args:
            checkpoint_id: ID of the checkpoint to rollback to
            
        Returns:
            True if successful, False otherwise
        """
        try:
            # Load checkpoint metadata
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"Checkpoint {checkpoint_id} not found in index")
                return False
                
            metadata = self.checkpoint_index[checkpoint_id]
            
            # Load the checkpoint session
            checkpoint_session = await self._load_checkpoint_session(checkpoint_id)
            if not checkpoint_session:
                logger.error(f"Failed to load checkpoint session {checkpoint_id}")
                return False
            
            # Create rollback checkpoint of current state first
            current_session = self.session_manager.current_session
            if current_session:
                # Find the last message for rollback checkpoint
                if current_session.messages:
                    last_message = current_session.messages[-1]
                    await self.create_checkpoint(
                        current_session,
                        last_message,
                        CheckpointType.ROLLBACK,
                        name=f"Before rollback to {checkpoint_id[:8]}"
                    )
            
            # Restore the checkpoint session
            self.session_manager.current_session = checkpoint_session
            
            logger.info(f"Rolled back to checkpoint {checkpoint_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error rolling back to checkpoint {checkpoint_id}: {e}")
            return False
    
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
        try:
            # Load the source checkpoint
            if checkpoint_id not in self.checkpoint_index:
                logger.error(f"Checkpoint {checkpoint_id} not found")
                return None
                
            source_session = await self._load_checkpoint_session(checkpoint_id)
            if not source_session:
                logger.error(f"Failed to load checkpoint session {checkpoint_id}")
                return None
            
            # Create a new session with flattened snapshot
            branch_session = await self._build_flat_snapshot(source_session)
            
            # Update metadata for branching
            branch_session.metadata["branched_from"] = checkpoint_id
            branch_session.metadata["branch_point"] = self.checkpoint_index[checkpoint_id].message_id
            
            # Create branch checkpoint
            if branch_session.messages:
                last_message = branch_session.messages[-1]
                branch_checkpoint_id = await self.create_checkpoint(
                    branch_session,
                    last_message,
                    CheckpointType.BRANCH,
                    name=name or f"Branch from {checkpoint_id[:8]}",
                    description=description
                )
                
                # Set as current session
                self.session_manager.current_session = branch_session
                
                logger.info(f"Created branch {branch_checkpoint_id} from checkpoint {checkpoint_id}")
                return branch_checkpoint_id
            
            return None
            
        except Exception as e:
            logger.error(f"Error branching from checkpoint {checkpoint_id}: {e}")
            return None
    
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
        checkpoints = []
        
        for cp_id, metadata in self.checkpoint_index.items():
            # Apply filters
            if session_id and metadata.session_id != session_id:
                continue
            if checkpoint_type and metadata.type != checkpoint_type:
                continue
                
            checkpoints.append({
                "id": cp_id,
                "type": metadata.type.value,
                "created_at": metadata.created_at,
                "session_id": metadata.session_id,
                "message_count": metadata.message_count,
                "name": metadata.name,
                "description": metadata.description,
                "auto": metadata.auto
            })
        
        # Sort by creation time (newest first)
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)
        
        return checkpoints[:limit]
    
    async def cleanup_old_checkpoints(self) -> int:
        """
        Clean up old checkpoints according to retention policy.
        
        Returns:
            Number of checkpoints cleaned up
        """
        await self.cleanup_queue.put('cleanup')
        return 0  # Actual count will be logged by worker
    
    def collect_lineage(self, session_id: str) -> List[str]:
        """
        Collect the full lineage of a session following 'continued_from' links.
        
        Args:
            session_id: ID of the session to trace
            
        Returns:
            List of session IDs from root to the given session
        """
        chain = []
        current = session_id
        
        while current:
            chain.insert(0, current)
            # Get the continued_from link from session index
            session_info = self.session_manager.session_index.get(current, {})
            current = session_info.get("continued_from")
            
        return chain
    
    async def _build_flat_snapshot(self, tail_session: Session) -> Session:
        """
        Build a flattened snapshot containing the complete conversation history.
        
        Args:
            tail_session: The session to build snapshot from
            
        Returns:
            New session with flattened message history
        """
        # Collect lineage
        lineage = self.collect_lineage(tail_session.id)
        
        # Create new session for the snapshot
        merged_session = Session(
            metadata={
                "branched_from": tail_session.id,
                "lineage": lineage,
                "flattened_snapshot": True,
                "original_created_at": lineage[0] if lineage else tail_session.created_at
            }
        )
        
        # Merge messages from all sessions in lineage
        for session_id in lineage:
            if session_id == tail_session.id:
                # Use the tail session directly
                source_session = tail_session
            else:
                # Load the session
                source_session = self.session_manager.load_session(session_id)
                
            if source_session:
                for message in source_session.messages:
                    # Create a copy of the message
                    merged_message = Message(
                        role=message.role,
                        content=message.content,
                        category=message.category,
                        id=message.id,
                        timestamp=message.timestamp,
                        metadata=message.metadata.copy(),
                        tokens=message.tokens
                    )
                    merged_session.add_message(merged_message)
        
        # Deduplicate system messages (keep only the latest of each type)
        await self._dedupe_system_messages(merged_session)
        
        return merged_session
    
    async def _dedupe_system_messages(self, session: Session) -> None:
        """
        Remove duplicate system messages, keeping only the latest of each type.
        
        Args:
            session: Session to deduplicate
        """
        seen_system_types = set()
        messages_to_keep = []
        
        # Process messages in reverse order to keep latest
        for message in reversed(session.messages):
            if message.category == MessageCategory.SYSTEM:
                msg_type = message.metadata.get("type", "generic")
                if msg_type not in seen_system_types:
                    seen_system_types.add(msg_type)
                    messages_to_keep.append(message)
            else:
                messages_to_keep.append(message)
        
        # Restore original order
        session.messages = list(reversed(messages_to_keep))
    
    async def _checkpoint_worker(self) -> None:
        """Async worker that processes checkpoint creation requests."""
        while True:
            try:
                action, session, metadata = await self.checkpoint_queue.get()
                
                if action == 'create':
                    await self._create_checkpoint_file(session, metadata)
                    
                self.checkpoint_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in checkpoint worker: {e}")
    
    async def _cleanup_worker(self) -> None:
        """Async worker that processes cleanup requests."""
        while True:
            try:
                action = await self.cleanup_queue.get()
                
                if action == 'cleanup':
                    cleaned_count = await self._perform_cleanup()
                    logger.info(f"Cleaned up {cleaned_count} old checkpoints")
                    
                self.cleanup_queue.task_done()
                
            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup worker: {e}")
    
    async def _create_checkpoint_file(self, session: Session, metadata: CheckpointMetadata) -> None:
        """
        Create the actual checkpoint file.
        
        Args:
            session: Session to checkpoint
            metadata: Checkpoint metadata
        """
        try:
            # Build flattened snapshot if this is a branch or manual checkpoint
            if metadata.type in [CheckpointType.BRANCH, CheckpointType.MANUAL]:
                checkpoint_session = await self._build_flat_snapshot(session)
            else:
                # For auto checkpoints, just use the current session
                checkpoint_session = session
            
            # Create checkpoint data with proper enum serialization
            metadata_dict = metadata.__dict__.copy()
            metadata_dict["type"] = metadata.type.value  # Convert enum to string
            
            checkpoint_data = {
                "metadata": metadata_dict,
                "session": checkpoint_session.to_dict()
            }
            
            # Compress and save
            checkpoint_file = self.checkpoints_path / f"{metadata.id}.json.gz"
            compressed_data = gzip.compress(json.dumps(checkpoint_data).encode('utf-8'))
            
            with open(checkpoint_file, 'wb') as f:
                f.write(compressed_data)
            
            # Update index
            self.checkpoint_index[metadata.id] = metadata
            self._save_checkpoint_index()
            
            logger.debug(f"Created checkpoint file: {metadata.id}")
            
        except Exception as e:
            logger.error(f"Error creating checkpoint file {metadata.id}: {e}")
    
    async def _load_checkpoint_session(self, checkpoint_id: str) -> Optional[Session]:
        """
        Load a session from a checkpoint file.
        
        Args:
            checkpoint_id: ID of the checkpoint to load
            
        Returns:
            Session object if successful, None otherwise
        """
        try:
            checkpoint_file = self.checkpoints_path / f"{checkpoint_id}.json.gz"
            
            if not checkpoint_file.exists():
                logger.error(f"Checkpoint file not found: {checkpoint_file}")
                return None
            
            # Load and decompress
            with open(checkpoint_file, 'rb') as f:
                compressed_data = f.read()
                
            data = json.loads(gzip.decompress(compressed_data).decode('utf-8'))
            
            # Extract session data
            session_data = data.get("session", {})
            return Session.from_dict(session_data)
            
        except Exception as e:
            logger.error(f"Error loading checkpoint {checkpoint_id}: {e}")
            return None
    
    async def _perform_cleanup(self) -> int:
        """
        Perform cleanup of old checkpoints according to retention policy.
        
        Returns:
            Number of checkpoints cleaned up
        """
        try:
            now = datetime.now()
            cleaned_count = 0
            
            # Get retention settings
            keep_all_hours = self.config.retention["keep_all_hours"]
            keep_every_nth = self.config.retention["keep_every_nth"]
            max_age_days = self.config.retention["max_age_days"]
            
            # Group checkpoints by age
            recent_cutoff = now - timedelta(hours=keep_all_hours)
            old_cutoff = now - timedelta(days=max_age_days)
            
            auto_checkpoints = []
            for cp_id, metadata in self.checkpoint_index.items():
                if metadata.type == CheckpointType.AUTO:
                    created_at = datetime.fromisoformat(metadata.created_at)
                    auto_checkpoints.append((cp_id, metadata, created_at))
            
            # Sort by creation time
            auto_checkpoints.sort(key=lambda x: x[2])
            
            # Apply retention rules
            checkpoints_to_delete = []
            
            for i, (cp_id, metadata, created_at) in enumerate(auto_checkpoints):
                # Delete if too old
                if created_at < old_cutoff:
                    checkpoints_to_delete.append(cp_id)
                    continue
                
                # Keep all recent checkpoints
                if created_at >= recent_cutoff:
                    continue
                
                # For older checkpoints, keep every Nth
                if i % keep_every_nth != 0:
                    checkpoints_to_delete.append(cp_id)
            
            # Enforce hard limit on auto checkpoints
            if len(auto_checkpoints) > self.config.max_auto_checkpoints:
                excess_count = len(auto_checkpoints) - self.config.max_auto_checkpoints
                oldest_checkpoints = auto_checkpoints[:excess_count]
                for cp_id, _, _ in oldest_checkpoints:
                    if cp_id not in checkpoints_to_delete:
                        checkpoints_to_delete.append(cp_id)
            
            # Delete the checkpoints
            for cp_id in checkpoints_to_delete:
                await self._delete_checkpoint(cp_id)
                cleaned_count += 1
            
            return cleaned_count
            
        except Exception as e:
            logger.error(f"Error during checkpoint cleanup: {e}")
            return 0
    
    async def _delete_checkpoint(self, checkpoint_id: str) -> None:
        """
        Delete a checkpoint file and remove from index.
        
        Args:
            checkpoint_id: ID of the checkpoint to delete
        """
        try:
            # Remove file
            checkpoint_file = self.checkpoints_path / f"{checkpoint_id}.json.gz"
            if checkpoint_file.exists():
                checkpoint_file.unlink()
            
            # Remove from index
            if checkpoint_id in self.checkpoint_index:
                del self.checkpoint_index[checkpoint_id]
                self._save_checkpoint_index()
            
            logger.debug(f"Deleted checkpoint: {checkpoint_id}")
            
        except Exception as e:
            logger.error(f"Error deleting checkpoint {checkpoint_id}: {e}")
    
    def _load_checkpoint_index(self) -> None:
        """Load the checkpoint index from disk."""
        try:
            if self.index_path.exists():
                with open(self.index_path, 'r') as f:
                    data = json.load(f)
                    
                # Convert dict data back to CheckpointMetadata objects
                for cp_id, metadata_dict in data.items():
                    # Convert type string back to enum
                    metadata_dict["type"] = CheckpointType(metadata_dict["type"])
                    self.checkpoint_index[cp_id] = CheckpointMetadata(**metadata_dict)
                    
        except Exception as e:
            logger.error(f"Error loading checkpoint index: {e}")
            self.checkpoint_index = {}
    
    def _save_checkpoint_index(self) -> None:
        """Save the checkpoint index to disk."""
        try:
            # Convert CheckpointMetadata objects to dicts for serialization
            index_data = {}
            for cp_id, metadata in self.checkpoint_index.items():
                metadata_dict = metadata.__dict__.copy()
                metadata_dict["type"] = metadata.type.value  # Convert enum to string
                index_data[cp_id] = metadata_dict
            
            # Write to temp file first for atomic operation
            temp_path = self.index_path.with_suffix('.tmp')
            with open(temp_path, 'w') as f:
                json.dump(index_data, f, indent=2)
            
            # Atomic rename
            temp_path.replace(self.index_path)
            
        except Exception as e:
            logger.error(f"Error saving checkpoint index: {e}") 