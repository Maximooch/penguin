import functools
import logging
import time
from contextlib import contextmanager
from typing import Any, Callable, Optional, Generator

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def track_startup_time(component_name: str) -> Callable:
    """Decorator to track initialization time of async components."""

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        async def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            try:
                result = await func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.info(f"{component_name} initialized in {elapsed:.2f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"{component_name} failed after {elapsed:.2f}s: {str(e)}")
                raise

        return wrapper

    return decorator


def track_time_sync(operation_name: str) -> Callable:
    """Decorator to track execution time of sync functions.

    Args:
        operation_name: Name to use in logs for this operation

    Example:
        @track_time_sync("database_query")
        def fetch_users():
            return db.query(User)
    """

    def decorator(func: Callable) -> Callable:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> Any:
            start_time = time.time()
            try:
                result = func(*args, **kwargs)
                elapsed = time.time() - start_time
                logger.debug(f"{operation_name} completed in {elapsed:.4f}s")
                return result
            except Exception as e:
                elapsed = time.time() - start_time
                logger.error(f"{operation_name} failed after {elapsed:.4f}s: {str(e)}")
                raise

        return wrapper

    return decorator


@contextmanager
def time_block(operation_name: str, log_level: str = "debug") -> Generator[None, None, None]:
    """Context manager for timing code blocks.

    Args:
        operation_name: Name to use in logs
        log_level: Log level - "debug", "info", "warning"

    Example:
        with time_block("data_processing"):
            process_large_dataset()
    """
    start_time = time.time()
    log_func = getattr(logger, log_level, logger.debug)
    try:
        yield
        elapsed = time.time() - start_time
        log_func(f"{operation_name} completed in {elapsed:.4f}s")
    except Exception as e:
        elapsed = time.time() - start_time
        logger.error(f"{operation_name} failed after {elapsed:.4f}s: {str(e)}")
        raise


class AccumulatedTimer:
    """Accumulate timing across multiple calls.

    Useful for tracking total time spent in repeated operations.

    Example:
        timer = AccumulatedTimer("api_calls")
        for request in requests:
            with timer:
                make_api_call(request)
        print(timer.summary())  # "api_calls: 15 calls, 2.34s total, 0.156s avg"
    """

    def __init__(self, name: str):
        self.name = name
        self.total_time = 0.0
        self.call_count = 0
        self._start_time: Optional[float] = None

    def __enter__(self) -> "AccumulatedTimer":
        self._start_time = time.time()
        return self

    def __exit__(self, *args) -> None:
        if self._start_time:
            self.total_time += time.time() - self._start_time
            self.call_count += 1
            self._start_time = None

    @property
    def average_time(self) -> float:
        return self.total_time / self.call_count if self.call_count > 0 else 0.0

    def summary(self) -> str:
        return f"{self.name}: {self.call_count} calls, {self.total_time:.4f}s total, {self.average_time:.4f}s avg"

    def reset(self) -> None:
        """Reset accumulated statistics."""
        self.total_time = 0.0
        self.call_count = 0
