"""
LanceDB Memory Provider for Penguin AI System

This provider implements vector storage and search using LanceDB, a high-performance
vector database built on the Lance columnar format. LanceDB provides excellent
performance for both vector similarity search and hybrid search capabilities.

Key Features:
- Fast vector similarity search with automatic indexing
- Hybrid search combining vector and full-text search
- Built-in embedding support with multiple models
- Efficient storage using Lance columnar format
- Support for metadata filtering and complex queries
- Automatic schema inference and validation
"""

import asyncio
import logging
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union
import json
import re

try:
    import lancedb
    from lancedb.embeddings import get_registry
    from lancedb.pydantic import LanceModel, Vector
    import numpy as np
    import pandas as pd
    import pyarrow as pa
    LANCEDB_AVAILABLE = True
except ImportError:
    LANCEDB_AVAILABLE = False
    lancedb = None
    LanceModel = None
    Vector = None
    # Import these anyway for basic functionality
    try:
        import numpy as np
        import pandas as pd
        import pyarrow as pa
    except ImportError:
        np = None
        pd = None
        pa = None

from penguin.memory.providers.base import MemoryProvider

logger = logging.getLogger(__name__)


# Only define MemoryRecord if LanceDB is available
if LANCEDB_AVAILABLE:
    class MemoryRecord(LanceModel):
        """Pydantic model for memory records in LanceDB"""
        
        # Core fields
        memory_id: str
        content: str
        
        # Metadata fields
        timestamp: str
        memory_type: str
        categories: List[str]
        file_path: Optional[str] = None
        source: Optional[str] = None
        
        # Additional metadata as JSON string (LanceDB doesn't support Dict[str, Any])
        metadata_json: str = "{}"
        
        # Note: Vector field will be added dynamically when embedding function is available
else:
    # Placeholder when LanceDB is not available
    MemoryRecord = None


class LanceMemoryProvider(MemoryProvider):
    """
    LanceDB-based memory provider for high-performance vector search.
    
    This provider uses LanceDB for storing and searching memory records with
    vector embeddings. It supports both semantic search via embeddings and
    full-text search capabilities.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize LanceDB memory provider.
        
        Args:
            config: Configuration dictionary containing provider settings
        """
        if not LANCEDB_AVAILABLE:
            raise ImportError(
                "LanceDB is not available. Install with: pip install lancedb"
            )
        
        super().__init__(config)
        
        self.storage_path = Path(config.get('storage_path', './memory_db'))
        self.storage_path.mkdir(parents=True, exist_ok=True)
        
        self.table_name = config.get('table_name', 'memory_records')
        
        # Define memory paths
        from penguin.config import WORKSPACE_PATH
        self.memory_paths = {
            "notes": os.path.join(WORKSPACE_PATH, "notes"),
            "conversations": os.path.join(WORKSPACE_PATH, "conversations"),
        }
        
        # Initialize connection and embedding function
        self._db = None
        self._table = None
        self._embedding_function = None
        self._schema = None
        
        # Performance tracking
        self._stats = {
            "total_memories": 0,
            "search_count": 0,
            "last_indexed": None,
            "index_created": False
        }
        
        logger.info(f"Initialized LanceDB provider at {self.storage_path}")
    
    def _get_connection(self):
        """Get or create database connection"""
        if self._db is None:
            self._db = lancedb.connect(str(self.storage_path))
            logger.debug(f"Connected to LanceDB at {self.storage_path}")
        return self._db
    
    def _get_embedding_function(self):
        """Get or create embedding function"""
        if self._embedding_function is None:
            try:
                # Try to get the embedding function from registry
                registry = get_registry()
                
                if "sentence-transformers" in self.embedding_model:
                    func = registry.get("sentence-transformers").create(
                        name=self.embedding_model
                    )
                elif "openai" in self.embedding_model:
                    func = registry.get("openai").create(
                        name=self.embedding_model
                    )
                else:
                    # Default to sentence transformers
                    func = registry.get("sentence-transformers").create(
                        name="sentence-transformers/all-MiniLM-L6-v2"
                    )
                
                self._embedding_function = func
                logger.debug(f"Created embedding function: {self.embedding_model}")
                
            except Exception as e:
                logger.warning(f"Failed to create embedding function: {e}")
                # Fallback to manual embedding if needed
                self._embedding_function = None
        
        return self._embedding_function
    
    def _get_schema(self):
        """Get or create table schema with embedding function"""
        if self._schema is None:
            if not LANCEDB_AVAILABLE:
                raise ImportError("LanceDB is not available")
                
            embedding_func = self._get_embedding_function()
            
            if embedding_func:
                # Create schema with embedding function
                class MemoryRecordWithEmbedding(LanceModel):
                    memory_id: str
                    content: str = embedding_func.SourceField()
                    timestamp: str
                    memory_type: str
                    categories: List[str]
                    file_path: Optional[str] = None
                    source: Optional[str] = None
                    metadata_json: str = "{}"
                    vector: Vector(embedding_func.ndims()) = embedding_func.VectorField()
                
                self._schema = MemoryRecordWithEmbedding
            else:
                # Fallback schema without embedding function
                self._schema = MemoryRecord
        
        return self._schema
    
    async def _initialize_provider(self) -> None:
        """Provider-specific initialization logic."""
        # Initialize connection and table
        await self._get_table()
        # Asynchronously index memory files on startup
        asyncio.create_task(self.index_memory_files())
        logger.debug("LanceDB provider initialized and indexing started")
    
    async def _get_table(self):
        """Get or create table"""
        if self._table is None:
            db = self._get_connection()
            schema = self._get_schema()
            
            try:
                # Try to open existing table
                self._table = db.open_table(self.table_name)
                logger.debug(f"Opened existing table: {self.table_name}")
            except Exception:
                # Create new table
                self._table = db.create_table(
                    self.table_name,
                    schema=schema,
                    mode="create"
                )
                logger.info(f"Created new table: {self.table_name}")
        
        return self._table
    
    async def add_memory(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        categories: Optional[List[str]] = None
    ) -> str:
        """
        Add a memory record to the database.
        
        Args:
            content: The text content of the memory
            metadata: Additional metadata for the memory
            categories: List of categories for the memory
            
        Returns:
            The unique ID of the added memory
        """
        try:
            table = await self._get_table()
            
            # Generate unique memory ID
            memory_id = f"mem_{int(time.time() * 1000000)}"
            
            # Prepare record data
            metadata = metadata or {}
            categories = categories or []
            
            import json
            
            # Clean metadata to remove non-serializable items
            clean_metadata = {}
            for k, v in metadata.items():
                if k != "categories":  # Categories are handled separately
                    try:
                        json.dumps(v)  # Test if serializable
                        clean_metadata[k] = v
                    except (TypeError, ValueError):
                        # Skip non-serializable values
                        continue
            
            record_data = {
                "memory_id": memory_id,
                "content": content,
                "timestamp": datetime.now().isoformat(),
                "memory_type": clean_metadata.get("memory_type", "general"),
                "categories": categories,
                "file_path": clean_metadata.get("file_path"),
                "source": clean_metadata.get("source"),
                "metadata_json": json.dumps(clean_metadata)
            }
            
            # Add to table (embedding will be computed automatically if function is available)
            table.add([record_data])
            
            # Update stats
            self._stats["total_memories"] += 1
            self._stats["last_indexed"] = datetime.now().isoformat()
            
            # Create index if we have enough records and haven't created one yet
            if (self._stats["total_memories"] > 100 and 
                not self._stats["index_created"]):
                await self._create_index()
            
            logger.debug(f"Added memory record: {memory_id}")
            return memory_id
            
        except Exception as e:
            logger.error(f"Error adding memory: {e}")
            raise
    
    async def search_memory(
        self,
        query: str,
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for memories using vector similarity.
        
        Args:
            query: The search query
            max_results: Maximum number of results to return
            filters: Optional filters to apply
            
        Returns:
            List of matching memory records with scores
        """
        try:
            table = await self._get_table()
            
            # Build search query
            search_query = table.search(query).limit(max_results)
            
            # Apply filters if provided
            if filters:
                filter_conditions = []
                
                # Handle common filter types
                if "memory_type" in filters:
                    filter_conditions.append(f"memory_type = '{filters['memory_type']}'")
                
                # Note: Category filtering is not supported in this version of LanceDB
                # if "categories" in filters and filters["categories"]:
                #     # LanceDB doesn't support array filtering in this version
                #     pass
                
                if "date_after" in filters:
                    filter_conditions.append(f"timestamp >= '{filters['date_after']}'")
                
                if "date_before" in filters:
                    filter_conditions.append(f"timestamp <= '{filters['date_before']}'")
                
                if "file_path" in filters:
                    filter_conditions.append(f"file_path = '{filters['file_path']}'")
                
                # Combine filters with AND
                if filter_conditions:
                    filter_sql = " AND ".join(filter_conditions)
                    search_query = search_query.where(filter_sql)
            
            # Execute search
            results = search_query.to_pandas()
            
            # Format results
            import json
            formatted_results = []
            for _, row in results.iterrows():
                # Deserialize metadata JSON
                try:
                    metadata_dict = json.loads(row.get("metadata_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    metadata_dict = {}
                
                result = {
                    "id": row["memory_id"],
                    "content": row["content"],
                    "metadata": {
                        "timestamp": row["timestamp"],
                        "memory_type": row["memory_type"],
                        "categories": row["categories"],
                        "file_path": row.get("file_path"),
                        "source": row.get("source"),
                        **metadata_dict
                    },
                    "score": row.get("_distance", 0.0),
                    "relevance": max(0, 100 - (row.get("_distance", 1.0) * 100))
                }
                formatted_results.append(result)
            
            # Update stats
            self._stats["search_count"] += 1
            
            logger.debug(f"Search returned {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logger.error(f"Error searching memory: {e}")
            return []
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific memory by ID.
        
        Args:
            memory_id: Unique identifier of the memory
            
        Returns:
            Dictionary containing memory data or None if not found
        """
        try:
            table = await self._get_table()
            
            # Query for specific memory ID
            results = table.search("").where(f"memory_id = '{memory_id}'").limit(1).to_pandas()
            
            if len(results) == 0:
                return None
            
            row = results.iloc[0]
            
            # Deserialize metadata JSON
            import json
            try:
                metadata_dict = json.loads(row.get("metadata_json", "{}"))
            except (json.JSONDecodeError, TypeError):
                metadata_dict = {}
            
            return {
                "id": row["memory_id"],
                "content": row["content"],
                "metadata": {
                    "timestamp": row["timestamp"],
                    "memory_type": row["memory_type"],
                    "categories": row["categories"],
                    "file_path": row.get("file_path"),
                    "source": row.get("source"),
                    **metadata_dict
                }
            }
            
        except Exception as e:
            logger.error(f"Error getting memory {memory_id}: {e}")
            return None
    
    async def delete_memory(self, memory_id: str) -> bool:
        """
        Delete a memory record.
        
        Args:
            memory_id: The ID of the memory to delete
            
        Returns:
            True if deletion was successful
        """
        try:
            table = await self._get_table()
            
            # Delete the record
            table.delete(f"memory_id = '{memory_id}'")
            
            # Update stats
            self._stats["total_memories"] = max(0, self._stats["total_memories"] - 1)
            
            logger.debug(f"Deleted memory record: {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error deleting memory {memory_id}: {e}")
            return False
    
    async def update_memory(
        self,
        memory_id: str,
        content: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update a memory record.
        
        Args:
            memory_id: The ID of the memory to update
            content: New content
            metadata: New metadata
            
        Returns:
            True if update was successful
        """
        try:
            # Get existing memory first
            existing = await self.get_memory(memory_id)
            if not existing:
                return False
            
            # Merge updates with existing data
            new_content = content if content is not None else existing["content"]
            new_metadata = existing["metadata"].copy()
            if metadata:
                new_metadata.update(metadata)
            
            # LanceDB doesn't support direct updates, so we delete and re-add
            await self.delete_memory(memory_id)
            
            # Re-add with updated content using the same memory ID
            import json
            
            # Clean metadata to remove non-serializable items
            clean_metadata = {}
            for k, v in new_metadata.items():
                if k != "categories":  # Categories are handled separately
                    try:
                        json.dumps(v)  # Test if serializable
                        clean_metadata[k] = v
                    except (TypeError, ValueError):
                        # Skip non-serializable values
                        continue
            
            record_data = {
                "memory_id": memory_id,  # Use the same ID
                "content": new_content,
                "timestamp": datetime.now().isoformat(),
                "memory_type": clean_metadata.get("memory_type", "general"),
                "categories": new_metadata.get("categories", []),
                "file_path": clean_metadata.get("file_path"),
                "source": clean_metadata.get("source"),
                "metadata_json": json.dumps(clean_metadata)
            }
            
            table = await self._get_table()
            table.add([record_data])
            
            logger.debug(f"Updated memory record: {memory_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error updating memory {memory_id}: {e}")
            return False
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the memory database.
        
        Returns:
            Dictionary containing database statistics
        """
        try:
            table = await self._get_table()
            
            # Get basic table info (stats() method doesn't exist in this version)
            try:
                table_count = len(table)
            except:
                table_count = self._stats["total_memories"]
            
            stats = {
                "provider": "lancedb",
                "total_memories": table_count,
                "storage_path": str(self.storage_path),
                "table_name": self.table_name,
                "embedding_model": self.embedding_model,
                "search_count": self._stats["search_count"],
                "last_indexed": self._stats["last_indexed"],
                "index_created": self._stats["index_created"]
            }
            
            return stats
            
        except Exception as e:
            logger.error(f"Error getting memory stats: {e}")
            return {"provider": "lancedb", "error": str(e)}
    
    async def backup_memories(self, backup_path: str) -> bool:
        """
        Backup memories to a file.
        
        Args:
            backup_path: Path to save the backup
            
        Returns:
            True if backup was successful
        """
        try:
            table = await self._get_table()
            
            # Export to pandas and save as parquet
            df = table.to_pandas()
            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            df.to_parquet(backup_file)
            
            logger.info(f"Backed up {len(df)} memories to {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error backing up memories: {e}")
            return False
    
    async def restore_memories(self, backup_path: str) -> bool:
        """
        Restore memories from a backup file.
        
        Args:
            backup_path: Path to the backup file
            
        Returns:
            True if restore was successful
        """
        try:
            backup_file = Path(backup_path)
            if not backup_file.exists():
                logger.error(f"Backup file not found: {backup_path}")
                return False
            
            # Load backup data
            df = pd.read_parquet(backup_file)
            
            # Get or create table
            table = await self._get_table()
            
            # Add data to table
            table.add(df)
            
            # Update stats
            self._stats["total_memories"] += len(df)
            self._stats["last_indexed"] = datetime.now().isoformat()
            
            logger.info(f"Restored {len(df)} memories from {backup_path}")
            return True
            
        except Exception as e:
            logger.error(f"Error restoring memories: {e}")
            return False
    
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the memory provider.
        
        Returns:
            Dictionary containing health status
        """
        health_status = {
            "provider": "lancedb",
            "status": "unknown",
            "checks": {},
            "timestamp": datetime.now().isoformat()
        }
        
        try:
            # Check database connection
            db = self._get_connection()
            health_status["checks"]["database_connection"] = "ok"
            
            # Check table access
            table = await self._get_table()
            health_status["checks"]["table_access"] = "ok"
            
            # Check embedding function
            embedding_func = self._get_embedding_function()
            if embedding_func:
                health_status["checks"]["embedding_function"] = "ok"
            else:
                health_status["checks"]["embedding_function"] = "warning"
            
            # Check storage path
            if self.storage_path.exists() and self.storage_path.is_dir():
                health_status["checks"]["storage_path"] = "ok"
            else:
                health_status["checks"]["storage_path"] = "error"
            
            # Overall status
            if all(check in ["ok", "warning"] for check in health_status["checks"].values()):
                health_status["status"] = "healthy"
            else:
                health_status["status"] = "unhealthy"
            
        except Exception as e:
            health_status["status"] = "error"
            health_status["error"] = str(e)
            logger.error(f"Health check failed: {e}")
        
        return health_status
    
    async def _create_index(self):
        """Create vector index for better search performance"""
        try:
            table = await self._get_table()
            
            # Create vector index if we have a vector column
            if "vector" in table.schema.names:
                table.create_index("vector", index_type="ivf_pq")
                self._stats["index_created"] = True
                logger.info("Created vector index for improved search performance")
            
        except Exception as e:
            logger.warning(f"Failed to create index: {e}")
    
    async def hybrid_search(
        self,
        query: str,
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None,
        vector_weight: float = 0.7,
        text_weight: float = 0.3
    ) -> List[Dict[str, Any]]:
        """
        Perform hybrid search combining vector and text search.
        
        Args:
            query: The search query
            max_results: Maximum number of results to return
            filters: Optional filters to apply
            vector_weight: Weight for vector search results
            text_weight: Weight for text search results
            
        Returns:
            List of matching memory records with combined scores
        """
        try:
            table = await self._get_table()
            
            # Perform hybrid search if supported
            search_query = table.search(query, query_type="hybrid").limit(max_results)
            
            # Apply filters if provided
            if filters:
                filter_conditions = []
                
                if "memory_type" in filters:
                    filter_conditions.append(f"memory_type = '{filters['memory_type']}'")
                
                # Note: Category filtering is not supported in this version of LanceDB
                # if "categories" in filters and filters["categories"]:
                #     # LanceDB doesn't support array filtering in this version
                #     pass
                
                if filter_conditions:
                    filter_sql = " AND ".join(filter_conditions)
                    search_query = search_query.where(filter_sql)
            
            # Execute search
            results = search_query.to_pandas()
            
            # Format results
            import json
            formatted_results = []
            for _, row in results.iterrows():
                # Deserialize metadata JSON
                try:
                    metadata_dict = json.loads(row.get("metadata_json", "{}"))
                except (json.JSONDecodeError, TypeError):
                    metadata_dict = {}
                
                result = {
                    "id": row["memory_id"],
                    "content": row["content"],
                    "metadata": {
                        "timestamp": row["timestamp"],
                        "memory_type": row["memory_type"],
                        "categories": row["categories"],
                        "file_path": row.get("file_path"),
                        "source": row.get("source"),
                        **metadata_dict
                    },
                    "score": row.get("_distance", 0.0),
                    "relevance": max(0, 100 - (row.get("_distance", 1.0) * 100))
                }
                formatted_results.append(result)
            
            logger.debug(f"Hybrid search returned {len(formatted_results)} results")
            return formatted_results
            
        except Exception as e:
            logger.warning(f"Hybrid search failed, falling back to vector search: {e}")
            # Fallback to regular vector search
            return await self.search_memory(query, max_results, filters)
    
    def close(self):
        """Close the database connection"""
        if self._db:
            # LanceDB connections are automatically managed
            self._db = None
            self._table = None
            logger.debug("Closed LanceDB connection")

    # Helper methods for file indexing (adapted from ChromaDB implementation)
    def parse_memory(self, content: str) -> Dict[str, Any]:
        """Parse memory content and extract metadata"""
        memory_info = {
            "timestamp": datetime.now().isoformat(),
            "type": "conversation",
            "summary": "",
        }

        try:
            data = json.loads(content)
            if isinstance(data, dict):
                memory_info.update(
                    {
                        "type": data.get("type", "declarative"),
                        "summary": data.get("summary", ""),
                    }
                )
        except json.JSONDecodeError:
            lines = content.split("\n")
            if lines:
                memory_info["summary"] = lines[0][:100]

        return memory_info

    def extract_categories(self, content: str) -> List[str]:
        """Extract categories and return them as a list of strings"""
        categories = set()
        category_keywords = {
            "task": ["task", "todo", "done", "complete"],
            "project": ["project", "milestone", "planning"],
            "error": ["error", "bug", "issue", "fix"],
            "decision": ["decision", "chose", "selected", "agreed"],
            "research": ["research", "investigation", "analysis"],
            "code": ["code", "implementation", "function", "class"],
        }
        content_lower = content.lower()
        for category, keywords in category_keywords.items():
            if any(keyword in content_lower for keyword in keywords):
                categories.add(category)
        return sorted(list(categories))

    def extract_date_from_path(self, filename: str) -> str:
        """Extract date from filename like chat_20240902_175411.md"""
        match = re.search(r"(\d{8})_(\d{6})", filename)
        if match:
            date_str, time_str = match.groups()
            return f"{date_str[:4]}-{date_str[4:6]}-{date_str[6:]}T{time_str[:2]}:{time_str[2:4]}:{time_str[4:]}"
        return datetime.now().isoformat()

    async def index_memory_files(self) -> str:
        """Index all memory files from workspace directories."""
        logger.info("Starting memory file indexing...")
        indexed_count = 0
        skipped_count = 0 # In this version, we re-index all for simplicity
        
        for memory_type, base_path in self.memory_paths.items():
            if not os.path.exists(base_path):
                logger.warning(f"Memory path not found: {base_path}")
                continue
            
            for filename in os.listdir(base_path):
                if filename.endswith((".md", ".txt", ".json")):
                    file_path = os.path.join(base_path, filename)
                    try:
                        with open(file_path, "r", encoding="utf-8") as f:
                            content = f.read()

                        if not content.strip():
                            continue

                        # Extract metadata
                        parsed_meta = self.parse_memory(content)
                        categories = self.extract_categories(content)
                        
                        metadata = {
                            "memory_type": memory_type,
                            "file_path": file_path,
                            "source": "file_index",
                            "timestamp": self.extract_date_from_path(filename),
                            **parsed_meta
                        }
                        
                        # Use add_memory to add to LanceDB
                        await self.add_memory(
                            content=content,
                            metadata=metadata,
                            categories=categories
                        )
                        indexed_count += 1
                    
                    except Exception as e:
                        logger.error(f"Failed to index file {file_path}: {e}")

        result_message = f"Memory indexing complete. Indexed {indexed_count} files, skipped {skipped_count}."
        logger.info(result_message)
        return result_message
