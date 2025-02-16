import os
from datetime import datetime
from typing import Any, Dict, List

import yaml


class SummaryNotes:
    def __init__(self, file_path: str = "notes/summary_notes.yml"):
        self.file_path = file_path
        os.makedirs(os.path.dirname(self.file_path), exist_ok=True)
        self.summaries: List[Dict[str, Any]] = self.load_summaries()

    def load_summaries(self) -> List[Dict[str, Any]]:
        """Load summaries from the file."""
        try:
            with open(self.file_path) as file:
                return yaml.safe_load(file) or []
        except FileNotFoundError:
            return []

    def save_summaries(self):
        """Save summaries to the file."""
        with open(self.file_path, "w") as file:
            yaml.dump(self.summaries, file)

    def add_summary(self, category: str, content: str):
        """Add a new summary to the list and save it."""
        summary = {
            "timestamp": datetime.now().isoformat(),
            "category": category,
            "content": content,
        }

        # Check for duplicate content using any() for efficiency
        if not any(
            s["category"] == category and s["content"] == content
            for s in self.summaries
        ):
            self.summaries.append(summary)
            self.save_summaries()

    def get_summaries(self) -> List[Dict[str, Any]]:
        """Retrieve all stored summaries."""
        return self.summaries

    def clear_summaries(self):
        """Clear all stored summaries."""
        self.summaries = []
        self.save_summaries()
