import json
import os
import uuid
from typing import List, Optional, Dict, Any
from .task import Task, TaskStatus
from .project import Project, ProjectStatus
import logging
from config import WORKSPACE_PATH

logger = logging.getLogger(__name__)

class TaskManager:
    def __init__(self, logger: logging.Logger):
        self.tasks: Dict[str, Task] = {}
        self.projects: Dict[str, Project] = {}
        self.logger = logger
        self.tasks_folder = os.path.join(WORKSPACE_PATH, "tasks")
        if not os.path.exists(self.tasks_folder):
            os.makedirs(self.tasks_folder)
        self.current_project: Optional[Project] = None
        self.load_tasks()

    def create_task(self, name: str, description: str, project_id: Optional[str] = None, parent_id: Optional[str] = None) -> Task:
        task_id = str(uuid.uuid4())
        task = Task(task_id, name, description, project_id, parent_id)
        self.tasks[task_id] = task
        if project_id and project_id in self.projects:
            self.projects[project_id].add_task(task)
        elif self.current_project:
            self.current_project.add_task(task)
            task.project_id = self.current_project.id
        return task

    def create_project(self, name: str, description: str) -> Project:
        project_id = str(uuid.uuid4())
        project = Project(project_id, name, description, self.logger)
        self.projects[project_id] = project
        self.set_current_project(project)
        return project

    def get_task(self, task_id: str) -> Optional[Task]:
        return self.tasks.get(task_id)

    def add_task_to_project(self, project: Project, task: Task):
        project.add_task(task)
        task.project_id = project.id
        # Ensure to save tasks after modifying
        self.save_tasks()

    def get_project(self, project_id: str) -> Optional[Project]:
        return self.projects.get(project_id)

    def update_task(self, task_id: str, progress: int) -> None:
        task = self.get_task(task_id)
        if task:
            task.update_progress(progress)
            self.save_tasks()

    # TODO: a much more efficient way to do this would be to use a database
    # TODO: and to have a many-to-one relationship between tasks and projects
    # TODO: a much nicer way to visualize this. Maybe a tree structure? Maybe a graph? Maybe a matrix? Or maybe even something on a website that's easy to use?
    def get_task_board(self) -> str:
        header = "| Task ID | Task Name | Description | Status | Progress | Project | Parent Task |"
        separator = "|---------|-----------|-------------|--------|----------|---------|-------------|"
        rows = [header, separator]
        
        for task in self.tasks.values():
            project_name = self.projects[task.project_id].name if task.project_id else "N/A"
            parent_task_name = self.tasks[task.parent_id].name if task.parent_id else "N/A"
            task_str = f"| {task.id[:8]} | {task.name[:10]:10} | {task.description[:11]:11} | {task.status.value:6} | {task.progress:3}% | {project_name[:7]:7} | {parent_task_name[:11]:11} |"
            rows.append(task_str)
        
        return "\n".join(rows)

    def _format_table(self, headers: List[str], rows: List[List[str]]) -> str:
        """Helper method to format tables with dynamic column widths"""
        # Calculate column widths based on headers and content
        widths = [len(h) for h in headers]
        for row in rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(str(cell)))

        # Create format string for rows
        fmt = " | ".join(f"{{:<{w}}}" for w in widths)
        separator = "-+-".join("-" * w for w in widths)

        # Format table
        lines = [fmt.format(*headers), separator]
        for row in rows:
            lines.append(fmt.format(*row))

        return "\n".join(lines)

    def get_project_board(self) -> str:
        """Get a formatted list of all projects"""
        if not self.projects:
            return "No projects found"
            
        headers = ["ID", "Name", "Description", "Status", "Progress", "Tasks"]
        rows = []
        
        for project in self.projects.values():
            task_count = len(project.task_ids)
            rows.append([
                project.id[:4] + "…",
                project.name[:20],
                project.description[:20] + "…" if len(project.description) > 20 else project.description,
                project.status.value,
                f"{project.progress}%",
                str(task_count)
            ])
        
        return self._format_table(headers, rows)

    def save_tasks(self) -> None:
        data = {
            "tasks": [task.to_dict() for task in self.tasks.values()],
            "projects": [project.to_dict() for project in self.projects.values()]
        }
        file_path = os.path.join(self.tasks_folder, "tasks_and_projects.json")
        try:
            with open(file_path, "w") as f:
                json.dump(data, f, indent=2)
            self.logger.info(f"Tasks and projects saved to {file_path}")
        except Exception as e:
            self.logger.error(f"Error saving tasks and projects: {str(e)}")

    def load_tasks(self) -> None:
        file_path = os.path.join(self.tasks_folder, "tasks_and_projects.json")
        try:
            if os.path.exists(file_path):
                with open(file_path, "r") as f:
                    data = json.load(f)
                
                self.tasks = {task_data["id"]: Task.from_dict(task_data) for task_data in data.get("tasks", [])}
                self.projects = {project_data["id"]: Project.from_dict(project_data, self.logger) for project_data in data.get("projects", [])}

                # Link tasks to projects
                for task in self.tasks.values():
                    if task.project_id and task.project_id in self.projects:
                        self.projects[task.project_id].add_task(task)

            self.logger.info(f"Tasks and projects loaded from {file_path}")
        except Exception as e:
            self.logger.error(f"Error loading tasks and projects: {str(e)}")

    # Compatibility methods
    def get_current_task(self) -> Optional[Task]:
        # For compatibility, return the first task of the current project
        if self.current_project and self.current_project.task_ids:
            return self.tasks.get(self.current_project.task_ids[0])
        return None

    def set_current_task(self, task: Task) -> None:
        # For compatibility, we don't need to do anything here
        pass

    def get_current_project(self) -> Optional[Project]:
        return self.current_project

    def set_current_project(self, project: Project) -> None:
        self.current_project = project

    def get_task_by_name(self, name: str) -> Optional[Task]:
        for task in self.tasks.values():
            if task.name.lower() == name.lower():
                return task
        return None

    def get_project_by_name(self, name: str) -> Optional[Project]:
        """Get project by name"""
        for project in self.projects.values():
            if project.name.lower() == name.lower():
                # logger.debug(f"Found project: {project.name}, Attributes: {vars(project)}")
                return project
        # logger.debug(f"Project not found: {name}")
        return None
    
    def get_project_details(self, project_name: str) -> str:
        """Get detailed status of a project"""
        project = self.get_project_by_name(project_name)
        if not project:
            raise ValueError(f"Project not found: {project_name}")
        
        details = [
            f"Project: {project.name}",
            f"Description: {project.description}",
            f"Status: {project.status.value}",
            f"Progress: {project.progress}%",
            "\nTasks:"
        ]
        
        for task_id in project.task_ids:
            task = self.tasks.get(task_id)
            if task:
                details.append(f"  - {task.name}: {task.status.value} ({task.progress}%)")
        
        return "\n".join(details)

    def remove_task(self, task: Task) -> None:
        if task.id in self.tasks:
            del self.tasks[task.id]
        if task.project_id and task.project_id in self.projects:
            self.projects[task.project_id].remove_task(task.id)

    def clear_completed_tasks(self) -> None:
        completed_task_ids = [task_id for task_id, task in self.tasks.items() if task.status == TaskStatus.COMPLETED]
        for task_id in completed_task_ids:
            task = self.tasks[task_id]
            self.remove_task(task)

    def complete_task(self, task_name: str) -> str:
        task = self.get_task_by_name(task_name)
        if task:
            task.status = TaskStatus.COMPLETED
            task.progress = 100
            self.save_tasks()
            return f"Task '{task_name}' marked as complete."
        else:
            return f"Task not found: {task_name}"

    def add_subtask(self, parent_task_name: str, subtask_name: str, subtask_description: str) -> Optional[Task]:
        parent_task = self.get_task_by_name(parent_task_name)
        if parent_task:
            subtask = self.create_task(subtask_name, subtask_description, parent_task.project_id, parent_task.id)
            return subtask
        return None

    def run_task(self, task: Task, chat_function: Any, message_count: int):
        from agent.run_agent import run_agent
        try:
            for progress in run_agent(task, chat_function, message_count):
                self.logger.info(f"Task progress: {progress}")
                # TODO: Here you could implement real-time updates to a UI or notification system
                yield progress
        except Exception as e:
            self.logger.error(f"Error running task {task.name}: {str(e)}")
            task.status = TaskStatus.FAILED
        finally:
            self.save_tasks()

    def analyze_workflow(self) -> Dict[str, Any]:
        # This is a placeholder for workflow analysis
        analysis = {
            "average_task_duration": self._calculate_average_task_duration(),
            "completion_rate": self._calculate_completion_rate(),
            "bottlenecks": self._identify_bottlenecks()
        }
        self.logger.info(f"Workflow analysis completed: {analysis}")
        return analysis

    def _calculate_average_task_duration(self) -> float:
        # Placeholder implementation
        return 0.0

    def _calculate_completion_rate(self) -> float:
        total_tasks = len(self.tasks)
        completed_tasks = len([task for task in self.tasks.values() if task.status == TaskStatus.COMPLETED])
        return completed_tasks / total_tasks if total_tasks > 0 else 0

    def _identify_bottlenecks(self) -> List[str]:
        # Placeholder implementation
        return []

    def update_project_status(self, project_name: str, status: ProjectStatus) -> str:
           project = self.get_project_by_name(project_name)
           if project:
               project.status = status
               self.save_tasks()
               return f"Project updated: {project}"
           return f"Project not found: {project_name}"

    def complete_project(self, project_name: str) -> str:
      project = self.get_project_by_name(project_name)
      if project:
          project.status = ProjectStatus.COMPLETED
          project.progress = 100
          self.save_tasks()  # Save changes
          return f"Project completed: {project}"
      return f"Project not found: {project_name}"

    # def complete_project(self, project_name: str) -> str:
    #        return self.update_project_status(project_name, ProjectStatus.COMPLETED)

    # def update_project_status(self, project_name: str, status: TaskStatus) -> str:
    #     project = self.get_project_by_name(project_name)
    #     if project:
    #         project.status = status
    #         self.save_tasks()
    #         return f"Project updated: {project}"
    #     return f"Project not found: {project_name}"

    # def complete_project(self, project_name: str) -> str:
    #   project = self.get_project_by_name(project_name)
    #   if project:
    #       project.status = TaskStatus.COMPLETED
    #       project.progress = 100
    #       self.save_tasks()
    #       return f"Project completed: {project}"
    #   return f"Project not found: {project_name}"

    def get_task_details(self, task_name: str) -> str:
        """Get detailed status of a task"""
        task = self.get_task_by_name(task_name)
        if not task:
            raise ValueError(f"Task not found: {task_name}")
        
        details = [
            f"Task: {task.name}",
            f"Description: {task.description}",
            f"Status: {task.status.value}",
            f"Progress: {task.progress}%"
        ]
        
        if task.project_id:
            project = self.projects.get(task.project_id)
            if project:
                details.append(f"Project: {project.name}")
            
        if task.subtasks:
            details.append("Subtasks:")
            for subtask in task.subtasks:
                details.append(f"  - {subtask.name}: {subtask.status.value} ({subtask.progress}%)")
            
        return "\n".join(details)