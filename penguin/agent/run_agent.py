from typing import Callable, Generator, Tuple, Union
from .task import Task, TaskStatus
from .project import Project, ProjectStatus
from config import MAX_TASK_ITERATIONS, TASK_COMPLETION_PHRASE
import time
import logging
from chat import print_bordered_message, PENGUIN_COLOR, TOOL_COLOR

def run_agent(item: Union[Task, Project], chat_function: Callable, message_count: int) -> Generator[Tuple[int, int, str], None, Union[Task, Project]]:
    if isinstance(item, Task):
        goal = f"Complete the task: {item.name}\nDescription: {item.description}"
    elif isinstance(item, Project):
        goal = f"Complete the project: {item.name}\nDescription: {item.description}"
    else:
        raise ValueError(f"Unsupported item type: {type(item)}")

    iteration = 0
    while True:
        iteration += 1
        response, exit_continuation = chat_function(goal, message_count, current_iteration=iteration)
        
        yield iteration, -1, response  # -1 indicates no fixed max iterations

        if exit_continuation or TASK_COMPLETION_PHRASE in response:
            break

        goal = "Continue with the next step. If the task/project is completed, respond with '{TASK_COMPLETION_PHRASE}'."

    if isinstance(item, Task):
        item.status = TaskStatus.COMPLETED
    elif isinstance(item, Project):
        item.status = ProjectStatus.COMPLETED

    return item