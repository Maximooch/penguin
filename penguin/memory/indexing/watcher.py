"""
File System Watcher

Monitors directories for file changes and triggers re-indexing events.
Uses the `watchdog` library for efficient, OS-native file system event handling.
"""

import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, List

from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

if TYPE_CHECKING:
    from .incremental import IncrementalIndexer

logger = logging.getLogger(__name__)


class IndexingEventHandler(FileSystemEventHandler):
    """Handles file system events and triggers the indexer."""

    def __init__(self, indexer: "IncrementalIndexer"):
        self.indexer = indexer

    def on_modified(self, event):
        if not event.is_directory:
            logger.debug(f"File modified: {event.src_path}")
            self.indexer.add_to_queue(event.src_path)

    def on_created(self, event):
        if not event.is_directory:
            logger.debug(f"File created: {event.src_path}")
            self.indexer.add_to_queue(event.src_path)

    def on_deleted(self, event):
        if not event.is_directory:
            logger.debug(f"File deleted: {event.src_path}")
            self.indexer.remove_from_index(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            logger.debug(f"File moved: {event.src_path} to {event.dest_path}")
            self.indexer.remove_from_index(event.src_path)
            self.indexer.add_to_queue(event.dest_path)


class FileSystemWatcher:
    """
    Watches specified directories for file changes and notifies an indexer.
    """

    def __init__(self, directories: List[str], indexer: "IncrementalIndexer"):
        self.directories = [Path(d).resolve() for d in directories]
        self.indexer = indexer
        self.observer = Observer()

    def start(self):
        """Start watching the configured directories."""
        if not self.directories:
            logger.warning("No directories to watch.")
            return

        event_handler = IndexingEventHandler(self.indexer)
        for directory in self.directories:
            if not directory.exists() or not directory.is_dir():
                logger.warning(f"Watch directory not found or not a directory: {directory}")
                continue
            
            self.observer.schedule(event_handler, str(directory), recursive=True)
            logger.info(f"Watching for file changes in: {directory}")

        if not self.observer.emitters:
            logger.error("Could not start watcher, no valid directories found.")
            return

        self.observer.start()

    def stop(self):
        """Stop watching for file changes."""
        if self.observer.is_alive():
            self.observer.stop()
            self.observer.join()
            logger.info("File system watcher stopped.") 