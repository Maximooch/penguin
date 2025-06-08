"""
Enhanced Memory Provider Base Classes

Provides the abstract base class and common utilities for all memory providers.
"""

import asyncio
import hashlib
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

logger = logging.getLogger(__name__)


class MemoryProviderError(Exception):
    """Base exception for memory provider errors"""
    pass


class MemoryProvider(ABC):
    """
    Enhanced abstract base class for memory providers.
    
    Defines a comprehensive interface for storing, searching, and managing
    memories across different backend implementations.
    """
    
    def __init__(self, config: Dict[str, Any]):
        """
        Initialize the memory provider with configuration.
        
        Args:
            config: Provider-specific configuration dictionary
        """
        self.config = config
        self.embedding_model = config.get('embedding_model', 'sentence-transformers/all-MiniLM-L6-v2')
        self._initialized = False
        self._stats = {
            'total_memories': 0,
            'searches_performed': 0,
            'last_updated': None
        }
    
    async def initialize(self) -> None:
        """Initialize the provider. Must be called before use."""
        if not self._initialized:
            await self._initialize_provider()
            self._initialized = True
            logger.info(f"Initialized {self.__class__.__name__}")
    
    @abstractmethod
    async def _initialize_provider(self) -> None:
        """Provider-specific initialization logic."""
        pass
    
    @abstractmethod
    async def add_memory(
        self, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None, 
        categories: Optional[List[str]] = None
    ) -> str:
        """
        Add a new memory entry.
        
        Args:
            content: The content to be stored
            metadata: Optional metadata associated with the content
            categories: Optional list of categories for the memory
            
        Returns:
            A unique identifier for the stored memory
            
        Raises:
            MemoryProviderError: If the operation fails
        """
        pass
    
    @abstractmethod
    async def search_memory(
        self, 
        query: str, 
        max_results: int = 5, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        Search for relevant memories.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            filters: Optional filters to apply to the search
            
        Returns:
            List of dicts containing search results with 'content', 'metadata', 
            'score', and 'id' keys
            
        Raises:
            MemoryProviderError: If the search fails
        """
        pass
    
    @abstractmethod
    async def get_memory(self, memory_id: str) -> Optional[Dict[str, Any]]:
        """
        Get a specific memory by ID.
        
        Args:
            memory_id: Unique identifier of the memory
            
        Returns:
            Dictionary containing memory data or None if not found
        """
        pass
    
    @abstractmethod
    async def update_memory(
        self, 
        memory_id: str, 
        content: Optional[str] = None, 
        metadata: Optional[Dict[str, Any]] = None
    ) -> bool:
        """
        Update an existing memory entry.
        
        Args:
            memory_id: Unique identifier of the memory to update
            content: New content (if provided)
            metadata: New metadata (if provided)
            
        Returns:
            True if successful, False if memory not found
            
        Raises:
            MemoryProviderError: If the operation fails
        """
        pass
    
    @abstractmethod
    async def delete_memory(self, memory_id: str) -> bool:
        """
        Delete a memory entry.
        
        Args:
            memory_id: Unique identifier of the memory to delete
            
        Returns:
            True if successful, False if memory not found
            
        Raises:
            MemoryProviderError: If the operation fails
        """
        pass
    
    @abstractmethod
    async def get_memory_stats(self) -> Dict[str, Any]:
        """
        Get statistics about the memory store.
        
        Returns:
            Dictionary containing statistics like total memories, 
            storage size, etc.
        """
        pass
    
    @abstractmethod
    async def backup_memories(self, backup_path: str) -> bool:
        """
        Backup all memories to a file.
        
        Args:
            backup_path: Path where backup should be saved
            
        Returns:
            True if successful
            
        Raises:
            MemoryProviderError: If backup fails
        """
        pass
    
    @abstractmethod
    async def restore_memories(self, backup_path: str) -> bool:
        """
        Restore memories from a backup file.
        
        Args:
            backup_path: Path to backup file
            
        Returns:
            True if successful
            
        Raises:
            MemoryProviderError: If restore fails
        """
        pass
    
    @abstractmethod
    async def health_check(self) -> Dict[str, Any]:
        """
        Perform a health check on the provider.
        
        Returns:
            Dictionary containing health status and metrics
        """
        pass
    
    async def list_memories(
        self, 
        limit: int = 100, 
        offset: int = 0, 
        filters: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """
        List memories with pagination support.
        
        Args:
            limit: Maximum number of memories to return
            offset: Number of memories to skip
            filters: Optional filters to apply
            
        Returns:
            List of memory dictionaries
        """
        # Default implementation using search with empty query
        # Providers can override for more efficient listing
        all_results = await self.search_memory("", max_results=limit + offset, filters=filters)
        return all_results[offset:offset + limit]
    
    def format_results(self, results: List[Dict[str, Any]]) -> str:
        """
        Format search results for display.
        
        Args:
            results: List of search result dictionaries
            
        Returns:
            Formatted string representation of results
        """
        if not results:
            return "No results found."
        
        formatted = []
        for i, result in enumerate(results, 1):
            content = result.get('content', '')
            # Truncate long content
            if len(content) > 200:
                content = content[:200] + "..."
            
            formatted.append(f"{i}. Score: {result.get('score', 0):.3f}")
            formatted.append(f"   Content: {content}")
            
            metadata = result.get('metadata', {})
            if metadata:
                formatted.append(f"   Metadata: {metadata}")
            
            formatted.append(f"   ID: {result.get('id', 'unknown')}")
            formatted.append("")
        
        return "\n".join(formatted)
    
    def _generate_content_hash(self, content: str) -> str:
        """Generate a hash for content deduplication."""
        return hashlib.sha256(content.encode('utf-8')).hexdigest()[:16]
    
    def _update_stats(self, operation: str, **kwargs):
        """Update internal statistics."""
        if operation == 'add':
            self._stats['total_memories'] += 1
        elif operation == 'search':
            self._stats['searches_performed'] += 1
        elif operation == 'delete':
            self._stats['total_memories'] = max(0, self._stats['total_memories'] - 1)
        
        self._stats['last_updated'] = datetime.now().isoformat()
    
    async def close(self) -> None:
        """Close the provider and clean up resources."""
        # Default implementation - providers can override
        self._initialized = False
        logger.info(f"Closed {self.__class__.__name__}")


class MemoryTool:
    """
    Enhanced memory tool that uses the new provider system.
    
    Provides a high-level interface for memory operations while delegating
    to the configured provider implementation.
    """
    
    def __init__(self, provider: MemoryProvider):
        """
        Initialize with a memory provider.
        
        Args:
            provider: The memory provider to use
        """
        self.provider = provider
    
    async def add_memory(
        self, 
        content: str, 
        metadata: Optional[Dict[str, Any]] = None,
        categories: Optional[List[str]] = None
    ) -> str:
        """
        Add a new memory entry using the configured provider.
        
        Args:
            content: The content to be stored
            metadata: Optional metadata associated with the content
            categories: Optional list of categories
            
        Returns:
            Success message with memory ID
        """
        try:
            if not self.provider._initialized:
                await self.provider.initialize()
            
            memory_id = await self.provider.add_memory(content, metadata, categories)
            return f"Memory added successfully. ID: {memory_id}"
        except Exception as e:
            error_msg = f"Failed to add memory: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    async def search_memory(
        self, 
        query: str, 
        max_results: int = 5,
        filters: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Search for relevant memories using the configured provider.
        
        Args:
            query: Search query string
            max_results: Maximum number of results to return
            filters: Optional filters to apply
            
        Returns:
            Formatted string of search results
        """
        try:
            if not self.provider._initialized:
                await self.provider.initialize()
            
            results = await self.provider.search_memory(query, max_results, filters)
            return self.provider.format_results(results)
        except Exception as e:
            error_msg = f"Memory search failed: {str(e)}"
            logger.error(error_msg)
            return error_msg
    
    async def get_stats(self) -> str:
        """Get memory system statistics."""
        try:
            if not self.provider._initialized:
                await self.provider.initialize()
            
            stats = await self.provider.get_memory_stats()
            formatted_stats = []
            for key, value in stats.items():
                formatted_stats.append(f"{key}: {value}")
            
            return "\n".join(formatted_stats)
        except Exception as e:
            error_msg = f"Failed to get memory stats: {str(e)}"
            logger.error(error_msg)
            return error_msg 