"""ProjectManager - Main interface for the Project and Task Management System.

This module provides a comprehensive project and task management interface with
both synchronous and asynchronous APIs, event integration, and advanced features
like dependency tracking, DAG-based scheduling, and resource management.
"""

import asyncio
import hashlib
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple, Union

import networkx as nx

from .models import (
    Blueprint,
    BlueprintItem,
    ExecutionRecord,
    ExecutionResult,
    Project,
    StateTransition,
    Task,
    TaskPhase,
    TaskStatus,
)
from .storage import ProjectStorage
from .exceptions import (
    ProjectError, TaskError, ValidationError, ProjectNotFoundError, 
    TaskNotFoundError, StateTransitionError, DependencyError
)

logger = logging.getLogger(__name__)


class ProjectManager:
    """Main interface for project and task management.
    
    Features:
    - Dual sync/async API for maximum flexibility
    - SQLite-backed persistent storage with ACID transactions
    - Event-driven updates with EventBus integration
    - Dependency tracking and validation
    - Resource constraint management
    - Execution tracking and metrics
    """
    
    def __init__(self, workspace_path: Union[str, Path]):
        """Initialize ProjectManager with workspace path.
        
        Args:
            workspace_path: Root directory for projects and database
        """
        self.workspace_path = Path(workspace_path)
        self.workspace_path.mkdir(parents=True, exist_ok=True)
        
        # Initialize storage
        db_path = self.workspace_path / "projects.db"
        self.storage = ProjectStorage(db_path)
        
        # Event system integration
        self._event_bus = None
        try:
            from penguin.utils.events import EventBus
            self._event_bus = EventBus.get_instance()
            logger.info("EventBus integration enabled")
        except ImportError:
            logger.warning("EventBus not available - events will be disabled")
        
        # DAG scheduler state
        self._dag: Optional[nx.DiGraph] = None
        self._dag_project_id: Optional[str] = None
        
        # Default tie-breaker order for DAG frontier selection
        self._tie_breakers: List[str] = [
            "priority_desc",
            "due_date_asc",
            "sequence",
            "effort_asc",
            "value_desc",
            "risk_asc",
            "created_at_asc",
        ]
        
        logger.info(f"ProjectManager initialized with workspace: {workspace_path}")
    
    # ==================== Project Operations ====================
    
    def create_project(
        self, 
        name: str, 
        description: str,
        tags: Optional[List[str]] = None,
        budget_tokens: Optional[int] = None,
        budget_minutes: Optional[int] = None,
        **metadata
    ) -> Project:
        """Create a new project.
        
        Args:
            name: Project name (must be unique)
            description: Project description
            tags: Optional list of tags for categorization
            budget_tokens: Optional token budget limit
            budget_minutes: Optional time budget in minutes
            **metadata: Additional project metadata
            
        Returns:
            Created Project instance
            
        Raises:
            ValidationError: If name is invalid or already exists
        """
        if not name or not name.strip():
            raise ValidationError("Project name cannot be empty", field="name")
        
        # Check for existing project with same name
        existing = self.storage.get_project_by_name(name.strip())
        if existing:
            raise ValidationError(f"Project '{name}' already exists", field="name")
        
        # Create project
        now = datetime.utcnow().isoformat()
        project_id = self._generate_id(name)
        
        # Set up workspace paths
        workspace_path = self.workspace_path / "projects" / project_id
        context_path = workspace_path / "context"
        
        project = Project(
            id=project_id,
            name=name.strip(),
            description=description,
            created_at=now,
            updated_at=now,
            workspace_path=workspace_path,
            context_path=context_path,
            tags=tags or [],
            metadata=metadata,
            budget_tokens=budget_tokens,
            budget_minutes=budget_minutes
        )
        
        # Create directories
        workspace_path.mkdir(parents=True, exist_ok=True)
        context_path.mkdir(parents=True, exist_ok=True)
        
        # Save to storage
        self.storage.create_project(project)
        
        # Publish event
        self._publish_event("project_created", {
            "project_id": project.id,
            "project_name": project.name
        })
        
        logger.info(f"Created project: {name} ({project.id})")
        return project
    
    async def create_project_async(
        self, 
        name: str, 
        description: str,
        tags: Optional[List[str]] = None,
        budget_tokens: Optional[int] = None,
        budget_minutes: Optional[int] = None,
        **metadata
    ) -> Project:
        """Async version of create_project."""
        def _create_project():
            return self.create_project(
                name=name,
                description=description,
                tags=tags,
                budget_tokens=budget_tokens,
                budget_minutes=budget_minutes,
                **metadata
            )
        return await asyncio.get_event_loop().run_in_executor(None, _create_project)
    
    def get_project(self, project_id: str) -> Optional[Project]:
        """Get a project by ID."""
        return self.storage.get_project(project_id)
    
    async def get_project_async(self, project_id: str) -> Optional[Project]:
        """Async version of get_project."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_project, project_id
        )
    
    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get a project by name."""
        return self.storage.get_project_by_name(name)
    
    def list_projects(self, status: Optional[str] = None) -> List[Project]:
        """List all projects, optionally filtered by status."""
        return self.storage.list_projects(status)
    
    async def list_projects_async(self, status: Optional[str] = None) -> List[Project]:
        """Async version of list_projects."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.list_projects, status
        )
    
    # ==================== Task Operations ====================
    
    def create_task(
        self,
        title: str,
        description: str,
        project_id: Optional[str] = None,
        parent_task_id: Optional[str] = None,
        priority: int = 0,
        tags: Optional[List[str]] = None,
        dependencies: Optional[List[str]] = None,
        due_date: Optional[str] = None,
        budget_tokens: Optional[int] = None,
        budget_minutes: Optional[int] = None,
        allowed_tools: Optional[List[str]] = None,
        acceptance_criteria: Optional[List[str]] = None,
        **metadata
    ) -> Task:
        """Create a new task.
        
        Args:
            title: Task title (must be unique within project)
            description: Detailed task description
            project_id: Optional parent project ID
            parent_task_id: Optional parent task for hierarchical tasks
            priority: Task priority (lower = higher priority)
            tags: Optional list of tags
            dependencies: Optional list of task IDs this task depends on
            due_date: Optional due date in ISO format
            budget_tokens: Optional token budget limit
            budget_minutes: Optional time budget in minutes
            allowed_tools: Optional list of allowed tools for execution
            acceptance_criteria: Optional list of acceptance criteria
            **metadata: Additional task metadata
            
        Returns:
            Created Task instance
            
        Raises:
            ValidationError: If title is invalid or already exists
            ProjectNotFoundError: If project_id doesn't exist
            TaskNotFoundError: If parent_task_id doesn't exist
            DependencyError: If dependencies create cycles
        """
        if not title or not title.strip():
            raise ValidationError("Task title cannot be empty", field="title")
        
        # Validate project exists
        if project_id:
            project = self.storage.get_project(project_id)
            if not project:
                raise ProjectNotFoundError(f"Project '{project_id}' not found", project_id)
        
        # Validate parent task exists and is in same project
        if parent_task_id:
            parent_task = self.storage.get_task(parent_task_id)
            if not parent_task:
                raise TaskNotFoundError(f"Parent task '{parent_task_id}' not found", parent_task_id)
            if parent_task.project_id != project_id:
                raise ValidationError("Parent task must be in the same project", field="parent_task_id")
        
        # Check for existing task with same title in project
        existing = self.storage.get_task_by_title(title.strip(), project_id)
        if existing:
            scope = f"project '{project_id}'" if project_id else "independent tasks"
            raise ValidationError(f"Task '{title}' already exists in {scope}", field="title")
        
        # Validate dependencies exist and don't create cycles
        if dependencies:
            self._validate_dependencies(dependencies, project_id)
        
        # Create task
        now = datetime.utcnow().isoformat()
        task_id = self._generate_id(title)
        
        task = Task(
            id=task_id,
            title=title.strip(),
            description=description,
            status=TaskStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            priority=priority,
            project_id=project_id,
            parent_task_id=parent_task_id,
            tags=tags or [],
            dependencies=dependencies or [],
            due_date=due_date,
            metadata=metadata,
            budget_tokens=budget_tokens,
            budget_minutes=budget_minutes,
            allowed_tools=allowed_tools,
            acceptance_criteria=acceptance_criteria or []
        )
        
        # Save to storage
        self.storage.create_task(task)
        
        # Publish event
        self._publish_event("task_created", {
            "task_id": task.id,
            "task_title": task.title,
            "project_id": project_id
        })
        
        logger.info(f"Created task: {title} ({task.id})")
        return task
    
    async def create_task_async(
        self,
        title: str,
        description: str,
        project_id: Optional[str] = None,
        **kwargs
    ) -> Task:
        """Async version of create_task."""
        def _create_task():
            return self.create_task(
                title=title,
                description=description,
                project_id=project_id,
                **kwargs
            )
        return await asyncio.get_event_loop().run_in_executor(None, _create_task)
    
    def get_task(self, task_id: str) -> Optional[Task]:
        """Get a task by ID with full execution history."""
        return self.storage.get_task(task_id)
    
    async def get_task_async(self, task_id: str) -> Optional[Task]:
        """Async version of get_task."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_task, task_id
        )
    
    def get_task_by_title(self, title: str, project_id: Optional[str] = None) -> Optional[Task]:
        """Get a task by title, optionally within a specific project."""
        return self.storage.get_task_by_title(title, project_id)
    
    def update_task_status(
        self, 
        task_id: str, 
        new_status: TaskStatus, 
        reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """Update a task's status with validation and event publishing.
        
        Args:
            task_id: ID of task to update
            new_status: New status to transition to
            reason: Optional reason for the transition
            user_id: Optional user ID making the change
            
        Returns:
            True if transition was successful
            
        Raises:
            TaskNotFoundError: If task doesn't exist
            StateTransitionError: If transition is invalid
        """
        task = self.storage.get_task(task_id)
        if not task:
            raise TaskNotFoundError(f"Task '{task_id}' not found", task_id)
        
        # Attempt transition
        if not task.transition_to(new_status, reason, user_id):
            raise StateTransitionError(
                f"Invalid transition from {task.status.value} to {new_status.value}",
                task.status.value,
                new_status.value,
                task_id
            )
        
        # Update in storage
        self.storage.update_task(task)
        
        # Get old status for event publishing
        old_status = None
        if task.transition_history:
            # Get the most recent transition's from_state
            old_status = task.transition_history[-1].from_state.value
        else:
            # If no transition history, this is the first transition
            old_status = "unknown"
        
        # Publish event
        self._publish_event("task_status_changed", {
            "task_id": task.id,
            "old_status": old_status,
            "new_status": new_status.value,
            "reason": reason
        })
        
        logger.info(f"Task {task_id} status changed to {new_status.value}")
        return True
    
    async def update_task_status_async(
        self, 
        task_id: str, 
        new_status: TaskStatus, 
        reason: Optional[str] = None,
        user_id: Optional[str] = None
    ) -> bool:
        """Async version of update_task_status."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.update_task_status, task_id, new_status, reason, user_id
        )
    
    def list_tasks(
        self,
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        parent_task_id: Optional[str] = None
    ) -> List[Task]:
        """List tasks with optional filtering."""
        return self.storage.list_tasks(project_id, status, parent_task_id)
    
    async def list_tasks_async(
        self,
        project_id: Optional[str] = None,
        status: Optional[TaskStatus] = None,
        parent_task_id: Optional[str] = None
    ) -> List[Task]:
        """Async version of list_tasks."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.list_tasks, project_id, status, parent_task_id
        )
    
    def get_active_tasks(self) -> List[Task]:
        """Get all active tasks across all projects."""
        return self.storage.get_active_tasks()
    
    async def get_active_tasks_async(self) -> List[Task]:
        """Async version of get_active_tasks."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_active_tasks
        )
    
    def get_next_task(self, project_id: Optional[str] = None) -> Optional[Task]:
        """Return the next executable task.

        Args:
            project_id: If provided, limit the search to tasks within this
                project.  When *None* (default) the search spans **all** active
                tasks (legacy behaviour).
        """
        active_tasks = self.get_active_tasks()

        # Optional project-scoped filtering
        if project_id is not None:
            active_tasks = [t for t in active_tasks if t.project_id == project_id]

        if not active_tasks:
            return None

        # Filter out tasks that are blocked by dependencies
        unblocked_tasks: list[Task] = [t for t in active_tasks if not self._is_task_blocked(t)]
        if not unblocked_tasks:
            return None

        # Choose the highest-priority task (lower number = higher priority)
        unblocked_tasks.sort(key=lambda t: (t.priority, t.created_at))
        return unblocked_tasks[0]
    
    async def get_next_task_async(self, project_id: Optional[str] = None) -> Optional[Task]:
        """Async wrapper for ``get_next_task`` with optional project filter."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_next_task, project_id
        )
    
    # ==================== Advanced Features ====================
    
    def plan_project_from_spec(self, spec_text: str, project_name: Optional[str] = None) -> Dict[str, Any]:
        """Create a project plan from a natural language specification.
        
        This is a placeholder for future implementation that would:
        1. Route spec through the Engine for analysis
        2. Receive a JSON work breakdown structure  
        3. Bulk-insert projects and tasks with dependencies
        
        Args:
            spec_text: Natural language project specification
            project_name: Optional project name override
            
        Returns:
            Dictionary with project and task creation results
        """
        # For now, return a placeholder structure
        logger.warning("plan_project_from_spec is not yet implemented")
        return {
            "status": "not_implemented",
            "message": "This feature will be implemented in a future version",
            "spec_text": spec_text[:100] + "..." if len(spec_text) > 100 else spec_text
        }
    
    def get_project_metrics(self, project_id: str) -> Dict[str, Any]:
        """Get comprehensive metrics for a project."""
        project = self.storage.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' not found", project_id)
        
        tasks = self.list_tasks(project_id)
        
        # Calculate basic metrics
        total_tasks = len(tasks)
        completed_tasks = len([t for t in tasks if t.status == TaskStatus.COMPLETED])
        active_tasks = len([t for t in tasks if t.status == TaskStatus.ACTIVE])
        failed_tasks = len([t for t in tasks if t.status == TaskStatus.FAILED])
        
        completion_rate = completed_tasks / total_tasks if total_tasks > 0 else 0.0
        
        # Calculate execution metrics
        total_executions = sum(len(t.execution_history) for t in tasks)
        total_tokens = sum(
            sum(r.tokens_used.values()) for t in tasks for r in t.execution_history
        )
        
        return {
            "project_id": project_id,
            "project_name": project.name,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "active_tasks": active_tasks,
            "failed_tasks": failed_tasks,
            "completion_rate": completion_rate,
            "total_executions": total_executions,
            "total_tokens": total_tokens,
            "created_at": project.created_at,
            "updated_at": project.updated_at
        }
    
    # ==================== Helper Methods ====================
    
    def _generate_id(self, text: str) -> str:
        """Generate a unique ID based on text and timestamp."""
        timestamp = datetime.utcnow().isoformat()
        content = f"{text}_{timestamp}_{uuid.uuid4().hex[:8]}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]
    
    def _validate_dependencies(self, dependencies: List[str], project_id: Optional[str]) -> None:
        """Validate task dependencies exist and don't create cycles."""
        for dep_id in dependencies:
            dep_task = self.storage.get_task(dep_id)
            if not dep_task:
                raise TaskNotFoundError(f"Dependency task '{dep_id}' not found", dep_id)
            
            # Ensure dependency is in same project (or both are independent)
            if dep_task.project_id != project_id:
                raise DependencyError(
                    f"Dependency task must be in the same project", dep_id
                )
        
        # TODO: Implement cycle detection algorithm
        # For now, we'll skip cycle detection but this should be added
        logger.debug(f"Validated {len(dependencies)} dependencies")
    
    def _is_task_blocked(self, task: Task) -> bool:
        """Check if a task is blocked by incomplete dependencies."""
        if not task.dependencies:
            return False
        
        for dep_id in task.dependencies:
            dep_task = self.storage.get_task(dep_id)
            if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                return True
        
        return False
    
    def _publish_event(self, event_type: str, data: Dict[str, Any]) -> None:
        """Publish an event if EventBus is available."""
        if self._event_bus:
            try:
                # Check if we're in an async context
                try:
                    loop = asyncio.get_running_loop()
                    # We're in an async context, schedule the coroutine as a task
                    asyncio.create_task(self._event_bus.publish(event_type, data))
                except RuntimeError:
                    # No running event loop, try to create one
                    try:
                        loop = asyncio.new_event_loop()
                        asyncio.set_event_loop(loop)
                        loop.run_until_complete(self._event_bus.publish(event_type, data))
                        loop.close()
                    except Exception as e:
                        logger.debug(f"Could not publish event {event_type}: {e}")
            except Exception as e:
                logger.debug(f"Failed to publish event {event_type}: {e}")
        else:
            logger.debug(f"Event {event_type} not published (EventBus not available)")
    
    # ==================== DAG Scheduling ====================
    
    def build_dag(self, project_id: str, force: bool = False) -> nx.DiGraph:
        """Build or retrieve the dependency DAG for a project.
        
        Args:
            project_id: Project ID to build DAG for.
            force: If True, rebuild even if cached.
            
        Returns:
            NetworkX DiGraph with tasks as nodes and dependencies as edges.
        """
        if not force and self._dag is not None and self._dag_project_id == project_id:
            return self._dag
        
        tasks = self.list_tasks(project_id)
        dag = nx.DiGraph()
        
        # Add all tasks as nodes
        for task in tasks:
            dag.add_node(task.id, task=task)
        
        # Add dependency edges (from dependency -> task)
        for task in tasks:
            for dep_id in task.dependencies:
                if dag.has_node(dep_id):
                    dag.add_edge(dep_id, task.id)
        
        # Check for cycles
        if not nx.is_directed_acyclic_graph(dag):
            cycles = list(nx.simple_cycles(dag))
            raise DependencyError(
                f"Dependency cycle detected in project {project_id}: {cycles[:3]}"
            )
        
        self._dag = dag
        self._dag_project_id = project_id
        
        logger.debug(f"Built DAG for project {project_id}: {len(tasks)} tasks, {dag.number_of_edges()} edges")
        return dag
    
    def get_ready_tasks(self, project_id: str) -> List[Task]:
        """Get tasks that are ready to execute (all dependencies satisfied).
        
        A task is ready if:
        - It's in ACTIVE status
        - All its dependencies are COMPLETED
        - It's not blocked
        
        Args:
            project_id: Project to get ready tasks for.
            
        Returns:
            List of ready tasks, sorted by tie-breakers.
        """
        dag = self.build_dag(project_id)
        tasks = self.list_tasks(project_id)
        task_map = {t.id: t for t in tasks}
        
        ready = []
        for task in tasks:
            if task.status != TaskStatus.ACTIVE:
                continue
            
            # Check all dependencies are completed
            all_deps_done = True
            for dep_id in task.dependencies:
                dep_task = task_map.get(dep_id)
                if not dep_task or dep_task.status != TaskStatus.COMPLETED:
                    all_deps_done = False
                    break
            
            if all_deps_done:
                ready.append(task)
        
        # Sort by tie-breakers
        return self._sort_by_tie_breakers(ready)
    
    async def get_ready_tasks_async(self, project_id: str) -> List[Task]:
        """Async version of get_ready_tasks."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_ready_tasks, project_id
        )
    
    def get_next_task_dag(self, project_id: str) -> Optional[Task]:
        """Get the next task to execute from the DAG frontier.
        
        This is the DAG-aware version of get_next_task that respects
        dependencies and uses tie-breakers for selection.
        
        Args:
            project_id: Project to get next task for.
            
        Returns:
            The highest-priority ready task, or None if no tasks are ready.
        """
        ready = self.get_ready_tasks(project_id)
        return ready[0] if ready else None
    
    async def get_next_task_dag_async(self, project_id: str) -> Optional[Task]:
        """Async version of get_next_task_dag."""
        return await asyncio.get_event_loop().run_in_executor(
            None, self.get_next_task_dag, project_id
        )
    
    def _sort_by_tie_breakers(self, tasks: List[Task]) -> List[Task]:
        """Sort tasks by configured tie-breakers.
        
        Tie-breaker format: "field_direction" where direction is asc or desc.
        Special cases:
        - priority_desc: higher priority score first
        - sequence: alpha < beta < rc < ga
        """
        def sort_key(task: Task) -> Tuple:
            keys = []
            for tb in self._tie_breakers:
                if tb == "priority_desc":
                    # Higher priority score = more urgent
                    keys.append(-task.priority_score())
                elif tb == "due_date_asc":
                    # Earlier due date first, None last
                    keys.append(task.due_date or "9999-99-99")
                elif tb == "sequence":
                    # Sequence order: alpha=1, beta=2, rc=3, ga=4, None=0
                    seq_order = {"alpha": 1, "beta": 2, "rc": 3, "ga": 4}
                    keys.append(seq_order.get(task.sequence, 0) if task.sequence else 0)
                elif tb == "effort_asc":
                    # Lower effort first, None last
                    keys.append(task.effort if task.effort is not None else 999)
                elif tb == "value_desc":
                    # Higher value first, None last
                    keys.append(-(task.value if task.value is not None else 0))
                elif tb == "risk_asc":
                    # Lower risk first, None last
                    keys.append(task.risk if task.risk is not None else 999)
                elif tb == "created_at_asc":
                    keys.append(task.created_at)
            return tuple(keys)
        
        return sorted(tasks, key=sort_key)
    
    def get_dag_stats(self, project_id: str) -> Dict[str, Any]:
        """Get statistics about the project's task DAG.
        
        Args:
            project_id: Project to analyze.
            
        Returns:
            Dictionary with DAG statistics.
        """
        dag = self.build_dag(project_id)
        tasks = self.list_tasks(project_id)
        
        # Count by status
        status_counts = {}
        for task in tasks:
            status_counts[task.status.value] = status_counts.get(task.status.value, 0) + 1
        
        # Count by phase
        phase_counts = {}
        for task in tasks:
            phase_counts[task.phase.value] = phase_counts.get(task.phase.value, 0) + 1
        
        # Find critical path (longest path)
        try:
            critical_path = nx.dag_longest_path(dag)
        except nx.NetworkXError:
            critical_path = []
        
        # Get frontier (ready tasks)
        ready = self.get_ready_tasks(project_id)
        
        return {
            "project_id": project_id,
            "total_tasks": len(tasks),
            "total_edges": dag.number_of_edges(),
            "status_counts": status_counts,
            "phase_counts": phase_counts,
            "ready_count": len(ready),
            "ready_task_ids": [t.id for t in ready[:10]],
            "critical_path_length": len(critical_path),
            "critical_path": critical_path[:10],
            "is_acyclic": nx.is_directed_acyclic_graph(dag),
        }
    
    def export_dag_dot(self, project_id: str) -> str:
        """Export the DAG in DOT format for visualization.
        
        Args:
            project_id: Project to export.
            
        Returns:
            DOT format string.
        """
        dag = self.build_dag(project_id)
        
        lines = ["digraph TaskDAG {"]
        lines.append("  rankdir=LR;")
        lines.append("  node [shape=box];")
        
        for node_id in dag.nodes():
            task = dag.nodes[node_id].get("task")
            if task:
                label = f"{task.title[:30]}\\n[{task.status.value}]"
                color = {
                    TaskStatus.COMPLETED: "green",
                    TaskStatus.ACTIVE: "blue",
                    TaskStatus.RUNNING: "orange",
                    TaskStatus.FAILED: "red",
                }.get(task.status, "gray")
                lines.append(f'  "{node_id}" [label="{label}", color="{color}"];')
        
        for src, dst in dag.edges():
            lines.append(f'  "{src}" -> "{dst}";')
        
        lines.append("}")
        return "\n".join(lines)
    
    def set_tie_breakers(self, tie_breakers: List[str]) -> None:
        """Set the tie-breaker order for DAG frontier selection.
        
        Args:
            tie_breakers: List of tie-breaker names in priority order.
                Valid values: priority_desc, due_date_asc, sequence,
                effort_asc, value_desc, risk_asc, created_at_asc
        """
        self._tie_breakers = tie_breakers
        logger.info(f"Set tie-breakers: {tie_breakers}")
    
    def invalidate_dag(self) -> None:
        """Invalidate the cached DAG, forcing rebuild on next access."""
        self._dag = None
        self._dag_project_id = None
    
    # ==================== Blueprint Integration ====================
    
    def sync_blueprint(
        self,
        blueprint: Blueprint,
        project_id: Optional[str] = None,
        create_missing: bool = True,
        update_existing: bool = True,
    ) -> Dict[str, Any]:
        """Sync a Blueprint to the project, creating/updating tasks.
        
        Args:
            blueprint: Parsed Blueprint object.
            project_id: Target project ID. If None, creates a new project.
            create_missing: Create tasks that don't exist.
            update_existing: Update tasks that already exist.
            
        Returns:
            Dictionary with sync results (created, updated, skipped counts).
        """
        # Create or get project
        if project_id is None:
            project = self.create_project(
                name=blueprint.title,
                description=blueprint.overview or f"Project from Blueprint: {blueprint.title}",
                tags=blueprint.labels,
            )
            project_id = project.id
        else:
            project = self.get_project(project_id)
            if not project:
                raise ProjectNotFoundError(f"Project '{project_id}' not found", project_id)
        
        # Get existing tasks by blueprint_id
        existing_tasks = self.list_tasks(project_id)
        existing_by_blueprint = {t.blueprint_id: t for t in existing_tasks if t.blueprint_id}
        
        # Track results
        created = []
        updated = []
        skipped = []
        
        # Build ID mapping for dependencies
        id_mapping: Dict[str, str] = {}  # blueprint_id -> task_id
        for task in existing_tasks:
            if task.blueprint_id:
                id_mapping[task.blueprint_id] = task.id
        
        # First pass: create/update tasks (without dependencies)
        for item in blueprint.items:
            existing = existing_by_blueprint.get(item.id)
            
            if existing:
                if update_existing:
                    # Update existing task
                    self._update_task_from_blueprint_item(existing, item, blueprint)
                    self.storage.update_task(existing)
                    updated.append(item.id)
                    id_mapping[item.id] = existing.id
                else:
                    skipped.append(item.id)
                    id_mapping[item.id] = existing.id
            elif create_missing:
                # Create new task
                task = self._create_task_from_blueprint_item(item, blueprint, project_id)
                self.storage.create_task(task)
                created.append(item.id)
                id_mapping[item.id] = task.id
            else:
                skipped.append(item.id)
        
        # Second pass: resolve dependencies
        for item in blueprint.items:
            task_id = id_mapping.get(item.id)
            if not task_id:
                continue
            
            task = self.storage.get_task(task_id)
            if not task:
                continue
            
            # Resolve dependency IDs
            resolved_deps = []
            for dep_blueprint_id in item.depends_on:
                dep_task_id = id_mapping.get(dep_blueprint_id)
                if dep_task_id:
                    resolved_deps.append(dep_task_id)
                else:
                    logger.warning(f"Dependency {dep_blueprint_id} not found for task {item.id}")
            
            if resolved_deps != task.dependencies:
                task.dependencies = resolved_deps
                task.updated_at = datetime.utcnow().isoformat()
                self.storage.update_task(task)
        
        # Invalidate DAG cache
        self.invalidate_dag()
        
        result = {
            "project_id": project_id,
            "blueprint_title": blueprint.title,
            "created": created,
            "updated": updated,
            "skipped": skipped,
            "total_items": len(blueprint.items),
        }
        
        self._publish_event("blueprint_synced", result)
        logger.info(f"Synced blueprint '{blueprint.title}': {len(created)} created, {len(updated)} updated")
        
        return result
    
    def _create_task_from_blueprint_item(
        self,
        item: BlueprintItem,
        blueprint: Blueprint,
        project_id: str,
    ) -> Task:
        """Create a Task from a BlueprintItem."""
        now = datetime.utcnow().isoformat()
        
        # Convert priority string to int
        priority_map = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        priority = priority_map.get(item.priority.lower(), 2)
        
        return Task(
            id=self._generate_id(item.title),
            title=item.title,
            description=item.description,
            status=TaskStatus.ACTIVE,
            created_at=now,
            updated_at=now,
            priority=priority,
            project_id=project_id,
            parent_task_id=None,  # Will be set if parent_id is resolved
            tags=item.labels,
            dependencies=[],  # Will be resolved in second pass
            due_date=item.due_date,
            acceptance_criteria=item.acceptance_criteria,
            blueprint_id=item.id,
            blueprint_source=item.source_file,
            phase=TaskPhase.PENDING,
            effort=item.effort,
            value=item.value,
            risk=item.risk,
            sequence=item.sequence,
            agent_role=item.agent_role or blueprint.default_agent_role,
            required_tools=item.required_tools or blueprint.default_required_tools,
            skills=item.skills or blueprint.default_skills,
            parallelizable=item.parallelizable,
            batch=item.batch,
            recipe=item.recipe,
            assignees=item.assignees,
        )
    
    def _update_task_from_blueprint_item(
        self,
        task: Task,
        item: BlueprintItem,
        blueprint: Blueprint,
    ) -> None:
        """Update a Task from a BlueprintItem."""
        task.title = item.title
        task.description = item.description
        task.tags = item.labels
        task.due_date = item.due_date
        task.acceptance_criteria = item.acceptance_criteria
        task.effort = item.effort
        task.value = item.value
        task.risk = item.risk
        task.sequence = item.sequence
        task.agent_role = item.agent_role or blueprint.default_agent_role
        task.required_tools = item.required_tools or blueprint.default_required_tools
        task.skills = item.skills or blueprint.default_skills
        task.parallelizable = item.parallelizable
        task.batch = item.batch
        task.recipe = item.recipe
        task.assignees = item.assignees
        task.updated_at = datetime.utcnow().isoformat()
        
        # Convert priority string to int
        priority_map = {"critical": 0, "high": 1, "medium": 2, "low": 3}
        task.priority = priority_map.get(item.priority.lower(), 2)
    
    # ==================== Context and Integration ====================
    
    def add_project_context(
        self, 
        project_id: str, 
        content: str, 
        context_type: str = "notes",
        filename: Optional[str] = None
    ) -> Path:
        """Add context content to a project's context directory.
        
        Args:
            project_id: ID of the project
            content: Content to add
            context_type: Type of context (notes, docs, research, etc.)
            filename: Optional filename override
            
        Returns:
            Path to the created context file
            
        Raises:
            ProjectNotFoundError: If project doesn't exist
        """
        project = self.storage.get_project(project_id)
        if not project:
            raise ProjectNotFoundError(f"Project '{project_id}' not found", project_id)
        
        if not project.context_path:
            raise ProjectError("Project has no context path configured", project_id)
        
        # Create context file
        if not filename:
            timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
            filename = f"{context_type}_{timestamp}.md"
        
        context_file = project.context_path / filename
        
        # Write content with markdown context wrapper
        wrapped_content = f"# {context_type.title()}\n\n<context>\n{content}\n</context>\n"
        context_file.write_text(wrapped_content)
        
        logger.info(f"Added context to project {project_id}: {filename}")
        return context_file 