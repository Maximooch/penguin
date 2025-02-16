import logging
from abc import ABC, abstractmethod
from typing import Dict, List


class WebSearchProvider(ABC):
    """Base class for web search providers"""

    @abstractmethod
    def search(self, query: str, max_results: int = 5) -> List[Dict[str, str]]:
        """
        Execute a web search and return results

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            List of dicts containing search results with 'title' and 'snippet' keys
        """
        pass

    def format_results(self, results: List[Dict[str, str]]) -> str:
        """Default formatter for search results"""
        formatted = []
        for i, result in enumerate(results, 1):
            formatted.append(f"{i}. {result['title']}")
            formatted.append(f"   {result['snippet']}\n")
        return "\n".join(formatted)


class WebSearchTool:
    """Main web search tool that can use different search providers"""

    def __init__(self, provider: WebSearchProvider):
        self.provider = provider

    def execute_search(self, query: str, max_results: int = 5) -> str:
        """
        Execute search using configured provider and return formatted results

        Args:
            query: Search query string
            max_results: Maximum number of results to return

        Returns:
            Formatted string of search results
        """
        logger.debug(
            f"Executing search with query: '{query}', max_results: {max_results}"
        )
        try:
            results = self.provider.search(query, max_results)
            logger.debug(f"Search results: {results}")
            formatted_results = self.provider.format_results(results)
            logger.debug(f"Formatted results: {formatted_results}")
            return formatted_results
        except Exception as e:
            error_msg = f"Search failed: {str(e)}"
            logger.error(error_msg)
            return error_msg


logger = logging.getLogger(__name__)
