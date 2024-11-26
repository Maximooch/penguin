from typing import List, Dict, Any, Optional
from .task import Task
import logging
from enum import Enum

class ProjectStatus(Enum):
    NOT_STARTED = "Not_Started"
    IN_PROGRESS = "In_Progress"
    COMPLETED = "Completed"


class Project:
    def __init__(self, id: str, name: str, description: str, logger: logging.Logger):
        self.id = id
        self.name = name
        self.description = description
        self.task_ids: List[str] = []
        self.status = ProjectStatus.NOT_STARTED  # Use ProjectStatus here
        self.progress = 0
        self.logger = logger

    def add_task(self, task: Task):
        self.task_ids.append(task.id)
        self.logger.info(f"Task {task.name} added to project {self.name}")

    def remove_task(self, task_id: str) -> None:
        if task_id in self.task_ids:
            self.task_ids.remove(task_id)

    def get_task_ids(self) -> List[str]:
        return self.task_ids

    def update_progress(self) -> None:
        # This method should be called by TaskManager after updating tasks
        if not self.task_ids:
            self.progress = 0.0
            self.status = ProjectStatus.NOT_STARTED
            return

        total_progress = sum(task.progress for task in self.get_tasks())
        self.progress = total_progress / len(self.task_ids)

        if self.progress == 100:
            self.status = ProjectStatus.COMPLETED
        elif self.progress > 0:
            self.status = ProjectStatus.IN_PROGRESS
        else:
            self.status = ProjectStatus.NOT_STARTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "task_ids": self.task_ids,
            "status": self.status.value,  # Serialize status as its value
            "progress": self.progress,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any], logger: logging.Logger) -> 'Project':
       project = cls(
           id=data["id"],
           name=data["name"],
           description=data["description"],
           logger=logger
       )
       project.task_ids = data.get("task_ids", [])
       status_str = data.get("status", ProjectStatus.NOT_STARTED.value)
       for status in ProjectStatus:
           if status.value.lower() == status_str.lower():
               project.status = status
               break
       else:
           raise ValueError(f"Invalid ProjectStatus: {status_str}")
       project.progress = data.get("progress", 0)
       return project

    def __str__(self):
        return f"Project: {self.name} - {self.description} - Status: {self.status.value} - Progress: {self.progress:.2f}%"

    def get_tasks(self, task_manager) -> List[Task]:
        return [task_manager.get_task_by_id(task_id) for task_id in self.task_ids]

    def update_status(self, status: ProjectStatus) -> None:
        """Update project status"""
        self.status = status
        if status == ProjectStatus.COMPLETED:
            self.progress = 100
        elif status == ProjectStatus.NOT_STARTED:
            self.progress = 0

    def calculate_progress(self, task_manager) -> float:
        """Calculate project progress based on tasks"""
        if not self.task_ids:
            return 0.0
        
        total_progress = 0
        valid_tasks = 0
        
        for task_id in self.task_ids:
            task = task_manager.tasks.get(task_id)
            if task:
                total_progress += task.progress
                valid_tasks += 1
        
        return total_progress / valid_tasks if valid_tasks > 0 else 0.0

