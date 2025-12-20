"""
Callback signature adaptation utilities.

Normalizes stream callbacks to a consistent async (chunk: str, message_type: str) signature.
This consolidates duplicated callback handling logic from core.py and api_client.py.
"""
import asyncio
import inspect
import logging
from typing import Awaitable, Callable, Optional, Any

logger = logging.getLogger(__name__)


def adapt_stream_callback(
    callback: Optional[Callable[..., Any]],
    suppress_errors: bool = True,
) -> Optional[Callable[[str, str], Awaitable[None]]]:
    """
    Normalize a stream callback to async (chunk: str, message_type: str) signature.

    Handles:
    - Sync and async callbacks
    - 1-param (chunk only) and 2-param (chunk, message_type) signatures
    - Error suppression (logged but not raised)

    Args:
        callback: The original callback (sync or async, 1 or 2 params)
        suppress_errors: If True, log errors but don't raise (default True)

    Returns:
        Normalized async callback with (chunk, message_type) signature, or None

    Example:
        # Normalize any callback to standard signature
        normalized = adapt_stream_callback(user_callback)
        if normalized:
            await normalized("Hello", "assistant")
    """
    if not callback:
        return None

    # Detect callback signature
    try:
        sig = inspect.signature(callback)
        arity = len(sig.parameters)
    except (ValueError, TypeError):
        # If we can't inspect, assume 1 parameter
        arity = 1

    is_async = asyncio.iscoroutinefunction(callback)

    if is_async:
        if arity >= 2:
            # Already async with correct signature
            async def async_passthrough(chunk: str, message_type: str) -> None:
                try:
                    await callback(chunk, message_type)
                except Exception as e:
                    if suppress_errors:
                        logger.debug("Stream callback error: %s", e, exc_info=True)
                    else:
                        raise

            return async_passthrough
        else:
            # Async but only takes chunk
            async def async_single_param(chunk: str, message_type: str) -> None:
                try:
                    await callback(chunk)
                except Exception as e:
                    if suppress_errors:
                        logger.debug("Stream callback error: %s", e, exc_info=True)
                    else:
                        raise

            return async_single_param
    else:
        # Sync callback - run in executor
        if arity >= 2:
            async def sync_two_params(chunk: str, message_type: str) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, callback, chunk, message_type)
                except Exception as e:
                    if suppress_errors:
                        logger.debug("Stream callback error: %s", e, exc_info=True)
                    else:
                        raise

            return sync_two_params
        else:
            async def sync_single_param(chunk: str, message_type: str) -> None:
                try:
                    loop = asyncio.get_running_loop()
                    await loop.run_in_executor(None, callback, chunk)
                except Exception as e:
                    if suppress_errors:
                        logger.debug("Stream callback error: %s", e, exc_info=True)
                    else:
                        raise

            return sync_single_param


def get_callback_arity(callback: Callable) -> int:
    """
    Get the number of parameters a callback accepts.

    Args:
        callback: Any callable

    Returns:
        Number of parameters, or 1 if inspection fails
    """
    try:
        sig = inspect.signature(callback)
        return len(sig.parameters)
    except (ValueError, TypeError):
        return 1
