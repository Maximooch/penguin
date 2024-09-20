from typing import Optional, Dict, Any, List
from enum import Enum

class TaskStatus(Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    FAILED = "Failed"

class Task:
    def __init__(self, id: str, name: str, description: str, project_id: Optional[str] = None, parent_id: Optional[str] = None):
        self.id = id
        self.name = name
        self.description = description
        self.project_id = project_id
        self.parent_id = parent_id
        self.status = TaskStatus.NOT_STARTED
        self.progress = 0
        self.subtasks: List['Task'] = []  # Add this line

    def update_progress(self, progress: int) -> None:
        self.progress = max(0, min(100, progress))
        if self.progress == 100:
            self.status = TaskStatus.COMPLETED
        elif self.progress > 0:
            self.status = TaskStatus.IN_PROGRESS
        else:
            self.status = TaskStatus.NOT_STARTED

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "description": self.description,
            "project_id": self.project_id,
            "parent_id": self.parent_id,
            "status": self.status.value,
            "progress": self.progress,
            "subtasks": [subtask.to_dict() for subtask in self.subtasks]  # Add this line
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'Task':
       task = cls(
           id=data["id"],
           name=data["name"],
           description=data["description"],
           project_id=data.get("project_id"),
           parent_id=data.get("parent_id")
       )
       status_str = data.get("status", TaskStatus.NOT_STARTED.value)
       for status in TaskStatus:
           if status.value.lower() == status_str.lower():
               task.status = status
               break
       else:
           raise ValueError(f"Invalid TaskStatus: {status_str}")
       task.progress = data.get("progress", 0)
       task.subtasks = [cls.from_dict(subtask_data) for subtask_data in data.get("subtasks", [])]
       return task

    def add_subtask(self, subtask: 'Task'):
        self.subtasks.append(subtask)

    def __str__(self):
        return f"Task: {self.name} - {self.description} - Status: {self.status.value} - Progress: {self.progress}%"