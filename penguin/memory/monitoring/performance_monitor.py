"""
Performance Monitor for the Memory System

Provides a class to track performance metrics and health of the memory system,
including search times, indexing speed, and cache hit rates.
"""

import logging
import time
from collections import deque
from typing import Any, Dict, List

try:
    import numpy as np
    NUMPY_AVAILABLE = True
except ImportError:
    NUMPY_AVAILABLE = False


logger = logging.getLogger(__name__)


class MemoryPerformanceMonitor:
    """
    Monitors and reports on the performance and health of the memory system.
    """

    def __init__(self, max_log_size: int = 100):
        self.metrics: Dict[str, deque] = {
            'search_times': deque(maxlen=max_log_size),
            'index_times': deque(maxlen=max_log_size),
            'cache_hits': deque(maxlen=max_log_size),
            'cache_misses': deque(maxlen=max_log_size),
        }

    def track_search(self, start_time: float, end_time: float, result_count: int):
        """Tracks a search operation's performance."""
        duration = (end_time - start_time) * 1000  # Convert to milliseconds
        self.metrics['search_times'].append({
            'duration_ms': duration,
            'result_count': result_count,
            'timestamp': end_time,
        })

    def track_indexing(self, start_time: float, end_time: float, items_indexed: int):
        """Tracks an indexing operation's performance."""
        duration = end_time - start_time
        self.metrics['index_times'].append({
            'duration_s': duration,
            'items_indexed': items_indexed,
            'timestamp': end_time,
        })

    def track_cache_hit(self):
        """Records a cache hit."""
        self.metrics['cache_hits'].append(time.time())

    def track_cache_miss(self):
        """Records a cache miss."""
        self.metrics['cache_misses'].append(time.time())

    def generate_health_report(self) -> Dict[str, Any]:
        """
        Generates a comprehensive health report with aggregated metrics.
        """
        if not NUMPY_AVAILABLE:
            logger.warning("Numpy not installed, some metrics will be unavailable.")
            return {"error": "Numpy is required for full metrics."}

        search_times = [m['duration_ms'] for m in self.metrics['search_times']]
        items_indexed = [m['items_indexed'] for m in self.metrics['index_times']]
        indexing_durations = [m['duration_s'] for m in self.metrics['index_times']]

        cache_hits = len(self.metrics['cache_hits'])
        cache_misses = len(self.metrics['cache_misses'])
        total_cache_lookups = cache_hits + cache_misses

        return {
            'search_stats': {
                'count': len(search_times),
                'avg_latency_ms': np.mean(search_times) if search_times else 0,
                'p95_latency_ms': np.percentile(search_times, 95) if search_times else 0,
                'max_latency_ms': np.max(search_times) if search_times else 0,
            },
            'indexing_stats': {
                'total_indexed': sum(items_indexed),
                'files_per_second': sum(items_indexed) / sum(indexing_durations) if indexing_durations else 0,
            },
            'cache_stats': {
                'hit_rate': (cache_hits / total_cache_lookups) * 100 if total_cache_lookups > 0 else 0,
                'total_hits': cache_hits,
                'total_misses': cache_misses,
            },
            'report_generated_at': time.time()
        } 