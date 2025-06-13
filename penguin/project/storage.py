"""SQLite-backed storage system for Projects and Tasks.

This module provides persistent storage for the project management system using
SQLite with ACID transactions, supporting both sync and async operations.
"""

import sqlite3
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
from contextlib import contextmanager

from .models import Project, Task, TaskStatus, ExecutionRecord, StateTransition
from .exceptions import StorageError, ProjectNotFoundError, TaskNotFoundError

logger = logging.getLogger(__name__)


class ProjectStorage:
    """SQLite-backed storage for projects and tasks."""
    
    def __init__(self, db_path: Union[str, Path]):
        """Initialize storage with database path.
        
        Args:
            db_path: Path to SQLite database file
        """
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        
        # Initialize database schema
        self._init_schema()
        
        logger.info(f"Initialized ProjectStorage at {self.db_path}")
    
    def _init_schema(self) -> None:
        """Initialize database schema with tables for projects and tasks."""
        with self._get_connection() as conn:
            # Projects table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS projects (
                    id TEXT PRIMARY KEY,
                    name TEXT NOT NULL,
                    description TEXT,
                    status TEXT DEFAULT 'active',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    workspace_path TEXT,
                    context_path TEXT,
                    tags TEXT,  -- JSON array
                    priority INTEGER DEFAULT 0,
                    metadata TEXT,  -- JSON object
                    budget_tokens INTEGER,
                    budget_minutes INTEGER,
                    start_date TEXT,
                    due_date TEXT
                )
            """)
            
            # Tasks table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS tasks (
                    id TEXT PRIMARY KEY,
                    title TEXT NOT NULL,
                    description TEXT,
                    status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    priority INTEGER DEFAULT 0,
                    project_id TEXT,
                    parent_task_id TEXT,
                    tags TEXT,  -- JSON array
                    dependencies TEXT,  -- JSON array of task IDs
                    due_date TEXT,
                    progress INTEGER DEFAULT 0,
                    metadata TEXT,  -- JSON object
                    review_notes TEXT,
                    reviewed_by TEXT,
                    reviewed_at TEXT,
                    budget_tokens INTEGER,
                    budget_minutes INTEGER,
                    allowed_tools TEXT,  -- JSON array
                    acceptance_criteria TEXT,  -- JSON array
                    definition_of_done TEXT,
                    FOREIGN KEY (project_id) REFERENCES projects (id) ON DELETE CASCADE,
                    FOREIGN KEY (parent_task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            """)
            
            # Execution records table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS execution_records (
                    id TEXT PRIMARY KEY,
                    task_id TEXT NOT NULL,
                    executor_id TEXT DEFAULT 'system',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    result TEXT,
                    response TEXT,
                    task_prompt TEXT,
                    iterations INTEGER DEFAULT 0,
                    max_iterations INTEGER DEFAULT 5,
                    tokens_used TEXT,  -- JSON object
                    tools_used TEXT,   -- JSON array
                    execution_context TEXT,  -- JSON object
                    error_details TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            """)
            
            # State transitions table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS state_transitions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    task_id TEXT NOT NULL,
                    from_state TEXT NOT NULL,
                    to_state TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    reason TEXT,
                    user_id TEXT,
                    FOREIGN KEY (task_id) REFERENCES tasks (id) ON DELETE CASCADE
                )
            """)
            
            # Indexes for better query performance
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_project_id ON tasks (project_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_status ON tasks (status)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_tasks_parent_id ON tasks (parent_task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_execution_records_task_id ON execution_records (task_id)")
            conn.execute("CREATE INDEX IF NOT EXISTS idx_state_transitions_task_id ON state_transitions (task_id)")
            
            conn.commit()
    
    @contextmanager
    def _get_connection(self):
        """Get database connection with proper error handling."""
        conn = None
        try:
            conn = sqlite3.connect(str(self.db_path))
            conn.row_factory = sqlite3.Row  # Enable column access by name
            yield conn
        except sqlite3.Error as e:
            if conn:
                conn.rollback()
            raise StorageError(f"Database error: {e}")
        finally:
            if conn:
                conn.close()
    
    # Project operations
    
    def create_project(self, project: Project) -> None:
        """Create a new project in the database."""
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO projects (
                    id, name, description, status, created_at, updated_at,
                    workspace_path, context_path, tags, priority, metadata,
                    budget_tokens, budget_minutes, start_date, due_date
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                project.id, project.name, project.description, project.status,
                project.created_at, project.updated_at,
                str(project.workspace_path) if project.workspace_path else None,
                str(project.context_path) if project.context_path else None,
                json.dumps(project.tags) if project.tags else None,
                project.priority,
                json.dumps(project.metadata) if project.metadata else None,
                project.budget_tokens, project.budget_minutes,
                project.start_date, project.due_date
            ))
            conn.commit()
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE id = ?", (project_id,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_project(row)
    
    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get a project by name."""
        with self._get_connection() as conn:
            row = conn.execute(
                "SELECT * FROM projects WHERE name = ?", (name,)
            ).fetchone()
            
            if not row:
                return None
            
            return self._row_to_project(row)
    
    def update_project(self, project: Project) -> None:
        """Update an existing project."""
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE projects SET
                    name = ?, description = ?, status = ?, updated_at = ?,
                    workspace_path = ?, context_path = ?, tags = ?, priority = ?,
                    metadata = ?, budget_tokens = ?, budget_minutes = ?,
                    start_date = ?, due_date = ?
                WHERE id = ?
            """, (
                project.name, project.description, project.status, project.updated_at,
                str(project.workspace_path) if project.workspace_path else None,
                str(project.context_path) if project.context_path else None,
                json.dumps(project.tags) if project.tags else None,
                project.priority,
                json.dumps(project.metadata) if project.metadata else None,
                project.budget_tokens, project.budget_minutes,
                project.start_date, project.due_date,
                project.id
            ))
            conn.commit()
    
    def delete_project(self, project_id: str) -> None:
        """Delete a project and all its tasks."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
            conn.commit()
    
    def list_projects(self, status: Optional[str] = None) -> List[Project]:
        """List all projects, optionally filtered by status."""
        query = "SELECT * FROM projects"
        params = []
        
        if status:
            query += " WHERE status = ?"
            params.append(status)
        
        query += " ORDER BY created_at DESC"
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            return [self._row_to_project(row) for row in rows]
    
    # Task operations
    
    def create_task(self, task: Task) -> None:
        """Create a new task in the database."""
        with self._get_connection() as conn:
            # Insert task
            conn.execute("""
                INSERT INTO tasks (
                    id, title, description, status, created_at, updated_at,
                    priority, project_id, parent_task_id, tags, dependencies,
                    due_date, progress, metadata, review_notes, reviewed_by,
                    reviewed_at, budget_tokens, budget_minutes, allowed_tools,
                    acceptance_criteria, definition_of_done
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                task.id, task.title, task.description, task.status.value,
                task.created_at, task.updated_at, task.priority,
                task.project_id, task.parent_task_id,
                json.dumps(task.tags) if task.tags else None,
                json.dumps(task.dependencies) if task.dependencies else None,
                task.due_date, task.progress,
                json.dumps(task.metadata) if task.metadata else None,
                task.review_notes, task.reviewed_by, task.reviewed_at,
                task.budget_tokens, task.budget_minutes,
                json.dumps(task.allowed_tools) if task.allowed_tools else None,
                json.dumps(task.acceptance_criteria) if task.acceptance_criteria else None,
                task.definition_of_done
            ))
            
            # Insert execution records
            for record in task.execution_history:
                self._insert_execution_record(conn, record)
            
            # Insert state transitions
            for transition in task.transition_history:
                self._insert_state_transition(conn, task.id, transition)
            
            conn.commit()
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID with full execution history."""
        with self._get_connection() as conn:
            # Get task data
            row = conn.execute(
                "SELECT * FROM tasks WHERE id = ?", (task_id,)
            ).fetchone()
            
            if not row:
                return None
            
            # Get execution records
            execution_rows = conn.execute(
                "SELECT * FROM execution_records WHERE task_id = ? ORDER BY started_at",
                (task_id,)
            ).fetchall()
            
            # Get state transitions
            transition_rows = conn.execute(
                "SELECT * FROM state_transitions WHERE task_id = ? ORDER BY timestamp",
                (task_id,)
            ).fetchall()
            
            return self._row_to_task(row, execution_rows, transition_rows)
    
    def get_task_by_title(self, title: str, project_id: Optional[str] = None) -> Optional[Task]:
        """Get a task by title, optionally within a specific project."""
        query = "SELECT * FROM tasks WHERE title = ?"
        params = [title]
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        with self._get_connection() as conn:
            row = conn.execute(query, params).fetchone()
            
            if not row:
                return None
            
            # Get execution records and transitions
            task_id = row["id"]
            execution_rows = conn.execute(
                "SELECT * FROM execution_records WHERE task_id = ? ORDER BY started_at",
                (task_id,)
            ).fetchall()
            
            transition_rows = conn.execute(
                "SELECT * FROM state_transitions WHERE task_id = ? ORDER BY timestamp",
                (task_id,)
            ).fetchall()
            
            return self._row_to_task(row, execution_rows, transition_rows)
    
    def update_task(self, task: Task) -> None:
        """Update an existing task."""
        with self._get_connection() as conn:
            # Update task
            conn.execute("""
                UPDATE tasks SET
                    title = ?, description = ?, status = ?, updated_at = ?,
                    priority = ?, parent_task_id = ?, tags = ?, dependencies = ?,
                    due_date = ?, progress = ?, metadata = ?, review_notes = ?,
                    reviewed_by = ?, reviewed_at = ?, budget_tokens = ?,
                    budget_minutes = ?, allowed_tools = ?, acceptance_criteria = ?,
                    definition_of_done = ?
                WHERE id = ?
            """, (
                task.title, task.description, task.status.value, task.updated_at,
                task.priority, task.parent_task_id,
                json.dumps(task.tags) if task.tags else None,
                json.dumps(task.dependencies) if task.dependencies else None,
                task.due_date, task.progress,
                json.dumps(task.metadata) if task.metadata else None,
                task.review_notes, task.reviewed_by, task.reviewed_at,
                task.budget_tokens, task.budget_minutes,
                json.dumps(task.allowed_tools) if task.allowed_tools else None,
                json.dumps(task.acceptance_criteria) if task.acceptance_criteria else None,
                task.definition_of_done,
                task.id
            ))
            
            # Update execution records - delete old ones and insert new ones
            conn.execute("DELETE FROM execution_records WHERE task_id = ?", (task.id,))
            for record in task.execution_history:
                self._insert_execution_record(conn, record)
            
            # Update state transitions - delete old ones and insert new ones
            conn.execute("DELETE FROM state_transitions WHERE task_id = ?", (task.id,))
            for transition in task.transition_history:
                self._insert_state_transition(conn, task.id, transition)
            
            conn.commit()
    
    def delete_task(self, task_id: str) -> None:
        """Delete a task and all its execution records."""
        with self._get_connection() as conn:
            conn.execute("DELETE FROM tasks WHERE id = ?", (task_id,))
            conn.commit()
    
    def list_tasks(
        self, 
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        parent_task_id: Optional[str] = None
    ) -> List[Task]:
        """List tasks with optional filtering."""
        query = "SELECT * FROM tasks WHERE 1=1"
        params = []
        
        if project_id:
            query += " AND project_id = ?"
            params.append(project_id)
        
        if status:
            query += " AND status = ?"
            params.append(status.value)
        
        if parent_task_id:
            query += " AND parent_task_id = ?"
            params.append(parent_task_id)
        
        query += " ORDER BY created_at DESC"
        
        with self._get_connection() as conn:
            rows = conn.execute(query, params).fetchall()
            
            # For efficiency, we'll get tasks without full execution history
            # Use get_task() if you need the complete execution history
            return [self._row_to_task(row) for row in rows]
    
    def get_active_tasks(self) -> List[Task]:
        """Get all active tasks."""
        return self.list_tasks(status=TaskStatus.ACTIVE)
    
    def get_task_dependencies(self, task_id: str) -> List[Task]:
        """Get all tasks that this task depends on."""
        task = self.get_task(task_id)
        if not task or not task.dependencies:
            return []
        
        with self._get_connection() as conn:
            # Use parameterized query with proper escaping
            placeholders = ', '.join(['?'] * len(task.dependencies))
            query = f"SELECT * FROM tasks WHERE id IN ({placeholders})"
            
            rows = conn.execute(query, task.dependencies).fetchall()
            return [self._row_to_task(row) for row in rows]
    
    # Helper methods
    
    def _insert_execution_record(self, conn: sqlite3.Connection, record: ExecutionRecord) -> None:
        """Insert an execution record into the database."""
        conn.execute("""
            INSERT INTO execution_records (
                id, task_id, executor_id, started_at, completed_at, result,
                response, task_prompt, iterations, max_iterations, tokens_used,
                tools_used, execution_context, error_details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            record.id, record.task_id, record.executor_id, record.started_at,
            record.completed_at, record.result.value if record.result else None,
            record.response, record.task_prompt, record.iterations,
            record.max_iterations,
            json.dumps(record.tokens_used) if record.tokens_used else None,
            json.dumps(record.tools_used) if record.tools_used else None,
            json.dumps(record.execution_context) if record.execution_context else None,
            record.error_details
        ))
    
    def _insert_state_transition(self, conn: sqlite3.Connection, task_id: str, transition: StateTransition) -> None:
        """Insert a state transition into the database."""
        conn.execute("""
            INSERT INTO state_transitions (
                task_id, from_state, to_state, timestamp, reason, user_id
            ) VALUES (?, ?, ?, ?, ?, ?)
        """, (
            task_id, transition.from_state.value, transition.to_state.value,
            transition.timestamp, transition.reason, transition.user_id
        ))
    
    def _row_to_project(self, row: sqlite3.Row) -> Project:
        """Convert a database row to a Project object."""
        return Project(
            id=row["id"],
            name=row["name"],
            description=row["description"] or "",
            status=row["status"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            workspace_path=Path(row["workspace_path"]) if row["workspace_path"] else None,
            context_path=Path(row["context_path"]) if row["context_path"] else None,
            tags=json.loads(row["tags"]) if row["tags"] else [],
            priority=row["priority"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            budget_tokens=row["budget_tokens"],
            budget_minutes=row["budget_minutes"],
            start_date=row["start_date"],
            due_date=row["due_date"]
        )
    
    def _row_to_task(
        self, 
        row: sqlite3.Row, 
        execution_rows: Optional[List[sqlite3.Row]] = None,
        transition_rows: Optional[List[sqlite3.Row]] = None
    ) -> Task:
        """Convert a database row to a Task object."""
        task = Task(
            id=row["id"],
            title=row["title"],
            description=row["description"] or "",
            status=TaskStatus(row["status"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            priority=row["priority"],
            project_id=row["project_id"],
            parent_task_id=row["parent_task_id"],
            tags=json.loads(row["tags"]) if row["tags"] else [],
            dependencies=json.loads(row["dependencies"]) if row["dependencies"] else [],
            due_date=row["due_date"],
            progress=row["progress"],
            metadata=json.loads(row["metadata"]) if row["metadata"] else {},
            review_notes=row["review_notes"],
            reviewed_by=row["reviewed_by"],
            reviewed_at=row["reviewed_at"],
            budget_tokens=row["budget_tokens"],
            budget_minutes=row["budget_minutes"],
            allowed_tools=json.loads(row["allowed_tools"]) if row["allowed_tools"] else None,
            acceptance_criteria=json.loads(row["acceptance_criteria"]) if row["acceptance_criteria"] else [],
            definition_of_done=row["definition_of_done"]
        )
        
        # Add execution records if provided
        if execution_rows:
            task.execution_history = [self._row_to_execution_record(r) for r in execution_rows]
        
        # Add state transitions if provided
        if transition_rows:
            task.transition_history = [self._row_to_state_transition(r) for r in transition_rows]
        
        return task
    
    def _row_to_execution_record(self, row: sqlite3.Row) -> ExecutionRecord:
        """Convert a database row to an ExecutionRecord object."""
        from .models import ExecutionResult
        
        return ExecutionRecord(
            id=row["id"],
            task_id=row["task_id"],
            executor_id=row["executor_id"],
            started_at=row["started_at"],
            completed_at=row["completed_at"],
            result=ExecutionResult(row["result"]) if row["result"] else None,
            response=row["response"] or "",
            task_prompt=row["task_prompt"] or "",
            iterations=row["iterations"],
            max_iterations=row["max_iterations"],
            tokens_used=json.loads(row["tokens_used"]) if row["tokens_used"] else {},
            tools_used=json.loads(row["tools_used"]) if row["tools_used"] else [],
            execution_context=json.loads(row["execution_context"]) if row["execution_context"] else {},
            error_details=row["error_details"]
        )
    
    def _row_to_state_transition(self, row: sqlite3.Row) -> StateTransition:
        """Convert a database row to a StateTransition object."""
        return StateTransition(
            from_state=TaskStatus(row["from_state"]),
            to_state=TaskStatus(row["to_state"]),
            timestamp=row["timestamp"],
            reason=row["reason"],
            user_id=row["user_id"]
        ) 