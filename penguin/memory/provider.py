from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional


class MemoryProvider(ABC):
    """Base class for memory providers"""

    @abstractmethod
    def add_memory(
        self, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a new memory entry

        Args:
            content: The content to be stored
            metadata: Optional metadata associated with the content

        Returns:
            A unique identifier for the stored memory
        """
        pass

    @abstractmethod
    def search_memory(self, query: str, max_results: int = 5) -> List[Dict[str, Any]]:
        """
        Search for relevant memories

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of dicts containing search results with 'content' and 'metadata' keys
        """
        pass

    def format_results(self, results: List[Dict[str, Any]]) -> str:
        """Default formatter for memory search results"""
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"{i}. Content: {result['content']}")
            if result.get("metadata"):
                formatted.append(f"   Metadata: {result['metadata']}")
            formatted.append("")
        return "\n".join(formatted)


class MemoryTool:
    """Main memory tool that can use different memory providers"""

    def __init__(self, provider: MemoryProvider):
        self.provider = provider

    def add_memory(
        self, content: str, metadata: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Add a new memory entry using the configured provider

        Args:
            content: The content to be stored
            metadata: Optional metadata associated with the content

        Returns:
            A unique identifier for the stored memory
        """
        try:
            memory_id = self.provider.add_memory(content, metadata)
            return f"Memory added successfully. ID: {memory_id}"
        except Exception as e:
            error_msg = f"Failed to add memory: {str(e)}"
            logger.error(error_msg)
            return error_msg

    def search_memory(self, query: str, max_results: int = 5) -> str:
        """
        Search for relevant memories using the configured provider

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            Formatted string of search results
        """
        try:
            results = self.provider.search_memory(query, max_results)
            formatted_results = self.provider.format_results(results)
            return formatted_results
        except Exception as e:
            error_msg = f"Memory search failed: {str(e)}"
            logger.error(error_msg)
            return error_msg


import logging

logger = logging.getLogger(__name__)
