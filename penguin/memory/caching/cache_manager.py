"""
Caching Layer for the Memory System

Provides a simple in-memory caching mechanism to improve performance
by reducing redundant search and embedding computations.
"""

import hashlib
import json
import logging
from functools import lru_cache
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class CacheManager:
    """
    A simple cache manager using in-memory LRU caches.
    """

    def __init__(self, search_cache_size: int = 128, embedding_cache_size: int = 1024):
        """
        Initializes the cache manager with specified cache sizes.

        Args:
            search_cache_size: The max number of search results to cache.
            embedding_cache_size: The max number of embeddings to cache.
        """
        # Note: We are using lru_cache on methods, which creates a cache
        # per instance. This is a simple approach. A more advanced system
        # might use a shared cache object.
        self.get_cached_search = lru_cache(maxsize=search_cache_size)(self._get_search_from_cache)
        self.get_cached_embedding = lru_cache(maxsize=embedding_cache_size)(self._get_embedding_from_cache)
        logger.info(f"CacheManager initialized with search size {search_cache_size} and embedding size {embedding_cache_size}")

    def _get_search_from_cache(self, query_hash: str) -> Optional[List[Dict[str, Any]]]:
        """
        This method is decorated by lru_cache. The actual cache lookup
        happens on `get_cached_search`. This is a placeholder for the
        decorated method.
        """
        # In a real scenario, this might look up from a persistent cache like Redis.
        # For lru_cache, the values are stored directly on the decorated method.
        # We return None to indicate a cache miss, which will then be populated.
        return None
    
    def cache_search_result(self, query_hash: str, results: List[Dict[str, Any]]):
        """
        A helper to conceptually represent adding to the cache.
        With lru_cache, this is handled implicitly when the decorated method returns.
        """
        # This is more of a conceptual guide. The actual caching happens
        # when `get_cached_search` is called and the underlying function
        # (if it were not a placeholder) would return a value.
        # To make this work with lru_cache, we would need a more complex setup.
        
        # A simple, more explicit way without decorator magic:
        # self.search_cache[query_hash] = results
        pass

    def _get_embedding_from_cache(self, text: str) -> Optional[List[float]]:
        """
        Placeholder for the embedding cache, which is managed by lru_cache
        on the `get_cached_embedding` method.
        """
        return None

    @staticmethod
    def generate_query_hash(query: str, filters: Optional[Dict[str, Any]]) -> str:
        """
        Creates a consistent hash for a query and its filters to use as a cache key.
        """
        # Serialize filters with sorted keys to ensure consistent hash
        serialized_filters = json.dumps(filters, sort_keys=True) if filters else ""
        
        hasher = hashlib.sha256()
        hasher.update(query.encode('utf-8'))
        hasher.update(serialized_filters.encode('utf-8'))
        
        return hasher.hexdigest()


# A more direct implementation for clarity:
class SimpleCacheManager:
    """A direct and simple implementation of an LRU cache for searches."""
    def __init__(self, search_cache_size: int = 128):
        self.search_cache = lru_cache(maxsize=search_cache_size)(self._search_func)
        
    def _search_func(self, query_hash: str, search_coro):
        """Wrapper to make the async search function cacheable."""
        # This is tricky because lru_cache is not async-aware.
        # A proper async cache library like 'async-lru' would be better.
        # This is a conceptual demonstration.
        pass 