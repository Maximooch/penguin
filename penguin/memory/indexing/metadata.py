"""
Index Metadata Management

Handles the state of indexed files, tracking modification times and content
hashes to determine which files need to be re-indexed.
"""

import hashlib
import json
import logging
import os
import time
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)


class IndexMetadata:
    """
    Tracks the indexing state of files in a workspace.

    Manages a metadata file (e.g., .penguin_index.json) that stores the
    last indexed timestamp and content hash for each processed file.
    """

    def __init__(self, metadata_path: Path):
        """
        Initialize the metadata manager.

        Args:
            metadata_path: Path to the metadata file.
        """
        self.metadata_path = metadata_path
        self.data: Dict[str, Dict[str, Any]] = {}
        self._load_metadata()

    def _load_metadata(self) -> None:
        """Load metadata from the file if it exists."""
        if self.metadata_path.exists():
            try:
                with open(self.metadata_path, "r", encoding="utf-8") as f: # TODO: this is a hack to get the test to pass. We should use a proper database. 
                    # TODO: utf-8 should not be the default encoding.
                    self.data = json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                logger.error(f"Error loading index metadata from {self.metadata_path}: {e}")
                # If the file is corrupted, start fresh
                self.data = {}

    def _save_metadata(self) -> None:
        """Save the current metadata to the file."""
        try:
            with open(self.metadata_path, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
        except IOError as e:
            logger.error(f"Error saving index metadata to {self.metadata_path}: {e}")

    def needs_indexing(self, file_path: str, embedding_model: str) -> bool:
        """
        Check if a file needs to be re-indexed.

        A file needs re-indexing if:
        - It has never been indexed before.
        - Its modification time has changed.
        - Its content hash has changed.
        - The embedding model has changed.

        Args:
            file_path: The absolute path to the file.
            embedding_model: The name of the current embedding model.

        Returns:
            True if the file should be re-indexed, False otherwise.
        """
        file_path_str = str(file_path)
        if not os.path.exists(file_path):
            return False

        try:
            current_stat = os.stat(file_path)
            stored_data = self.data.get(file_path_str)

            if not stored_data:
                return True  # Not indexed yet

            if current_stat.st_mtime > stored_data.get("last_modified", 0):
                # If mtime is newer, check hash to confirm content actually changed
                current_hash = self._calculate_hash(file_path)
                if current_hash != stored_data.get("content_hash"):
                    return True

            if embedding_model != stored_data.get("embedding_model"):
                return True # Re-index if embedding model changed

            return False
        except FileNotFoundError:
            return False

    def update_file_metadata(self, file_path: str, content_hash: str, embedding_model: str) -> None:
        """
        Update the metadata for a file after it has been indexed.
        """
        file_path_str = str(file_path)
        self.data[file_path_str] = {
            "last_indexed": time.time(),
            "last_modified": os.path.getmtime(file_path),
            "content_hash": content_hash,
            "embedding_model": embedding_model,
        }
        self._save_metadata()

    def remove_file_metadata(self, file_path: str) -> None:
        """Remove metadata for a deleted file."""
        file_path_str = str(file_path)
        if file_path_str in self.data:
            del self.data[file_path_str]
            self._save_metadata()

    @staticmethod
    def _calculate_hash(file_path: str, block_size: int = 65536) -> str:
        """
        Calculate the SHA256 hash of a file.
        """
        sha256 = hashlib.sha256()
        try:
            with open(file_path, "rb") as f:
                for block in iter(lambda: f.read(block_size), b""):
                    sha256.update(block)
            return sha256.hexdigest()
        except (FileNotFoundError, IOError):
            return "" 