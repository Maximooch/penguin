"""
File Memory Provider

Simple file-based memory provider for basic functionality without external dependencies.
Uses a single JSONL file for storage and performs in-memory vector search.
"""

import asyncio
import json
import logging
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

from penguin.memory.embedding import get_embedder
from .base import MemoryProvider, MemoryProviderError

logger = logging.getLogger(__name__)


class FileMemoryProvider(MemoryProvider):
    """
    Simple file-based memory provider using a single JSONL file.

    Features:
    - Stores all memories in a single `memories.jsonl` file.
    - No external dependencies (except numpy for vector search).
    - Performs in-memory vector search if embeddings are enabled.
    - Human-readable storage format.
    """

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)

        self.storage_path = Path(config.get('storage_path', './memory_db'))
        self.storage_dir = self.storage_path / config.get('storage_dir', 'file_memory')
        self.storage_dir.mkdir(parents=True, exist_ok=True)

        # Alias for backward compatibility with older tests expecting `memories_dir`
        # Both `storage_dir` and `memories_dir` refer to the same directory.
        self.memories_dir = self.storage_dir

        self.memory_file = self.storage_dir / "memories.jsonl"
        
        self.enable_embeddings = config.get('enable_embeddings', True)
        if self.enable_embeddings and not NUMPY_AVAILABLE:
            logger.warning("Numpy not installed. Disabling embedding support for FileProvider.")
            self.enable_embeddings = False

        self._embedder = None
        if self.enable_embeddings:
            self._embedder = get_embedder(self.embedding_model)

        self._in_memory_db: List[Dict[str, Any]] = []
        self._lock = asyncio.Lock()

    async def _initialize_provider(self) -> None:
        """Load existing memories from the JSONL file."""
        async with self._lock:
            if not self.memory_file.exists():
                self._in_memory_db = []
            else:
                with open(self.memory_file, "r", encoding="utf-8") as f:
                    self._in_memory_db = [json.loads(line) for line in f]
        
        self._stats['total_memories'] = len(self._in_memory_db)
        logger.info(f"File memory provider initialized with {len(self._in_memory_db)} memories.")

    async def add_memory(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        categories: Optional[List[str]] = None,
    ) -> str:
        """Add a new memory to the JSONL file."""
        memory_id = str(uuid.uuid4())
        
        record = {
            "id": memory_id,
            "content": content,
            "metadata": metadata or {},
            "categories": categories or [],
            "created_at": datetime.now().isoformat(),
            "embedding": None,
        }

        if self.enable_embeddings and self._embedder:
            vector = self._embedder([content])[0]
            # Ensure vector is a plain list for JSON serialization
            record["embedding"] = vector.tolist() if hasattr(vector, 'tolist') else list(vector)

        async with self._lock:
            self._in_memory_db.append(record)
            with open(self.memory_file, "a", encoding="utf-8") as f:
                f.write(json.dumps(record) + "\n")
            
            self._update_stats('add')
        
        return memory_id

    async def search_memory(
        self,
        query: str,
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Search memories using vector search (if enabled) or keyword search."""
        async with self._lock:
            if not self._in_memory_db:
                return []

            if self.enable_embeddings and self._embedder:
                results = self._vector_search(query, max_results)
            else:
                results = self._keyword_search(query, max_results)
        
        self._update_stats('search')
        # Filtering would be applied here if needed
        return results

    def _vector_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Perform in-memory vector search."""
        query_vector = np.array(self._embedder([query])[0])
        
        memories_with_embeddings = [m for m in self._in_memory_db if m.get("embedding")]
        if not memories_with_embeddings:
            return []

        db_vectors = np.array([m["embedding"] for m in memories_with_embeddings])
        
        # Cosine similarity
        query_norm = query_vector / np.linalg.norm(query_vector)
        db_norms = np.linalg.norm(db_vectors, axis=1)
        db_vectors_normalized = db_vectors / db_norms[:, np.newaxis]
        scores = np.dot(db_vectors_normalized, query_norm)

        top_indices = np.argsort(scores)[::-1][:max_results]

        return [{
            "id": memories_with_embeddings[i]["id"],
            "content": memories_with_embeddings[i]["content"],
            "metadata": memories_with_embeddings[i]["metadata"],
            "score": scores[i],
        } for i in top_indices if scores[i] > 0]

    def _keyword_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Perform simple case-insensitive keyword search."""
        query_lower = query.lower()
        results = []
        for record in self._in_memory_db:
            if query_lower in record["content"].lower():
                results.append({
                    "id": record["id"],
                    "content": record["content"],
                    "metadata": record["metadata"],
                    "score": 1.0, # Simple score
                })
        # A more sophisticated scoring could be added here
        return results[:max_results]
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        async with self._lock:
            for record in self._in_memory_db:
                if record["id"] == memory_id:
                    return record
        return None

    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory by filtering it out and rewriting the file."""
        async with self._lock:
            original_count = len(self._in_memory_db)
            self._in_memory_db = [m for m in self._in_memory_db if m["id"] != memory_id]
            
            if len(self._in_memory_db) < original_count:
                self._rewrite_db_file()
                self._update_stats('delete')
                return True
        return False

    async def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Update a memory by replacing it."""
        async with self._lock:
            for i, record in enumerate(self._in_memory_db):
                if record["id"] == memory_id:
                    if content is not None:
                        record["content"] = content
                        if self.enable_embeddings and self._embedder:
                            vector = self._embedder([content])[0]
                            record["embedding"] = vector.tolist() if hasattr(vector, 'tolist') else list(vector)
                    if metadata is not None:
                        record["metadata"] = metadata
                    
                    self._in_memory_db[i] = record
                    self._rewrite_db_file()
                    return True
        return False

    def _rewrite_db_file(self):
        """Atomically rewrite the entire database file."""
        temp_file = self.memory_file.with_suffix(".tmp")
        with open(temp_file, "w", encoding="utf-8") as f:
            for record in self._in_memory_db:
                f.write(json.dumps(record) + "\n")
        temp_file.rename(self.memory_file)

    async def get_memory_stats(self) -> Dict[str, Any]:
        file_size = self.memory_file.stat().st_size if self.memory_file.exists() else 0
        return {
            "provider": "file",
            "total_memories": len(self._in_memory_db),
            "file_size_bytes": file_size,
        }

    async def health_check(self) -> Dict[str, Any]:
        return {"status": "ok" if self.memory_file.parent.exists() else "error"}
        
    async def backup_memories(self, backup_path: str) -> bool:
        """Create a compressed backup (.zip) of the memory file.

        Args:
            backup_path: Destination path for the zip file.

        Returns:
            True if backup succeeded.
        """
        try:
            backup_path = Path(backup_path)
            backup_path.parent.mkdir(parents=True, exist_ok=True)

            # Use shutil.make_archive requires path without extension
            if backup_path.suffix:
                archive_base = backup_path.with_suffix("")
                archive_format = backup_path.suffix.lstrip(".")  # 'zip' expected by tests
            else:
                archive_base = backup_path
                archive_format = 'zip'

            import shutil
            # The make_archive function returns path of the created archive
            shutil.make_archive(str(archive_base), archive_format, root_dir=self.storage_dir)

            # Ensure archive exists at the exact requested path
            created_path = archive_base.with_suffix('.' + archive_format)
            if created_path != backup_path:
                created_path.rename(backup_path)

            return backup_path.exists()
        except Exception as e:
            logger.error(f"Failed to back up memories: {e}")
            return False

    async def restore_memories(self, backup_path: str) -> bool:
        """Restore memories from a backup zip file by extracting the archive.

        Args:
            backup_path: Path to the backup archive.

        Returns:
            True if restore succeeded.
        """
        try:
            backup_path = Path(backup_path)
            if not backup_path.exists():
                logger.warning("Backup path does not exist: %s", backup_path)
                return False

            import shutil, tempfile
            with tempfile.TemporaryDirectory() as tmpdir:
                shutil.unpack_archive(str(backup_path), tmpdir)
                tmp_memory_file = Path(tmpdir) / self.memory_file.name
                if tmp_memory_file.exists():
                    # Replace existing memory file
                    shutil.move(str(tmp_memory_file), self.memory_file)
                    await self._initialize_provider()  # Reload into memory
                    return True
            return False
        except Exception as e:
            logger.error(f"Failed to restore memories: {e}")
            return False 