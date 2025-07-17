"""
Resilience and error handling utilities for the Penguin project system.

This module provides retry mechanisms, circuit breakers, and structured error handling
for network operations and external API calls.
"""

import asyncio
import logging
import time
from enum import Enum
from typing import Any, Callable, Dict, List, Optional, TypeVar, Union
from dataclasses import dataclass, field
from functools import wraps

logger = logging.getLogger(__name__)

T = TypeVar('T')

class ErrorType(Enum):
    """Classification of error types for different handling strategies."""
    NETWORK_ERROR = "network_error"
    RATE_LIMIT_ERROR = "rate_limit_error"
    AUTHENTICATION_ERROR = "auth_error"
    VALIDATION_ERROR = "validation_error"
    RESOURCE_NOT_FOUND = "resource_not_found"
    CONFLICT_ERROR = "conflict_error"
    UNKNOWN_ERROR = "unknown_error"

@dataclass
class ErrorContext:
    """Context information for error handling and recovery."""
    error_type: ErrorType
    original_error: Exception
    attempt_number: int
    total_attempts: int
    operation_name: str
    context_data: Dict[str, Any] = field(default_factory=dict)
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for logging and reporting."""
        return {
            "error_type": self.error_type.value,
            "error_message": str(self.original_error),
            "attempt_number": self.attempt_number,
            "total_attempts": self.total_attempts,
            "operation_name": self.operation_name,
            "context_data": self.context_data
        }

class RetryStrategy:
    """Configurable retry strategy for operations."""
    
    def __init__(
        self,
        max_attempts: int = 3,
        base_delay: float = 1.0,
        max_delay: float = 60.0,
        exponential_base: float = 2.0,
        jitter: bool = True
    ):
        self.max_attempts = max_attempts
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.exponential_base = exponential_base
        self.jitter = jitter
    
    def get_delay(self, attempt: int) -> float:
        """Calculate delay for the given attempt number."""
        if attempt <= 0:
            return 0
        
        delay = self.base_delay * (self.exponential_base ** (attempt - 1))
        delay = min(delay, self.max_delay)
        
        if self.jitter:
            import random
            delay = delay * (0.5 + random.random() * 0.5)  # Add 0-50% jitter
        
        return delay

class CircuitBreaker:
    """Circuit breaker pattern implementation for external service calls."""
    
    def __init__(
        self,
        failure_threshold: int = 5,
        recovery_timeout: int = 60,
        expected_exception: Exception = Exception
    ):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self.expected_exception = expected_exception
        
        self.failure_count = 0
        self.last_failure_time = None
        self.state = "CLOSED"  # CLOSED, OPEN, HALF_OPEN
    
    def call(self, func: Callable[..., T], *args, **kwargs) -> T:
        """Execute function with circuit breaker protection."""
        if self.state == "OPEN":
            if self._should_attempt_reset():
                self.state = "HALF_OPEN"
            else:
                raise Exception("Circuit breaker is OPEN")
        
        try:
            result = func(*args, **kwargs)
            self._on_success()
            return result
        except self.expected_exception as e:
            self._on_failure()
            raise e
    
    def _should_attempt_reset(self) -> bool:
        """Check if enough time has passed to attempt a reset."""
        if self.last_failure_time is None:
            return True
        return time.time() - self.last_failure_time >= self.recovery_timeout
    
    def _on_success(self):
        """Handle successful operation."""
        self.failure_count = 0
        self.state = "CLOSED"
    
    def _on_failure(self):
        """Handle failed operation."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        
        if self.failure_count >= self.failure_threshold:
            self.state = "OPEN"

def classify_error(error: Exception) -> ErrorType:
    """Classify an error for appropriate handling strategy."""
    error_str = str(error).lower()
    error_type = type(error).__name__.lower()
    
    # Network-related errors
    if any(keyword in error_str for keyword in ['connection', 'timeout', 'network', 'dns']):
        return ErrorType.NETWORK_ERROR
    
    # Rate limiting
    if any(keyword in error_str for keyword in ['rate limit', 'too many requests', '429']):
        return ErrorType.RATE_LIMIT_ERROR
    
    # Authentication errors
    if any(keyword in error_str for keyword in ['unauthorized', 'authentication', 'token', '401', '403']):
        return ErrorType.AUTHENTICATION_ERROR
    
    # Resource not found
    if any(keyword in error_str for keyword in ['not found', '404']):
        return ErrorType.RESOURCE_NOT_FOUND
    
    # Conflict errors
    if any(keyword in error_str for keyword in ['conflict', 'already exists', '409']):
        return ErrorType.CONFLICT_ERROR
    
    # Validation errors
    if any(keyword in error_str for keyword in ['validation', 'invalid', 'bad request', '400']):
        return ErrorType.VALIDATION_ERROR
    
    return ErrorType.UNKNOWN_ERROR

def resilient_operation(
    operation_name: str,
    retry_strategy: Optional[RetryStrategy] = None,
    circuit_breaker: Optional[CircuitBreaker] = None,
    context_data: Optional[Dict[str, Any]] = None
):
    """
    Decorator for making operations resilient with retry and circuit breaker patterns.
    
    Args:
        operation_name: Name of the operation for logging
        retry_strategy: Custom retry strategy, uses default if None
        circuit_breaker: Circuit breaker instance, creates default if None
        context_data: Additional context data for error reporting
    """
    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        nonlocal retry_strategy, circuit_breaker
        
        if retry_strategy is None:
            retry_strategy = RetryStrategy()
        
        if circuit_breaker is None:
            circuit_breaker = CircuitBreaker()
        
        @wraps(func)
        async def async_wrapper(*args, **kwargs) -> T:
            last_error = None
            
            for attempt in range(1, retry_strategy.max_attempts + 1):
                try:
                    if circuit_breaker:
                        result = await asyncio.get_event_loop().run_in_executor(
                            None, circuit_breaker.call, lambda: func(*args, **kwargs)
                        )
                    else:
                        result = await func(*args, **kwargs)
                    
                    if attempt > 1:
                        logger.info(f"Operation '{operation_name}' succeeded on attempt {attempt}")
                    
                    return result
                
                except Exception as e:
                    last_error = e
                    error_type = classify_error(e)
                    
                    error_context = ErrorContext(
                        error_type=error_type,
                        original_error=e,
                        attempt_number=attempt,
                        total_attempts=retry_strategy.max_attempts,
                        operation_name=operation_name,
                        context_data=context_data or {}
                    )
                    
                    logger.warning(f"Operation '{operation_name}' failed on attempt {attempt}: {e}")
                    
                    # Don't retry certain error types
                    if error_type in [ErrorType.AUTHENTICATION_ERROR, ErrorType.VALIDATION_ERROR]:
                        logger.error(f"Non-retryable error in '{operation_name}': {error_context.to_dict()}")
                        raise e
                    
                    # If this is the last attempt, don't wait
                    if attempt == retry_strategy.max_attempts:
                        break
                    
                    # Wait before retrying
                    delay = retry_strategy.get_delay(attempt)
                    logger.info(f"Retrying '{operation_name}' in {delay:.2f} seconds...")
                    await asyncio.sleep(delay)
            
            # All attempts failed
            logger.error(f"Operation '{operation_name}' failed after {retry_strategy.max_attempts} attempts")
            raise last_error
        
        @wraps(func)
        def sync_wrapper(*args, **kwargs) -> T:
            # For sync functions, convert to async temporarily
            async def async_func(*args, **kwargs):
                return func(*args, **kwargs)
            
            return asyncio.run(async_wrapper(*args, **kwargs))
        
        # Return appropriate wrapper based on function type
        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        else:
            return sync_wrapper
    
    return decorator

class OperationResult:
    """Structured result type for operations with error handling."""
    
    def __init__(self, success: bool, data: Any = None, error: Optional[Exception] = None, 
                 error_context: Optional[ErrorContext] = None):
        self.success = success
        self.data = data
        self.error = error
        self.error_context = error_context
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "success": self.success,
            "data": self.data
        }
        
        if self.error:
            result["error"] = str(self.error)
        
        if self.error_context:
            result["error_context"] = self.error_context.to_dict()
        
        return result
    
    @classmethod
    def success(cls, data: Any = None) -> "OperationResult":
        """Create a successful result."""
        return cls(success=True, data=data)
    
    @classmethod
    def failure(cls, error: Exception, error_context: Optional[ErrorContext] = None) -> "OperationResult":
        """Create a failed result."""
        return cls(success=False, error=error, error_context=error_context)

def safe_operation(operation_name: str, context_data: Optional[Dict[str, Any]] = None):
    """
    Decorator that wraps operations in a try-catch and returns OperationResult.
    
    Args:
        operation_name: Name of the operation for logging
        context_data: Additional context data for error reporting
    """
    def decorator(func: Callable[..., T]) -> Callable[..., OperationResult]:
        @wraps(func)
        def wrapper(*args, **kwargs) -> OperationResult:
            try:
                result = func(*args, **kwargs)
                return OperationResult.success(result)
            except Exception as e:
                error_type = classify_error(e)
                error_context = ErrorContext(
                    error_type=error_type,
                    original_error=e,
                    attempt_number=1,
                    total_attempts=1,
                    operation_name=operation_name,
                    context_data=context_data or {}
                )
                
                logger.error(f"Operation '{operation_name}' failed: {error_context.to_dict()}")
                return OperationResult.failure(e, error_context)
        
        return wrapper
    
    return decorator