"""
Enhanced profiling utilities for Penguin startup and runtime performance analysis.

This module provides decorators, context managers, and utilities for tracking
performance bottlenecks, especially during startup.
"""

import logging
import time
import functools
import threading
from contextlib import contextmanager
from collections import defaultdict, deque
from typing import Dict, List, Optional, Any, Callable
from datetime import datetime
import asyncio

logger = logging.getLogger(__name__)


class ProfilerStats:
    """Thread-safe profiler statistics collector."""
    
    def __init__(self):
        self._lock = threading.Lock()
        self._timings: Dict[str, List[float]] = defaultdict(list)
        self._call_counts: Dict[str, int] = defaultdict(int)
        self._memory_usage: Dict[str, List[int]] = defaultdict(list)
        self._async_tasks: Dict[str, Dict[str, Any]] = {}
        self._startup_phases: List[Dict[str, Any]] = []
        self._enabled = True
        
    def record_timing(self, name: str, duration: float, metadata: Optional[Dict[str, Any]] = None):
        """Record a timing measurement."""
        if not self._enabled:
            return
            
        with self._lock:
            self._timings[name].append(duration)
            self._call_counts[name] += 1
            
            if metadata:
                # Store most recent metadata for each operation
                if not hasattr(self, '_metadata'):
                    self._metadata = {}
                self._metadata[name] = metadata
    
    def record_memory(self, name: str, memory_mb: int):
        """Record memory usage."""
        if not self._enabled:
            return
            
        with self._lock:
            self._memory_usage[name].append(memory_mb)
    
    def record_async_task(self, name: str, task_id: str, status: str, duration: Optional[float] = None):
        """Record async task lifecycle."""
        if not self._enabled:
            return
            
        with self._lock:
            if name not in self._async_tasks:
                self._async_tasks[name] = {}
                
            self._async_tasks[name][task_id] = {
                "status": status,
                "duration": duration,
                "timestamp": datetime.now().isoformat()
            }
    
    def record_startup_phase(self, phase: str, duration: float, details: Optional[Dict[str, Any]] = None):
        """Record a startup phase completion."""
        if not self._enabled:
            return
            
        with self._lock:
            self._startup_phases.append({
                "phase": phase,
                "duration": duration,
                "timestamp": datetime.now().isoformat(),
                "details": details or {}
            })
    
    def get_summary(self) -> Dict[str, Any]:
        """Get comprehensive performance summary."""
        if not self._enabled:
            return {"enabled": False}
            
        with self._lock:
            # Calculate timing statistics
            timing_stats = {}
            for name, timings in self._timings.items():
                if timings:
                    timing_stats[name] = {
                        "count": len(timings),
                        "total": sum(timings),
                        "avg": sum(timings) / len(timings),
                        "min": min(timings),
                        "max": max(timings),
                        "latest": timings[-1] if timings else 0
                    }
            
            # Calculate memory statistics
            memory_stats = {}
            for name, memory_list in self._memory_usage.items():
                if memory_list:
                    memory_stats[name] = {
                        "count": len(memory_list),
                        "avg_mb": sum(memory_list) / len(memory_list),
                        "max_mb": max(memory_list),
                        "latest_mb": memory_list[-1] if memory_list else 0
                    }
            
            return {
                "enabled": True,
                "timing_stats": timing_stats,
                "memory_stats": memory_stats,
                "async_tasks": dict(self._async_tasks),
                "startup_phases": list(self._startup_phases),
                "total_operations": sum(self._call_counts.values())
            }
    
    def get_startup_report(self) -> str:
        """Get a formatted startup performance report."""
        if not self._enabled:
            return "Profiling disabled"
            
        summary = self.get_summary()
        
        report_lines = [
            "=== Penguin Startup Performance Report ===",
            f"Total operations tracked: {summary['total_operations']}",
            ""
        ]
        
        # Startup phases
        if summary['startup_phases']:
            report_lines.append("Startup Phases:")
            total_startup = sum(phase['duration'] for phase in summary['startup_phases'])
            for phase in summary['startup_phases']:
                duration = phase['duration']
                percentage = (duration / total_startup * 100) if total_startup > 0 else 0
                report_lines.append(f"  {phase['phase']}: {duration:.4f}s ({percentage:.1f}%)")
            report_lines.append(f"  TOTAL STARTUP: {total_startup:.4f}s")
            report_lines.append("")
        
        # Top slow operations
        timing_stats = summary.get('timing_stats', {})
        if timing_stats:
            report_lines.append("Slowest Operations:")
            sorted_ops = sorted(timing_stats.items(), key=lambda x: x[1]['total'], reverse=True)
            for name, stats in sorted_ops[:10]:
                report_lines.append(f"  {name}: {stats['total']:.4f}s (avg: {stats['avg']:.4f}s, count: {stats['count']})")
            report_lines.append("")
        
        # Memory usage
        memory_stats = summary.get('memory_stats', {})
        if memory_stats:
            report_lines.append("Memory Usage:")
            for name, stats in memory_stats.items():
                report_lines.append(f"  {name}: {stats['avg_mb']:.1f}MB avg (max: {stats['max_mb']:.1f}MB)")
            report_lines.append("")
        
        # Async tasks status
        async_tasks = summary.get('async_tasks', {})
        if async_tasks:
            report_lines.append("Async Tasks:")
            for task_name, tasks in async_tasks.items():
                completed = sum(1 for t in tasks.values() if t['status'] == 'completed')
                running = sum(1 for t in tasks.values() if t['status'] == 'running')
                failed = sum(1 for t in tasks.values() if t['status'] == 'failed')
                report_lines.append(f"  {task_name}: {completed} completed, {running} running, {failed} failed")
        
        return "\n".join(report_lines)
    
    def reset(self):
        """Reset all statistics."""
        with self._lock:
            self._timings.clear()
            self._call_counts.clear()
            self._memory_usage.clear()
            self._async_tasks.clear()
            self._startup_phases.clear()
    
    def enable(self):
        """Enable profiling."""
        self._enabled = True
    
    def disable(self):
        """Disable profiling."""
        self._enabled = False


# Global profiler instance
profiler = ProfilerStats()


@contextmanager
def profile_operation(name: str, metadata: Optional[Dict[str, Any]] = None):
    """Context manager to profile an operation."""
    if not profiler._enabled:
        yield
        return
        
    start_time = time.perf_counter()
    start_memory = get_memory_usage()
    
    try:
        yield
    finally:
        end_time = time.perf_counter()
        end_memory = get_memory_usage()
        
        duration = end_time - start_time
        profiler.record_timing(name, duration, metadata)
        
        if start_memory and end_memory:
            profiler.record_memory(name, end_memory - start_memory)


def profile_function(name: Optional[str] = None, include_args: bool = False):
    """Decorator to profile function calls."""
    def decorator(func):
        operation_name = name or f"{func.__module__}.{func.__qualname__}"
        
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            metadata = {}
            if include_args:
                metadata['args_count'] = len(args)
                metadata['kwargs_keys'] = list(kwargs.keys())
                
            with profile_operation(operation_name, metadata):
                return func(*args, **kwargs)
        
        return wrapper
    return decorator


def profile_async_function(name: Optional[str] = None, include_args: bool = False):
    """Decorator to profile async function calls."""
    def decorator(func):
        operation_name = name or f"{func.__module__}.{func.__qualname__}"
        
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            metadata = {}
            if include_args:
                metadata['args_count'] = len(args)
                metadata['kwargs_keys'] = list(kwargs.keys())
                
            with profile_operation(operation_name, metadata):
                return await func(*args, **kwargs)
        
        return wrapper
    return decorator


@contextmanager
def profile_startup_phase(phase_name: str):
    """Context manager specifically for startup phases."""
    start_time = time.perf_counter()
    
    try:
        yield
    finally:
        end_time = time.perf_counter()
        duration = end_time - start_time
        profiler.record_startup_phase(phase_name, duration)


def get_memory_usage() -> Optional[int]:
    """Get current memory usage in MB."""
    try:
        import psutil
        process = psutil.Process()
        return int(process.memory_info().rss / 1024 / 1024)
    except ImportError:
        return None


def enable_profiling():
    """Enable performance profiling."""
    profiler.enable()
    logger.info("Performance profiling enabled")


def disable_profiling():
    """Disable performance profiling."""
    profiler.disable()
    logger.info("Performance profiling disabled")


def reset_profiling():
    """Reset all profiling statistics."""
    profiler.reset()
    logger.info("Performance profiling statistics reset")


def get_profiling_summary() -> Dict[str, Any]:
    """Get current profiling summary."""
    return profiler.get_summary()


def print_startup_report():
    """Print the startup performance report."""
    report = profiler.get_startup_report()
    print(report)
    logger.info("Startup performance report generated")


def log_startup_report():
    """Log the startup performance report."""
    report = profiler.get_startup_report()
    logger.info(f"Startup Performance Report:\n{report}")


# Async task tracking utilities
class AsyncTaskTracker:
    """Helper for tracking async task lifecycles."""
    
    def __init__(self, task_name: str):
        self.task_name = task_name
        self.task_id = f"{task_name}_{int(time.time() * 1000)}"
        self.start_time = None
    
    def start(self):
        """Mark task as started."""
        self.start_time = time.perf_counter()
        profiler.record_async_task(self.task_name, self.task_id, "running")
    
    def complete(self):
        """Mark task as completed."""
        if self.start_time:
            duration = time.perf_counter() - self.start_time
            profiler.record_async_task(self.task_name, self.task_id, "completed", duration)
    
    def fail(self, error: Optional[Exception] = None):
        """Mark task as failed."""
        if self.start_time:
            duration = time.perf_counter() - self.start_time
            profiler.record_async_task(self.task_name, self.task_id, "failed", duration)


@contextmanager
def track_async_task(task_name: str):
    """Context manager for tracking async task lifecycle."""
    tracker = AsyncTaskTracker(task_name)
    tracker.start()
    
    try:
        yield tracker
    except Exception:
        tracker.fail()
        raise
    else:
        tracker.complete() 