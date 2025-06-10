"""
FAISS Memory Provider

High-performance vector search provider using FAISS for semantic similarity.
Requires: pip install faiss-cpu sentence-transformers
"""

import json
import logging
import os
import pickle
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from .base import MemoryProvider, MemoryProviderError

logger = logging.getLogger(__name__)


class FAISSMemoryProvider(MemoryProvider):
    """
    High-performance memory provider using FAISS for vector search.
    
    Features:
    - Fast vector similarity search using FAISS
    - Sentence transformer embeddings
    - Persistent storage of index and metadata
    - Configurable index types
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize FAISS memory provider.
        
        Args:
            config: Configuration dictionary with FAISS-specific options
        """
        super().__init__(config)
        
        # Configuration
        self.storage_path = Path(config.get('storage_path', './memory_db'))
        self.storage_dir = self.storage_path / config.get('storage_dir', 'faiss_memory')
        self.index_type = config.get('index_type', 'IndexFlatIP')
        self.dimension = config.get('dimension', 384)  # Default for all-MiniLM-L6-v2
        
        # File paths
        self.index_file = self.storage_dir / 'faiss.index'
        self.metadata_file = self.storage_dir / 'metadata.json'
        self.embeddings_file = self.storage_dir / 'embeddings.pkl'
        
        # Runtime objects
        self._faiss = None
        self._embedding_model = None
        self._index = None
        self._metadata = {}
        
        # Create storage directory
        self.storage_dir.mkdir(parents=True, exist_ok=True)
    
    async def _initialize_provider(self) -> None:
        """Initialize FAISS provider with embeddings model."""
        try:
            # Import FAISS
            import faiss
            self._faiss = faiss
            
            # Import sentence transformers
            from sentence_transformers import SentenceTransformer
            self._embedding_model = SentenceTransformer(self.embedding_model)
            
            # Load or create FAISS index
            if self.index_file.exists():
                self._index = faiss.read_index(str(self.index_file))
                logger.info(f"Loaded existing FAISS index with {self._index.ntotal} vectors")
            else:
                # Create new index based on type
                if self.index_type == 'IndexFlatIP':
                    self._index = faiss.IndexFlatIP(self.dimension)
                elif self.index_type == 'IndexFlatL2':
                    self._index = faiss.IndexFlatL2(self.dimension)
                else:
                    # Default to Inner Product
                    self._index = faiss.IndexFlatIP(self.dimension)
                
                logger.info(f"Created new FAISS index: {self.index_type}")
            
            # Load metadata
            if self.metadata_file.exists():
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    self._metadata = json.load(f)
            
            logger.info(f"FAISS memory provider initialized at {self.storage_dir}")
            
        except ImportError as e:
            raise MemoryProviderError(f"FAISS dependencies missing: {str(e)}. Install with: pip install faiss-cpu sentence-transformers")
        except Exception as e:
            raise MemoryProviderError(f"Failed to initialize FAISS provider: {str(e)}")
    
    async def add_memory(
        self, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None, 
        categories: Optional[List[str]] = None
    ) -> str:
        """Add a new memory entry with vector embedding."""
        if not self._initialized:
            await self.initialize()

        if not self._index or not self._embedding_model:
            raise MemoryProviderError("Provider components are missing after initialization.")
        
        try:
            memory_id = str(uuid.uuid4())
            
            # Generate embedding
            embedding = self._embedding_model.encode([content])
            
            # Add to FAISS index
            self._index.add(embedding)
            
            # Store metadata
            self._metadata[memory_id] = {
                'content': content,
                'metadata': metadata or {},
                'categories': categories or [],
                'created_at': datetime.now().isoformat(),
                'index_position': self._index.ntotal - 1  # Position in FAISS index
            }
            
            # Save to disk
            await self._save_index_and_metadata()
            self._update_stats('add')
            
            logger.debug(f"Added memory {memory_id} to FAISS index")
            return memory_id
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to add memory: {str(e)}")
    
    async def search_memory(
        self, 
        query: str, 
        max_results: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search memories using vector similarity."""
        if not self._initialized:
            await self.initialize()

        if not self._index or not self._embedding_model:
            raise MemoryProviderError("Provider components are missing after initialization.")
        
        try:
            if not query.strip():
                # Return recent memories if no query
                return await self._get_recent_memories(max_results, filters)
            
            # Generate query embedding
            query_embedding = self._embedding_model.encode([query])
            
            # Prevent searching on an empty index
            if self._index.ntotal == 0:
                logger.warning("Attempted to search an empty FAISS index. Returning no results.")
                return []
            
            # Search FAISS index
            distances, indices = self._index.search(query_embedding, min(max_results, self._index.ntotal))
            
            results = []
            for distance, index in zip(distances[0], indices[0]):
                if index == -1:  # FAISS returns -1 for invalid indices
                    continue
                
                # Find metadata by index position
                memory_data = None
                for memory_id, meta in self._metadata.items():
                    if meta.get('index_position') == index:
                        memory_data = meta
                        memory_data['id'] = memory_id
                        break
                
                if memory_data:
                    result = {
                        'id': memory_data['id'],
                        'content': memory_data['content'],
                        'metadata': memory_data['metadata'],
                        'categories': memory_data['categories'],
                        'score': float(distance),  # FAISS distance as score
                        'created_at': memory_data['created_at']
                    }
                    
                    # Apply filters
                    if self._matches_filters(result, filters):
                        results.append(result)
            
            self._update_stats('search')
            return results[:max_results]
            
        except Exception as e:
            raise MemoryProviderError(f"Search failed: {str(e)}")
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        if memory_id not in self._metadata:
            return None
        
        memory_data = self._metadata[memory_id].copy()
        memory_data['id'] = memory_id
        return memory_data
    
    async def update_memory(
        self, 
        memory_id: str, 
        content: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update an existing memory entry."""
        if memory_id not in self._metadata:
            return False
        
        try:
            memory_data = self._metadata[memory_id]
            
            # If content changed, need to regenerate embedding and update index
            if content is not None and content != memory_data['content']:
                # For simplicity in Stage 1, we'll recreate the entire index
                # In Stage 2, we could implement more efficient updates
                old_index_pos = memory_data['index_position']
                
                # Generate new embedding
                new_embedding = self._embedding_model.encode([content])
                
                # For now, we'll mark the old entry as deleted and add a new one
                # This is not optimal but works for Stage 1
                self._index.add(new_embedding)
                memory_data['content'] = content
                memory_data['index_position'] = self._index.ntotal - 1
            
            if metadata is not None:
                memory_data['metadata'] = metadata
            
            memory_data['updated_at'] = datetime.now().isoformat()
            
            await self._save_index_and_metadata()
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to update memory: {str(e)}")
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry."""
        if memory_id not in self._metadata:
            return False
        
        try:
            # Remove from metadata (FAISS index cleanup would be done in Stage 2)
            del self._metadata[memory_id]
            
            await self._save_index_and_metadata()
            self._update_stats('delete')
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to delete memory: {str(e)}")
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get FAISS storage statistics."""
        try:
            total_size = 0
            if self.storage_dir.exists():
                for file_path in self.storage_dir.glob('*'):
                    total_size += file_path.stat().st_size
            
            return {
                'provider_type': 'faiss',
                'storage_path': str(self.storage_dir),
                'total_memories': len(self._metadata),
                'faiss_index_size': self._index.ntotal if self._index else 0,
                'index_type': self.index_type,
                'dimension': self.dimension,
                'storage_size_bytes': total_size,
                'storage_size_mb': round(total_size / (1024 * 1024), 2),
                'embedding_model': self.embedding_model,
                'searches_performed': self._stats['searches_performed'],
                'last_updated': self._stats['last_updated']
            }
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to get stats: {str(e)}")
    
    async def backup_memories(self, backup_path: str) -> bool:
        """Backup FAISS index and metadata."""
        try:
            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create backup archive
            import shutil
            shutil.make_archive(
                str(backup_file.with_suffix('')),
                'zip',
                self.storage_dir
            )
            
            logger.info(f"FAISS memories backed up to {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Backup failed: {str(e)}")
    
    async def restore_memories(self, backup_path: str) -> bool:
        """Restore FAISS index and metadata from backup."""
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise MemoryProviderError(f"Backup file not found: {backup_path}")
        
        try:
            # Extract backup
            import shutil
            temp_dir = self.storage_dir.parent / 'temp_restore'
            temp_dir.mkdir(exist_ok=True)
            
            shutil.unpack_archive(backup_file, temp_dir)
            
            # Replace current storage
            if self.storage_dir.exists():
                shutil.rmtree(self.storage_dir)
            
            extracted_dir = temp_dir / self.storage_dir.name
            if extracted_dir.exists():
                shutil.move(str(extracted_dir), str(self.storage_dir))
            
            # Clean up
            shutil.rmtree(temp_dir)
            
            # Reinitialize
            await self._initialize_provider()
            
            logger.info(f"FAISS memories restored from {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Restore failed: {str(e)}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on FAISS provider."""
        health_status = {
            'status': 'healthy',
            'checks': {},
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Check FAISS availability
            try:
                import faiss
                health_status['checks']['faiss_import'] = 'OK'
            except ImportError:
                health_status['status'] = 'unhealthy'
                health_status['checks']['faiss_import'] = 'FAISS not available - install with: pip install faiss-cpu'
            
            # Check sentence transformers
            try:
                from sentence_transformers import SentenceTransformer
                health_status['checks']['sentence_transformers'] = 'OK'
            except ImportError:
                health_status['status'] = 'unhealthy'
                health_status['checks']['sentence_transformers'] = 'sentence-transformers not available'
            
            # Check index status
            if self._index is not None:
                health_status['checks']['faiss_index'] = f'OK - {self._index.ntotal} vectors'
            else:
                health_status['status'] = 'degraded'
                health_status['checks']['faiss_index'] = 'Index not initialized'
            
            # Check storage
            if not self.storage_dir.exists():
                health_status['status'] = 'degraded'
                health_status['checks']['storage'] = 'Storage directory missing'
            else:
                health_status['checks']['storage'] = 'OK'
            
            return health_status
            
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['checks']['general'] = f'Health check failed: {str(e)}'
            return health_status
    
    async def _save_index_and_metadata(self):
        """Save FAISS index and metadata to disk."""
        try:
            # Save FAISS index
            if self._index:
                self._faiss.write_index(self._index, str(self.index_file))
            
            # Save metadata
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            raise MemoryProviderError(f"Failed to save index and metadata: {str(e)}")
    
    async def _get_recent_memories(self, max_results: int, filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get recent memories when no query is provided."""
        memories = []
        
        # Sort by creation time
        sorted_items = sorted(
            self._metadata.items(),
            key=lambda x: x[1]['created_at'],
            reverse=True
        )
        
        for memory_id, memory_data in sorted_items[:max_results * 2]:  # Get extra for filtering
            result = {
                'id': memory_id,
                'content': memory_data['content'],
                'metadata': memory_data['metadata'],
                'categories': memory_data['categories'],
                'score': 1.0,  # Default score
                'created_at': memory_data['created_at']
            }
            
            if self._matches_filters(result, filters):
                memories.append(result)
                if len(memories) >= max_results:
                    break
        
        return memories
    
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