from typing import List, Dict
import json
import os
from config import WORKSPACE_PATH

class TaskPlanner:
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.plans: List[Dict] = []
        self.current_plan_index = 0

    def add_plan(self, description: str, subtasks: List[str]):
        plan = {
            "description": description,
            "subtasks": [{"description": st, "completed": False} for st in subtasks]
        }
        self.plans.append(plan)

    def mark_subtask_complete(self, plan_index: int, subtask_index: int):
        self.plans[plan_index]["subtasks"][subtask_index]["completed"] = True

    def get_current_plan(self):
        return self.plans[self.current_plan_index] if self.plans else None

    def move_to_next_plan(self):
        if self.current_plan_index < len(self.plans) - 1:
            self.current_plan_index += 1
            return True
        return False

    def save_to_file(self):
        file_path = os.path.join(WORKSPACE_PATH, f"{self.task_name}_plan.json")
        with open(file_path, "w") as f:
            json.dump(self.plans, f, indent=2)

    def load_from_file(self):
        file_path = os.path.join(WORKSPACE_PATH, f"{self.task_name}_plan.json")
        try:
            with open(file_path, "r") as f:
                self.plans = json.load(f)
        except FileNotFoundError:
            pass