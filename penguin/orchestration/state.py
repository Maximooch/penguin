"""Workflow state persistence for orchestration.

Stores workflow state in SQLite for durability across restarts.
Conversation history is stored separately and referenced by snapshot_id.
"""

import json
import logging
import sqlite3
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .backend import PhaseResult, WorkflowInfo, WorkflowPhase, WorkflowStatus

logger = logging.getLogger(__name__)


@dataclass
class WorkflowState:
    """Complete state of a workflow for persistence."""
    
    workflow_id: str
    task_id: str
    blueprint_id: Optional[str] = None
    project_id: Optional[str] = None
    
    # Status
    status: WorkflowStatus = WorkflowStatus.PENDING
    phase: WorkflowPhase = WorkflowPhase.PENDING
    progress: int = 0
    
    # Timestamps
    started_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    
    # Context reference (conversation history stored separately)
    context_snapshot_id: Optional[str] = None
    
    # Phase results
    phase_results: List[PhaseResult] = field(default_factory=list)
    
    # Artifacts (paths to files)
    artifacts: Dict[str, Any] = field(default_factory=dict)
    
    # Error tracking
    error_message: Optional[str] = None
    retry_count: int = 0
    
    # Config used for this workflow
    config: Dict[str, Any] = field(default_factory=dict)
    
    def to_info(self) -> WorkflowInfo:
        """Convert to WorkflowInfo summary."""
        return WorkflowInfo(
            workflow_id=self.workflow_id,
            task_id=self.task_id,
            blueprint_id=self.blueprint_id,
            project_id=self.project_id,
            status=self.status,
            phase=self.phase,
            started_at=self.started_at or datetime.utcnow(),
            updated_at=self.updated_at or datetime.utcnow(),
            progress=self.progress,
            error_message=self.error_message,
        )
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "workflow_id": self.workflow_id,
            "task_id": self.task_id,
            "blueprint_id": self.blueprint_id,
            "project_id": self.project_id,
            "status": self.status.value,
            "phase": self.phase.value,
            "progress": self.progress,
            "started_at": self.started_at.isoformat() if self.started_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
            "completed_at": self.completed_at.isoformat() if self.completed_at else None,
            "context_snapshot_id": self.context_snapshot_id,
            "phase_results": [pr.to_dict() for pr in self.phase_results],
            "artifacts": self.artifacts,
            "error_message": self.error_message,
            "retry_count": self.retry_count,
            "config": self.config,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "WorkflowState":
        """Create from dictionary."""
        # Parse timestamps
        started_at = None
        if data.get("started_at"):
            started_at = datetime.fromisoformat(data["started_at"])
        
        updated_at = None
        if data.get("updated_at"):
            updated_at = datetime.fromisoformat(data["updated_at"])
        
        completed_at = None
        if data.get("completed_at"):
            completed_at = datetime.fromisoformat(data["completed_at"])
        
        # Parse phase results
        phase_results = []
        for pr_data in data.get("phase_results", []):
            phase_results.append(PhaseResult(
                phase=WorkflowPhase(pr_data["phase"]),
                success=pr_data["success"],
                started_at=datetime.fromisoformat(pr_data["started_at"]),
                completed_at=datetime.fromisoformat(pr_data["completed_at"]),
                artifacts=pr_data.get("artifacts", {}),
                error_message=pr_data.get("error_message"),
                retry_count=pr_data.get("retry_count", 0),
            ))
        
        return cls(
            workflow_id=data["workflow_id"],
            task_id=data["task_id"],
            blueprint_id=data.get("blueprint_id"),
            project_id=data.get("project_id"),
            status=WorkflowStatus(data.get("status", "pending")),
            phase=WorkflowPhase(data.get("phase", "pending")),
            progress=data.get("progress", 0),
            started_at=started_at,
            updated_at=updated_at,
            completed_at=completed_at,
            context_snapshot_id=data.get("context_snapshot_id"),
            phase_results=phase_results,
            artifacts=data.get("artifacts", {}),
            error_message=data.get("error_message"),
            retry_count=data.get("retry_count", 0),
            config=data.get("config", {}),
        )


@dataclass
class ContextSnapshot:
    """Snapshot of conversation/execution context for a workflow checkpoint."""
    
    snapshot_id: str
    workflow_id: str
    phase: WorkflowPhase
    created_at: datetime
    
    # Conversation history (serialized)
    conversation_history: List[Dict[str, Any]] = field(default_factory=list)
    
    # Tool outputs from this phase
    tool_outputs: List[Dict[str, Any]] = field(default_factory=list)
    
    # Additional context
    metadata: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "snapshot_id": self.snapshot_id,
            "workflow_id": self.workflow_id,
            "phase": self.phase.value,
            "created_at": self.created_at.isoformat(),
            "conversation_history": self.conversation_history,
            "tool_outputs": self.tool_outputs,
            "metadata": self.metadata,
        }
    
    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ContextSnapshot":
        """Create from dictionary."""
        return cls(
            snapshot_id=data["snapshot_id"],
            workflow_id=data["workflow_id"],
            phase=WorkflowPhase(data["phase"]),
            created_at=datetime.fromisoformat(data["created_at"]),
            conversation_history=data.get("conversation_history", []),
            tool_outputs=data.get("tool_outputs", []),
            metadata=data.get("metadata", {}),
        )


class WorkflowStateStorage:
    """SQLite-backed storage for workflow state and context snapshots."""
    
    def __init__(self, db_path: Path):
        """Initialize storage with database path.
        
        Args:
            db_path: Path to SQLite database file.
        """
        self.db_path = db_path
        self._init_db()
    
    def _init_db(self) -> None:
        """Initialize database schema."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS workflow_states (
                    workflow_id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    blueprint_id TEXT,
                    project_id TEXT,
                    status TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    progress INTEGER DEFAULT 0,
                    started_at TEXT,
                    updated_at TEXT,
                    completed_at TEXT,
                    context_snapshot_id TEXT,
                    phase_results TEXT,  -- JSON
                    artifacts TEXT,  -- JSON
                    error_message TEXT,
                    retry_count INTEGER DEFAULT 0,
                    config TEXT,  -- JSON
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE TABLE IF NOT EXISTS context_snapshots (
                    snapshot_id TEXT PRIMARY KEY,
                    workflow_id TEXT NOT NULL,
                    phase TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    conversation_history TEXT,  -- JSON
                    tool_outputs TEXT,  -- JSON
                    metadata TEXT,  -- JSON
                    FOREIGN KEY (workflow_id) REFERENCES workflow_states(workflow_id)
                )
            """)
            
            # Indexes for common queries
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_task 
                ON workflow_states(task_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_project 
                ON workflow_states(project_id)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_workflow_status 
                ON workflow_states(status)
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_snapshot_workflow 
                ON context_snapshots(workflow_id)
            """)
            
            conn.commit()
        
        logger.debug(f"Initialized workflow state storage at {self.db_path}")
    
    def save_state(self, state: WorkflowState) -> None:
        """Save or update workflow state."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO workflow_states (
                    workflow_id, task_id, blueprint_id, project_id,
                    status, phase, progress,
                    started_at, updated_at, completed_at,
                    context_snapshot_id, phase_results, artifacts,
                    error_message, retry_count, config
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                state.workflow_id,
                state.task_id,
                state.blueprint_id,
                state.project_id,
                state.status.value,
                state.phase.value,
                state.progress,
                state.started_at.isoformat() if state.started_at else None,
                state.updated_at.isoformat() if state.updated_at else None,
                state.completed_at.isoformat() if state.completed_at else None,
                state.context_snapshot_id,
                json.dumps([pr.to_dict() for pr in state.phase_results]),
                json.dumps(state.artifacts),
                state.error_message,
                state.retry_count,
                json.dumps(state.config),
            ))
            conn.commit()
    
    def get_state(self, workflow_id: str) -> Optional[WorkflowState]:
        """Get workflow state by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM workflow_states WHERE workflow_id = ?",
                (workflow_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_state(row)
    
    def get_state_by_task(self, task_id: str) -> Optional[WorkflowState]:
        """Get the most recent workflow state for a task."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM workflow_states 
                   WHERE task_id = ? 
                   ORDER BY created_at DESC LIMIT 1""",
                (task_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return self._row_to_state(row)
    
    def list_states(
        self,
        project_id: Optional[str] = None,
        status_filter: Optional[List[WorkflowStatus]] = None,
        limit: int = 100,
    ) -> List[WorkflowState]:
        """List workflow states with optional filtering."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            
            query = "SELECT * FROM workflow_states WHERE 1=1"
            params: List[Any] = []
            
            if project_id:
                query += " AND project_id = ?"
                params.append(project_id)
            
            if status_filter:
                placeholders = ",".join("?" * len(status_filter))
                query += f" AND status IN ({placeholders})"
                params.extend([s.value for s in status_filter])
            
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
            
            cursor = conn.execute(query, params)
            return [self._row_to_state(row) for row in cursor.fetchall()]
    
    def delete_state(self, workflow_id: str) -> bool:
        """Delete a workflow state and its snapshots."""
        with sqlite3.connect(self.db_path) as conn:
            # Delete snapshots first
            conn.execute(
                "DELETE FROM context_snapshots WHERE workflow_id = ?",
                (workflow_id,)
            )
            # Delete state
            cursor = conn.execute(
                "DELETE FROM workflow_states WHERE workflow_id = ?",
                (workflow_id,)
            )
            conn.commit()
            return cursor.rowcount > 0
    
    def cleanup_old(self, older_than_days: int = 30) -> int:
        """Delete completed workflows older than specified days."""
        with sqlite3.connect(self.db_path) as conn:
            cutoff = datetime.utcnow().isoformat()
            # This is a simplified check - in production, compute proper date
            
            # Get workflow IDs to delete
            cursor = conn.execute("""
                SELECT workflow_id FROM workflow_states 
                WHERE status IN ('completed', 'cancelled', 'failed')
                AND completed_at IS NOT NULL
                AND julianday('now') - julianday(completed_at) > ?
            """, (older_than_days,))
            
            workflow_ids = [row[0] for row in cursor.fetchall()]
            
            if not workflow_ids:
                return 0
            
            # Delete snapshots
            placeholders = ",".join("?" * len(workflow_ids))
            conn.execute(
                f"DELETE FROM context_snapshots WHERE workflow_id IN ({placeholders})",
                workflow_ids
            )
            
            # Delete states
            cursor = conn.execute(
                f"DELETE FROM workflow_states WHERE workflow_id IN ({placeholders})",
                workflow_ids
            )
            
            conn.commit()
            return cursor.rowcount
    
    def _row_to_state(self, row: sqlite3.Row) -> WorkflowState:
        """Convert database row to WorkflowState."""
        # Parse JSON fields
        phase_results_data = json.loads(row["phase_results"] or "[]")
        phase_results = []
        for pr_data in phase_results_data:
            phase_results.append(PhaseResult(
                phase=WorkflowPhase(pr_data["phase"]),
                success=pr_data["success"],
                started_at=datetime.fromisoformat(pr_data["started_at"]),
                completed_at=datetime.fromisoformat(pr_data["completed_at"]),
                artifacts=pr_data.get("artifacts", {}),
                error_message=pr_data.get("error_message"),
                retry_count=pr_data.get("retry_count", 0),
            ))
        
        return WorkflowState(
            workflow_id=row["workflow_id"],
            task_id=row["task_id"],
            blueprint_id=row["blueprint_id"],
            project_id=row["project_id"],
            status=WorkflowStatus(row["status"]),
            phase=WorkflowPhase(row["phase"]),
            progress=row["progress"],
            started_at=datetime.fromisoformat(row["started_at"]) if row["started_at"] else None,
            updated_at=datetime.fromisoformat(row["updated_at"]) if row["updated_at"] else None,
            completed_at=datetime.fromisoformat(row["completed_at"]) if row["completed_at"] else None,
            context_snapshot_id=row["context_snapshot_id"],
            phase_results=phase_results,
            artifacts=json.loads(row["artifacts"] or "{}"),
            error_message=row["error_message"],
            retry_count=row["retry_count"],
            config=json.loads(row["config"] or "{}"),
        )
    
    # Context snapshot methods
    
    def save_snapshot(self, snapshot: ContextSnapshot) -> None:
        """Save a context snapshot."""
        with sqlite3.connect(self.db_path) as conn:
            conn.execute("""
                INSERT OR REPLACE INTO context_snapshots (
                    snapshot_id, workflow_id, phase, created_at,
                    conversation_history, tool_outputs, metadata
                ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """, (
                snapshot.snapshot_id,
                snapshot.workflow_id,
                snapshot.phase.value,
                snapshot.created_at.isoformat(),
                json.dumps(snapshot.conversation_history),
                json.dumps(snapshot.tool_outputs),
                json.dumps(snapshot.metadata),
            ))
            conn.commit()
    
    def get_snapshot(self, snapshot_id: str) -> Optional[ContextSnapshot]:
        """Get a context snapshot by ID."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                "SELECT * FROM context_snapshots WHERE snapshot_id = ?",
                (snapshot_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return ContextSnapshot(
                snapshot_id=row["snapshot_id"],
                workflow_id=row["workflow_id"],
                phase=WorkflowPhase(row["phase"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                conversation_history=json.loads(row["conversation_history"] or "[]"),
                tool_outputs=json.loads(row["tool_outputs"] or "[]"),
                metadata=json.loads(row["metadata"] or "{}"),
            )
    
    def get_latest_snapshot(self, workflow_id: str) -> Optional[ContextSnapshot]:
        """Get the most recent snapshot for a workflow."""
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            cursor = conn.execute(
                """SELECT * FROM context_snapshots 
                   WHERE workflow_id = ? 
                   ORDER BY created_at DESC LIMIT 1""",
                (workflow_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            return ContextSnapshot(
                snapshot_id=row["snapshot_id"],
                workflow_id=row["workflow_id"],
                phase=WorkflowPhase(row["phase"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                conversation_history=json.loads(row["conversation_history"] or "[]"),
                tool_outputs=json.loads(row["tool_outputs"] or "[]"),
                metadata=json.loads(row["metadata"] or "{}"),
            )
    
    def create_snapshot(
        self,
        workflow_id: str,
        phase: WorkflowPhase,
        conversation_history: List[Dict[str, Any]],
        tool_outputs: Optional[List[Dict[str, Any]]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> ContextSnapshot:
        """Create and save a new context snapshot."""
        snapshot = ContextSnapshot(
            snapshot_id=str(uuid.uuid4()),
            workflow_id=workflow_id,
            phase=phase,
            created_at=datetime.utcnow(),
            conversation_history=conversation_history,
            tool_outputs=tool_outputs or [],
            metadata=metadata or {},
        )
        self.save_snapshot(snapshot)
        return snapshot

