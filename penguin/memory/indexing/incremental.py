"""
Incremental Indexer

Orchestrates the process of scanning directories, processing files,
and adding them to the memory provider.
"""

import asyncio
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

from penguin.memory.providers.base import MemoryProvider
from .metadata import IndexMetadata
from .processors import (
    ContentProcessor,
    GenericTextProcessor,
    MarkdownProcessor,
    PythonCodeProcessor,
)

logger = logging.getLogger(__name__)


class IncrementalIndexer:
    """
    Efficiently indexes files in a workspace by processing only new or
    changed files.
    """

    def __init__(self, provider: MemoryProvider, config: Dict[str, Any]):
        self.provider = provider
        self.config = config
        self.workspace_path = Path(config.get("workspace_path", ".")).resolve()
        
        # Initialize metadata manager
        metadata_file = self.workspace_path / ".penguin_index.json"
        self.metadata = IndexMetadata(metadata_file)
        
        # Initialize content processors (with priority)
        self.processors: List[ContentProcessor] = [
            PythonCodeProcessor(),
            MarkdownProcessor(),
            GenericTextProcessor(),  # Fallback
        ]

        self._queue = asyncio.Queue()
        self._workers: List[asyncio.Task] = []

    async def start_workers(self, num_workers: int = 4):
        """Start the worker tasks that process files from the queue."""
        self._workers = [
            asyncio.create_task(self._worker()) for _ in range(num_workers)
        ]
        logger.info(f"Started {num_workers} indexing workers.")

    async def stop_workers(self):
        """Stop all worker tasks."""
        await self._queue.join()  # Wait for the queue to be empty
        for worker in self._workers:
            worker.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        logger.info("Indexing workers stopped.")

    async def _worker(self):
        """The worker task that processes files from the queue."""
        while True:
            file_path = await self._queue.get()
            try:
                await self._process_file(file_path)
            except Exception as e:
                logger.error(f"Error processing file {file_path} in worker: {e}")
            finally:
                self._queue.task_done()

    def add_to_queue(self, file_path: str):
        """Add a file to the processing queue."""
        self._queue.put_nowait(file_path)

    def remove_from_index(self, file_path: str):
        """Remove a file from the memory provider and metadata."""
        # This needs to be implemented based on how memory IDs are stored/retrieved
        # For now, we'll just remove metadata.
        # A lookup from file_path to memory_id would be needed.
        logger.info(f"File {file_path} deleted. Removing from metadata.")
        self.metadata.remove_file_metadata(file_path)
        # To fully remove from the provider, we'd need to:
        # memory_id = self.metadata.get_memory_id_for_file(file_path)
        # await self.provider.delete_memory(memory_id)


    async def sync_directory(self, directory: str, force_full: bool = False):
        """
        Scan a directory and add any new or modified files to the indexing queue.
        """
        logger.info(f"Syncing directory: {directory} (force_full={force_full})")
        directory_path = Path(directory).resolve()
        
        for file_path in directory_path.rglob("*"):
            if file_path.is_file():
                if force_full or self.metadata.needs_indexing(str(file_path), self.provider.embedding_model):
                    self.add_to_queue(str(file_path))
        
        logger.info(f"Sync for {directory} complete. Check queue for pending files.")

    async def _process_file(self, file_path: str):
        """
        Process a single file: select a processor, extract content, and add to memory.
        """
        logger.debug(f"Processing file: {file_path}")
        
        # 1. Select the right processor
        selected_processor = None
        for processor in self.processors:
            if processor.can_process(file_path):
                selected_processor = processor
                break
        
        if not selected_processor:
            logger.debug(f"No suitable processor found for {file_path}. Skipping.")
            return

        # 2. Process the file to get content and metadata
        processed_data = await selected_processor.process(file_path)
        if not processed_data:
            logger.debug(f"Processor failed for {file_path}. Skipping.")
            return
            
        # 3. Add to the memory provider
        try:
            await self.provider.add_memory(
                content=processed_data["content"],
                metadata=processed_data["metadata"],
                categories=[processed_data["metadata"].get("file_type", "general")]
            )
        except Exception as e:
            logger.error(f"Failed to add memory for file {file_path}: {e}")
            return

        # 4. Update the index metadata
        content_hash = self.metadata._calculate_hash(file_path)
        self.metadata.update_file_metadata(file_path, content_hash, self.provider.embedding_model)
        logger.info(f"Successfully indexed file: {file_path}") 