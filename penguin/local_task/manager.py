"""
Local Project/Task Manager

A system for managing projects and tasks locally with the following features:
- Projects and tasks stored in a projects_tasks.json file
- Each project has its own folder in the workspace
- Each project has a context folder for storing notes/documents/research
- Context content is stored in markdown files with <context>content</context> format
"""

import hashlib
import json
import logging
import shutil
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

from rich import box  # type: ignore
from rich.console import Console  # type: ignore
from rich.panel import Panel  # type: ignore
from rich.table import Table  # type: ignore
from rich.tree import Tree  # type: ignore

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)


try:
    from config import WORKSPACE_PATH, Config
except ImportError:
    WORKSPACE_PATH = (
        Path.cwd()
    )  # Default to current directory if no config, for testing

try:
    from utils.errors import error_handler
except ImportError:
    # Create a simple error handler for testing
    class SimpleErrorHandler:
        def log_error(self, error, context=None, fatal=False):
            print(f"Error: {str(error)}")
            if context:
                print(f"Context: {context}")

    error_handler = SimpleErrorHandler()


@dataclass
class Task:
    """
    Represents a task that can be independent or associated with a project.

    Attributes:
        id: Unique identifier for the task
        title: Name/title of the task
        description: Detailed description of what needs to be done
        status: Current state - active, completed, or archived
        created_at: ISO format timestamp of creation
        updated_at: ISO format timestamp of last update
        priority: Integer priority level (lower is higher priority)
        project_id: Optional ID of parent project (None if independent)
        tags: List of tag strings for categorization
        dependencies: List of task IDs that must be completed first
        due_date: Optional due date in ISO format
        progress: Task completion percentage (0-100)
        metadata: Additional task-specific metadata
        review_notes: Optional notes from human review
        reviewed_by: Optional name of reviewer
        reviewed_at: Optional ISO format timestamp of review
    """

    id: str
    title: str
    description: str
    status: str  # 'active', 'cancelled', 'failed', 'pending_review', 'completed', 'archived'
    created_at: str
    updated_at: str
    priority: int
    project_id: Optional[str] = None  # None means independent task
    tags: List[str] = field(default_factory=list)
    dependencies: List[str] = field(default_factory=list)
    due_date: Optional[str] = None
    progress: int = 0
    metadata: Dict = field(default_factory=dict)
    review_notes: Optional[str] = None
    reviewed_by: Optional[str] = None
    reviewed_at: Optional[str] = None

    def mark_pending_review(self, notes: str) -> None:
        """Mark task as pending human review"""
        self.status = "pending_review"
        self.updated_at = datetime.now().isoformat()
        self.review_notes = notes

    def approve(self, reviewer: str, notes: Optional[str] = None) -> None:
        """Approve task completion"""
        self.status = "completed"
        self.reviewed_by = reviewer
        self.reviewed_at = datetime.now().isoformat()
        if notes:
            self.review_notes = notes


@dataclass
class Project:
    """
    Represents a project containing tasks and context information.

    Attributes:
        id: Unique identifier for the project
        name: Project name
        description: Project description/details
        created_at: ISO format timestamp of creation
        updated_at: ISO format timestamp of last update
        tasks: Dictionary mapping task IDs to Task objects
        context_path: Path to project's context directory
    """

    id: str
    name: str
    description: str
    created_at: str
    updated_at: str
    tasks: Dict[str, Task]
    context_path: Path

    def to_dict(self) -> Dict:
        """Convert Project to a JSON-serializable dictionary."""
        data = asdict(self)
        # Convert Path to string for JSON serialization
        data["context_path"] = str(data["context_path"])
        return data

    @classmethod
    def from_dict(cls, data: Dict) -> "Project":
        """Create Project instance from a dictionary, converting string path back to Path."""
        data["context_path"] = Path(data["context_path"])
        return cls(**data)


class ProjectManager:
    """
    Manages projects and tasks within a workspace.

    Handles creation, deletion, updates and queries of projects and tasks.
    Maintains persistent storage in JSON format and manages project directories.
    """

    def __init__(self, workspace_root: Path):
        """
        Initialize ProjectManager with workspace directory.

        Args:
            workspace_root: Root directory for all projects and data
        """
        self.workspace_root = Path(workspace_root)
        self.projects_dir = self.workspace_root / "projects"
        self.data_file = self.workspace_root / "projects_and_tasks.json"
        self.workspace_file = self.workspace_root / "independent_tasks.json"
        self.console = Console()

        # Add debug logging
        logger.debug(f"Initializing ProjectManager with workspace: {workspace_root}")

        # Create necessary directories if they don't exist
        self.workspace_root.mkdir(parents=True, exist_ok=True)
        self.projects_dir.mkdir(parents=True, exist_ok=True)

        self.projects: Dict[str, Project] = {}
        self.independent_tasks: Dict[str, Task] = {}
        self._load_data()

        # Log loaded data
        logger.debug(
            f"Loaded {len(self.projects)} projects and {len(self.independent_tasks)} independent tasks"
        )

    def _generate_id(self, text: str) -> str:
        """
        Generate a short unique ID based on text content and current timestamp.

        Args:
            text: Input text to generate ID from

        Returns:
            8-character hexadecimal ID
        """
        content = f"{text}{datetime.now().isoformat()}"
        return hashlib.sha1(content.encode()).hexdigest()[:8]

    def create(
        self,
        name: str,
        description: str,
        project_name: Optional[str] = None,
        is_task: bool = False,
    ) -> Union[Project, Task]:
        """
        Create a new project or task.

        Args:
            name: Name of the project/task
            description: Description of the project/task
            project_name: If provided, creates a task under this project
            is_task: If True, creates an independent task even if project_name is None

        Returns:
            Project or Task instance
        """
        if project_name is not None:
            # Create a task under the specified project
            project = self._find_project_by_name(project_name)
            if not project:
                raise ValueError(f"Project {project_name} not found")
            return self._create_task(name, description, project.id)
        elif is_task:
            # Create an independent task
            return self._create_independent_task(name, description)
        else:
            # Create a project
            return self._create_project(name, description)

    def delete(self, name: str) -> None:
        """
        Delete a project or task by name.

        Args:
            name: Name of project/task to delete

        Raises:
            ValueError: If no project/task found with given name
        """
        # Try to find it as a project first
        project = self._find_project_by_name(name)
        if project:
            project_dir = self.projects_dir / project.name
            shutil.rmtree(project_dir)
            del self.projects[project.id]
            return

        # If not a project, try to find it as a task
        task = self._find_task_by_name(name)
        if task:
            if task.project_id:
                project = self.projects[task.project_id]
                del project.tasks[task.id]
                self._save_data()
            else:
                # Handle independent task deletion
                self._delete_independent_task(task.id)
            return

        raise ValueError(f"No project or task found with name: {name}")

    def complete(self, name: str) -> None:
        """
        Mark a project or task as completed.

        Args:
            name: Name of project/task to complete

        Raises:
            ValueError: If no project/task found with given name
        """
        task = self._find_task_by_name(name)
        if task:
            task.status = "completed"
            task.updated_at = datetime.now().isoformat()
            if task.project_id:
                self._save_data()
            else:
                self._save_independent_task(task)
            return

        project = self._find_project_by_name(name)
        if project:
            # Mark all tasks in project as completed
            for task in project.tasks.values():
                task.status = "completed"
                task.updated_at = datetime.now().isoformat()
            self._save_data()
            return

        raise ValueError(f"No project or task found with name: {name}")

    def status(self, name: Optional[str] = None) -> Dict:
        """
        Get status information for a specific item or overview of all items.

        Args:
            name: Optional name of project/task to get status for

        Returns:
            Dictionary containing status information

        Raises:
            ValueError: If name provided but no matching project/task found
        """
        if not name:
            return self._get_overall_status()

        project = self._find_project_by_name(name)
        if project:
            return self._get_project_status(project.id)

        task = self._find_task_by_name(name)
        if task:
            return self._get_task_status(task)

        raise ValueError(f"No project or task found with name: {name}")

    def update_status(self, name: str, description: str) -> None:
        """
        Update description/status of a project or task.

        Args:
            name: Name of project/task to update
            description: New description text

        Raises:
            ValueError: If no project/task found with given name
        """
        project = self._find_project_by_name(name)
        if project:
            project.description = description
            project.updated_at = datetime.now().isoformat()
            self._save_data()
            return

        task = self._find_task_by_name(name)
        if task:
            task.description = description
            task.updated_at = datetime.now().isoformat()
            self._save_data()
            return

        raise ValueError(f"No project or task found with name: {name}")

    def list(self, project_name: Optional[str] = None) -> List[Dict]:
        """
        List all tasks and optionally projects, or tasks under specific project.

        Args:
            project_name: Optional project name to list tasks for

        Returns:
            List of dictionaries containing item information

        Raises:
            ValueError: If project_name provided but not found
        """
        if project_name:
            project = self._find_project_by_name(project_name)
            if not project:
                raise ValueError(f"Project not found: {project_name}")
            return self._list_project_tasks(project.id)

        return self._list_all()

    def _list_all(self) -> List[Dict]:
        """
        List all projects and independent tasks.

        Returns:
            List of dictionaries containing basic info for all items
        """
        items = []

        # Add all projects
        for project in self.projects.values():
            items.append(
                {
                    "type": "project",
                    "id": project.id,
                    "name": project.name,
                    "description": project.description,
                    "status": "active",  # Projects could have their own status
                    "tasks_count": len(project.tasks),
                }
            )

        # Add all independent tasks
        for task in self.independent_tasks.values():
            items.append(
                {
                    "type": "task",
                    "id": task.id,
                    "name": task.title,
                    "description": task.description,
                    "status": task.status,
                }
            )

        return items

    def _find_project_by_name(self, name: str) -> Optional[Project]:
        """
        Find project by name (case-insensitive).

        Args:
            name: Project name to search for

        Returns:
            Project if found, None otherwise
        """
        name_lower = name.lower()
        return next(
            (p for p in self.projects.values() if p.name.lower() == name_lower), None
        )

    def _find_task_by_name(self, name: str) -> Optional[Task]:
        """
        Find task by name (case-insensitive).

        Args:
            name: Task name to search for

        Returns:
            Task if found, None otherwise
        """
        name_lower = name.lower()

        # Search in projects
        for project in self.projects.values():
            task = next(
                (t for t in project.tasks.values() if t.title.lower() == name_lower),
                None,
            )
            if task:
                return task

        # Search independent tasks
        return next(
            (
                t
                for t in self.independent_tasks.values()
                if t.title.lower() == name_lower
            ),
            None,
        )

    def _create_independent_task(self, name: str, description: str) -> Task:
        """
        Create a task not associated with any project.

        Args:
            name: Task name
            description: Task description

        Returns:
            New Task instance
        """
        task = Task(
            id=self._generate_id(name),
            title=name,
            description=description,
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            priority=1,
            project_id=None,
            tags=[],
            dependencies=[],
        )

        self.independent_tasks[task.id] = task
        self._save_data()
        return task

    def _create_project(self, name: str, description: str) -> Project:
        """
        Create a new project with directory structure.

        Args:
            name: Project name
            description: Project description

        Returns:
            New Project instance

        Raises:
            ValueError: If project with name already exists
        """
        project_id = self._generate_id(name)
        project_dir = self.projects_dir / name

        if project_dir.exists():
            raise ValueError(f"Project {name} already exists")

        # Create project directory structure
        project_dir.mkdir(parents=True)
        (project_dir / "context").mkdir()

        # Initialize project
        project = Project(
            id=project_id,
            name=name,
            description=description,
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            tasks={},
            context_path=project_dir / "context",
        )

        self.projects[project_id] = project
        self._save_data()
        return project

    def _create_task(self, name: str, description: str, project_id: str) -> Task:
        """
        Create a task associated with a project.

        Args:
            name: Task name
            description: Task description
            project_id: ID of parent project

        Returns:
            New Task instance

        Raises:
            ValueError: If project_id not found
        """
        project = self.projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        task = Task(
            id=self._generate_id(name),
            title=name,
            description=description,
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            priority=1,
            project_id=project_id,
            tags=[],
            dependencies=[],
        )

        project.tasks[task.id] = task
        self._save_data()
        return task

    def _save_data(self):
        """Save all projects and tasks to JSON file."""
        data = {
            "projects": {
                pid: {
                    **project.to_dict(),
                    "tasks": {tid: asdict(task) for tid, task in project.tasks.items()},
                }
                for pid, project in self.projects.items()
            },
            "independent_tasks": {
                tid: asdict(task) for tid, task in self.independent_tasks.items()
            },
        }

        with self.data_file.open("w") as f:
            json.dump(data, f, indent=2)

    def _load_data(self):
        """Load all projects and tasks from JSON file if it exists."""
        if not self.data_file.exists():
            return

        try:
            with self.data_file.open("r") as f:
                data = json.load(f)

                # Load projects
                self.projects = {}
                for pid, pdata in data.get("projects", {}).items():
                    # Convert tasks dict to Task objects
                    task_dict = pdata.pop("tasks", {})  # Remove tasks temporarily
                    tasks = {tid: Task(**tdata) for tid, tdata in task_dict.items()}

                    # Create project with proper Path object for context_path
                    context_path = pdata.pop(
                        "context_path"
                    )  # Remove and handle separately
                    project = Project(
                        **pdata, tasks=tasks, context_path=Path(context_path)
                    )
                    self.projects[pid] = project

                # Load independent tasks
                self.independent_tasks = {
                    tid: Task(**tdata)
                    for tid, tdata in data.get("independent_tasks", {}).items()
                }
        except (json.JSONDecodeError, FileNotFoundError) as e:
            logger.error(f"Error loading data: {str(e)}")
            # Initialize empty if loading fails
            self.projects = {}
            self.independent_tasks = {}

    def add_context(
        self, project_id: str, content: str, context_type: str = "notes"
    ) -> Path:
        """
        Add context content to project's context directory.

        Args:
            project_id: ID of project to add context to
            content: Content text to write
            context_type: Type of context (default: notes)

        Returns:
            Path to created context file

        Raises:
            ValueError: If project_id not found
        """
        project = self.projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        context_file = project.context_path / f"{context_type}_{timestamp}.md"

        with context_file.open("w") as f:
            f.write(content)

        return context_file

    def list_projects(self, verbose: bool = False) -> List[Dict]:
        """List all projects with their basic info"""
        project_list = []
        for project in self.projects.values():
            info = {
                "id": project.id,
                "name": project.name,
                "description": project.description,
                "active_tasks": len(
                    [t for t in project.tasks.values() if t.status == "active"]
                ),
                "total_tasks": len(project.tasks),
            }
            if verbose:
                info.update(
                    {
                        "created_at": project.created_at,
                        "updated_at": project.updated_at,
                        "context_path": str(project.context_path),
                    }
                )
            project_list.append(info)
        return project_list

    def get_project_status(self, project_id: str) -> Dict:
        """Get detailed status of a specific project"""
        project = self.projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        tasks_by_status = {"active": [], "completed": [], "archived": []}

        for task in project.tasks.values():
            tasks_by_status[task.status].append(
                {
                    "id": task.id,
                    "title": task.title,
                    "priority": task.priority,
                    "tags": task.tags,
                }
            )

        return {
            "id": project.id,
            "name": project.name,
            "description": project.description,
            "tasks": tasks_by_status,
            "created_at": project.created_at,
            "updated_at": project.updated_at,
        }

    def _list_project_tasks(self, project_id: str) -> List[Dict]:
        """List all tasks for a specific project"""
        project = self.projects.get(project_id)
        if not project:
            raise ValueError(f"Project {project_id} not found")

        return [
            {
                "id": task.id,
                "name": task.title,
                "description": task.description,
                "status": task.status,
                "priority": task.priority,
                "tags": task.tags,
                "created_at": task.created_at,
                "updated_at": task.updated_at,
            }
            for task in project.tasks.values()
        ]

    def _delete_independent_task(self, task_id: str) -> None:
        """Delete an independent task"""
        if task_id in self.independent_tasks:
            del self.independent_tasks[task_id]
            self._save_data()

    def display(self, project_name: Optional[str] = None) -> str:
        """
        Display projects and tasks in a beautiful hierarchical view.
        Returns a string representation instead of printing directly.

        Args:
            project_name: Optional name of specific project to display

        Returns:
            String containing the formatted display output
        """
        try:
            if project_name:
                return self._display_project(project_name)
            else:
                return self._display_all()
        except Exception as e:
            logger.error(f"Error in display: {str(e)}")
            return str(e)

    def _display_all(self) -> str:
        """Display all projects and tasks in a tree structure"""
        tree = Tree("📂 Workspace")

        # Add projects
        for project in self.projects.values():
            project_tree = tree.add(
                f"[bold blue]📁 {project.name}[/] [dim]({len(project.tasks)} tasks)[/]"
            )

            # Group tasks by status
            tasks_by_status = {"active": "🔵", "completed": "✅", "archived": "📦"}

            for status, emoji in tasks_by_status.items():
                tasks = [t for t in project.tasks.values() if t.status == status]
                if tasks:
                    status_tree = project_tree.add(f"{emoji} {status.title()}")
                    for task in sorted(tasks, key=lambda x: x.priority):
                        priority_indicator = (
                            "🔴"
                            if task.priority == 1
                            else "🟡"
                            if task.priority == 2
                            else "🟢"
                        )
                        task_text = f"{priority_indicator} {task.title}"
                        if task.tags:
                            task_text += (
                                f" [dim]{', '.join(f'#{tag}' for tag in task.tags)}[/]"
                            )
                        status_tree.add(task_text)

        # Add independent tasks
        if self.independent_tasks:
            independent_tree = tree.add("[bold yellow]📎 Independent Tasks[/]")
            for task in self.independent_tasks.values():
                priority_indicator = (
                    "🔴" if task.priority == 1 else "🟡" if task.priority == 2 else "🟢"
                )
                task_text = f"{priority_indicator} {task.title} [{task.status}]"
                if task.tags:
                    task_text += f" [dim]{', '.join(f'#{tag}' for tag in task.tags)}[/]"
                independent_tree.add(task_text)

        # Create a string representation
        console = Console(record=True)
        console.print(tree)
        return console.export_text()

    def _display_project(self, project_name: str) -> str:
        """Display detailed view of a specific project"""
        project = self._find_project_by_name(project_name)
        if not project:
            return f"Project '{project_name}' not found"

        console = Console(record=True)

        # Project header with better styling
        console.print(
            Panel(
                f"[bold blue]{project.name}[/]\n[dim]{project.description}[/]",
                title="[white]Project Details[/]",
                border_style="blue",
                padding=(1, 2),
            )
        )

        # Tasks table with improved styling
        table = Table(
            box=box.ROUNDED,
            title="[bold]Tasks Overview[/]",
            title_style="white",
            border_style="bright_blue",
            padding=(0, 1),
            collapse_padding=True,
        )

        # Column styling improvements
        table.add_column("Priority", justify="center", style="bold", width=8)
        table.add_column("Task", style="cyan", min_width=20, max_width=30)
        table.add_column("Status", justify="center", width=8)
        table.add_column("Progress", justify="right", width=10)
        table.add_column("Due Date", justify="center", width=12)
        table.add_column("Tags", min_width=15, max_width=25)
        table.add_column("Dependencies", min_width=15, max_width=25)

        for task in sorted(
            project.tasks.values(), key=lambda x: (x.status != "active", x.priority)
        ):
            priority_indicator = {
                1: "[red]🔴 HIGH[/]",
                2: "[yellow]🟡 MED[/]",
                3: "[green]🟢 LOW[/]",
            }.get(task.priority, "[dim]⚪ ---[/]")

            status_indicator = {
                "active": "[blue]● ACTIVE[/]",
                "completed": "[green]✓ DONE[/]",
                "archived": "[dim]◆ ARCH[/]",
            }.get(task.status, "?")

            # Format progress with color
            progress_value = task.progress if hasattr(task, "progress") else 0
            progress = f"[{'green' if progress_value >= 70 else 'yellow' if progress_value >= 30 else 'red'}]{progress_value}%[/]"

            # Format due date with color based on proximity
            if task.due_date:
                due = datetime.fromisoformat(task.due_date)
                days_left = (due - datetime.now()).days
                due_date = due.strftime("%Y-%m-%d")
                due_color = (
                    "green" if days_left > 7 else "yellow" if days_left > 2 else "red"
                )
                due_date = f"[{due_color}]{due_date}[/]"
            else:
                due_date = "[dim]---[/]"

            # Format task title with metadata
            task_title = (
                f"[bold]{task.title}[/]\n"
                f"[dim]{task.metadata.get('complexity', '---')} complexity[/]"
            )

            # Format tags with color
            tags = (
                ", ".join(f"[blue]#{tag}[/]" for tag in task.tags)
                if task.tags
                else "[dim]---[/]"
            )

            # Format dependencies with color
            dependent_tasks = []
            for dep_id in task.dependencies:
                dep_task = project.tasks.get(dep_id)
                if dep_task:
                    dependent_tasks.append(f"[cyan]{dep_task.title}[/]")
            dependencies = (
                ", ".join(dependent_tasks) if dependent_tasks else "[dim]---[/]"
            )

            table.add_row(
                priority_indicator,
                task_title,
                status_indicator,
                progress,
                due_date,
                tags,
                dependencies,
            )

        console.print(table)
        return console.export_text()

    def display_dependencies(self, task_name: str) -> None:
        """
        Display dependency graph for a specific task.

        Args:
            task_name: Name of the task to show dependencies for
        """
        task = self._find_task_by_name(task_name)
        if not task:
            self.console.print(f"[red]Task '{task_name}' not found[/]")
            return

        def build_dependency_tree(task_id: str, tree: Tree, seen: set = None) -> None:
            if seen is None:
                seen = set()

            if task_id in seen:
                tree.add("[red]Circular dependency detected![/]")
                return

            seen.add(task_id)
            current_task = None

            # Find task in projects or independent tasks
            if task.project_id:
                project = self.projects[task.project_id]
                current_task = project.tasks.get(task_id)
            else:
                current_task = self.independent_tasks.get(task_id)

            if not current_task:
                tree.add(f"[red]Missing task: {task_id}[/]")
                return

            # Add dependencies recursively
            for dep_id in current_task.dependencies:
                dep_tree = tree.add(f"[cyan]{current_task.title}[/]")
                build_dependency_tree(dep_id, dep_tree, seen.copy())

        # Create main tree
        tree = Tree(f"[bold blue]{task.title}[/] Dependencies")
        for dep_id in task.dependencies:
            build_dependency_tree(dep_id, tree)

        # Add metadata
        if task.metadata:
            meta_tree = tree.add("[yellow]Metadata[/]")
            for key, value in task.metadata.items():
                if isinstance(value, list):
                    value = ", ".join(value)
                meta_tree.add(f"[dim]{key}:[/] {value}")

        # Add progress info
        progress_tree = tree.add("[green]Progress[/]")
        progress_tree.add(f"Status: {task.status}")
        progress_tree.add(f"Progress: {task.progress}%")
        if task.due_date:
            due_date = datetime.fromisoformat(task.due_date).strftime("%Y-%m-%d")
            progress_tree.add(f"Due date: {due_date}")

        # Create a string representation
        console = Console(record=True)
        console.print(tree)
        return console.export_text()

    def visualize(self, project_name: str = None) -> None:
        """Generate visualizations for project(s)"""
        if project_name:
            projects = [self._find_project_by_name(project_name)]
        else:
            projects = list(self.projects.values())

        if not projects:
            self.console.print("[red]No projects found to visualize[/]")
            return

        # Generate visualizations
        dashboard_path = self.visualizer.create_dashboard(projects)
        gantt_path = self.visualizer.create_gantt_chart(projects)

        self.console.print("\n[green]Visualizations generated:[/]")
        self.console.print(f"Dashboard: {dashboard_path}")
        self.console.print(f"Gantt Chart: {gantt_path}")

        # Show terminal charts
        self.visualizer.show_terminal_charts(projects)

    def _get_overall_status(self) -> Dict:
        """Get overall status of all projects and tasks"""
        total_projects = len(self.projects)
        total_tasks = sum(len(p.tasks) for p in self.projects.values()) + len(
            self.independent_tasks
        )

        status_counts = {"active": 0, "completed": 0, "archived": 0}

        # Count project tasks
        for project in self.projects.values():
            for task in project.tasks.values():
                status_counts[task.status] += 1

        # Count independent tasks
        for task in self.independent_tasks.values():
            status_counts[task.status] += 1

        return {
            "total_projects": total_projects,
            "total_tasks": total_tasks,
            "tasks_by_status": status_counts,
            "completion_rate": (status_counts["completed"] / total_tasks * 100)
            if total_tasks > 0
            else 0,
        }

    def display_all(self) -> str:
        """Display all projects and tasks in a unified view."""
        try:
            return self._display_all()  # Call the existing internal method
        except Exception as e:
            logger.error(f"Error in display_all: {str(e)}")
            return str(e)

    def process_list_command(self) -> Dict[str, Any]:
        """Process the /list command and return formatted output"""
        try:
            output = self.display_all()
            return {
                "assistant_response": "Here's the current workspace overview:",
                "action_results": [
                    {"action": "list", "result": output, "status": "completed"}
                ],
            }
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "project_manager",
                    "method": "process_list_command",
                },
            )
            return {
                "assistant_response": f"Error displaying workspace: {str(e)}",
                "action_results": [],
            }

    def create_task(
        self, name: str, description: str, project_name: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Create a new task, either independent or in a project.

        Args:
            name: Name of the task
            description: Task description
            project_name: Optional project to add task to
        """
        try:
            if project_name:
                # Create task in project
                project = self._find_project_by_name(project_name)
                if not project:
                    raise ValueError(f"Project not found: {project_name}")
                # Use _create_project_task instead of _create_task
                task = self._create_project_task(project.id, name, description)
            else:
                # Create independent task
                task = self._create_independent_task(name, description)

            self._save_data()  # Force immediate save

            return {
                "action": "task_create",
                "result": f"Created task: {task.title}",
                "status": "completed",
            }
        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "project_manager",
                    "method": "create_task",
                    "name": name,
                    "description": description,
                },
            )
            return {
                "action": "task_create",
                "result": f"Error creating task: {str(e)}",
                "status": "error",
            }

    def complete_task(self, name: str) -> Dict[str, Any]:
        """Complete a task and return status information"""
        try:
            task = self._find_task_by_name(name)
            if not task:
                return {
                    "status": "error",
                    "result": f"No task found with name: {name}",
                    "metadata": None,
                }

            # Update task state
            task.status = "completed"
            task.updated_at = datetime.now().isoformat()

            # Save changes
            if task.project_id:
                self._save_data()
            else:
                self._save_independent_task(task)

            # Return completion status with metadata
            return {
                "status": "completed",
                "result": f"Task '{name}' completed successfully",
                "metadata": {
                    "task_id": task.id,
                    "project_id": task.project_id,
                    "continuous_mode": task.metadata.get("continuous_mode", False)
                    if task.metadata
                    else False,
                    "completion_time": datetime.now().isoformat(),
                },
            }

        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "project_manager",
                    "method": "complete_task",
                    "task_name": name,
                },
            )
            return {
                "status": "error",
                "result": f"Error completing task: {str(e)}",
                "metadata": None,
            }

    def _save_independent_tasks(self) -> None:
        """Save independent tasks to the workspace"""
        try:
            data = {
                "independent_tasks": {
                    task_id: self._task_to_dict(task)
                    for task_id, task in self.independent_tasks.items()
                }
            }

            with open(self.workspace_file, "w") as f:
                json.dump(data, f, indent=2)

        except Exception as e:
            error_handler.log_error(
                e,
                context={
                    "component": "project_manager",
                    "method": "_save_independent_tasks",
                },
            )
            raise

    def _task_to_dict(self, task: Task) -> Dict[str, Any]:
        """Convert a Task object to a dictionary for serialization"""
        return {
            "id": task.id,
            "title": task.title,
            "description": task.description,
            "status": task.status,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
            "priority": task.priority,
            "project_id": task.project_id,
            "tags": task.tags if hasattr(task, "tags") else [],
            "dependencies": task.dependencies if hasattr(task, "dependencies") else [],
            "due_date": task.due_date if hasattr(task, "due_date") else None,
            "progress": task.progress if hasattr(task, "progress") else 0,
            "metadata": task.metadata if hasattr(task, "metadata") else {},
            "review_notes": task.review_notes
            if hasattr(task, "review_notes")
            else None,
            "reviewed_by": task.reviewed_by if hasattr(task, "reviewed_by") else None,
            "reviewed_at": task.reviewed_at if hasattr(task, "reviewed_at") else None,
        }

    def create_project(self, name: str, description: str) -> Dict[str, Any]:
        """Create a new project"""
        try:
            project = self.create(name, description)
            self._save_data()  # Force immediate save

            return {
                "action": "project_create",
                "result": f"Created project: {project.name}",
                "status": "completed",
            }
        except Exception as e:
            return {
                "action": "project_create",
                "result": f"Error creating project: {str(e)}",
                "status": "error",
            }

    def get_project_status(self, name: str) -> Dict[str, Any]:
        """Get status of a project"""
        try:
            project = self._find_project_by_name(name)
            if not project:
                raise ValueError(f"Project not found: {name}")

            active_tasks = [t for t in project.tasks.values() if t.status == "active"]
            completed_tasks = [
                t for t in project.tasks.values() if t.status == "completed"
            ]

            result = (
                f"Project: {project.name}\n"
                f"Description: {project.description}\n"
                f"Tasks: active: {len(active_tasks)}, completed: {len(completed_tasks)}\n"
                f"Created: {project.created_at}\n"
                f"Last Updated: {project.updated_at}"
            )

            return {"action": "project_status", "result": result, "status": "completed"}
        except Exception as e:
            return {
                "action": "project_status",
                "result": f"Error getting project status: {str(e)}",
                "status": "error",
            }

    def get_task_status(self, name: str) -> Dict[str, Any]:
        """Get status of a task"""
        try:
            task = self._find_task_by_name(name)
            if not task:
                raise ValueError(f"Task not found: {name}")

            result = (
                f"Task: {task.title}\n"
                f"Status: {task.status}\n"
                f"Progress: {task.progress}%\n"
                f"Priority: {task.priority}\n"
            )

            if task.due_date:
                result += f"Due Date: {task.due_date}\n"
            if task.tags:
                result += f"Tags: {', '.join(task.tags)}\n"
            if task.project_id:
                project = self.projects[task.project_id]
                result += f"Project: {project.name}\n"

            return {"action": "task_status", "result": result, "status": "completed"}
        except Exception as e:
            return {
                "action": "task_status",
                "result": f"Error getting task status: {str(e)}",
                "status": "error",
            }

    async def get_next_task(self) -> Optional[Dict[str, Any]]:
        """
        Get next highest priority active task.

        Returns the active task with:
        1. Lowest priority number (highest priority)
        2. If same priority, most recently created
        """
        logger.debug("Getting next task...")

        # Collect all active tasks from both independent and project tasks
        active_tasks = []

        # Add independent tasks
        for task in self.independent_tasks.values():
            if task.status == "active":
                logger.debug(
                    f"Found active independent task: {task.title} (priority: {task.priority}, created: {task.created_at})"
                )
                active_tasks.append(task)

        # Add project tasks
        for project in self.projects.values():
            for task in project.tasks.values():
                if task.status == "active":
                    logger.debug(
                        f"Found active project task: {task.title} (priority: {task.priority}, created: {task.created_at})"
                    )
                    active_tasks.append(task)

        if active_tasks:
            # Sort by priority (lower number = higher priority)
            # For same priority, use newer tasks first (reverse chronological order)
            next_task = max(active_tasks, key=lambda t: (-t.priority, t.created_at))

            logger.debug(
                f"Selected next task: {next_task.title} (priority: {next_task.priority}, created: {next_task.created_at})"
            )

            return {
                "title": next_task.title,
                "description": next_task.description,
                "id": next_task.id,
                "project_id": next_task.project_id,
                "priority": next_task.priority,
                "metadata": next_task.metadata
                if hasattr(next_task, "metadata")
                else {},
                "status": next_task.status,
                "progress": next_task.progress if hasattr(next_task, "progress") else 0,
                "due_date": next_task.due_date
                if hasattr(next_task, "due_date")
                else None,
            }

        logger.debug("No active tasks found")
        return None

    def get_task_context(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get context for a task by ID"""
        # Search independent tasks
        if task_id in self.independent_tasks:
            task = self.independent_tasks[task_id]
            return task.metadata if hasattr(task, "metadata") else None

        # Search project tasks
        for project in self.projects.values():
            if task_id in project.tasks:
                task = project.tasks[task_id]
                return task.metadata if hasattr(task, "metadata") else None

        return None

    # Why is this code here?

    # async def _execute_task(self, name: str, description: str) -> None:
    #     """Execute a task with just description"""
    #     try:
    #         task_prompt = (
    #             f"Execute task: {name}\n"
    #             f"Description: {description}\n"  # Use description for task context
    #             f"Respond with {self.TASK_COMPLETION_PHRASE} when finished."
    #         )

    #         await self.core.process_input({"text": task_prompt})

    #     except Exception as e:
    #         logger.error(f"Error in task execution: {str(e)}")
    #         self._display_message(f"Error: {str(e)}", "error")

    def _create_project_task(
        self, project_id: str, name: str, description: str
    ) -> Task:
        """Create a task within a project"""
        task = Task(
            id=self._generate_id(name),
            title=name,
            description=description,
            status="active",
            created_at=datetime.now().isoformat(),
            updated_at=datetime.now().isoformat(),
            priority=1,
            project_id=project_id,
        )

        if project_id in self.projects:
            self.projects[project_id].tasks[task.id] = task
            self._save_data()
            return task

        raise ValueError(f"Project {project_id} not found")

    def get_project(self, name: str) -> Optional[Project]:
        """
        Get a project by name.

        Args:
            name: Name of the project to retrieve

        Returns:
            Project object if found, None otherwise
        """
        try:
            return self._find_project_by_name(name)
        except ValueError:
            return None
