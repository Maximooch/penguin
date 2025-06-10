"""
SQLite Memory Provider

Lightweight, dependency-free memory provider using SQLite with FTS5 for 
full-text search and JSON storage for embeddings and metadata.
"""

import asyncio
import json
import logging
import sqlite3
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from penguin.memory.embedding import get_embedder
from .base import MemoryProvider, MemoryProviderError

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False

logger = logging.getLogger(__name__)


class SQLiteMemoryProvider(MemoryProvider):
    """
    Lightweight memory provider using SQLite with FTS5 for full-text search.
    
    Features:
    - Full-text search with FTS5
    - JSON storage for metadata and embeddings
    - ACID transactions
    - No external dependencies
    - Automatic database initialization
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize SQLite memory provider.
        
        Args:
            config: Configuration dictionary with 'database_file' and other options
        """
        super().__init__(config)
        
        # Configuration
        self.database_file = config.get('database_file', 'penguin_memory.db')
        self.storage_path = Path(config.get('storage_path', './memory_db'))
        self.enable_fts = config.get('enable_fts', True)
        self.enable_embeddings = config.get('enable_embeddings', True)
        
        # Full database path
        self.db_path = self.storage_path / self.database_file
        
        # Connection will be initialized in _initialize_provider
        self._connection = None
        
        # Create storage directory
        self.storage_path.mkdir(parents=True, exist_ok=True)

        if self.enable_embeddings and not NUMPY_AVAILABLE:
            logger.warning("Numpy is not installed. Disabling embedding support for SQLite.")
            self.enable_embeddings = False

        self._embedder = None
        if self.enable_embeddings:
            self._embedder = get_embedder(self.embedding_model)
    
    async def _initialize_provider(self) -> None:
        """Initialize SQLite database and tables."""
        try:
            # Create connection
            self._connection = sqlite3.connect(str(self.db_path))
            self._connection.row_factory = sqlite3.Row  # Enable dict-like access
            
            # Enable foreign keys and WAL mode for better performance
            self._connection.execute("PRAGMA foreign_keys = ON")
            self._connection.execute("PRAGMA journal_mode = WAL")
            
            # Create main memories table
            self._connection.execute("""
                CREATE TABLE IF NOT EXISTS memories (
                    id TEXT PRIMARY KEY,
                    content TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    metadata TEXT,  -- JSON
                    categories TEXT,  -- JSON array
                    embedding TEXT,  -- JSON-serialized vector
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            # Create FTS5 virtual table for full-text search
            if self.enable_fts:
                self._connection.execute("""
                    CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                        id UNINDEXED,
                        content,
                        categories,
                        content='memories',
                        content_rowid='rowid'
                    )
                """)
                
                # Create triggers to keep FTS table in sync
                self._connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_insert AFTER INSERT ON memories
                    BEGIN
                        INSERT INTO memories_fts(id, content, categories) 
                        VALUES (new.id, new.content, new.categories);
                    END
                """)
                
                self._connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_delete AFTER DELETE ON memories
                    BEGIN
                        DELETE FROM memories_fts WHERE id = old.id;
                    END
                """)
                
                self._connection.execute("""
                    CREATE TRIGGER IF NOT EXISTS memories_fts_update AFTER UPDATE ON memories
                    BEGIN
                        DELETE FROM memories_fts WHERE id = old.id;
                        INSERT INTO memories_fts(id, content, categories) 
                        VALUES (new.id, new.content, new.categories);
                    END
                """)
            
            # Create indexes for better performance
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_created_at ON memories(created_at)")
            self._connection.execute("CREATE INDEX IF NOT EXISTS idx_memories_content_hash ON memories(content_hash)")
            
            self._connection.commit()
            
            # Update stats
            self._stats['total_memories'] = self._get_total_count()
            
            logger.info(f"SQLite memory provider initialized at {self.db_path}")
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to initialize SQLite provider: {str(e)}")
    
    async def add_memory(
        self, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None, 
        categories: Optional[List[str]] = None
    ) -> str:
        """Add a new memory entry to SQLite database."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            memory_id = str(uuid.uuid4())
            content_hash = self._generate_content_hash(content)
            
            # Serialize JSON fields
            metadata_json = json.dumps(metadata or {})
            categories_json = json.dumps(categories or [])
            
            embedding_json = None
            if self.enable_embeddings and self._embedder:
                vector = self._embedder([content])[0]
                # Ensure vector is a plain list for JSON serialization
                embedding_json = json.dumps(vector.tolist() if hasattr(vector, 'tolist') else list(vector))

            # Insert into database
            self._connection.execute("""
                INSERT INTO memories (id, content, content_hash, metadata, categories, embedding, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                memory_id,
                content,
                content_hash,
                metadata_json,
                categories_json,
                embedding_json,
                datetime.now().isoformat(),
                datetime.now().isoformat()
            ))
            
            self._connection.commit()
            self._update_stats('add')
            
            logger.debug(f"Added memory {memory_id}")
            return memory_id
            
        except Exception as e:
            self._connection.rollback()
            raise MemoryProviderError(f"Failed to add memory: {str(e)}")
    
    async def search_memory(
        self, 
        query: str, 
        max_results: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search memories using multiple search strategies."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            results = []
            search_mode = filters.get('search_mode', 'auto') if filters else 'auto'
            
            # Vector search has priority if enabled and query is suitable
            if query.strip() and self.enable_embeddings and search_mode in ['auto', 'vector']:
                vector_results = await self._vector_search(query, max_results)
                results.extend(vector_results)

            if query.strip() and self.enable_fts and len(results) < max_results:
                if search_mode in ['auto', 'fts']:
                    # Use FTS5 for better search
                    sql = """
                        SELECT m.id, m.content, m.metadata, m.categories, m.created_at,
                               f.rank as score
                        FROM memories_fts f
                        JOIN memories m ON f.id = m.id
                        WHERE memories_fts MATCH ?
                        ORDER BY f.rank
                        LIMIT ?
                    """
                    cursor = self._connection.execute(sql, (query, max_results - len(results)))
                    results.extend(self._process_search_results(cursor))
                
                # Add fuzzy search for partial matches
                if search_mode in ['auto', 'fuzzy'] and len(results) < max_results:
                    fuzzy_results = await self._fuzzy_search(query, max_results - len(results))
                    results.extend(fuzzy_results)
                
                # Add glob/pattern search
                if search_mode in ['auto', 'glob'] and len(results) < max_results:
                    glob_results = await self._glob_search(query, max_results - len(results))
                    results.extend(glob_results)
                    
            elif query.strip():
                # Fallback to LIKE search
                sql = """
                    SELECT id, content, metadata, categories, created_at,
                           1.0 as score
                    FROM memories
                    WHERE content LIKE ?
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                cursor = self._connection.execute(sql, (f"%{query}%", max_results))
                results.extend(self._process_search_results(cursor))
            else:
                # Return recent memories if no query
                sql = """
                    SELECT id, content, metadata, categories, created_at,
                           1.0 as score
                    FROM memories
                    ORDER BY created_at DESC
                    LIMIT ?
                """
                cursor = self._connection.execute(sql, (max_results,))
                results.extend(self._process_search_results(cursor))
            
            # Remove duplicates and apply filters
            unique_results = []
            seen_ids = set()
            for result in results:
                if result['id'] not in seen_ids and self._matches_filters(result, filters):
                    unique_results.append(result)
                    seen_ids.add(result['id'])
            
            self._update_stats('search')
            return unique_results[:max_results]
            
        except Exception as e:
            raise MemoryProviderError(f"Search failed: {str(e)}")
    
    def _process_search_results(self, cursor) -> List[Dict[str, Any]]:
        """Process database cursor results into standard format."""
        results = []
        for row in cursor.fetchall():
            result = {
                'id': row['id'],
                'content': row['content'],
                'metadata': json.loads(row['metadata']),
                'categories': json.loads(row['categories']),
                'score': float(row['score']),
                'created_at': row['created_at']
            }
            results.append(result)
        return results
    
    async def _vector_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Perform in-memory vector search."""
        if not self.enable_embeddings or not self._embedder:
            return []

        query_vector = np.array(self._embedder([query])[0])

        # Fetch all records with embeddings
        cursor = self._connection.execute("SELECT id, content, metadata, categories, embedding, created_at FROM memories WHERE embedding IS NOT NULL")
        all_memories = cursor.fetchall()

        if not all_memories:
            return []

        # Calculate cosine similarity in-memory
        ids = [row['id'] for row in all_memories]
        contents = [row['content'] for row in all_memories]
        metadatas = [json.loads(row['metadata']) for row in all_memories]
        categories_list = [json.loads(row['categories']) for row in all_memories]
        created_ats = [row['created_at'] for row in all_memories]
        
        db_vectors = np.array([json.loads(row['embedding']) for row in all_memories])
        
        # Normalize vectors
        query_norm = query_vector / np.linalg.norm(query_vector)
        db_norms = np.linalg.norm(db_vectors, axis=1)
        db_vectors_normalized = db_vectors / db_norms[:, np.newaxis]
        
        # Cosine similarity
        scores = np.dot(db_vectors_normalized, query_norm)

        # Get top N results
        top_indices = np.argsort(scores)[::-1][:max_results]

        return [{
            'id': ids[i],
            'content': contents[i],
            'metadata': metadatas[i],
            'categories': categories_list[i],
            'created_at': created_ats[i],
            'score': scores[i]
        } for i in top_indices if scores[i] > 0] # Return only if score is positive
    
    async def _fuzzy_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Implement fuzzy search using edit distance."""
        try:
            # Simple fuzzy search using LIKE with variations
            query_words = query.lower().split()
            fuzzy_patterns = []
            
            for word in query_words:
                # Add variations: missing characters, extra characters, swapped
                if len(word) > 3:
                    fuzzy_patterns.extend([
                        f"%{word[:-1]}%",  # Missing last char
                        f"%{word[1:]}%",   # Missing first char
                        f"%{word}%",       # Exact
                    ])
                else:
                    fuzzy_patterns.append(f"%{word}%")
            
            results = []
            for pattern in fuzzy_patterns[:3]:  # Limit patterns to avoid too many queries
                sql = """
                    SELECT id, content, metadata, categories, created_at,
                           0.7 as score
                    FROM memories
                    WHERE content LIKE ? COLLATE NOCASE
                    LIMIT ?
                """
                cursor = self._connection.execute(sql, (pattern, max_results))
                results.extend(self._process_search_results(cursor))
                
                if len(results) >= max_results:
                    break
            
            return results[:max_results]
            
        except Exception as e:
            logger.warning(f"Fuzzy search error: {str(e)}")
            return []
    
    async def _glob_search(self, query: str, max_results: int) -> List[Dict[str, Any]]:
        """Implement glob-style pattern search."""
        try:
            # Convert simple glob patterns to SQL LIKE patterns
            if '*' in query or '?' in query:
                # Convert glob to SQL LIKE
                sql_pattern = query.replace('*', '%').replace('?', '_')
                
                sql = """
                    SELECT id, content, metadata, categories, created_at,
                           0.8 as score
                    FROM memories
                    WHERE content LIKE ? COLLATE NOCASE
                    LIMIT ?
                """
                cursor = self._connection.execute(sql, (sql_pattern, max_results))
                return self._process_search_results(cursor)
            
            return []
            
        except Exception as e:
            logger.warning(f"Glob search error: {str(e)}")
            return []
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            cursor = self._connection.execute("""
                SELECT id, content, metadata, categories, created_at, updated_at
                FROM memories
                WHERE id = ?
            """, (memory_id,))
            
            row = cursor.fetchone()
            if not row:
                return None
            
            return {
                'id': row['id'],
                'content': row['content'],
                'metadata': json.loads(row['metadata']),
                'categories': json.loads(row['categories']),
                'created_at': row['created_at'],
                'updated_at': row['updated_at']
            }
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to get memory: {str(e)}")
    
    async def update_memory(
        self, 
        memory_id: str, 
        content: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update an existing memory entry."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            # Check if memory exists
            existing = await self.get_memory(memory_id)
            if not existing:
                return False
            
            # Prepare update fields
            updates = []
            params = []
            
            if content is not None:
                updates.append("content = ?")
                params.append(content)
                updates.append("content_hash = ?")
                params.append(self._generate_content_hash(content))
                if self.enable_embeddings and self._embedder:
                    vector = self._embedder([content])[0]
                    updates.append("embedding = ?")
                    # Ensure vector is a plain list for JSON serialization
                    params.append(json.dumps(vector.tolist() if hasattr(vector, 'tolist') else list(vector)))
            
            if metadata is not None:
                updates.append("metadata = ?")
                params.append(json.dumps(metadata))
            
            if updates:
                updates.append("updated_at = ?")
                params.append(datetime.now().isoformat())
                params.append(memory_id)
                
                sql = f"UPDATE memories SET {', '.join(updates)} WHERE id = ?"
                self._connection.execute(sql, params)
                self._connection.commit()
            
            return True
            
        except Exception as e:
            self._connection.rollback()
            raise MemoryProviderError(f"Failed to update memory: {str(e)}")
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            cursor = self._connection.execute("DELETE FROM memories WHERE id = ?", (memory_id,))
            self._connection.commit()
            
            if cursor.rowcount > 0:
                self._update_stats('delete')
                return True
            return False
            
        except Exception as e:
            self._connection.rollback()
            raise MemoryProviderError(f"Failed to delete memory: {str(e)}")
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get database statistics."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            # Get total count
            total_count = self._get_total_count()
            
            # Get database size
            db_size = self.db_path.stat().st_size if self.db_path.exists() else 0
            
            # Get oldest and newest entries
            cursor = self._connection.execute("""
                SELECT MIN(created_at) as oldest, MAX(created_at) as newest
                FROM memories
            """)
            row = cursor.fetchone()
            
            return {
                'provider_type': 'sqlite',
                'database_path': str(self.db_path),
                'total_memories': total_count,
                'database_size_bytes': db_size,
                'database_size_mb': round(db_size / (1024 * 1024), 2),
                'oldest_memory': row['oldest'],
                'newest_memory': row['newest'],
                'fts_enabled': self.enable_fts,
                'embeddings_enabled': self.enable_embeddings,
                'searches_performed': self._stats['searches_performed'],
                'last_updated': self._stats['last_updated']
            }
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to get stats: {str(e)}")
    
    async def backup_memories(self, backup_path: str) -> bool:
        """Backup database to a file."""
        if not self._connection:
            raise MemoryProviderError("Provider not initialized")
        
        try:
            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create backup connection
            backup_conn = sqlite3.connect(str(backup_file))
            
            # Perform backup
            self._connection.backup(backup_conn)
            backup_conn.close()
            
            logger.info(f"Database backed up to {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Backup failed: {str(e)}")
    
    async def restore_memories(self, backup_path: str) -> bool:
        """Restore database from a backup file."""
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise MemoryProviderError(f"Backup file not found: {backup_path}")
        
        try:
            # Close current connection
            if self._connection:
                self._connection.close()
            
            # Copy backup file to current database location
            import shutil
            shutil.copy2(backup_file, self.db_path)
            
            # Reinitialize
            await self._initialize_provider()
            
            logger.info(f"Database restored from {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Restore failed: {str(e)}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on SQLite database."""
        health_status = {
            'status': 'healthy',
            'checks': {},
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Check if database file exists and is accessible
            if not self.db_path.exists():
                health_status['status'] = 'unhealthy'
                health_status['checks']['database_file'] = 'Database file does not exist'
            else:
                health_status['checks']['database_file'] = 'OK'
            
            # Check connection
            if not self._connection:
                health_status['status'] = 'unhealthy'
                health_status['checks']['connection'] = 'No database connection'
            else:
                # Test query
                self._connection.execute("SELECT 1").fetchone()
                health_status['checks']['connection'] = 'OK'
            
            # Check FTS table if enabled
            if self.enable_fts and self._connection:
                try:
                    self._connection.execute("SELECT COUNT(*) FROM memories_fts").fetchone()
                    health_status['checks']['fts_table'] = 'OK'
                except Exception as e:
                    health_status['status'] = 'degraded'
                    health_status['checks']['fts_table'] = f'FTS table error: {str(e)}'
            
            # Check database integrity
            if self._connection:
                cursor = self._connection.execute("PRAGMA integrity_check")
                result = cursor.fetchone()[0]
                if result == 'ok':
                    health_status['checks']['integrity'] = 'OK'
                else:
                    health_status['status'] = 'unhealthy'
                    health_status['checks']['integrity'] = f'Integrity check failed: {result}'
            
            return health_status
            
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['checks']['general'] = f'Health check failed: {str(e)}'
            return health_status
    
    async def close(self) -> None:
        """Close database connection."""
        if self._connection:
            self._connection.close()
            self._connection = None
        await super().close()
    
    def _get_total_count(self) -> int:
        """Get total number of memories in database."""
        if not self._connection:
            return 0
        
        try:
            cursor = self._connection.execute("SELECT COUNT(*) FROM memories")
            return cursor.fetchone()[0]
        except Exception:
            return 0
    
    def _matches_filters(self, result: Dict[str, Any], filters: Optional[Dict[str, Any]]) -> bool:
        """Check if a result matches the provided filters."""
        if not filters:
            return True
        
        # Category filter
        if 'categories' in filters:
            filter_categories = filters['categories']
            if isinstance(filter_categories, str):
                filter_categories = [filter_categories]
            
            result_categories = result.get('categories', [])
            if not any(cat in result_categories for cat in filter_categories):
                return False
        
        # Date range filter
        if 'date_after' in filters or 'date_before' in filters:
            created_at = result.get('created_at', '')
            if 'date_after' in filters and created_at < filters['date_after']:
                return False
            if 'date_before' in filters and created_at > filters['date_before']:
                return False
        
        # Metadata filters
        if 'metadata' in filters:
            result_metadata = result.get('metadata', {})
            for key, value in filters['metadata'].items():
                if result_metadata.get(key) != value:
                    return False
        
        return True 