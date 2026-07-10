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
import hashlib
import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from penguin.system.checkpoint_cleanup import build_checkpoint_cleanup_plan
from penguin.system.runtime_diagnostics import record_runtime_duration
from penguin.system.state import Message, MessageCategory, Session
from penguin.system.storage_safety import StorageSafetyMonitor, StorageSafetyStatus

logger = logging.getLogger(__name__)


class CheckpointType(Enum):
    """Types of checkpoints that can be created."""

    AUTO = "auto"  # Automatic checkpoint every N messages
    MANUAL = "manual"  # User-created checkpoint with optional name
    BRANCH = "branch"  # Checkpoint created when branching
    ROLLBACK = "rollback"  # Checkpoint created before rollback


@dataclass
class CheckpointConfig:
    """Configuration for checkpoint behavior."""

    enabled: bool = True
    frequency: int = 1  # Checkpoint every N messages
    planes: Dict[str, bool] = field(
        default_factory=lambda: {
            "conversation": True,
            "tasks": False,  # Will be enabled in Phase 2
            "code": False,  # Will be enabled in Phase 3
        }
    )
    retention: Dict[str, int] = field(
        default_factory=lambda: {
            "keep_all_hours": 24,
            "keep_every_nth": 10,
            "max_age_days": 30,
        }
    )
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
        config: Optional[CheckpointConfig] = None,
        storage_safety_monitor: Optional[StorageSafetyMonitor] = None,
    ):
        """
        Initialize the checkpoint manager.

        Args:
            workspace_path: Base workspace directory
            session_manager: SessionManager instance for lineage operations
            config: Checkpoint configuration
            storage_safety_monitor: Optional injected disk-safety monitor
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
        self._auto_checkpoint_count = 0
        self._pending_auto_checkpoints = 0
        self.refresh_admission_counters()
        self._storage_safety_monitor = storage_safety_monitor or StorageSafetyMonitor(
            self.workspace_path,
            checkpoint_path=self.checkpoints_path,
        )
        self._last_storage_safety_status: Optional[StorageSafetyStatus] = None
        self._checkpoint_block_reason: Optional[str] = None
        self._last_logged_block_reason: Optional[str] = None

        # Async worker setup (queues created lazily in the owning event loop)
        self.checkpoint_queue: Optional[asyncio.Queue] = None
        self.cleanup_queue: Optional[asyncio.Queue] = None
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._workers_started = False
        self._worker_tasks: List[asyncio.Task] = []

        # Message counter for frequency control
        self._message_counter = 0

        logger.info(
            "CheckpointManager initialized with %s existing checkpoints",
            len(self.checkpoint_index),
        )

    async def start_workers(self) -> None:
        """Start the async worker tasks."""
        if self._workers_started:
            return

        # Bind queues to the current running loop and spawn workers in the same loop
        loop = asyncio.get_running_loop()
        self._loop = loop
        self.checkpoint_queue = asyncio.Queue()
        self.cleanup_queue = asyncio.Queue()

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

        # Skip certain system messages
        if message.category == MessageCategory.SYSTEM:
            # Checkpoint only action results and important system markers.
            important_markers = [
                "action executed",
                "session transition",
                "iteration marker",
            ]
            if not any(
                marker in message.content.lower() for marker in important_markers
            ):
                return False

        # Apply frequency filter
        self._message_counter += 1
        if (self._message_counter % self.config.frequency) != 0:
            return False
        return self._allow_auto_checkpoint()

    async def create_checkpoint(
        self,
        session: Session,
        message: Message,
        checkpoint_type: CheckpointType = CheckpointType.AUTO,
        name: Optional[str] = None,
        description: Optional[str] = None,
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
        if checkpoint_type == CheckpointType.AUTO and not self._allow_auto_checkpoint():
            return None

        # Ensure workers are started
        if not self._workers_started:
            await self.start_workers()

        # Generate checkpoint ID
        checkpoint_id = (
            f"cp_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}"
        )

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
            auto=(checkpoint_type == CheckpointType.AUTO),
        )

        # Enqueue for async processing (queue is guaranteed after start_workers)
        assert self.checkpoint_queue is not None
        if checkpoint_type == CheckpointType.AUTO:
            self._pending_auto_checkpoints += 1
        try:
            await self.checkpoint_queue.put(("create", session, metadata))
        except BaseException:
            if checkpoint_type == CheckpointType.AUTO:
                self._pending_auto_checkpoints = max(
                    0,
                    self._pending_auto_checkpoints - 1,
                )
            raise

        logger.debug(f"Enqueued checkpoint creation: {checkpoint_id}")
        return checkpoint_id

    def refresh_admission_counters(self) -> None:
        """Refresh cached checkpoint counts after index load or test mutation."""

        self._auto_checkpoint_count = sum(
            1
            for metadata in self.checkpoint_index.values()
            if metadata.type == CheckpointType.AUTO
        )

    def get_storage_safety_status(self) -> Dict[str, Any]:
        """Return current checkpoint admission evidence for diagnostics/UI."""

        status = self._last_storage_safety_status
        payload: Dict[str, Any] = (
            status.to_dict()
            if status is not None
            else {
                "level": "unknown",
                "allow_background_writes": self._checkpoint_block_reason is None,
                "reasons": [],
            }
        )
        payload.update(
            {
                "block_reason": self._checkpoint_block_reason,
                "auto_checkpoint_count": self._auto_checkpoint_count,
                "pending_auto_checkpoints": self._pending_auto_checkpoints,
                "max_auto_checkpoints": self.config.max_auto_checkpoints,
            }
        )
        return payload

    def plan_checkpoint_cleanup(
        self,
        *,
        active_session_ids: Optional[Set[str]] = None,
        now: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Return a read-only cleanup plan with no source-data mutation."""

        active_sessions = set(active_session_ids or ())
        current_session = getattr(self.session_manager, "current_session", None)
        current_session_id = getattr(current_session, "id", None)
        if current_session_id:
            active_sessions.add(str(current_session_id))
        retention = self.config.retention
        return build_checkpoint_cleanup_plan(
            self.checkpoints_path,
            self.checkpoint_index,
            keep_all_hours=retention.get("keep_all_hours", 24),
            keep_every_nth=retention.get("keep_every_nth", 10),
            max_age_days=retention.get("max_age_days", 30),
            max_auto_checkpoints=self.config.max_auto_checkpoints,
            active_session_ids=active_sessions,
            now=now,
        ).to_dict()

    def _allow_auto_checkpoint(self) -> bool:
        """Return whether one new automatic checkpoint may be enqueued."""

        admitted_count = self._auto_checkpoint_count + self._pending_auto_checkpoints
        if admitted_count >= self.config.max_auto_checkpoints:
            self._record_checkpoint_block("max_auto_checkpoints")
            return False

        status = self._storage_safety_monitor.check()
        self._last_storage_safety_status = status
        if not status.allow_background_writes:
            self._record_checkpoint_block("storage_critical")
            return False

        self._checkpoint_block_reason = None
        self._last_logged_block_reason = None
        if status.level.value == "warning":
            logger.warning(
                "Checkpoint storage pressure warning: %s",
                status.to_dict(),
            )
        return True

    def _record_checkpoint_block(self, reason: str) -> None:
        """Record and rate-limit one automatic-checkpoint admission warning."""

        self._checkpoint_block_reason = reason
        if self._last_logged_block_reason == reason:
            return
        self._last_logged_block_reason = reason
        logger.warning(
            "Automatic checkpoint blocked: reason=%s status=%s",
            reason,
            self.get_storage_safety_status(),
        )

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
                        name=f"Before rollback to {checkpoint_id[:8]}",
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
        description: Optional[str] = None,
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
            branch_session.metadata["branch_point"] = self.checkpoint_index[
                checkpoint_id
            ].message_id
            source_metadata = (
                source_session.metadata
                if isinstance(source_session.metadata, dict)
                else {}
            )
            if isinstance(source_metadata.get("directory"), str):
                branch_session.metadata["directory"] = source_metadata["directory"]
            if isinstance(name, str) and name.strip():
                branch_session.metadata["title"] = name.strip()
            elif (
                isinstance(source_metadata.get("title"), str)
                and source_metadata["title"].strip()
            ):
                branch_session.metadata["title"] = (
                    f"{source_metadata['title'].strip()} (branch)"
                )

            # Create branch checkpoint
            if branch_session.messages:
                last_message = branch_session.messages[-1]
                branch_checkpoint_id = await self.create_checkpoint(
                    branch_session,
                    last_message,
                    CheckpointType.BRANCH,
                    name=name or f"Branch from {checkpoint_id[:8]}",
                    description=description,
                )

                # Set as current session
                self.session_manager.current_session = branch_session

                logger.info(
                    "Created branch %s from checkpoint %s",
                    branch_checkpoint_id,
                    checkpoint_id,
                )
                return branch_checkpoint_id

            return None

        except Exception as e:
            logger.error(f"Error branching from checkpoint {checkpoint_id}: {e}")
            return None

    def list_checkpoints(
        self,
        session_id: Optional[str] = None,
        checkpoint_type: Optional[CheckpointType] = None,
        limit: int = 50,
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

            checkpoints.append(
                {
                    "id": cp_id,
                    "type": metadata.type.value,
                    "created_at": metadata.created_at,
                    "session_id": metadata.session_id,
                    "message_count": metadata.message_count,
                    "name": metadata.name,
                    "description": metadata.description,
                    "auto": metadata.auto,
                }
            )

        # Sort by creation time (newest first)
        checkpoints.sort(key=lambda x: x["created_at"], reverse=True)

        return checkpoints[:limit]

    async def cleanup_old_checkpoints(
        self,
        *,
        execute: bool = False,
        confirmation: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Plan cleanup by default and require explicit confirmation to mutate.

        Args:
            execute: Whether to execute the reviewed retention plan.
            confirmation: Exact resolved workspace path required for execution.

        Returns:
            Dry-run plan or completed cleanup result.

        Raises:
            PermissionError: If destructive execution lacks exact confirmation.
        """

        plan = self.plan_checkpoint_cleanup()
        if not execute:
            return {"status": "dry_run", **plan}

        expected_confirmation = str(self.workspace_path.expanduser().resolve())
        if confirmation != expected_confirmation:
            raise PermissionError(
                "Checkpoint cleanup execution requires confirmation equal to the "
                f"resolved workspace path: {expected_confirmation}"
            )
        cleaned_count = await asyncio.to_thread(
            self._archive_cleanup_candidates,
            plan,
        )
        return {
            "status": "completed",
            "dry_run": False,
            "cleaned_count": cleaned_count,
            "reviewed_candidate_count": plan["candidate_count"],
            "reviewed_candidate_bytes": plan["candidate_bytes"],
        }

    def _archive_cleanup_candidates(self, plan: Dict[str, Any]) -> int:
        """Move reviewed candidates to a recoverable archive and update the index."""

        recovery_plan = plan.get("recovery_plan", {})
        archive_value = recovery_plan.get("archive_destination")
        if not isinstance(archive_value, str) or not archive_value:
            raise RuntimeError("Cleanup plan has no archive destination")
        archive_path = Path(archive_value).expanduser().resolve()
        checkpoint_root = self.checkpoints_path.expanduser().resolve()
        if checkpoint_root not in archive_path.parents:
            raise RuntimeError(
                "Checkpoint archive must remain below checkpoint storage"
            )
        archive_path.mkdir(parents=True, exist_ok=False)

        manifest: Dict[str, Any] = {
            "state": "planned",
            "generated_at": plan.get("generated_at"),
            "source": str(checkpoint_root),
            "archive": str(archive_path),
            "candidates": [],
            "moved": [],
        }
        for candidate in plan.get("candidates", []):
            source_value = candidate.get("path")
            checkpoint_id = candidate.get("checkpoint_id")
            if not isinstance(source_value, str) or not isinstance(checkpoint_id, str):
                continue
            source = Path(source_value).expanduser().resolve()
            if source.parent != checkpoint_root:
                raise RuntimeError(f"Unsafe checkpoint cleanup source: {source}")
            manifest["candidates"].append(
                {
                    "checkpoint_id": checkpoint_id,
                    "source": str(source),
                    "size_bytes": candidate.get("size_bytes", 0),
                    "sha256": _sha256_file(source),
                }
            )

        manifest_path = archive_path / "manifest.json"
        _write_json_atomic(manifest_path, manifest)
        try:
            for candidate in manifest["candidates"]:
                source = Path(candidate["source"])
                target = archive_path / source.name
                if target.exists():
                    raise FileExistsError(f"Archive target already exists: {target}")
                source.replace(target)
                manifest["moved"].append(
                    {
                        **candidate,
                        "archive_path": str(target),
                    }
                )
                self.checkpoint_index.pop(candidate["checkpoint_id"], None)
            manifest["state"] = "completed"
            self.refresh_admission_counters()
            self._save_checkpoint_index()
            _write_json_atomic(manifest_path, manifest)
        except Exception:
            manifest["state"] = "partial"
            _write_json_atomic(manifest_path, manifest)
            raise
        return len(manifest["moved"])

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
                "original_created_at": lineage[0]
                if lineage
                else tail_session.created_at,
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
                        tokens=message.tokens,
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
                assert self.checkpoint_queue is not None
                action, session, metadata = await self.checkpoint_queue.get()

                try:
                    if action == "create":
                        await self._create_checkpoint_file(session, metadata)
                finally:
                    if metadata.type == CheckpointType.AUTO:
                        self._pending_auto_checkpoints = max(
                            0,
                            self._pending_auto_checkpoints - 1,
                        )
                    self.checkpoint_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in checkpoint worker: {e}")

    async def _cleanup_worker(self) -> None:
        """Async worker that processes cleanup requests."""
        while True:
            try:
                assert self.cleanup_queue is not None
                action = await self.cleanup_queue.get()

                if action == "cleanup":
                    cleaned_count = await self._perform_cleanup()
                    logger.info(f"Cleaned up {cleaned_count} old checkpoints")

                self.cleanup_queue.task_done()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error(f"Error in cleanup worker: {e}")

    async def _create_checkpoint_file(
        self, session: Session, metadata: CheckpointMetadata
    ) -> None:
        """
        Create the actual checkpoint file.

        Args:
            session: Session to checkpoint
            metadata: Checkpoint metadata
        """
        persistence_started = time.perf_counter()
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

            serialization_started = time.perf_counter()
            checkpoint_data = {
                "metadata": metadata_dict,
                "session": checkpoint_session.to_dict(),
            }

            # Compress and save
            checkpoint_file = self.checkpoints_path / f"{metadata.id}.json.gz"
            compressed_data = gzip.compress(json.dumps(checkpoint_data).encode("utf-8"))
            record_runtime_duration(
                "checkpoint.serialization",
                (time.perf_counter() - serialization_started) * 1000,
            )

            write_started = time.perf_counter()
            with open(checkpoint_file, "wb") as f:
                f.write(compressed_data)
            record_runtime_duration(
                "checkpoint.write",
                (time.perf_counter() - write_started) * 1000,
            )

            # Update index
            self.checkpoint_index[metadata.id] = metadata
            if metadata.type == CheckpointType.AUTO:
                self._auto_checkpoint_count += 1
            index_started = time.perf_counter()
            self._save_checkpoint_index()
            record_runtime_duration(
                "checkpoint.index",
                (time.perf_counter() - index_started) * 1000,
            )

            logger.debug(f"Created checkpoint file: {metadata.id}")

        except Exception as e:
            logger.error(f"Error creating checkpoint file {metadata.id}: {e}")
        finally:
            record_runtime_duration(
                "checkpoint.persistence",
                (time.perf_counter() - persistence_started) * 1000,
            )

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
            with open(checkpoint_file, "rb") as f:
                compressed_data = f.read()

            data = json.loads(gzip.decompress(compressed_data).decode("utf-8"))

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
                metadata = self.checkpoint_index.pop(checkpoint_id)
                if metadata.type == CheckpointType.AUTO:
                    self._auto_checkpoint_count = max(
                        0,
                        self._auto_checkpoint_count - 1,
                    )
                self._save_checkpoint_index()

            logger.debug(f"Deleted checkpoint: {checkpoint_id}")

        except Exception as e:
            logger.error(f"Error deleting checkpoint {checkpoint_id}: {e}")

    def _load_checkpoint_index(self) -> None:
        """Load the checkpoint index from disk."""
        try:
            if self.index_path.exists():
                with open(self.index_path) as f:
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
            temp_path = self.index_path.with_suffix(".tmp")
            with open(temp_path, "w") as f:
                json.dump(index_data, f, indent=2)

            # Atomic rename
            temp_path.replace(self.index_path)

        except Exception as e:
            logger.error(f"Error saving checkpoint index: {e}")


def _sha256_file(path: Path) -> str:
    """Return a streaming SHA-256 digest for an archive manifest entry."""

    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json_atomic(path: Path, payload: Dict[str, Any]) -> None:
    """Write one JSON payload through a unique same-directory temporary file."""

    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with temporary.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2, sort_keys=True)
            handle.flush()
            os.fsync(handle.fileno())
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)
