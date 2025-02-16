import os
from typing import Dict, List

import yaml


class DeclarativeMemory:
    def __init__(self, file_path: str = "notes/declarative_notes.yml"):
        self.file_path = file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self.notes: List[Dict[str, str]] = self.load_notes()

    def load_notes(self) -> List[Dict[str, str]]:
        try:
            with open(self.file_path) as file:
                return yaml.safe_load(file) or []
        except FileNotFoundError:
            return []

    def save_notes(self):
        with open(self.file_path, "w") as file:
            yaml.dump(self.notes, file)

    def add_note(self, category: str, content: str):
        # Check if the note already exists
        for note in self.notes:
            if note["category"] == category and note["content"] == content:
                return  # Note already exists, do nothing

        # If the note doesn't exist, add it
        self.notes.append({"category": category, "content": content})
        self.save_notes()

    def get_notes(self) -> List[Dict[str, str]]:
        return self.notes

    def clear_notes(self):
        self.notes = []
        self.save_notes()
