from __future__ import annotations

import asyncio
import inspect
import json
import logging
import math
import os
import random
import time
from concurrent.futures import Future
from dataclasses import replace
from queue import Queue
from threading import BoundedSemaphore, Lock, Thread
from typing import Any, Awaitable, Callable, Dict, List, Optional

from penguin.system.runtime_diagnostics import record_runtime_duration
from penguin.tools.runtime import (
    ORDERED_TOOL_BATCH_NAME,
    OrderedToolBatchPlan,
    ToolCall,
    ToolExecutionPolicy,
    ToolResult,
    execute_tool_calls_ordered,
    execute_tool_calls_serially,
    legacy_action_result_from_tool_result,
    ordered_tool_batch_preflight_error_result,
    ordered_tool_batch_result_from_results,
    parse_ordered_tool_batch_plan,
    tool_call_from_responses_info,
    tool_call_with_schedule_metadata,
)
from penguin.utils.errors import (
    LLMEmptyResponseError,
    NativeToolHistoryPersistenceError,
)

from .contracts import (
    ErrorCategory,
    LLMCallResult,
    LLMCallStatus,
    LLMError,
    LLMProviderError,
)
from .provider_transform import (
    native_tool_format,
    normalize_anthropic_tools,
    normalize_openai_chat_tool_choice,
    normalize_openai_chat_tools,
    normalize_openai_responses_tool_choice,
    normalize_openai_responses_tools,
)
from .reasoning_variants import (
    native_reasoning_efforts,
    reasoning_efforts_from_metadata,
)

_REASONING_EFFORT_VARIANTS = {
    "none",
    "minimal",
    "low",
    "medium",
    "high",
    "xhigh",
    "ultra",
}
_PROVIDER_RETRY_BASE_SECONDS = 0.25
_PROVIDER_RETRY_MAX_SECONDS = 5.0
_PROVIDER_RETRY_JITTER_FRACTION = 0.20
_RUNTIME_STREAM_CALLBACK_TIMEOUT_SECONDS = 30.0
_REASONING_MAX_VARIANTS = {"max"}


class _RuntimeDaemonCallbackExecutor:
    """Run at most one synchronous UI callback without owning the loop executor.

    A callback can block forever. The worker is deliberately daemon-owned rather
    than ``asyncio``'s default executor, whose shutdown is awaited by
    ``asyncio.run``. One outstanding callback consumes the fixed capacity; later
    updates are intentionally dropped until it returns.
    """

    def __init__(self) -> None:
        self._work_queue: Queue = Queue()
        self._capacity = BoundedSemaphore(1)
        self._lock = Lock()
        self._worker: Optional[Thread] = None

    def submit(
        self,
        callback: Callable[..., Any],
        args: tuple[Any, ...],
    ) -> Optional[Future[Any]]:
        """Submit one callback or reject it when the bounded worker is busy."""

        if not self._capacity.acquire(blocking=False):
            return None
        future: Future[Any] = Future()
        try:
            with self._lock:
                if self._worker is None or not self._worker.is_alive():
                    self._worker = Thread(
                        target=self._run,
                        name="penguin-runtime-callback",
                        daemon=True,
                    )
                    self._worker.start()
                self._work_queue.put((callback, args, future))
        except Exception:
            self._capacity.release()
            raise
        return future

    def _run(self) -> None:
        """Process accepted callbacks without participating in executor shutdown."""

        while True:
            callback, args, future = self._work_queue.get()
            try:
                if not future.set_running_or_notify_cancel():
                    continue
                future.set_result(callback(*args))
            except BaseException as exc:
                future.set_exception(exc)
            finally:
                self._capacity.release()


_RUNTIME_SYNC_CALLBACK_EXECUTOR = _RuntimeDaemonCallbackExecutor()


class UnsupportedReasoningVariantError(ValueError):
    """Raised when a requested reasoning variant is unsupported by a model."""

    def __init__(
        self,
        *,
        provider: str,
        model: str,
        variant: str,
        supported: tuple[str, ...],
    ) -> None:
        self.provider = provider
        self.model = model
        self.variant = variant
        self.supported = supported
        super().__init__(
            f"Reasoning variant '{variant}' is not supported by "
            f"{provider or 'provider'}/{model or 'model'}"
        )

    def to_dict(self) -> Dict[str, Any]:
        """Return a client-safe structured error payload."""

        return {
            "code": "unsupported_reasoning_variant",
            "message": str(self),
            "provider": self.provider or None,
            "model": self.model or None,
            "variant": self.variant,
            "supported": list(self.supported),
        }
_REASONING_DISABLE_VARIANTS = {"off"}
_NATIVE_RESPONSE_COMPLETION_TOOLS = {"finish_response"}
logger = logging.getLogger(__name__)


def _tool_arguments_chars(arguments: Any) -> int:
    """Return a bounded-diagnostic argument size in characters."""

    if isinstance(arguments, str):
        return len(arguments)
    try:
        return len(json.dumps(arguments, sort_keys=True, default=str))
    except Exception:
        return len(str(arguments))


def _available_tool_names(tool_manager: Any) -> Optional[set[str]]:
    """Return known child tool names for ordered-batch preflight."""

    getter = getattr(tool_manager, "get_available_tool_names", None)
    if callable(getter):
        try:
            names = getter()
            if isinstance(names, set):
                return {str(name) for name in names}
            if isinstance(names, (list, tuple)):
                return {str(name) for name in names}
        except Exception:
            logger.debug("Failed to read available tool names", exc_info=True)
            return set()

    schema_getter = getattr(tool_manager, "get_responses_tools", None)
    if not callable(schema_getter):
        return None
    try:
        schemas = schema_getter(include_web_search=False)
    except TypeError:
        try:
            schemas = schema_getter()
        except Exception:
            logger.debug("Failed to read response tool schemas", exc_info=True)
            return set()
    except Exception:
        logger.debug("Failed to read response tool schemas", exc_info=True)
        return set()

    names: set[str] = set()
    if isinstance(schemas, list):
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            name = schema.get("name")
            if isinstance(name, str) and name.strip():
                names.add(name.strip())
            function_payload = schema.get("function")
            if isinstance(function_payload, dict):
                function_name = function_payload.get("name")
                if isinstance(function_name, str) and function_name.strip():
                    names.add(function_name.strip())
    return names


def _available_tool_schemas(tool_manager: Any) -> Optional[dict[str, dict[str, Any]]]:
    """Return tool schemas for ordered-batch child payload preflight."""

    getter = getattr(tool_manager, "get_available_tool_schemas", None)
    if callable(getter):
        try:
            schemas = getter()
            if isinstance(schemas, dict):
                return {
                    str(name): schema
                    for name, schema in schemas.items()
                    if isinstance(schema, dict)
                }
        except Exception:
            logger.debug("Failed to read available tool schemas", exc_info=True)
            return {}

    schema_getter = getattr(tool_manager, "get_responses_tools", None)
    if not callable(schema_getter):
        return None
    try:
        schemas = schema_getter(include_web_search=False)
    except TypeError:
        try:
            schemas = schema_getter()
        except Exception:
            logger.debug("Failed to read response tool schemas", exc_info=True)
            return {}
    except Exception:
        logger.debug("Failed to read response tool schemas", exc_info=True)
        return {}

    resolved: dict[str, dict[str, Any]] = {}
    if isinstance(schemas, list):
        for schema in schemas:
            if not isinstance(schema, dict):
                continue
            name = schema.get("name")
            if isinstance(name, str) and name.strip():
                resolved[name.strip()] = schema
            function_payload = schema.get("function")
            if isinstance(function_payload, dict):
                function_name = function_payload.get("name")
                if isinstance(function_name, str) and function_name.strip():
                    resolved[function_name.strip()] = {
                        **schema,
                        "parameters": function_payload.get("parameters"),
                    }
    return resolved


def _get_last_provider_error(api_client: Any) -> Optional[LLMError]:
    try:
        getter = getattr(api_client, "get_last_error", None)
        provider_error = getter() if callable(getter) else None
    except Exception:
        return None
    return provider_error if isinstance(provider_error, LLMError) else None


def _get_last_call_result(api_client: Any) -> Optional[LLMCallResult]:
    try:
        getter = getattr(api_client, "get_last_response_result", None)
        result = getter() if callable(getter) else None
    except Exception:
        return None
    return result if isinstance(result, LLMCallResult) else None


async def _get_response_result(
    *,
    api_client: Any,
    messages: List[Dict[str, Any]],
    stream: Optional[bool],
    stream_callback: Optional[Callable[..., Any]],
    extra_kwargs: Dict[str, Any],
) -> LLMCallResult:
    result_getter = getattr(api_client, "get_response_result", None)
    if callable(result_getter):
        result = await result_getter(
            messages,
            stream=stream,
            stream_callback=stream_callback,
            **extra_kwargs,
        )
        if isinstance(result, LLMCallResult):
            if result.succeeded and _is_provider_error_response(result.text):
                legacy_error = LLMError(
                    message=result.text,
                    category=ErrorCategory.RUNTIME,
                    retryable=False,
                )
                return replace(
                    result,
                    status=LLMCallStatus.FATAL_ERROR,
                    error=legacy_error,
                )
            return result

    text = await api_client.get_response(
        messages,
        stream=stream,
        stream_callback=stream_callback,
        **extra_kwargs,
    )
    result = _get_last_call_result(api_client)
    if result is not None:
        if result.succeeded and _is_provider_error_response(result.text):
            return replace(
                result,
                status=LLMCallStatus.FATAL_ERROR,
                error=LLMError(
                    message=result.text,
                    category=ErrorCategory.RUNTIME,
                    retryable=False,
                ),
            )
        return result
    provider_error = _get_last_provider_error(api_client)
    if provider_error is None and _is_provider_error_response(str(text or "")):
        provider_error = LLMError(
            message=str(text),
            category=ErrorCategory.RUNTIME,
            retryable=False,
        )
    return LLMCallResult(
        text=str(text or ""),
        status=(
            LLMCallStatus.RETRYABLE_ERROR
            if provider_error is not None and provider_error.retryable
            else LLMCallStatus.FATAL_ERROR
            if provider_error is not None
            else LLMCallStatus.COMPLETED
        ),
        error=provider_error,
    )


def _result_network_attempts(
    result: Optional[LLMCallResult],
    provider_error: Optional[LLMError],
) -> int:
    """Return physical sends consumed by one logical provider call."""

    candidates: List[Any] = []
    if isinstance(result, LLMCallResult):
        candidates.append(result.provider_data.get("network_attempts"))
        if result.error is not None:
            candidates.append(result.error.provider_data.get("network_attempts"))
    if provider_error is not None:
        candidates.append(provider_error.provider_data.get("network_attempts"))
    for raw_value in candidates:
        try:
            value = int(raw_value)
        except (TypeError, ValueError):
            continue
        if value > 0:
            return min(2, value)
    return 1


def _provider_supports_network_attempt_budget(api_client: Any) -> bool:
    handler = getattr(api_client, "client_handler", None)
    return bool(getattr(handler, "supports_runtime_network_attempt_budget", False))


def _provider_call_kwargs(
    api_client: Any,
    extra_kwargs: Dict[str, Any],
    *,
    network_attempt_budget: int,
) -> Dict[str, Any]:
    resolved = dict(extra_kwargs)
    if _provider_supports_network_attempt_budget(api_client):
        resolved["_penguin_network_attempt_budget"] = max(
            1,
            min(2, network_attempt_budget),
        )
    return resolved


def _call_result_failed(result: Optional[LLMCallResult]) -> bool:
    return isinstance(result, LLMCallResult) and result.status in {
        LLMCallStatus.RETRYABLE_ERROR,
        LLMCallStatus.FATAL_ERROR,
        LLMCallStatus.CANCELLED,
    }


def _raise_provider_failure(
    result: Optional[LLMCallResult],
    provider_error: Optional[LLMError],
    *,
    retry_exhausted: bool = False,
    attempts: int = 1,
) -> None:
    error = (
        result.error
        if isinstance(result, LLMCallResult) and isinstance(result.error, LLMError)
        else provider_error
    )
    if error is None:
        error = LLMError(
            message="Provider request failed",
            category=ErrorCategory.UNKNOWN,
            retryable=False,
        )
    retry_after_exceeds_ceiling = _retry_after_exceeds_ceiling(error)
    if retry_exhausted or retry_after_exceeds_ceiling:
        error_payload = error.to_dict()
        provider_data = dict(error_payload.get("provider_data") or {})
        if retry_exhausted:
            provider_data.update(
                {
                    "automatic_retry_exhausted": True,
                    "attempts": max(1, attempts),
                }
            )
        if retry_after_exceeds_ceiling:
            provider_data.update(
                {
                    "automatic_retry_skipped": "retry_after_exceeds_ceiling",
                    "retry_wait_ceiling_seconds": _provider_retry_max_seconds(),
                }
            )
        error_payload["provider_data"] = provider_data
        error = LLMError.from_dict(error_payload)
    raise LLMProviderError(error)


def _is_provider_error_response(response: Optional[str]) -> bool:
    if not isinstance(response, str):
        return False
    stripped = response.strip()
    return stripped.startswith(("[Error:", "Error:", "[Model finished"))


def should_retry_provider_failure(
    *,
    provider_error: Optional[LLMError],
    response: Optional[str],
    streamed_assistant_chunk: bool,
    pending_tool_call: bool,
) -> bool:
    """Return whether a failed provider call is safe to replay once."""

    if provider_error is None or not provider_error.retryable:
        return False
    if _retry_after_exceeds_ceiling(provider_error):
        return False
    provider_data = provider_error.provider_data
    if provider_data.get("partial_tool_call"):
        return False
    partial_output = provider_data.get("partial_output")
    if isinstance(partial_output, str) and partial_output:
        return False
    if streamed_assistant_chunk or pending_tool_call:
        return False
    if response and response.strip() and not _is_provider_error_response(response):
        return False
    return True


def _positive_float_from_env(name: str, default: float) -> float:
    """Return one non-negative runtime tuning value."""

    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value >= 0 else default


def _provider_retry_max_seconds() -> float:
    """Return the longest provider-directed delay Penguin will wait inline."""

    base = _positive_float_from_env(
        "PENGUIN_PROVIDER_RETRY_BASE_SECONDS",
        _PROVIDER_RETRY_BASE_SECONDS,
    )
    return max(
        base,
        _positive_float_from_env(
            "PENGUIN_PROVIDER_RETRY_MAX_SECONDS",
            _PROVIDER_RETRY_MAX_SECONDS,
        ),
    )


def _retry_after_seconds(provider_error: Optional[LLMError]) -> Optional[float]:
    """Return a finite provider retry minimum when one is available."""

    if provider_error is None or provider_error.retry_after_seconds is None:
        return None
    try:
        value = float(provider_error.retry_after_seconds)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value >= 0 else None


def _retry_after_exceeds_ceiling(provider_error: Optional[LLMError]) -> bool:
    """Return whether respecting Retry-After would exceed the inline wait budget."""

    retry_after = _retry_after_seconds(provider_error)
    return retry_after is not None and retry_after > _provider_retry_max_seconds()


def _provider_retry_delay_seconds(
    provider_error: Optional[LLMError],
    *,
    random_value: float,
) -> float:
    """Return retry delay without ever shortening a provider minimum."""

    base = _positive_float_from_env(
        "PENGUIN_PROVIDER_RETRY_BASE_SECONDS",
        _PROVIDER_RETRY_BASE_SECONDS,
    )
    maximum = _provider_retry_max_seconds()
    jitter_fraction = min(
        1.0,
        _positive_float_from_env(
            "PENGUIN_PROVIDER_RETRY_JITTER_FRACTION",
            _PROVIDER_RETRY_JITTER_FRACTION,
        ),
    )
    retry_after = _retry_after_seconds(provider_error)
    if retry_after is not None:
        # Retry-After is a minimum imposed by the provider. Do not jitter it and
        # never cap it to an earlier retry. The caller surfaces values above the
        # configured inline wait ceiling instead of violating the minimum.
        return max(base, retry_after)

    if not math.isfinite(random_value):
        random_value = 0.5
    centered_random = min(1.0, max(0.0, random_value)) * 2.0 - 1.0
    delay = base * (1.0 + centered_random * jitter_fraction)
    return min(maximum, max(0.0, delay))


def _runtime_stream_callback_timeout_seconds() -> float:
    value = _positive_float_from_env(
        "PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS",
        _RUNTIME_STREAM_CALLBACK_TIMEOUT_SECONDS,
    )
    return value if value > 0 else _RUNTIME_STREAM_CALLBACK_TIMEOUT_SECONDS


def _runtime_callback_args(
    callback: Callable[..., Any],
    chunk: str,
    message_type: str,
) -> tuple[Any, ...]:
    try:
        arity = len(inspect.signature(callback).parameters)
    except (TypeError, ValueError):
        arity = 2
    return (chunk, message_type) if arity >= 2 else (chunk,)


def _observe_timed_out_callback(task: "asyncio.Future[Any]") -> None:
    """Consume a detached callback task's late exception without blocking."""

    if task.cancelled():
        return
    try:
        task.result()
    except asyncio.CancelledError:
        return
    except Exception:
        logger.debug("Runtime callback failed after its timeout", exc_info=True)


async def _invoke_runtime_callback(
    callback: Callable[..., Any],
    *args: Any,
    callback_name: str = "Runtime callback",
) -> None:
    """Invoke a best-effort callback without letting it block core progress."""

    timeout = _runtime_stream_callback_timeout_seconds()
    is_async = asyncio.iscoroutinefunction(callback) or asyncio.iscoroutinefunction(
        getattr(callback, "__call__", None)
    )
    try:
        if is_async:
            result = callback(*args)
        else:
            submitted = _RUNTIME_SYNC_CALLBACK_EXECUTOR.submit(callback, args)
            if submitted is None:
                logger.warning(
                    "%s dropped because its bounded daemon worker is busy",
                    callback_name,
                )
                return
            submitted_future = asyncio.wrap_future(submitted)
            completed, _ = await asyncio.wait({submitted_future}, timeout=timeout)
            if not completed:
                logger.error("%s exceeded %.3fs", callback_name, timeout)
                return
            result = submitted_future.result()
        if inspect.isawaitable(result):
            callback_task = asyncio.ensure_future(result)
            completed, _ = await asyncio.wait({callback_task}, timeout=timeout)
            if not completed:
                callback_task.cancel()
                callback_task.add_done_callback(_observe_timed_out_callback)
                logger.error("%s exceeded %.3fs", callback_name, timeout)
                return
            callback_task.result()
    except Exception:
        logger.exception("%s failed", callback_name)


async def _invoke_runtime_stream_callback(
    callback: Callable[..., Any],
    chunk: str,
    message_type: str,
) -> None:
    """Invoke stream callbacks with legacy one-argument compatibility."""

    await _invoke_runtime_callback(
        callback,
        *_runtime_callback_args(callback, chunk, message_type),
        callback_name="Runtime stream callback",
    )


def _get_tool_payload(
    tool_manager: Any,
    *,
    include_web_search: bool,
) -> List[Dict[str, Any]]:
    tools_getter = getattr(tool_manager, "get_responses_tools", None)
    if not callable(tools_getter):
        return []
    signature = inspect.signature(tools_getter)
    accepts_include_web_search = "include_web_search" in signature.parameters or any(
        parameter.kind is inspect.Parameter.VAR_KEYWORD
        for parameter in signature.parameters.values()
    )
    if accepts_include_web_search:
        tools_payload = tools_getter(include_web_search=include_web_search)
    else:
        tools_payload = tools_getter()
    return list(tools_payload or [])


def _native_tool_name(tool: Dict[str, Any]) -> str:
    function_payload = tool.get("function")
    if isinstance(function_payload, dict):
        return str(function_payload.get("name") or tool.get("name") or "")
    return str(tool.get("name") or "")


def _filter_native_loop_control_tools(
    tools_payload: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Remove model-callable loop controls from native provider schemas."""

    filtered: List[Dict[str, Any]] = []
    omitted: set[str] = set()
    for tool in tools_payload:
        if not isinstance(tool, dict):
            continue
        tool_name = _native_tool_name(tool)
        if tool_name in _NATIVE_RESPONSE_COMPLETION_TOOLS:
            omitted.add(tool_name)
            continue
        filtered.append(tool)

    if omitted:
        logger.debug(
            "Omitted native response completion tool(s) from provider schema: %s",
            sorted(omitted),
        )
    return filtered


def prepare_native_tool_kwargs(model_config: Any, tool_manager: Any) -> Dict[str, Any]:
    """Build native tool kwargs for providers that support structured tool calls."""

    extra_kwargs: Dict[str, Any] = {}
    if model_config is None:
        return extra_kwargs

    tool_format = native_tool_format(model_config)
    if not tool_format:
        return extra_kwargs

    tools_payload = _get_tool_payload(
        tool_manager,
        include_web_search=tool_format == "openai_responses",
    )
    tools_payload = _filter_native_loop_control_tools(tools_payload)
    if not tools_payload:
        return extra_kwargs

    if tool_format == "openai_responses":
        normalized_tools = normalize_openai_responses_tools(tools_payload)
        if not normalized_tools:
            return extra_kwargs
        setattr(model_config, "interrupt_on_tool_call", True)
        extra_kwargs["tools"] = normalized_tools
        extra_kwargs["tool_choice"] = normalize_openai_responses_tool_choice("auto")
        return extra_kwargs

    if tool_format == "openai_chat":
        normalized_tools = normalize_openai_chat_tools(tools_payload)
        if not normalized_tools:
            return extra_kwargs
        setattr(model_config, "interrupt_on_tool_call", True)
        extra_kwargs["tools"] = normalized_tools
        extra_kwargs["tool_choice"] = normalize_openai_chat_tool_choice("auto")
        extra_kwargs["parallel_tool_calls"] = False
        return extra_kwargs

    if tool_format == "anthropic":
        normalized_tools = normalize_anthropic_tools(tools_payload)
        if not normalized_tools:
            return extra_kwargs
        setattr(model_config, "interrupt_on_tool_call", True)
        extra_kwargs["tools"] = normalized_tools
        extra_kwargs["tool_choice"] = {"type": "auto"}
        return extra_kwargs

    return extra_kwargs


def prepare_responses_tool_kwargs(
    model_config: Any, tool_manager: Any
) -> Dict[str, Any]:
    """Backward-compatible wrapper for native tool kwargs preparation."""

    return prepare_native_tool_kwargs(model_config, tool_manager)


def handler_has_pending_tool_call(api_client: Any) -> bool:
    """Return whether the active handler captured a tool call to execute."""

    try:
        handler = getattr(api_client, "client_handler", None)
        checker = getattr(handler, "has_pending_tool_call", None)
        if callable(checker):
            return bool(checker())
    except Exception:
        return False
    return False


def build_empty_response_diagnostics(
    *,
    messages: List[Dict[str, Any]],
    raw_response: Optional[str],
    model_config: Any = None,
    provider_error: Any = None,
    handler: Any = None,
) -> Dict[str, Any]:
    """Build detailed diagnostics for empty provider responses."""

    diagnostics: Dict[str, Any] = {
        "raw_response": repr(raw_response) if raw_response else "(None)",
        "response_length": len(raw_response) if raw_response else 0,
    }

    try:
        diagnostics["message_count"] = len(messages)
        diagnostics["total_chars"] = sum(
            len(str(m.get("content", ""))) for m in messages
        )
        diagnostics["approx_tokens"] = diagnostics["total_chars"] // 4
    except Exception:
        diagnostics["message_stats_error"] = "Failed to compute message stats"

    try:
        if model_config:
            diagnostics["model"] = getattr(model_config, "model", "unknown")
            diagnostics["provider"] = getattr(model_config, "provider", "unknown")
            diagnostics["max_context_window_tokens"] = getattr(
                model_config,
                "max_context_window_tokens",
                None,
            )
            diagnostics["max_output_tokens"] = getattr(
                model_config,
                "max_output_tokens",
                None,
            )
    except Exception:
        diagnostics["model_config_error"] = "Failed to get model config"

    api_error_detected = False
    error_type = "unknown"
    error_detail = None

    if provider_error is not None:
        api_error_detected = True
        error_type = getattr(
            getattr(provider_error, "category", None), "value", "unknown"
        )
        error_detail = getattr(provider_error, "message", None)
        diagnostics["handler_error"] = error_detail
        retry_after = getattr(provider_error, "retry_after_seconds", None)
        if retry_after is not None:
            diagnostics["retry_after_seconds"] = retry_after
    elif raw_response:
        stripped = raw_response.strip()
        if stripped.startswith("[Error:"):
            api_error_detected = True
            error_detail = stripped
            if "context" in stripped.lower() or "token" in stripped.lower():
                error_type = "context_window_exceeded"
            elif "quota" in stripped.lower() or "credit" in stripped.lower():
                error_type = "quota_exceeded"
            elif "rate" in stripped.lower() or "429" in stripped:
                error_type = "rate_limited"
            elif "auth" in stripped.lower() or "key" in stripped.lower():
                error_type = "authentication_error"
            elif "model" in stripped.lower() and "not found" in stripped.lower():
                error_type = "model_not_found"
            else:
                error_type = "api_error"

    diagnostics["api_error_detected"] = api_error_detected
    diagnostics["error_type"] = error_type
    if error_detail:
        diagnostics["error_detail"] = error_detail

    try:
        if handler is not None:
            last_error = getattr(handler, "last_error", None) or getattr(
                handler, "_last_error", None
            )
            if last_error:
                diagnostics["handler_error"] = str(last_error)
    except Exception:
        pass

        # TODO: review these user messages for clarity and helpfulness, and consider adding more specific guidance based on error type and diagnostics
    user_messages = {
        "context_window_exceeded": (
            f"Context window exceeded. Your conversation has ~{diagnostics.get('approx_tokens', '?')} tokens "
            "but the model limit may be lower."
        ),
        "quota_exceeded": "API quota/credits exceeded. Check your account balance and billing status.",
        "rate_limit": "Rate limit exceeded. Wait a moment and try again, or reduce request frequency.",
        "rate_limited": "Rate limit exceeded. Wait a moment and try again, or reduce request frequency.",
        "bad_request": (
            f"LLM upstream rejected the request. {error_detail or 'Check request parameters and token limits.'}"
        ),
        "provider_unavailable": "LLM upstream is unavailable. Wait a moment and try again.",
        "network": "LLM network request failed. Check connectivity and retry.",
        "timeout": "LLM request timed out. Wait a moment and try again.",
        "auth": "LLM authentication failed. Reconnect or check credentials.",
        "authentication_error": "API authentication failed. Check your API key is valid and properly configured.",
        "model_not_found": (
            f"Model '{diagnostics.get('model', 'unknown')}' not found. Check the model name is correct and you have access to it."
        ),
        "api_error": (
            f"API returned an error: {error_detail or 'Unknown error'}. Check the API status and your request parameters."
        ),
        "unknown": (
            f"Model returned empty response after retry. Conversation has {diagnostics.get('message_count', '?')} messages, "
            f"~{diagnostics.get('approx_tokens', '?')} tokens. Possible causes: (1) Context too large, (2) API issue, (3) Model refusing to respond."
        ),
    }
    diagnostics["user_message"] = user_messages.get(
        error_type, user_messages["unknown"]
    )
    diagnostics["summary"] = (
        f"Empty response from {diagnostics.get('model', 'unknown')} "
        f"(type={error_type}, msgs={diagnostics.get('message_count', '?')}, "
        f"tokens≈{diagnostics.get('approx_tokens', '?')})"
    )
    return diagnostics


async def call_with_retry(
    *,
    api_client: Any,
    messages: List[Dict[str, Any]],
    streaming: Optional[bool],
    stream_callback: Optional[Callable[..., Any]],
    extra_kwargs: Dict[str, Any],
    model_config: Any = None,
    retry_sleep: Callable[[float], Awaitable[Any]] = asyncio.sleep,
    retry_random: Callable[[], float] = random.random,
    usage_callback: Optional[Callable[[Dict[str, Any]], Any]] = None,
) -> str:
    """Call a provider at most twice when one replay is provably safe."""

    streamed_assistant_chunk = False
    replayed_retry_response = False
    attempts = 0

    async def _attempt(
        *,
        stream: Optional[bool],
        callback: Optional[Callable[..., Any]],
        kwargs: Dict[str, Any],
    ) -> LLMCallResult:
        try:
            return await _get_response_result(
                api_client=api_client,
                messages=messages,
                stream=stream,
                stream_callback=callback,
                extra_kwargs=kwargs,
            )
        finally:
            if usage_callback is not None:
                handler = getattr(api_client, "client_handler", None)
                getter = getattr(handler, "get_last_usage", None)
                try:
                    usage = getter() if callable(getter) else {}
                except Exception:
                    logger.warning(
                        "Failed to collect provider usage after an LLM attempt",
                        exc_info=True,
                    )
                    usage = {}
                try:
                    callback_result = usage_callback(
                        dict(usage) if isinstance(usage, dict) else {}
                    )
                    if inspect.isawaitable(callback_result):
                        await callback_result
                except Exception:
                    logger.warning(
                        "Failed to report provider usage after an LLM attempt",
                        exc_info=True,
                    )

    async def _tracked_stream_callback(
        chunk: str, message_type: str = "assistant"
    ) -> None:
        nonlocal streamed_assistant_chunk
        if chunk and message_type == "assistant":
            streamed_assistant_chunk = True
        if stream_callback is None:
            return
        await _invoke_runtime_stream_callback(
            stream_callback,
            chunk,
            message_type,
        )

    call_result = await _attempt(
        stream=streaming,
        callback=(
            _tracked_stream_callback
            if streaming and stream_callback
            else stream_callback
        ),
        kwargs=_provider_call_kwargs(
            api_client,
            extra_kwargs,
            network_attempt_budget=2,
        ),
    )
    assistant_response = call_result.text

    pending_tool_call = bool(
        call_result.pending_tool_call or handler_has_pending_tool_call(api_client)
    )
    streamed_attempt_output = bool(
        streamed_assistant_chunk or call_result.streamed_assistant_chunks
    )
    provider_error = call_result.error or _get_last_provider_error(api_client)
    attempts = _result_network_attempts(call_result, provider_error)
    if _call_result_failed(call_result):
        if attempts < 2 and should_retry_provider_failure(
            provider_error=provider_error,
            response=assistant_response,
            streamed_assistant_chunk=streamed_attempt_output,
            pending_tool_call=pending_tool_call,
        ):
            retry_delay = _provider_retry_delay_seconds(
                provider_error,
                random_value=retry_random(),
            )
            retry_started = time.perf_counter()
            await retry_sleep(retry_delay)
            record_runtime_duration(
                "provider.retry_backoff",
                (time.perf_counter() - retry_started) * 1000,
            )
            call_result = await _attempt(
                stream=False,
                callback=None,
                kwargs=_provider_call_kwargs(
                    api_client,
                    extra_kwargs,
                    network_attempt_budget=2 - attempts,
                ),
            )
            assistant_response = call_result.text
        else:
            _raise_provider_failure(
                call_result,
                provider_error,
                retry_exhausted=attempts >= 2 and bool(provider_error.retryable)
                if provider_error is not None
                else False,
                attempts=attempts,
            )
        if (
            streaming
            and stream_callback
            and assistant_response
            and assistant_response.strip()
            and call_result.succeeded
        ):
            await _tracked_stream_callback(assistant_response, "assistant")
            replayed_retry_response = True
        pending_tool_call = bool(
            call_result.pending_tool_call or handler_has_pending_tool_call(api_client)
        )
        streamed_attempt_output = bool(
            streamed_assistant_chunk or call_result.streamed_assistant_chunks
        )
        provider_error = call_result.error or _get_last_provider_error(api_client)
        attempts = min(
            2,
            attempts + _result_network_attempts(call_result, provider_error),
        )
        if _call_result_failed(call_result):
            _raise_provider_failure(
                call_result,
                provider_error,
                retry_exhausted=True,
                attempts=attempts,
            )

    if not assistant_response or not assistant_response.strip():
        if streamed_attempt_output:
            return assistant_response or ""
        if pending_tool_call:
            return assistant_response or ""
        if attempts < 2:
            retry_delay = _provider_retry_delay_seconds(
                provider_error,
                random_value=retry_random(),
            )
            retry_started = time.perf_counter()
            await retry_sleep(retry_delay)
            record_runtime_duration(
                "provider.retry_backoff",
                (time.perf_counter() - retry_started) * 1000,
            )
            call_result = await _attempt(
                stream=False,
                callback=None,
                kwargs=_provider_call_kwargs(
                    api_client,
                    extra_kwargs,
                    network_attempt_budget=2 - attempts,
                ),
            )
            assistant_response = call_result.text
            if (
                streaming
                and stream_callback
                and assistant_response
                and assistant_response.strip()
                and call_result.succeeded
            ):
                await _tracked_stream_callback(assistant_response, "assistant")
                replayed_retry_response = True
            pending_tool_call = bool(
                call_result.pending_tool_call
                or handler_has_pending_tool_call(api_client)
            )
            streamed_attempt_output = bool(
                streamed_assistant_chunk or call_result.streamed_assistant_chunks
            )
            provider_error = call_result.error or _get_last_provider_error(api_client)
            attempts = min(
                2,
                attempts + _result_network_attempts(call_result, provider_error),
            )
            if _call_result_failed(call_result):
                _raise_provider_failure(
                    call_result,
                    provider_error,
                    retry_exhausted=True,
                    attempts=attempts,
                )

    if not assistant_response or not assistant_response.strip():
        if streamed_attempt_output:
            return assistant_response or ""
        if pending_tool_call:
            return assistant_response or ""
        diagnostics = build_empty_response_diagnostics(
            messages=messages,
            raw_response=assistant_response,
            model_config=model_config,
            provider_error=provider_error,
            handler=getattr(api_client, "client_handler", None),
        )
        raise LLMEmptyResponseError(diagnostics["user_message"])

    if (
        streaming
        and stream_callback
        and assistant_response
        and assistant_response.strip()
        and not streamed_assistant_chunk
        and not replayed_retry_response
    ):
        await _tracked_stream_callback(assistant_response, "assistant")

    return assistant_response


async def execute_pending_tool_call(
    *,
    api_client: Any,
    tool_manager: Any,
    persist_action_result: Callable[[Dict[str, Any], Dict[str, Any]], None],
    persist_tool_call_record: Optional[Callable[[ToolCall], None]] = None,
    persist_tool_result_record: Optional[Callable[[ToolCall, ToolResult], None]] = None,
    execution_policy: Optional[ToolExecutionPolicy] = None,
    emit_action_start: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_action_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_tool_timeline: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    persist_native_tool_batch: Optional[
        Callable[[List[ToolCall], List[Dict[str, Any]]], bool]
    ] = None,
) -> Optional[Dict[str, Any]]:
    """Execute a pending provider-captured tool call using generic hooks."""

    results = await execute_pending_tool_calls(
        api_client=api_client,
        tool_manager=tool_manager,
        persist_action_result=persist_action_result,
        persist_tool_call_record=persist_tool_call_record,
        persist_tool_result_record=persist_tool_result_record,
        execution_policy=execution_policy,
        emit_action_start=emit_action_start,
        emit_action_result=emit_action_result,
        emit_tool_timeline=emit_tool_timeline,
        persist_native_tool_batch=persist_native_tool_batch,
    )
    return results[0] if results else None


async def _call_pending_tool_getter(getter: Any) -> Any:
    """Call a sync or async pending-tool getter."""

    if not callable(getter):
        return None
    result = getter()
    if asyncio.iscoroutine(result):
        return await result
    return result


async def _get_and_clear_pending_tool_infos(api_client: Any) -> List[Dict[str, Any]]:
    """Return all provider-captured tool calls from the active handler."""

    handler = getattr(api_client, "client_handler", None)
    try:
        plural_getter = getattr(handler, "get_and_clear_pending_tool_calls", None)
        tool_infos = await _call_pending_tool_getter(plural_getter)
    except Exception:
        logger.exception(
            "Failed to read pending tool calls from api_client=%r handler=%r "
            "via get_and_clear_pending_tool_calls",
            api_client,
            handler,
        )
        raise
    if isinstance(tool_infos, list):
        return [item for item in tool_infos if isinstance(item, dict)]
    if isinstance(tool_infos, dict):
        return [tool_infos]

    try:
        singular_getter = getattr(handler, "get_and_clear_last_tool_call", None)
        tool_info = await _call_pending_tool_getter(singular_getter)
    except Exception:
        logger.exception(
            "Failed to read pending tool call from api_client=%r handler=%r "
            "via get_and_clear_last_tool_call",
            api_client,
            handler,
        )
        raise

    return [tool_info] if isinstance(tool_info, dict) else []


def _provider_tool_call_id(tool_info: Dict[str, Any]) -> str:
    """Return the provider-issued id required to execute a native tool call."""

    for key in ("call_id", "tool_call_id", "item_id"):
        call_id = str(tool_info.get(key) or "").strip()
        if call_id:
            return call_id
    return ""


def _has_unique_provider_tool_call_ids(tool_infos: List[Dict[str, Any]]) -> bool:
    """Reject malformed provider tool batches before they can cause side effects."""

    call_ids = [_provider_tool_call_id(tool_info) for tool_info in tool_infos]
    if not call_ids or any(not call_id for call_id in call_ids):
        logger.warning(
            "Rejected pending native tool batch without provider call ids: count=%s",
            len(tool_infos),
        )
        return False
    if len(call_ids) != len(set(call_ids)):
        logger.warning(
            "Rejected pending native tool batch with duplicate provider call ids: ids=%s",
            call_ids,
        )
        return False
    return True


def _persist_best_effort_tool_record(
    callback: Callable[..., None],
    *args: Any,
    record_name: str,
) -> None:
    """Keep diagnostic record failures from interrupting model-visible history."""

    try:
        callback(*args)
    except Exception:
        logger.exception("Failed to persist %s", record_name)


async def _execute_ordered_batch_parent(
    *,
    parent_call: ToolCall,
    tool_manager: Any,
    available_tool_names: Optional[set[str]],
    available_tool_schemas: Optional[dict[str, dict[str, Any]]],
    metadata_getter: Optional[Callable[[str], Dict[str, Any]]],
    base_policy: ToolExecutionPolicy,
    persist_tool_call_record: Optional[Callable[[ToolCall], None]],
    persist_tool_result_record: Optional[Callable[[ToolCall, ToolResult], None]],
    emit_action_start: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    emit_action_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    emit_tool_timeline: Optional[Callable[[Dict[str, Any]], Awaitable[None]]],
    event_metadata: Dict[str, Any],
) -> ToolResult:
    """Execute one model-visible ordered batch and return its parent result."""

    plan = parse_ordered_tool_batch_plan(
        parent_call,
        available_tool_names=available_tool_names,
        available_tool_schemas=available_tool_schemas,
    )
    if plan.error:
        return ordered_tool_batch_preflight_error_result(parent_call, plan)

    child_calls = [
        tool_call_with_schedule_metadata(
            child_call,
            metadata_getter(child_call.name) if callable(metadata_getter) else None,
        )
        for child_call in plan.tool_calls
    ]
    plan = OrderedToolBatchPlan(
        parent_call_id=plan.parent_call_id,
        stop_on_error=plan.stop_on_error,
        tool_calls=tuple(child_calls),
        error=plan.error,
    )

    if persist_tool_call_record is not None:
        for child_call in child_calls:
            _persist_best_effort_tool_record(
                persist_tool_call_record,
                child_call,
                record_name="ordered native tool-call record",
            )

    if emit_action_start is not None:
        for child_call in child_calls:
            await _invoke_runtime_callback(
                emit_action_start,
                {
                    "id": child_call.id,
                    "type": child_call.name,
                    "action": child_call.name,
                    "params": (
                        json.dumps(child_call.arguments, sort_keys=True)
                        if isinstance(child_call.arguments, dict)
                        else str(child_call.arguments)
                    ),
                    "metadata": {
                        **event_metadata,
                        "source": "ordered_tool_batch_child",
                        "parent_tool_call_id": parent_call.id,
                    },
                },
                callback_name="Runtime tool action-start callback",
            )

    def _execute_child(child_call: ToolCall) -> Any:
        child_args = (
            child_call.arguments if isinstance(child_call.arguments, dict) else {}
        )
        return tool_manager.execute_tool(child_call.name, child_args)

    child_results = await execute_tool_calls_ordered(
        child_calls,
        _execute_child,
        policy=ToolExecutionPolicy(
            max_calls=(
                base_policy.max_calls
                if base_policy.max_calls is not None
                else len(child_calls)
            ),
            catch_exceptions=True,
            stop_on_error=plan.stop_on_error,
            max_output_chars=base_policy.max_output_chars,
            artifact_dir=base_policy.artifact_dir,
            truncation_direction=base_policy.truncation_direction,
        ),
    )

    for child_call, child_result in zip(child_calls, child_results):
        if persist_tool_result_record is not None:
            _persist_best_effort_tool_record(
                persist_tool_result_record,
                child_call,
                child_result,
                record_name="ordered native tool-result record",
            )
        legacy_child_result = legacy_action_result_from_tool_result(child_result)
        child_metadata = {
            **event_metadata,
            "source": "ordered_tool_batch_child",
            "parent_tool_call_id": parent_call.id,
        }
        if emit_action_result is not None:
            await _invoke_runtime_callback(
                emit_action_result,
                {
                    "id": child_call.id,
                    "status": legacy_child_result["status"],
                    "result": legacy_child_result["result"],
                    "action": legacy_child_result["action"],
                    "metadata": child_metadata,
                },
                callback_name="Runtime tool action-result callback",
            )
        if emit_tool_timeline is not None:
            await _invoke_runtime_callback(
                emit_tool_timeline,
                {
                    **legacy_child_result,
                    "tool_call_id": child_call.id,
                    "metadata": child_metadata,
                },
                callback_name="Runtime tool timeline callback",
            )

    return ordered_tool_batch_result_from_results(parent_call, plan, child_results)


async def execute_pending_tool_calls(
    *,
    api_client: Any,
    tool_manager: Any,
    persist_action_result: Callable[[Dict[str, Any], Dict[str, Any]], None],
    persist_tool_call_record: Optional[Callable[[ToolCall], None]] = None,
    persist_tool_result_record: Optional[Callable[[ToolCall, ToolResult], None]] = None,
    execution_policy: Optional[ToolExecutionPolicy] = None,
    emit_action_start: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_action_result: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    emit_tool_timeline: Optional[Callable[[Dict[str, Any]], Awaitable[None]]] = None,
    persist_image_artifacts: Optional[Callable[[Dict[str, Any]], None]] = None,
    persist_native_tool_batch: Optional[
        Callable[[List[ToolCall], List[Dict[str, Any]]], bool]
    ] = None,
) -> List[Dict[str, Any]]:
    """Execute all pending provider-captured tool calls using generic hooks."""

    tool_infos = await _get_and_clear_pending_tool_infos(api_client)
    if tool_infos and not _has_unique_provider_tool_call_ids(tool_infos):
        return []
    metadata_getter = getattr(tool_manager, "get_tool_runtime_metadata", None)
    tool_calls = [
        tool_call_with_schedule_metadata(
            tool_call,
            metadata_getter(tool_call.name) if callable(metadata_getter) else None,
        )
        for tool_call in (
            tool_call_from_responses_info(tool_info) for tool_info in tool_infos
        )
        if tool_call is not None
    ]
    if not tool_calls:
        return []

    batch_started = time.perf_counter()
    logger.info(
        "llm.tool_batch.start provider=%s model=%s count=%s names=%s args_chars=%s",
        getattr(getattr(api_client, "model_config", None), "provider", None),
        getattr(getattr(api_client, "model_config", None), "model", None),
        len(tool_calls),
        [tool_call.name for tool_call in tool_calls],
        sum(_tool_arguments_chars(tool_call.arguments) for tool_call in tool_calls),
    )

    if persist_tool_call_record is not None:
        for tool_call in tool_calls:
            _persist_best_effort_tool_record(
                persist_tool_call_record,
                tool_call,
                record_name="native tool-call record",
            )
    record_runtime_duration(
        "tool.queue",
        (time.perf_counter() - batch_started) * 1000,
    )

    parsed_args_by_id: Dict[str, Dict[str, Any]] = {}
    raw_args_by_id: Dict[str, str] = {}
    for tool_call in tool_calls:
        raw_args = tool_call.arguments
        if isinstance(raw_args, dict):
            parsed_args = raw_args
            raw_args_text = json.dumps(raw_args, sort_keys=True)
        else:
            raw_args_text = raw_args if isinstance(raw_args, str) else str(raw_args)
            try:
                parsed_args = (
                    json.loads(raw_args_text)
                    if isinstance(raw_args_text, str) and raw_args_text.strip()
                    else {}
                )
            except Exception:
                parsed_args = {}
        raw_args_by_id[tool_call.id] = raw_args_text
        if not isinstance(parsed_args, dict):
            parsed_args = {}
        parsed_args_by_id[tool_call.id] = parsed_args

    visible_tool_calls = [
        tool_call for tool_call in tool_calls if tool_call.name != "finish_response"
    ]

    event_metadata = {
        "provider": getattr(
            getattr(api_client, "model_config", None), "provider", None
        ),
        "model": getattr(getattr(api_client, "model_config", None), "model", None),
        "source": "responses_tool_call",
    }

    if emit_action_start is not None:
        for tool_call in visible_tool_calls:
            await _invoke_runtime_callback(
                emit_action_start,
                {
                    "id": tool_call.id,
                    "type": tool_call.name,
                    "action": tool_call.name,
                    "params": raw_args_by_id.get(tool_call.id, ""),
                    "metadata": event_metadata,
                },
                callback_name="Runtime tool action-start callback",
            )

    try:
        base_policy = execution_policy or ToolExecutionPolicy(catch_exceptions=True)
        known_tool_names = _available_tool_names(tool_manager)
        known_tool_schemas = _available_tool_schemas(tool_manager)

        async def _execute_scheduled_tool_call(
            current_tool_call: ToolCall,
        ) -> Any:
            if current_tool_call.name == ORDERED_TOOL_BATCH_NAME:
                return await _execute_ordered_batch_parent(
                    parent_call=current_tool_call,
                    tool_manager=tool_manager,
                    available_tool_names=known_tool_names,
                    available_tool_schemas=known_tool_schemas,
                    metadata_getter=metadata_getter,
                    base_policy=base_policy,
                    persist_tool_call_record=persist_tool_call_record,
                    persist_tool_result_record=persist_tool_result_record,
                    emit_action_start=emit_action_start,
                    emit_action_result=emit_action_result,
                    emit_tool_timeline=emit_tool_timeline,
                    event_metadata=event_metadata,
                )
            return tool_manager.execute_tool(
                current_tool_call.name,
                parsed_args_by_id.get(current_tool_call.id, {}),
            )

        schedule_started = time.perf_counter()
        scheduler_results = await execute_tool_calls_serially(
            tool_calls,
            _execute_scheduled_tool_call,
            policy=ToolExecutionPolicy(
                max_calls=(
                    base_policy.max_calls
                    if base_policy.max_calls is not None
                    else len(tool_calls)
                ),
                catch_exceptions=base_policy.catch_exceptions,
                stop_on_error=base_policy.stop_on_error,
                max_output_chars=base_policy.max_output_chars,
                artifact_dir=base_policy.artifact_dir,
                truncation_direction=base_policy.truncation_direction,
            ),
        )
        record_runtime_duration(
            "tool.batch.schedule",
            (time.perf_counter() - schedule_started) * 1000,
        )
        if not scheduler_results:
            logger.info(
                "llm.tool_batch.done provider=%s model=%s count=%s results=0 "
                "duration_ms=%.2f",
                getattr(getattr(api_client, "model_config", None), "provider", None),
                getattr(getattr(api_client, "model_config", None), "model", None),
                len(tool_calls),
                (time.perf_counter() - batch_started) * 1000,
            )
            return []
        persistence_started = time.perf_counter()
        action_results: List[Dict[str, Any]] = []
        native_batch_calls: List[ToolCall] = []
        native_batch_results: List[Dict[str, Any]] = []
        image_artifact_results: List[Dict[str, Any]] = []
        for tool_result in scheduler_results:
            source_tool_call = next(
                (
                    current_tool_call
                    for current_tool_call in tool_calls
                    if current_tool_call.id == tool_result.call_id
                ),
                None,
            )
            if source_tool_call is None:
                continue
            if persist_tool_result_record is not None:
                _persist_best_effort_tool_record(
                    persist_tool_result_record,
                    source_tool_call,
                    tool_result,
                    record_name="native tool-result record",
                )
            suppress_ui_artifacts = source_tool_call.name == "finish_response"
            raw_args_text = raw_args_by_id.get(source_tool_call.id, "")
            tool_call_id = source_tool_call.id
            legacy_action_result = legacy_action_result_from_tool_result(tool_result)
            structured_output = tool_result.structured_output or {}
            runtime_action_result = {
                **structured_output,
                **legacy_action_result,
                "tool_call_id": source_tool_call.id,
                "tool_arguments": raw_args_text,
                "output_hash": tool_result.output_hash,
            }
            if not suppress_ui_artifacts:
                if persist_native_tool_batch is None:
                    persist_action_result(
                        legacy_action_result,
                        {
                            "tool_call_id": tool_call_id,
                            "tool_arguments": runtime_action_result["tool_arguments"],
                        },
                    )
                else:
                    native_batch_calls.append(source_tool_call)
                    native_batch_results.append(runtime_action_result)
                if persist_image_artifacts is not None:
                    if persist_native_tool_batch is None:
                        persist_image_artifacts(runtime_action_result)
                    else:
                        # Image artifacts append ordinary messages.  Defer them
                        # until the native declaration/results batch is complete
                        # so they cannot interleave with provider replay state.
                        image_artifact_results.append(runtime_action_result)

            if emit_action_result is not None and not suppress_ui_artifacts:
                await _invoke_runtime_callback(
                    emit_action_result,
                    {
                        "id": tool_call_id,
                        "status": legacy_action_result["status"],
                        "result": legacy_action_result["result"],
                        "action": legacy_action_result["action"],
                        "metadata": event_metadata,
                    },
                    callback_name="Runtime tool action-result callback",
                )
            if emit_tool_timeline is not None and not suppress_ui_artifacts:
                await _invoke_runtime_callback(
                    emit_tool_timeline,
                    legacy_action_result,
                    callback_name="Runtime tool timeline callback",
                )
            action_results.append(
                legacy_action_result if suppress_ui_artifacts else runtime_action_result
            )
        record_runtime_duration(
            "tool.persistence",
            (time.perf_counter() - persistence_started) * 1000,
        )
        if native_batch_calls and persist_native_tool_batch is not None:
            try:
                persisted = persist_native_tool_batch(
                    native_batch_calls,
                    native_batch_results,
                )
            except NativeToolHistoryPersistenceError:
                raise
            except Exception as exc:
                # Fail closed: the durable tool records remain available for
                # diagnostics, but do not fall back to per-result native
                # writes that could leave an interleaved transcript.
                logger.exception("Failed to persist complete native tool batch")
                raise NativeToolHistoryPersistenceError(
                    [tool_call.id for tool_call in native_batch_calls],
                    reason=str(exc),
                ) from exc
            if not persisted:
                raise NativeToolHistoryPersistenceError(
                    [tool_call.id for tool_call in native_batch_calls],
                    reason="The native batch callback did not confirm persistence.",
                )
        if persist_image_artifacts is not None:
            for runtime_action_result in image_artifact_results:
                try:
                    persist_image_artifacts(runtime_action_result)
                except Exception:
                    logger.exception("Failed to persist deferred tool image artifact")
        logger.info(
            "llm.tool_batch.done provider=%s model=%s count=%s results=%s "
            "duration_ms=%.2f statuses=%s",
            getattr(getattr(api_client, "model_config", None), "provider", None),
            getattr(getattr(api_client, "model_config", None), "model", None),
            len(tool_calls),
            len(action_results),
            (time.perf_counter() - batch_started) * 1000,
            [result.status for result in scheduler_results],
        )
        return action_results
    except NativeToolHistoryPersistenceError:
        logger.error(
            "llm.tool_batch.native_history_failure provider=%s model=%s count=%s "
            "duration_ms=%.2f",
            getattr(getattr(api_client, "model_config", None), "provider", None),
            getattr(getattr(api_client, "model_config", None), "model", None),
            len(tool_calls),
            (time.perf_counter() - batch_started) * 1000,
        )
        raise
    except Exception as exc:
        logger.warning(
            "llm.tool_batch.error provider=%s model=%s count=%s duration_ms=%.2f "
            "error=%s",
            getattr(getattr(api_client, "model_config", None), "provider", None),
            getattr(getattr(api_client, "model_config", None), "model", None),
            len(tool_calls),
            (time.perf_counter() - batch_started) * 1000,
            exc,
        )
        if emit_action_result is not None:
            for tool_call in visible_tool_calls:
                await _invoke_runtime_callback(
                    emit_action_result,
                    {
                        "id": tool_call.id,
                        "status": "error",
                        "result": f"Error executing action {tool_call.name}: {exc}",
                        "action": tool_call.name,
                        "metadata": event_metadata,
                    },
                    callback_name="Runtime tool action-result callback",
                )
        return []
    finally:
        record_runtime_duration(
            "tool.batch",
            (time.perf_counter() - batch_started) * 1000,
        )


def resolve_reasoning_payload(model_config: Any) -> Optional[Dict[str, Any]]:
    """Return normalized reasoning payload from a model config when available."""

    getter = getattr(model_config, "get_reasoning_config", None)
    if not callable(getter):
        return None
    try:
        resolved = getter()
    except Exception:
        return None
    return dict(resolved) if isinstance(resolved, dict) else None


def build_reasoning_visibility_note(
    *,
    include_reasoning: bool,
    reasoning_text: str,
    reasoning_payload: Optional[Dict[str, Any]],
    usage: Optional[Dict[str, Any]],
) -> Optional[str]:
    """Return no UI note when visible reasoning is absent."""

    del include_reasoning, reasoning_text, reasoning_payload, usage
    return None


def build_reasoning_debug_snapshot(
    *,
    api_client: Optional[Any],
    session_id: Optional[str],
    request_id: Optional[str],
    model_config: Optional[Any],
    reasoning_payload: Optional[Dict[str, Any]],
    include_reasoning: bool,
    reasoning_text: str,
    reasoning_note: Optional[str],
    usage: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """Collect a persisted reasoning debug snapshot for the last request."""

    handler_snapshot: Dict[str, Any] = {}
    finish_reason = None
    if api_client is not None:
        getter = getattr(api_client, "get_reasoning_debug_snapshot", None)
        if callable(getter):
            try:
                resolved = getter()
                if isinstance(resolved, dict):
                    handler_snapshot = dict(resolved)
            except Exception:
                handler_snapshot = {}
        handler = getattr(api_client, "client_handler", None)
        finish_getter = getattr(handler, "get_last_finish_reason", None)
        if callable(finish_getter):
            try:
                finish_value = finish_getter()
                finish_reason = (
                    finish_value.value
                    if hasattr(finish_value, "value")
                    else str(finish_value)
                )
            except Exception:
                finish_reason = None

    return {
        "session_id": session_id,
        "request_id": request_id,
        "provider": getattr(model_config, "provider", None),
        "model": getattr(model_config, "model", None),
        "include_reasoning": include_reasoning,
        "reasoning_requested": bool(
            isinstance(reasoning_payload, dict) and reasoning_payload
        ),
        "reasoning_payload": dict(reasoning_payload or {}),
        "reasoning_text": reasoning_text,
        "reasoning_len": len(reasoning_text or ""),
        "reasoning_note": reasoning_note,
        "usage": dict(usage or {}),
        "finish_reason": finish_reason,
        "handler_debug": handler_snapshot,
    }


def persist_reasoning_debug_snapshot(
    core: Any,
    session_id: Optional[str],
    snapshot: Optional[Dict[str, Any]],
) -> None:
    """Persist latest reasoning debug snapshot for inspection."""

    if not isinstance(session_id, str) or not session_id.strip():
        return
    if not isinstance(snapshot, dict) or not snapshot:
        return
    snapshot_store = getattr(core, "_reasoning_debug_snapshots", None)
    if not isinstance(snapshot_store, dict):
        snapshot_store = {}
        setattr(core, "_reasoning_debug_snapshots", snapshot_store)
    snapshot_store[session_id] = dict(snapshot)


def build_reasoning_fallback_note(
    api_client: Any, usage: Optional[Dict[str, Any]] = None
) -> Optional[str]:
    """Return no fallback note when visible reasoning is absent."""

    del api_client, usage
    return None


def apply_reasoning_variant_override(
    model_config: Any,
    variant: Optional[str],
    *,
    supported_efforts: Any = None,
) -> Optional[Dict[str, Any]]:
    """Apply a temporary reasoning variant override to a model config."""

    if model_config is None:
        return None

    value = variant.strip().lower() if isinstance(variant, str) else ""
    if not value:
        return None

    snapshot = {
        "reasoning_enabled": getattr(model_config, "reasoning_enabled", False),
        "reasoning_effort": getattr(model_config, "reasoning_effort", None),
        "reasoning_max_tokens": getattr(model_config, "reasoning_max_tokens", None),
        "reasoning_exclude": getattr(model_config, "reasoning_exclude", False),
        "supports_reasoning": getattr(model_config, "supports_reasoning", None),
        "_has_supports_reasoning": hasattr(model_config, "supports_reasoning"),
    }

    if value in _REASONING_DISABLE_VARIANTS:
        model_config.reasoning_enabled = False
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        return snapshot

    provider_id = str(getattr(model_config, "provider", "") or "").strip().lower()
    model_id = str(getattr(model_config, "model", "") or "").strip()

    raw_metadata_variants = getattr(model_config, "supported_reasoning_levels", None)
    metadata_variants = reasoning_efforts_from_metadata(raw_metadata_variants)
    capability_variants = reasoning_efforts_from_metadata(supported_efforts)
    capability_declared = supported_efforts is not None
    metadata_declared = raw_metadata_variants is not None
    if capability_declared:
        supported_native_variants = capability_variants
    elif metadata_declared:
        supported_native_variants = metadata_variants
    else:
        supported_native_variants = native_reasoning_efforts(provider_id, model_id)

    if capability_declared or metadata_declared or supported_native_variants:
        if value not in supported_native_variants:
            raise UnsupportedReasoningVariantError(
                provider=provider_id,
                model=model_id,
                variant=value,
                supported=supported_native_variants,
            )

        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_EFFORT_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = value
        model_config.reasoning_max_tokens = None
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    if value in _REASONING_MAX_VARIANTS:
        model_config.reasoning_enabled = True
        model_config.reasoning_effort = None
        model_config.reasoning_max_tokens = 32000
        model_config.reasoning_exclude = False
        model_config.supports_reasoning = True
        return snapshot

    return None


def restore_reasoning_variant_override(
    model_config: Any, snapshot: Optional[Dict[str, Any]]
) -> None:
    """Restore model config reasoning settings from a snapshot."""

    if model_config is None or not isinstance(snapshot, dict):
        return

    model_config.reasoning_enabled = bool(snapshot.get("reasoning_enabled", False))
    model_config.reasoning_effort = snapshot.get("reasoning_effort")
    model_config.reasoning_max_tokens = snapshot.get("reasoning_max_tokens")
    model_config.reasoning_exclude = bool(snapshot.get("reasoning_exclude", False))
    if snapshot.get("_has_supports_reasoning"):
        model_config.supports_reasoning = snapshot.get("supports_reasoning")
    elif hasattr(model_config, "supports_reasoning"):
        try:
            delattr(model_config, "supports_reasoning")
        except Exception:
            pass


__all__ = [
    "apply_reasoning_variant_override",
    "build_empty_response_diagnostics",
    "build_reasoning_debug_snapshot",
    "build_reasoning_fallback_note",
    "build_reasoning_visibility_note",
    "call_with_retry",
    "execute_pending_tool_call",
    "execute_pending_tool_calls",
    "handler_has_pending_tool_call",
    "persist_reasoning_debug_snapshot",
    "prepare_native_tool_kwargs",
    "prepare_responses_tool_kwargs",
    "resolve_reasoning_payload",
    "restore_reasoning_variant_override",
]
