from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.layout import Layout
from enum import Enum
import random

class TaskStatus(Enum):
    NOT_STARTED = "Not Started"
    IN_PROGRESS = "In Progress"
    COMPLETED = "Completed"
    FAILED = "Failed"

class Task:
    def __init__(self, description):
        self.description = description
        self.status = TaskStatus.NOT_STARTED
        self.progress = 0

class TaskManager:
    def __init__(self):
        self.tasks = []

    def add_task(self, description):
        self.tasks.append(Task(description))

    def update_task_status(self, index, status, progress):
        if 0 <= index < len(self.tasks):
            self.tasks[index].status = status
            self.tasks[index].progress = progress

    def get_task_board(self):
        table = Table(title="Task Board")
        table.add_column("ID", style="cyan", no_wrap=True)
        table.add_column("Description", style="magenta")
        table.add_column("Status", style="green")
        table.add_column("Progress", style="yellow")

        for i, task in enumerate(self.tasks):
            table.add_row(
                str(i + 1),
                task.description,
                task.status.value,
                f"{task.progress}%"
            )

        return table

def get_chatbox():
    chat_history = [
        "User: Can you create a new task for implementing user authentication?",
        "Assistant: Certainly! I've added a new task for implementing user authentication to the task board.",
        "User: What's the status of the database schema design task?",
        "Assistant: The database schema design task is currently In Progress with 45% completion.",
    ]
    chat_content = "\n".join(chat_history)
    return Panel(chat_content, title="Chat", border_style="blue")

def main():
    console = Console()
    task_manager = TaskManager()

    # Add some sample tasks
    tasks = [
        "Implement user authentication",
        "Design database schema",
        "Create API endpoints",
        "Write unit tests",
        "Set up CI/CD pipeline"
    ]

    for task in tasks:
        task_manager.add_task(task)

    # Simulate some progress
    for i in range(len(task_manager.tasks)):
        status = random.choice(list(TaskStatus))
        progress = random.randint(0, 100)
        task_manager.update_task_status(i, status, progress)

    # Create layout
    layout = Layout()
    layout.split_column(
        Layout(name="upper"),
        Layout(name="lower")
    )
    layout["upper"].update(task_manager.get_task_board())
    layout["lower"].update(get_chatbox())

    # Display the task board and chatbox
    console.print(layout)

if __name__ == "__main__":
    main()