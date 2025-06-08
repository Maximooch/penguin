"""
File Memory Provider

Simple file-based memory provider for basic functionality without external dependencies.
Uses JSON files for storage and basic text search.
"""

import json
import logging
import os
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional
import shutil
import re

from .base import MemoryProvider, MemoryProviderError

logger = logging.getLogger(__name__)


class FileMemoryProvider(MemoryProvider):
    """
    Simple file-based memory provider using JSON storage.
    
    Features:
    - JSON file storage
    - Basic text search with regex
    - No external dependencies
    - Human-readable storage format
    - Simple backup/restore
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize file memory provider.
        
        Args:
            config: Configuration dictionary with storage options
        """
        super().__init__(config)
        
        # Configuration
        self.storage_path = Path(config.get('storage_path', './memory_db'))
        self.storage_dir = self.storage_path / config.get('storage_dir', 'file_memory')
        self.index_format = config.get('index_format', 'json')
        
        # File paths
        self.memories_dir = self.storage_dir / 'memories'
        self.index_file = self.storage_dir / 'index.json'
        self.metadata_file = self.storage_dir / 'metadata.json'
        
        # In-memory index for faster searches
        self._index = {}
        self._metadata = {
            'total_memories': 0,
            'created_at': datetime.now().isoformat(),
            'last_updated': None
        }
        
        # Create storage directories
        self._ensure_storage_dirs()
    
    def _ensure_storage_dirs(self):
        """Create storage directories if they don't exist."""
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self.memories_dir.mkdir(parents=True, exist_ok=True)
    
    async def _initialize_provider(self) -> None:
        """Initialize file provider by loading existing index."""
        try:
            # Load existing index if it exists
            if self.index_file.exists():
                with open(self.index_file, 'r', encoding='utf-8') as f:
                    self._index = json.load(f)
            
            # Load metadata if it exists
            if self.metadata_file.exists():
                with open(self.metadata_file, 'r', encoding='utf-8') as f:
                    stored_metadata = json.load(f)
                    self._metadata.update(stored_metadata)
            
            # Update stats from metadata
            self._stats['total_memories'] = self._metadata.get('total_memories', 0)
            
            logger.info(f"File memory provider initialized at {self.storage_dir}")
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to initialize file provider: {str(e)}")
    
    async def add_memory(
        self, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None, 
        categories: Optional[List[str]] = None
    ) -> str:
        """Add a new memory entry as a JSON file."""
        try:
            memory_id = str(uuid.uuid4())
            content_hash = self._generate_content_hash(content)
            now = datetime.now().isoformat()
            
            # Create memory data
            memory_data = {
                'id': memory_id,
                'content': content,
                'content_hash': content_hash,
                'metadata': metadata or {},
                'categories': categories or [],
                'created_at': now,
                'updated_at': now
            }
            
            # Save memory to file
            memory_file = self.memories_dir / f"{memory_id}.json"
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)
            
            # Update index
            self._index[memory_id] = {
                'file_path': str(memory_file),
                'content_preview': content[:100],  # First 100 chars for search
                'categories': categories or [],
                'created_at': now,
                'content_hash': content_hash
            }
            
            # Save index and metadata
            await self._save_index()
            await self._update_metadata('add')
            
            logger.debug(f"Added memory {memory_id}")
            return memory_id
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to add memory: {str(e)}")
    
    async def search_memory(
        self, 
        query: str, 
        max_results: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Search memories using basic text matching."""
        try:
            results = []
            query_lower = query.lower().strip()
            
            # Search through index
            for memory_id, index_entry in self._index.items():
                memory_data = await self._load_memory_file(memory_id)
                if not memory_data:
                    continue
                
                # Calculate relevance score
                score = self._calculate_relevance_score(memory_data, query_lower)
                
                if score > 0:
                    result = {
                        'id': memory_id,
                        'content': memory_data['content'],
                        'metadata': memory_data['metadata'],
                        'categories': memory_data['categories'],
                        'score': score,
                        'created_at': memory_data['created_at']
                    }
                    
                    # Apply filters
                    if self._matches_filters(result, filters):
                        results.append(result)
            
            # Sort by score and limit results
            results.sort(key=lambda x: x['score'], reverse=True)
            results = results[:max_results]
            
            # If no query provided, return recent memories
            if not query.strip() and not results:
                results = await self._get_recent_memories(max_results, filters)
            
            self._update_stats('search')
            return results
            
        except Exception as e:
            raise MemoryProviderError(f"Search failed: {str(e)}")
    
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific memory by ID."""
        try:
            return await self._load_memory_file(memory_id)
        except Exception as e:
            raise MemoryProviderError(f"Failed to get memory: {str(e)}")
    
    async def update_memory(
        self, 
        memory_id: str, 
        content: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """Update an existing memory entry."""
        try:
            memory_data = await self._load_memory_file(memory_id)
            if not memory_data:
                return False
            
            # Update fields
            if content is not None:
                memory_data['content'] = content
                memory_data['content_hash'] = self._generate_content_hash(content)
                
                # Update index preview
                self._index[memory_id]['content_preview'] = content[:100]
                self._index[memory_id]['content_hash'] = memory_data['content_hash']
            
            if metadata is not None:
                memory_data['metadata'] = metadata
            
            memory_data['updated_at'] = datetime.now().isoformat()
            
            # Save updated memory
            memory_file = Path(self._index[memory_id]['file_path'])
            with open(memory_file, 'w', encoding='utf-8') as f:
                json.dump(memory_data, f, indent=2, ensure_ascii=False)
            
            # Save updated index
            await self._save_index()
            
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to update memory: {str(e)}")
    
    async def delete_memory(self, memory_id: str) -> bool:
        """Delete a memory entry."""
        try:
            if memory_id not in self._index:
                return False
            
            # Delete memory file
            memory_file = Path(self._index[memory_id]['file_path'])
            if memory_file.exists():
                memory_file.unlink()
            
            # Remove from index
            del self._index[memory_id]
            
            # Save index and update metadata
            await self._save_index()
            await self._update_metadata('delete')
            
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to delete memory: {str(e)}")
    
    async def get_memory_stats(self) -> Dict[str, Any]:
        """Get file storage statistics."""
        try:
            total_size = 0
            file_count = 0
            
            # Calculate directory size
            for file_path in self.memories_dir.glob('*.json'):
                total_size += file_path.stat().st_size
                file_count += 1
            
            return {
                'provider_type': 'file',
                'storage_path': str(self.storage_dir),
                'total_memories': len(self._index),
                'total_files': file_count,
                'total_size_bytes': total_size,
                'total_size_mb': round(total_size / (1024 * 1024), 2),
                'oldest_memory': self._get_oldest_memory(),
                'newest_memory': self._get_newest_memory(),
                'searches_performed': self._stats['searches_performed'],
                'last_updated': self._stats['last_updated']
            }
            
        except Exception as e:
            raise MemoryProviderError(f"Failed to get stats: {str(e)}")
    
    async def backup_memories(self, backup_path: str) -> bool:
        """Backup all memories to a compressed archive."""
        try:
            backup_file = Path(backup_path)
            backup_file.parent.mkdir(parents=True, exist_ok=True)
            
            # Create backup archive
            shutil.make_archive(
                str(backup_file.with_suffix('')),  # Remove .zip extension
                'zip',
                self.storage_dir
            )
            
            logger.info(f"Memories backed up to {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Backup failed: {str(e)}")
    
    async def restore_memories(self, backup_path: str) -> bool:
        """Restore memories from a backup archive."""
        backup_file = Path(backup_path)
        if not backup_file.exists():
            raise MemoryProviderError(f"Backup file not found: {backup_path}")
        
        try:
            # Create temporary directory for extraction
            temp_dir = self.storage_dir.parent / 'temp_restore'
            temp_dir.mkdir(exist_ok=True)
            
            # Extract backup
            shutil.unpack_archive(backup_file, temp_dir)
            
            # Replace current storage with backup
            if self.storage_dir.exists():
                shutil.rmtree(self.storage_dir)
            
            # Move extracted content
            extracted_dir = temp_dir / self.storage_dir.name
            if extracted_dir.exists():
                shutil.move(str(extracted_dir), str(self.storage_dir))
            else:
                # Backup might be the entire storage directory
                shutil.move(str(temp_dir), str(self.storage_dir))
            
            # Clean up temp directory
            if temp_dir.exists():
                shutil.rmtree(temp_dir)
            
            # Reinitialize
            await self._initialize_provider()
            
            logger.info(f"Memories restored from {backup_path}")
            return True
            
        except Exception as e:
            raise MemoryProviderError(f"Restore failed: {str(e)}")
    
    async def health_check(self) -> Dict[str, Any]:
        """Perform health check on file storage."""
        health_status = {
            'status': 'healthy',
            'checks': {},
            'timestamp': datetime.now().isoformat()
        }
        
        try:
            # Check if storage directory exists and is writable
            if not self.storage_dir.exists():
                health_status['status'] = 'unhealthy'
                health_status['checks']['storage_directory'] = 'Storage directory does not exist'
            elif not os.access(self.storage_dir, os.W_OK):
                health_status['status'] = 'unhealthy'
                health_status['checks']['storage_directory'] = 'Storage directory is not writable'
            else:
                health_status['checks']['storage_directory'] = 'OK'
            
            # Check index file integrity
            if self.index_file.exists():
                try:
                    with open(self.index_file, 'r') as f:
                        json.load(f)
                    health_status['checks']['index_file'] = 'OK'
                except json.JSONDecodeError:
                    health_status['status'] = 'degraded'
                    health_status['checks']['index_file'] = 'Index file is corrupted'
            else:
                health_status['checks']['index_file'] = 'Index file missing (will be created)'
            
            # Check memory files consistency
            missing_files = 0
            for memory_id, index_entry in self._index.items():
                memory_file = Path(index_entry['file_path'])
                if not memory_file.exists():
                    missing_files += 1
            
            if missing_files > 0:
                health_status['status'] = 'degraded'
                health_status['checks']['memory_files'] = f'{missing_files} memory files missing'
            else:
                health_status['checks']['memory_files'] = 'OK'
            
            return health_status
            
        except Exception as e:
            health_status['status'] = 'unhealthy'
            health_status['checks']['general'] = f'Health check failed: {str(e)}'
            return health_status
    
    async def _load_memory_file(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """Load memory data from file."""
        if memory_id not in self._index:
            return None
        
        try:
            memory_file = Path(self._index[memory_id]['file_path'])
            if not memory_file.exists():
                return None
            
            with open(memory_file, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            return None
    
    async def _save_index(self):
        """Save the in-memory index to file."""
        try:
            with open(self.index_file, 'w', encoding='utf-8') as f:
                json.dump(self._index, f, indent=2, ensure_ascii=False)
        except Exception as e:
            raise MemoryProviderError(f"Failed to save index: {str(e)}")
    
    async def _update_metadata(self, operation: str):
        """Update and save metadata."""
        if operation == 'add':
            self._metadata['total_memories'] += 1
        elif operation == 'delete':
            self._metadata['total_memories'] = max(0, self._metadata['total_memories'] - 1)
        
        self._metadata['last_updated'] = datetime.now().isoformat()
        
        try:
            with open(self.metadata_file, 'w', encoding='utf-8') as f:
                json.dump(self._metadata, f, indent=2, ensure_ascii=False)
            
            self._update_stats(operation)
        except Exception as e:
            logger.warning(f"Failed to save metadata: {str(e)}")
    
    def _calculate_relevance_score(self, memory_data: Dict[str, Any], query: str) -> float:
        """Calculate relevance score for a memory based on query."""
        if not query:
            return 1.0  # Default score for empty query
        
        score = 0.0
        content = memory_data.get('content', '').lower()
        
        # Exact phrase match (highest score)
        if query in content:
            score += 2.0
        
        # Word matches
        query_words = query.split()
        content_words = content.split()
        
        for word in query_words:
            if word in content_words:
                score += 1.0
            else:
                # Partial word matches
                for content_word in content_words:
                    if word in content_word or content_word in word:
                        score += 0.5
                        break
        
        # Category matches
        categories = memory_data.get('categories', [])
        for category in categories:
            if query in category.lower():
                score += 0.5
        
        # Normalize score by content length (prefer shorter, more relevant content)
        if len(content) > 0:
            score = score / (len(content) / 1000 + 1)
        
        return score
    
    async def _get_recent_memories(self, max_results: int, filters: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Get recent memories when no query is provided."""
        memories = []
        
        # Sort index entries by creation time
        sorted_entries = sorted(
            self._index.items(),
            key=lambda x: x[1]['created_at'],
            reverse=True
        )
        
        for memory_id, _ in sorted_entries[:max_results * 2]:  # Get extra in case of filters
            memory_data = await self._load_memory_file(memory_id)
            if memory_data:
                result = {
                    'id': memory_id,
                    'content': memory_data['content'],
                    'metadata': memory_data['metadata'],
                    'categories': memory_data['categories'],
                    'score': 1.0,
                    'created_at': memory_data['created_at']
                }
                
                if self._matches_filters(result, filters):
                    memories.append(result)
                    if len(memories) >= max_results:
                        break
        
        return memories
    
    def _get_oldest_memory(self) -> Optional[str]:
        """Get the timestamp of the oldest memory."""
        if not self._index:
            return None
        
        oldest = min(self._index.values(), key=lambda x: x['created_at'])
        return oldest['created_at']
    
    def _get_newest_memory(self) -> Optional[str]:
        """Get the timestamp of the newest memory."""
        if not self._index:
            return None
        
        newest = max(self._index.values(), key=lambda x: x['created_at'])
        return newest['created_at']
    
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