from typing import List, Optional
import logging
from .task import Task, TaskStatus

class TaskManager:
    def __init__(self, logger: logging.Logger):
        self.tasks: List[Task] = []
        self.logger = logger

    def create_task(self, description: str) -> Task:
        task = Task(description, self.logger)
        self.tasks.append(task)
        return task

    def run_task(self, task: Task, chat_function: callable) -> None:
        task.run(chat_function)

    def get_task_board(self) -> str:
        header = "| Task Description | Status | Progress |"
        separator = "|-----------------|--------|----------|"
        rows = [header, separator]
        
        for task in self.tasks:
            row = f"| {task.description[:15]:<15} | {task.status.value:<6} | {task.progress:>3}%     |"
            rows.append(row)
        
        return "\n".join(rows)

    def get_task_by_description(self, description: str) -> Optional[Task]:
        for task in self.tasks:
            if task.description == description:
                return task
        return None

    def remove_task(self, task: Task) -> None:
        if task in self.tasks:
            self.tasks.remove(task)

    def clear_completed_tasks(self) -> None:
        # TODO: Add a check to see if the task is still running, if it is, don't remove it 
        # TODO: once task is completed, archive it instead of removing it
        self.tasks = [task for task in self.tasks if task.status != TaskStatus.COMPLETED]