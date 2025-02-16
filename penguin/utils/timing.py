import functools
import logging
import time
from typing import Any, Callable

from rich.console import Console

console = Console()
logger = logging.getLogger(__name__)


def track_startup_time(component_name: str) -> Callable:
    """Decorator to track initialization time of components"""

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
