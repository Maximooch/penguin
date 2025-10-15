"""Health monitoring and metrics collection for Penguin API.

Provides comprehensive health checks and performance metrics for Link integration.
"""

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Dict, Any, List, Optional
import psutil

logger = logging.getLogger(__name__)


@dataclass
class PerformanceMetrics:
    """Performance metrics tracking."""

    # Latency tracking (in milliseconds)
    request_count: int = 0
    total_latency_ms: float = 0.0
    min_latency_ms: float = float('inf')
    max_latency_ms: float = 0.0
    latencies_ms: List[float] = field(default_factory=list)

    # Success/failure tracking
    success_count: int = 0
    error_count: int = 0

    # Task-specific metrics
    total_task_duration_sec: float = 0.0
    task_count: int = 0

    # Timestamp
    last_reset: datetime = field(default_factory=datetime.utcnow)

    def record_request(self, latency_ms: float, success: bool = True):
        """Record a request with its latency."""
        self.request_count += 1
        self.total_latency_ms += latency_ms
        self.min_latency_ms = min(self.min_latency_ms, latency_ms)
        self.max_latency_ms = max(self.max_latency_ms, latency_ms)

        # Keep last 1000 latencies for percentile calculation
        self.latencies_ms.append(latency_ms)
        if len(self.latencies_ms) > 1000:
            self.latencies_ms.pop(0)

        if success:
            self.success_count += 1
        else:
            self.error_count += 1

    def record_task(self, duration_sec: float):
        """Record a completed task."""
        self.task_count += 1
        self.total_task_duration_sec += duration_sec

    @property
    def avg_latency_ms(self) -> float:
        """Average request latency."""
        if self.request_count == 0:
            return 0.0
        return self.total_latency_ms / self.request_count

    @property
    def p95_latency_ms(self) -> float:
        """95th percentile latency."""
        if not self.latencies_ms:
            return 0.0
        sorted_latencies = sorted(self.latencies_ms)
        index = int(len(sorted_latencies) * 0.95)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]

    @property
    def p99_latency_ms(self) -> float:
        """99th percentile latency."""
        if not self.latencies_ms:
            return 0.0
        sorted_latencies = sorted(self.latencies_ms)
        index = int(len(sorted_latencies) * 0.99)
        return sorted_latencies[min(index, len(sorted_latencies) - 1)]

    @property
    def success_rate(self) -> float:
        """Success rate (0.0 to 1.0)."""
        total = self.success_count + self.error_count
        if total == 0:
            return 1.0
        return self.success_count / total

    @property
    def avg_task_duration_sec(self) -> float:
        """Average task duration in seconds."""
        if self.task_count == 0:
            return 0.0
        return self.total_task_duration_sec / self.task_count

    def reset(self):
        """Reset all metrics."""
        self.request_count = 0
        self.total_latency_ms = 0.0
        self.min_latency_ms = float('inf')
        self.max_latency_ms = 0.0
        self.latencies_ms.clear()
        self.success_count = 0
        self.error_count = 0
        self.total_task_duration_sec = 0.0
        self.task_count = 0
        self.last_reset = datetime.utcnow()

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary."""
        return {
            "request_count": self.request_count,
            "avg_latency_ms": round(self.avg_latency_ms, 2),
            "p95_latency_ms": round(self.p95_latency_ms, 2),
            "p99_latency_ms": round(self.p99_latency_ms, 2),
            "min_latency_ms": round(self.min_latency_ms, 2) if self.min_latency_ms != float('inf') else 0,
            "max_latency_ms": round(self.max_latency_ms, 2),
            "success_rate": round(self.success_rate, 4),
            "error_count": self.error_count,
            "task_count": self.task_count,
            "avg_task_duration_sec": round(self.avg_task_duration_sec, 2),
            "last_reset": self.last_reset.isoformat()
        }


class HealthMonitor:
    """Health monitoring system for Penguin."""

    def __init__(self):
        self.metrics = PerformanceMetrics()
        self.start_time = datetime.utcnow()
        self.active_tasks = 0
        self.max_concurrent_tasks = int(os.getenv("PENGUIN_MAX_CONCURRENT_TASKS", "10"))

        # Process info
        try:
            self.process = psutil.Process()
        except Exception:
            self.process = None
            logger.warning("psutil not available, resource metrics will be limited")

    def get_resource_usage(self) -> Dict[str, Any]:
        """Get current resource usage."""
        if self.process:
            try:
                memory_info = self.process.memory_info()
                cpu_percent = self.process.cpu_percent(interval=0.1)

                return {
                    "memory_mb": round(memory_info.rss / 1024 / 1024, 2),
                    "memory_percent": round(self.process.memory_percent(), 2),
                    "cpu_percent": round(cpu_percent, 2),
                    "threads": self.process.num_threads(),
                    "active_tasks": self.active_tasks
                }
            except Exception as e:
                logger.warning(f"Error collecting resource metrics: {e}")
                return {
                    "memory_mb": 0,
                    "memory_percent": 0,
                    "cpu_percent": 0,
                    "threads": 0,
                    "active_tasks": self.active_tasks
                }
        else:
            return {
                "memory_mb": 0,
                "memory_percent": 0,
                "cpu_percent": 0,
                "threads": 0,
                "active_tasks": self.active_tasks
            }

    def get_agent_capacity(self) -> Dict[str, Any]:
        """Get agent capacity information."""
        available = max(0, self.max_concurrent_tasks - self.active_tasks)
        utilization = self.active_tasks / self.max_concurrent_tasks if self.max_concurrent_tasks > 0 else 0

        return {
            "max": self.max_concurrent_tasks,
            "active": self.active_tasks,
            "available": available,
            "utilization": round(utilization, 2)
        }

    def get_uptime(self) -> Dict[str, Any]:
        """Get uptime information."""
        uptime = datetime.utcnow() - self.start_time
        return {
            "start_time": self.start_time.isoformat(),
            "uptime_seconds": int(uptime.total_seconds()),
            "uptime_human": str(uptime)
        }

    async def get_comprehensive_health(self, core=None) -> Dict[str, Any]:
        """Get comprehensive health status.

        Args:
            core: Optional PenguinCore instance for detailed checks

        Returns:
            Dictionary with complete health information
        """
        # Basic status
        status = "healthy"

        # Check resource constraints
        resource_usage = self.get_resource_usage()
        if resource_usage["memory_percent"] > 90:
            status = "degraded"
        if resource_usage["cpu_percent"] > 90:
            status = "degraded"

        # Check capacity
        capacity = self.get_agent_capacity()
        if capacity["available"] == 0:
            status = "at_capacity"

        # Build comprehensive response
        health = {
            "status": status,
            "timestamp": datetime.utcnow().isoformat(),
            "uptime": self.get_uptime(),
            "resource_usage": resource_usage,
            "agent_capacity": capacity,
            "performance_metrics": self.metrics.to_dict()
        }

        # Add core-specific health if available
        if core:
            try:
                health["components"] = {
                    "core_initialized": core is not None,
                    "engine_available": hasattr(core, 'engine') and core.engine is not None,
                    "api_client_ready": hasattr(core, 'api_client') and core.api_client is not None,
                    "tool_manager_ready": hasattr(core, 'tool_manager') and core.tool_manager is not None,
                    "conversation_manager_ready": hasattr(core, 'conversation_manager') and core.conversation_manager is not None
                }

                # Get agent count
                if hasattr(core, 'list_agents'):
                    try:
                        agents = core.list_agents()
                        health["agents"] = {
                            "total": len(agents),
                            "active": len([a for a in agents if a != "default"])
                        }
                    except Exception:
                        pass

            except Exception as e:
                logger.warning(f"Error collecting core health metrics: {e}")

        return health

    def record_request(self, latency_ms: float, success: bool = True):
        """Record a request."""
        self.metrics.record_request(latency_ms, success)

    def record_task(self, duration_sec: float):
        """Record a task completion."""
        self.metrics.record_task(duration_sec)

    def increment_active_tasks(self):
        """Increment active task counter."""
        self.active_tasks += 1

    def decrement_active_tasks(self):
        """Decrement active task counter."""
        self.active_tasks = max(0, self.active_tasks - 1)

    def reset_metrics(self):
        """Reset performance metrics."""
        self.metrics.reset()


# Global health monitor instance
_health_monitor: Optional[HealthMonitor] = None


def get_health_monitor() -> HealthMonitor:
    """Get or create the global health monitor instance."""
    global _health_monitor
    if _health_monitor is None:
        _health_monitor = HealthMonitor()
    return _health_monitor


# Decorator for tracking request performance
def track_performance(func):
    """Decorator to track request performance."""
    if asyncio.iscoroutinefunction(func):
        async def async_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                get_health_monitor().record_request(latency_ms, success)
        return async_wrapper
    else:
        def sync_wrapper(*args, **kwargs):
            start_time = time.time()
            success = True
            try:
                result = func(*args, **kwargs)
                return result
            except Exception:
                success = False
                raise
            finally:
                latency_ms = (time.time() - start_time) * 1000
                get_health_monitor().record_request(latency_ms, success)
        return sync_wrapper
