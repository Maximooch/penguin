"""
Advanced Search Capabilities

Provides a class that orchestrates multiple search strategies, including
semantic, keyword, and AST-based searches, to provide more relevant results.
"""

import asyncio
import logging
from typing import Any, Dict, List, Optional

from penguin.memory.providers.base import MemoryProvider
from penguin.tools.core.ast_analyzer import ASTAnalyzer

logger = logging.getLogger(__name__)


class AdvancedSearch:
    """
    Performs advanced searches by combining multiple strategies.
    """

    def __init__(self, provider: MemoryProvider, ast_analyzer: Optional[ASTAnalyzer] = None):
        self.provider = provider
        self.ast_analyzer = ast_analyzer or ASTAnalyzer()

    async def search(
        self,
        query: str,
        max_results: int = 10,
        filters: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Performs a search using multiple strategies and merges the results.

        Args:
            query: The search query.
            max_results: The total maximum number of results to return.
            filters: Optional filters to apply to the searches.

        Returns:
            A ranked and deduplicated list of search results.
        """
        filters = filters or {}
        
        # Define search tasks to run in parallel
        tasks = [
            self._semantic_search(query, max_results, filters),
            self._keyword_search(query, max_results, filters),
        ]
        if self._is_code_query(query) and self.ast_analyzer:
            tasks.append(self._ast_search(query, max_results, filters))

        # Run searches concurrently
        results_from_all_searches = await asyncio.gather(*tasks, return_exceptions=True)
        
        # Flatten and filter out any exceptions/empty results
        all_results = []
        for res in results_from_all_searches:
            if isinstance(res, list):
                all_results.extend(res)

        # Merge and rank the results
        return self._merge_and_rank_results(all_results, max_results)

    async def _semantic_search(
        self, query: str, max_results: int, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Performs a semantic (vector) search."""
        logger.debug(f"Performing semantic search for: '{query}'")
        try:
            # We can hint the provider to use vector search if the provider supports it
            provider_filters = {**filters, "search_mode": "vector"}
            return await self.provider.search_memory(query, max_results, provider_filters)
        except Exception as e:
            logger.error(f"Semantic search failed: {e}")
            return []

    async def _keyword_search(
        self, query: str, max_results: int, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Performs a keyword (FTS or simple) search."""
        logger.debug(f"Performing keyword search for: '{query}'")
        try:
            # Hint the provider to use full-text search
            provider_filters = {**filters, "search_mode": "fts"}
            return await self.provider.search_memory(query, max_results, provider_filters)
        except Exception as e:
            logger.error(f"Keyword search failed: {e}")
            return []

    async def _ast_search(
        self, query: str, max_results: int, filters: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Performs an AST-aware search for code-related queries."""
        logger.debug(f"Performing AST search for: '{query}'")
        # This is a conceptual implementation. A real implementation would parse
        # the query to identify function/class names and then filter metadata.
        # For now, we'll filter based on a simple heuristic.
        
        # Example: if query is "function process_data", search for `process_data`
        # in the 'functions' field of the metadata.
        search_term = query.split()[-1] # Simplistic
        ast_filters = {**filters, "metadata_contains": ("functions", search_term)}

        try:
            return await self.provider.search_memory(
                search_term, max_results, ast_filters
            )
        except Exception as e:
            logger.error(f"AST search failed: {e}")
            return []

    def _is_code_query(self, query: str) -> bool:
        """A simple heuristic to guess if a query is code-related."""
        code_keywords = ["def", "class", "import", "function", "method", "return"]
        return any(keyword in query.lower() for keyword in code_keywords)

    def _merge_and_rank_results(
        self, results: List[Dict[str, Any]], max_results: int
    ) -> List[Dict[str, Any]]:
        """Deduplicates and ranks results from multiple search strategies."""
        unique_results: Dict[str, Dict[str, Any]] = {}
        
        for res in results:
            # Use memory ID to identify unique results
            memory_id = res.get("id")
            if not memory_id:
                continue

            if memory_id not in unique_results:
                unique_results[memory_id] = res
            else:
                # If we've seen this result before, boost its score
                # This is a simple ranking strategy; more complex ones could be used.
                current_score = unique_results[memory_id].get("score", 0.0)
                new_score = res.get("score", 0.0)
                unique_results[memory_id]["score"] = current_score + new_score + 0.1 # Boost score for appearing in multiple searches

        # Sort by final score
        sorted_results = sorted(
            unique_results.values(), key=lambda x: x.get("score", 0.0), reverse=True
        )

        return sorted_results[:max_results] 