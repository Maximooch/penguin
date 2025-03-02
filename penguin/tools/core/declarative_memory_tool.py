import logging
import os

from penguin.memory.declarative_memory import DeclarativeMemory

logger = logging.getLogger(__name__)


class DeclarativeMemoryTool:
    def __init__(self):
        try:
            base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            file_path = os.path.join(base_dir, "notes", "declarative_notes.yml")
            logger.info(f"Initializing DeclarativeMemory with file path: {file_path}")
            self.declarative_memory = DeclarativeMemory(file_path)
        except Exception as e:
            logger.error(f"Error initializing DeclarativeMemory: {str(e)}")
            raise

    def add_note(self, category: str, content: str) -> str:
        try:
            self.declarative_memory.add_note(category, content)
            return f"Added note to {category}: {content}"
        except Exception as e:
            error_msg = f"Error adding note: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def get_notes(self) -> list:
        try:
            notes = self.declarative_memory.get_notes()
            logger.debug(f"Retrieved notes from DeclarativeMemory: {notes}")
            return notes
        except Exception as e:
            logger.error(f"Error getting notes: {str(e)}")
            return []
