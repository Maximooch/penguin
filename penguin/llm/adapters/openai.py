from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import math
import os
import time
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import (
    Any,
    AsyncIterator,
    Awaitable,
    Callable,
    Dict,
    List,
    Optional,
    Tuple,
    Union,
    cast,
)

import httpx  # type: ignore
import tiktoken  # type: ignore
from openai import AsyncOpenAI  # type: ignore

from penguin.system.native_tool_history import sanitize_native_tool_messages
from penguin.system.runtime_diagnostics import (
    mark_runtime_progress,
    record_runtime_duration,
)
from penguin.web.services.provider_auth import (
    ProviderOAuthError,
    refresh_provider_oauth,
)
from penguin.web.services.provider_credentials import (
    get_provider_credential,
    oauth_record_expired,
    oauth_record_needs_refresh,
)

from ..api_client import ConnectionPoolManager
from ..contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMPreparedRequest,
    LLMProviderCapabilities,
    LLMProviderError,
    LLMRequestLifecycle,
    LLMUsage,
    ProviderRequestStatus,
    stable_payload_hash,
)
from ..model_config import ModelConfig, normalize_openai_service_tier
from ..provider_transform import (
    build_llm_error,
    extract_retry_after_seconds,
    normalize_finish_reason,
    normalize_openai_responses_tool_choice,
    normalize_openai_responses_tools,
)
from ..reasoning_variants import (
    openai_reasoning_efforts,
    reasoning_efforts_from_metadata,
)
from .base import BaseAdapter

logger = logging.getLogger(__name__)


def _log_info(message: str, *args: Any) -> None:
    logger.info(message, *args)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.info(message, *args)


def _log_error(message: str, *args: Any, exc_info: bool = False) -> None:
    logger.error(message, *args, exc_info=exc_info)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.error(message, *args, exc_info=exc_info)


_OPENAI_CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
_OPENAI_OAUTH_REFRESH_BUFFER_MS = 5 * 60 * 1000
_OPENAI_CODEX_TRACE_HEADER_KEYS = (
    "x-request-id",
    "request-id",
    "openai-request-id",
    "x-openai-request-id",
    "cf-ray",
    "x-amzn-trace-id",
)
_OPENAI_CODEX_CONNECT_TIMEOUT_SECONDS = 30.0
_OPENAI_CODEX_HEADER_TIMEOUT_SECONDS = 45.0
_OPENAI_CODEX_IDLE_TIMEOUT_SECONDS = 120.0
_OPENAI_CODEX_TOTAL_TIMEOUT_SECONDS = 900.0
_OPENAI_STREAM_CALLBACK_TIMEOUT_SECONDS = 30.0
_OPENAI_STREAM_CLEANUP_TIMEOUT_SECONDS = 2.0
_OPENAI_PARTIAL_OUTPUT_MAX_CHARS = 65_536


@dataclass(frozen=True)
class _CodexWatchdogConfig:
    """Bound every phase of one Codex HTTP/SSE attempt."""

    connect_seconds: float
    header_seconds: float
    idle_seconds: float
    total_seconds: float
    callback_seconds: float
    cleanup_seconds: float


class _CodexWatchdogTimeout(TimeoutError):
    """Internal timeout carrying a stable provider lifecycle stage."""

    def __init__(self, stage: str, timeout_seconds: float) -> None:
        super().__init__(f"{stage} after {timeout_seconds:.3f}s")
        self.stage = stage
        self.timeout_seconds = timeout_seconds


def _positive_timeout_from_env(name: str, default: float) -> float:
    """Read one positive timeout, falling back on invalid/disabled values."""

    try:
        value = float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) and value > 0 else default


def _oauth_trace_flags(record: Dict[str, Any] | None) -> Dict[str, bool]:
    payload = record if isinstance(record, dict) else {}
    return {
        "has_access": bool(str(payload.get("access") or "").strip()),
        "has_refresh": bool(str(payload.get("refresh") or "").strip()),
        "has_expires": isinstance(payload.get("expires"), int),
        "has_account": bool(str(payload.get("accountId") or "").strip()),
    }


class OpenAIAdapter(BaseAdapter):
    """Native OpenAI adapter using the Responses API.

    This adapter calls OpenAI's Responses API directly for both streaming and
    non-streaming requests. It supports reasoning tokens (o-series) via the
    unified ``reasoning`` parameter and performs basic multimodal handling by
    encoding local images to data URIs.

    The adapter adheres to the BaseAdapter interface expected by APIClient when
    ``client_preference == 'native'`` and ``provider == 'openai'``.
    """

    supports_runtime_network_attempt_budget = True

    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        api_key = (
            model_config.api_key
            or os.getenv("OPENAI_API_KEY")
            or os.getenv("OPENAI_OAUTH_ACCESS_TOKEN")
        )
        if not api_key:
            raise ValueError(
                "Missing OpenAI credentials. Set OPENAI_API_KEY, "
                "OPENAI_OAUTH_ACCESS_TOKEN, or model_config.api_key."
            )

        default_headers: Dict[str, str] = {}
        account_id = os.getenv("OPENAI_ACCOUNT_ID")
        if isinstance(account_id, str) and account_id.strip():
            default_headers["OpenAI-Account"] = account_id.strip()

        # Respect custom base URL if provided (e.g., Azure/OpenAI-compatible gateways)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=model_config.api_base or None,
            default_headers=default_headers or None,
            max_retries=0,
        )
        self._last_usage: Dict[str, Any] = {}
        self._last_error: Optional[LLMError] = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_reasoning_debug: Dict[str, Any] = {}
        self._last_request_lifecycle: Optional[LLMRequestLifecycle] = None
        self._network_attempts = 0
        self._network_attempt_budget = 2
        self._attempt_partial_output = ""
        self._reset_tool_call_state()

    @property
    def provider(self) -> str:
        return "openai"

    def _reset_tool_call_state(self) -> None:
        self._tool_call_acc: Dict[str, Any] = {
            "item_id": None,
            "call_id": None,
            "name": None,
            "arguments": "",
        }
        self._tool_call_acc_by_item: Dict[str, Dict[str, Any]] = {}
        self._pending_tool_calls: List[Dict[str, Any]] = []
        self._last_tool_call: Optional[Dict[str, Any]] = None

    def has_pending_tool_call(self) -> bool:
        """Return whether a structured Responses tool call is waiting to run."""
        return (
            bool(self._pending_tool_calls)
            or (
                isinstance(self._last_tool_call, dict)
                and bool(self._last_tool_call.get("name"))
            )
            or any(
                bool(
                    accumulator.get("name")
                    or accumulator.get("call_id")
                    or accumulator.get("item_id")
                    or accumulator.get("arguments")
                )
                for accumulator in self._tool_call_acc_by_item.values()
                if isinstance(accumulator, dict)
            )
        )

    def get_last_network_attempt_count(self) -> int:
        """Return physical provider sends made by the latest logical call."""

        return max(0, int(getattr(self, "_network_attempts", 0) or 0))

    def _record_network_attempt(self) -> None:
        """Record one physical provider send within the runtime-owned budget."""

        attempts = self.get_last_network_attempt_count()
        budget = max(1, int(getattr(self, "_network_attempt_budget", 2) or 2))
        if attempts >= budget:
            raise RuntimeError(
                f"OpenAI network attempt budget exhausted ({attempts}/{budget})"
            )
        self._network_attempts = attempts + 1

    def get_and_clear_last_tool_call(self) -> Optional[Dict[str, Any]]:
        """Return the latest structured tool call and clear adapter state."""
        pending = self.get_and_clear_pending_tool_calls()
        return dict(pending[-1]) if pending else None

    def get_and_clear_pending_tool_calls(self) -> List[Dict[str, Any]]:
        """Return all pending structured tool calls and clear adapter state."""
        pending = [dict(call) for call in self._pending_tool_calls]
        if not pending and isinstance(self._last_tool_call, dict):
            pending = [dict(self._last_tool_call)]
        self._reset_tool_call_state()
        return pending

    def _reset_response_state(self) -> None:
        self._last_usage = {}
        self._last_error = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_reasoning_debug = {}
        self._last_request_lifecycle = None

    def _set_last_error(self, error: Optional[LLMError]) -> None:
        self._last_error = error

    def get_last_error(self) -> Optional[LLMError]:
        if not isinstance(self._last_error, LLMError):
            return None
        return self._last_error

    def get_last_request_lifecycle(self) -> Optional[LLMRequestLifecycle]:
        """Return lifecycle diagnostics for the last provider request."""

        return self._last_request_lifecycle

    def _get_service_tier(self) -> Optional[str]:
        value = getattr(self.model_config, "service_tier", None)
        return normalize_openai_service_tier(value)

    def _set_last_finish_reason(self, finish_reason: Any) -> FinishReason:
        self._last_finish_reason = normalize_finish_reason(finish_reason)
        return self._last_finish_reason

    def get_last_finish_reason(self) -> FinishReason:
        return self._last_finish_reason

    def _responses_stream_error_detail(self, event: Any) -> str:
        payload = event if isinstance(event, dict) else {}
        error_payload: Any = payload.get("error") if payload else None
        response_payload: Any = payload.get("response") if payload else None
        if error_payload is None and event is not None:
            error_payload = getattr(event, "error", None)
        if response_payload is None and event is not None:
            response_payload = getattr(event, "response", None)

        detail_payload = (
            error_payload
            if error_payload is not None
            else response_payload
            if response_payload is not None
            else event
        )
        if isinstance(detail_payload, dict):
            message = detail_payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            try:
                return json.dumps(detail_payload, default=str)[:500]
            except Exception:
                return str(detail_payload)[:500]

        message = getattr(detail_payload, "message", None)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return str(detail_payload)[:500]

    def _responses_stream_error_taxonomy(
        self,
        event: Any,
    ) -> tuple[ErrorCategory, bool]:
        """Classify a Responses SSE error before deciding whether replay is safe."""

        root = self._to_dict(event)
        candidates: List[str] = []
        pending: List[Any] = [root]
        visited = 0
        while pending and visited < 8:
            visited += 1
            payload = pending.pop(0)
            if not isinstance(payload, dict):
                payload = self._to_dict(payload)
            if not isinstance(payload, dict):
                continue
            for key in ("type", "code", "message", "status"):
                value = payload.get(key)
                if value is not None:
                    candidates.append(str(value).strip().lower())
            for key in ("error", "response"):
                nested = payload.get(key)
                if nested is not None:
                    pending.append(nested)

        detail = " ".join(value for value in candidates if value)
        if any(
            token in detail
            for token in (
                "authentication",
                "invalid_api_key",
                "permission_denied",
                "unauthorized",
            )
        ):
            return ErrorCategory.AUTH, False
        if any(
            token in detail
            for token in (
                "invalid_request",
                "bad_request",
                "context_length",
                "unsupported",
                "not_found",
            )
        ):
            return ErrorCategory.BAD_REQUEST, False
        if any(token in detail for token in ("rate_limit", "too_many_requests")):
            return ErrorCategory.RATE_LIMIT, True
        if any(token in detail for token in ("timeout", "timed_out")):
            return ErrorCategory.TIMEOUT, True
        if any(
            token in detail
            for token in ("server_error", "api_error", "overloaded", "unavailable")
        ):
            return ErrorCategory.PROVIDER_UNAVAILABLE, True
        if any(token in detail for token in ("connection", "network")):
            return ErrorCategory.NETWORK, True
        # Unknown event errors are not provably safe to replay.
        return ErrorCategory.RUNTIME, False

    def _raise_responses_stream_error(self, event: Any) -> None:
        detail = self._responses_stream_error_detail(event)
        category, retryable = self._responses_stream_error_taxonomy(event)
        partial_tool_call = self.has_pending_tool_call()
        error = build_llm_error(
            message=detail,
            provider=self.provider,
            model=getattr(self.model_config, "model", None),
            category=category,
            retryable=retryable,
            finish_reason=FinishReason.ERROR,
            provider_data={
                "network_attempts": self.get_last_network_attempt_count(),
                "partial_output": str(self._attempt_partial_output or ""),
                "partial_tool_call": partial_tool_call,
            },
        )
        self._set_last_finish_reason(FinishReason.ERROR)
        self._set_last_error(error)
        if partial_tool_call:
            self._reset_tool_call_state()
        self._update_request_lifecycle(
            status=ProviderRequestStatus.FAILED,
            finish_reason=FinishReason.ERROR,
            error=error,
        )
        raise LLMProviderError(error)

    def _raise_responses_stream_incomplete(
        self,
        output_state: str,
        *,
        partial_output: str = "",
    ) -> None:
        partial_tool_call = output_state == "tool_call" or self.has_pending_tool_call()
        detail = (
            "OpenAI Responses stream ended before response.completed "
            f"(output_state={output_state})"
        )
        error = build_llm_error(
            message=detail,
            provider=self.provider,
            model=getattr(self.model_config, "model", None),
            category=ErrorCategory.NETWORK,
            retryable=True,
            finish_reason=FinishReason.ERROR,
            provider_data={
                "stage": "stream_incomplete",
                "partial_output": str(partial_output or ""),
                "partial_tool_call": partial_tool_call,
                "network_attempts": self.get_last_network_attempt_count(),
            },
        )
        self._set_last_finish_reason(FinishReason.ERROR)
        self._set_last_error(error)
        if partial_tool_call:
            self._reset_tool_call_state()
        self._update_request_lifecycle(
            status=ProviderRequestStatus.DISCONNECTED,
            finish_reason=FinishReason.ERROR,
            error=error,
        )
        raise LLMProviderError(error)

    def _raise_responses_transport_error(
        self,
        error: Exception,
        *,
        stage: str,
        partial_output: str = "",
    ) -> None:
        """Raise one typed native Responses transport failure with replay facts."""

        partial_tool_call = self.has_pending_tool_call()
        category = (
            ErrorCategory.TIMEOUT
            if "timeout" in stage
            or isinstance(error, (TimeoutError, httpx.TimeoutException))
            else ErrorCategory.NETWORK
        )
        llm_error = build_llm_error(
            message=f"OpenAI Responses {stage}: {error}",
            provider=self.provider,
            model=getattr(self.model_config, "model", None),
            category=category,
            retryable=True,
            finish_reason=FinishReason.ERROR,
            provider_data={
                "stage": stage,
                "partial_output": str(partial_output or ""),
                "partial_tool_call": partial_tool_call,
                "network_attempts": self.get_last_network_attempt_count(),
            },
        )
        self._set_last_error(llm_error)
        self._set_last_finish_reason(FinishReason.ERROR)
        if partial_tool_call:
            self._reset_tool_call_state()
        self._update_request_lifecycle(
            status=ProviderRequestStatus.DISCONNECTED,
            event_type=stage,
            finish_reason=FinishReason.ERROR,
            error=llm_error,
            provider_data=llm_error.provider_data,
        )
        raise LLMProviderError(llm_error) from error

    def _append_reasoning(self, reasoning_text: str) -> None:
        if reasoning_text:
            self._last_reasoning += reasoning_text

    def get_last_reasoning(self) -> str:
        return self._last_reasoning

    def get_reasoning_debug_snapshot(self) -> Dict[str, Any]:
        if not isinstance(self._last_reasoning_debug, dict):
            return {}
        return dict(self._last_reasoning_debug)

    def _start_reasoning_debug_snapshot(self, **fields: Any) -> None:
        self._last_reasoning_debug = {
            "event_types": [],
            "reasoning_event_types": [],
            **fields,
        }

    def _record_reasoning_debug_event(
        self, event_type: Any, payload: Any = None
    ) -> None:
        snapshot = self._last_reasoning_debug
        if not isinstance(snapshot, dict):
            return

        event_name = str(event_type or "").strip()
        if not event_name:
            return

        event_types = snapshot.setdefault("event_types", [])
        if (
            isinstance(event_types, list)
            and event_name not in event_types
            and len(event_types) < 64
        ):
            event_types.append(event_name)

        if "reasoning" in event_name or "thinking" in event_name:
            reasoning_event_types = snapshot.setdefault("reasoning_event_types", [])
            if (
                isinstance(reasoning_event_types, list)
                and event_name not in reasoning_event_types
                and len(reasoning_event_types) < 64
            ):
                reasoning_event_types.append(event_name)

        if event_name == "response.completed" and isinstance(payload, dict):
            snapshot["completed_event_present"] = True

    def _finalize_reasoning_debug_snapshot(self, **fields: Any) -> None:
        if not isinstance(self._last_reasoning_debug, dict):
            self._last_reasoning_debug = {}
        self._last_reasoning_debug.update(fields)

    def _normalize_usage(self, usage: Any) -> Dict[str, Any]:
        payload = self._to_dict(usage)
        if not payload:
            return {}

        input_details = self._to_dict(payload.get("input_tokens_details"))
        output_details = self._to_dict(payload.get("output_tokens_details"))
        normalized = LLMUsage.from_dict(
            {
                "input_tokens": payload.get("input_tokens"),
                "output_tokens": payload.get("output_tokens"),
                "reasoning_tokens": output_details.get("reasoning_tokens")
                or payload.get("reasoning_tokens"),
                "cache_read_tokens": input_details.get("cached_tokens")
                or payload.get("input_cache_read_tokens"),
                "cache_write_tokens": payload.get("input_cache_write_tokens"),
                "total_tokens": payload.get("total_tokens"),
                "cost": payload.get("cost")
                or payload.get("total_cost")
                or payload.get("usd"),
            }
        )
        return normalized.to_dict()

    def _set_last_usage(self, usage: Any) -> None:
        normalized = self._normalize_usage(usage)
        if normalized:
            self._last_usage = normalized

    def get_last_usage(self) -> Dict[str, Any]:
        """Return normalized usage from the latest request."""
        if not isinstance(self._last_usage, dict):
            return {}
        return dict(self._last_usage)

    def _to_dict(self, value: Any) -> Dict[str, Any]:
        if isinstance(value, dict):
            return value
        if hasattr(value, "model_dump"):
            try:
                dumped = value.model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        if hasattr(value, "dict"):
            try:
                dumped = value.dict()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        try:
            dumped = vars(value)
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
        return {}

    def _snapshot_tool_call(
        self,
        *,
        item_id: Any = None,
        call_id: Any = None,
        name: Any = None,
        arguments: Any = None,
        accumulator: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        active_acc = (
            accumulator if isinstance(accumulator, dict) else self._tool_call_acc
        )
        resolved_name = str(name or active_acc.get("name") or "").strip()
        if not resolved_name:
            return None

        resolved_arguments = arguments
        if not isinstance(resolved_arguments, str):
            resolved_arguments = active_acc.get("arguments", "")
        if not isinstance(resolved_arguments, str):
            resolved_arguments = ""

        resolved_item_id = item_id or active_acc.get("item_id")
        resolved_call_id = call_id or active_acc.get("call_id")
        return {
            "item_id": str(resolved_item_id).strip() if resolved_item_id else None,
            "call_id": str(resolved_call_id).strip() if resolved_call_id else None,
            "name": resolved_name,
            "arguments": resolved_arguments,
        }

    def _tool_call_accumulator_for_item(
        self,
        *,
        item_id: Any = None,
        call_id: Any = None,
    ) -> Dict[str, Any]:
        key = str(item_id or call_id or "").strip()
        if not key:
            return self._tool_call_acc
        if key not in self._tool_call_acc_by_item:
            self._tool_call_acc_by_item[key] = {
                "item_id": str(item_id).strip() if item_id else None,
                "call_id": str(call_id).strip() if call_id else None,
                "name": None,
                "arguments": "",
            }
        return self._tool_call_acc_by_item[key]

    def _remember_tool_call(self, tool_call: Dict[str, Any]) -> Dict[str, Any]:
        """Record one provider tool call without duplicating completed events."""
        call_id = str(tool_call.get("call_id") or "").strip()
        item_id = str(tool_call.get("item_id") or "").strip()
        name = str(tool_call.get("name") or "").strip()
        arguments = str(tool_call.get("arguments") or "")

        for pending in self._pending_tool_calls:
            same_call_id = call_id and call_id == str(pending.get("call_id") or "")
            same_item_id = item_id and item_id == str(pending.get("item_id") or "")
            if same_call_id or same_item_id:
                pending.update(tool_call)
                self._last_tool_call = pending
                return pending
            if (
                not call_id
                and not item_id
                and name == str(pending.get("name") or "")
                and arguments == str(pending.get("arguments") or "")
            ):
                self._last_tool_call = pending
                return pending

        remembered = dict(tool_call)
        self._pending_tool_calls.append(remembered)
        self._last_tool_call = remembered
        return remembered

    def _accumulate_function_call_item(
        self,
        item: Any,
        *,
        overwrite_arguments: bool,
    ) -> Optional[Dict[str, Any]]:
        item_payload = self._to_dict(item)
        if item_payload.get("type") != "function_call":
            return None

        item_id = item_payload.get("id")
        call_id = item_payload.get("call_id")
        name = item_payload.get("name")
        arguments = item_payload.get("arguments")
        accumulator = self._tool_call_accumulator_for_item(
            item_id=item_id,
            call_id=call_id,
        )

        if isinstance(item_id, str) and item_id.strip():
            accumulator["item_id"] = item_id.strip()
            self._tool_call_acc["item_id"] = item_id.strip()
        if isinstance(call_id, str) and call_id.strip():
            accumulator["call_id"] = call_id.strip()
            self._tool_call_acc["call_id"] = call_id.strip()
        if isinstance(name, str) and name.strip():
            accumulator["name"] = name.strip()
            self._tool_call_acc["name"] = name.strip()

        if isinstance(arguments, str):
            if overwrite_arguments:
                accumulator["arguments"] = arguments
                self._tool_call_acc["arguments"] = arguments
            elif arguments and not accumulator.get("arguments"):
                accumulator["arguments"] = arguments
                self._tool_call_acc["arguments"] = arguments

        return self._snapshot_tool_call(
            item_id=item_id,
            call_id=call_id,
            name=name,
            arguments=arguments if overwrite_arguments else None,
            accumulator=accumulator,
        )

    def _capture_responses_tool_event(self, event: Any) -> Optional[Dict[str, Any]]:
        payload = self._to_dict(event)
        etype = payload.get("type") or getattr(event, "type", None)

        if etype == "response.output_item.added":
            self._accumulate_function_call_item(
                payload.get("item") or getattr(event, "item", None),
                overwrite_arguments=False,
            )
            return None

        if etype == "response.function_call_arguments.delta":
            item_id = payload.get("item_id") or getattr(event, "item_id", None)
            delta = payload.get("delta") or getattr(event, "delta", None)
            accumulator = self._tool_call_accumulator_for_item(item_id=item_id)
            if isinstance(item_id, str) and item_id:
                accumulator["item_id"] = item_id
                self._tool_call_acc["item_id"] = item_id
            if isinstance(delta, str) and delta:
                accumulator["arguments"] = str(accumulator.get("arguments") or "")
                accumulator["arguments"] += delta
                self._tool_call_acc["arguments"] = accumulator["arguments"]
            return None

        if etype == "response.output_item.done":
            tool_call = self._accumulate_function_call_item(
                payload.get("item") or getattr(event, "item", None),
                overwrite_arguments=True,
            )
            if tool_call:
                self._remember_tool_call(tool_call)
            return tool_call

        if etype == "response.completed":
            tool_calls = self._extract_function_calls_from_response_object(
                payload.get("response") or getattr(event, "response", None)
            )
            for tool_call in tool_calls:
                self._remember_tool_call(tool_call)
            return tool_calls[-1] if tool_calls else None

        return None

    def _extract_function_calls_from_response_object(
        self,
        resp: Any,
    ) -> List[Dict[str, Any]]:
        output = None
        if isinstance(resp, dict):
            output = resp.get("output")
        else:
            output = getattr(resp, "output", None)

        if not isinstance(output, list):
            return []

        tool_calls: List[Dict[str, Any]] = []
        for item in output:
            tool_call = self._accumulate_function_call_item(
                item,
                overwrite_arguments=True,
            )
            if tool_call:
                tool_calls.append(tool_call)

        return tool_calls

    def _extract_function_call_from_response_object(
        self,
        resp: Any,
    ) -> Optional[Dict[str, Any]]:
        tool_calls = self._extract_function_calls_from_response_object(resp)
        return tool_calls[0] if tool_calls else None

    def _interrupt_on_tool_call(self) -> bool:
        return bool(getattr(self.model_config, "interrupt_on_tool_call", False))

    def get_capabilities(self) -> LLMProviderCapabilities:
        """Return OpenAI/Responses capability metadata."""

        configured_reasoning_levels = getattr(
            self.model_config, "supported_reasoning_levels", None
        )
        return LLMProviderCapabilities(
            provider=self.provider,
            model=str(getattr(self.model_config, "model", "") or ""),
            native_tools=True,
            streaming=bool(getattr(self.model_config, "streaming_enabled", True)),
            reasoning=bool(
                getattr(self.model_config, "reasoning_enabled", False)
                or self.model_config.get_reasoning_config()
            ),
            reasoning_efforts=(
                reasoning_efforts_from_metadata(configured_reasoning_levels)
                if configured_reasoning_levels is not None
                else openai_reasoning_efforts(self.model_config.model)
            ),
            vision=self.supports_vision(),
            resumable=True,
            max_context_tokens=getattr(
                self.model_config,
                "max_context_window_tokens",
                None,
            ),
            max_output_tokens=getattr(self.model_config, "max_output_tokens", None),
            provider_data={
                "api": "responses",
                "oauth_codex_supported": True,
                "service_tier": self._get_service_tier(),
            },
        )

    def _build_native_responses_request_params(
        self,
        *,
        processed_messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int],
        temperature: Optional[float],
        reasoning_config: Optional[Dict[str, Any]],
        instructions: Optional[str],
        previous_response_id: Optional[str],
        conversation_id: Optional[str],
        response_format: Optional[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]],
        tool_choice: Optional[Union[str, Dict[str, Any]]],
        service_tier: Optional[str],
    ) -> Dict[str, Any]:
        """Build the native Responses API request body."""

        input_parts = self._build_input_parts(processed_messages)
        if input_parts is not None:
            request_params: Dict[str, Any] = {
                "model": self.model_config.model,
                "input": input_parts,
                **(
                    {"max_output_tokens": max_output_tokens}
                    if max_output_tokens
                    else {}
                ),
                **({"reasoning": reasoning_config} if reasoning_config else {}),
            }
        else:
            input_text = self._build_transcript_input(processed_messages)
            request_params = {
                "model": self.model_config.model,
                "input": input_text,
                **(
                    {"max_output_tokens": max_output_tokens}
                    if max_output_tokens
                    else {}
                ),
                **({"reasoning": reasoning_config} if reasoning_config else {}),
            }

        if instructions:
            request_params["instructions"] = instructions
        if previous_response_id:
            request_params["previous_response_id"] = previous_response_id
        if conversation_id:
            request_params["conversation"] = conversation_id
        if response_format:
            request_params["response_format"] = response_format
        if tools:
            request_params["tools"] = tools
        if tool_choice:
            request_params["tool_choice"] = tool_choice
        if service_tier:
            request_params["service_tier"] = service_tier

        try:
            uses_effort_style = bool(self.model_config._uses_effort_style())
        except Exception:
            uses_effort_style = False
        if not uses_effort_style:
            request_params["temperature"] = temperature

        return request_params

    async def prepare_request(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        """Prepare the OpenAI provider request without sending it."""

        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens
        processed_messages = await self._process_messages_for_vision(messages)
        reasoning_config = self._prepare_reasoning_config(
            self.model_config.get_reasoning_config(),
            stream=stream,
        )
        temp_val = (
            temperature if temperature is not None else self.model_config.temperature
        )

        instructions: Optional[str] = kwargs.get("instructions")
        previous_response_id: Optional[str] = kwargs.get("previous_response_id")
        conversation_id: Optional[str] = kwargs.get("conversation")
        response_format: Optional[Dict[str, Any]] = kwargs.get("response_format")
        tools = normalize_openai_responses_tools(kwargs.get("tools"))
        tool_choice = normalize_openai_responses_tool_choice(kwargs.get("tool_choice"))
        service_tier = self._get_service_tier()

        oauth_record = self._peek_oauth_record_for_prepare()
        if oauth_record is not None:
            payload, model_id, model_fallback = self._build_codex_oauth_payload(
                processed_messages=processed_messages,
                temperature=temp_val,
                reasoning_config=reasoning_config,
                instructions=instructions,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                service_tier=service_tier,
            )
            return LLMPreparedRequest(
                provider=self.provider,
                model=model_id,
                protocol="openai_responses",
                route="openai.codex_oauth.responses",
                body=payload,
                transport="http_sse",
                capabilities=self.get_capabilities(),
                diagnostics={
                    "message_count": len(messages),
                    "processed_message_count": len(processed_messages),
                    "model_fallback": model_fallback,
                    "stream": stream,
                },
                provider_data={
                    "endpoint": _OPENAI_CODEX_RESPONSES_URL,
                    "header_names": ["Authorization", "Content-Type"],
                },
            )

        request_params = self._build_native_responses_request_params(
            processed_messages=processed_messages,
            max_output_tokens=max_output_tokens,
            temperature=temp_val,
            reasoning_config=reasoning_config,
            instructions=instructions,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            service_tier=service_tier,
        )
        return LLMPreparedRequest(
            provider=self.provider,
            model=str(self.model_config.model),
            protocol="openai_responses",
            route="openai.responses",
            body=request_params,
            transport="sdk_stream" if stream else "sdk",
            capabilities=self.get_capabilities(),
            diagnostics={
                "message_count": len(messages),
                "processed_message_count": len(processed_messages),
                "stream": stream,
            },
        )

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Create a completion using the Responses API.

        Args:
            messages: Conversation in OpenAI-style message format.
            max_output_tokens: Max output tokens (model dependent).
            temperature: Sampling temperature.
            stream: Whether to stream the response.
            stream_callback: Callback invoked with chunks during streaming. If
                provided by callers in Penguin it may accept (chunk) or
                (chunk, message_type). We will only pass a single positional
                argument here and let APIClient wrap signatures as needed.
        """
        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        raw_attempt_budget = kwargs.pop("_penguin_network_attempt_budget", 2)
        try:
            self._network_attempt_budget = max(1, min(2, int(raw_attempt_budget)))
        except (TypeError, ValueError):
            self._network_attempt_budget = 2
        self._network_attempts = 0
        self._attempt_partial_output = ""
        self._reset_tool_call_state()
        self._reset_response_state()

        processed_messages = await self._process_messages_for_vision(messages)

        reasoning_config = self._prepare_reasoning_config(
            self.model_config.get_reasoning_config(),
            stream=stream,
        )
        temp_val = (
            temperature if temperature is not None else self.model_config.temperature
        )

        # Pull optional openai-specific kwargs
        instructions: Optional[str] = kwargs.get("instructions")
        previous_response_id: Optional[str] = kwargs.get("previous_response_id")
        conversation_id: Optional[str] = kwargs.get("conversation")
        response_format: Optional[Dict[str, Any]] = kwargs.get("response_format")
        tools = normalize_openai_responses_tools(kwargs.get("tools"))
        tool_choice = normalize_openai_responses_tool_choice(kwargs.get("tool_choice"))
        service_tier = self._get_service_tier()

        oauth_record = await self._resolve_oauth_record_for_request()
        if oauth_record is not None:
            flags = _oauth_trace_flags(oauth_record)
            _log_info(
                "openai.request.route route=oauth_codex model=%s stream=%s "
                "service_tier=%s has_access=%s has_refresh=%s has_expires=%s "
                "has_account=%s",
                self.model_config.model,
                stream,
                service_tier,
                flags["has_access"],
                flags["has_refresh"],
                flags["has_expires"],
                flags["has_account"],
            )
            return await self._create_oauth_codex_completion(
                processed_messages=processed_messages,
                oauth_record=oauth_record,
                max_output_tokens=max_output_tokens,
                temperature=temp_val,
                stream=stream,
                stream_callback=stream_callback,
                reasoning_config=reasoning_config,
                instructions=instructions,
                previous_response_id=previous_response_id,
                conversation_id=conversation_id,
                response_format=response_format,
                tools=tools,
                tool_choice=tool_choice,
                service_tier=service_tier,
            )

        _log_info(
            "openai.request.route route=native_api model=%s stream=%s "
            "service_tier=%s oauth_env=%s api_key_present=%s",
            self.model_config.model,
            stream,
            service_tier,
            bool(str(os.getenv("OPENAI_OAUTH_ACCESS_TOKEN") or "").strip()),
            bool(self.client.api_key),
        )

        request_params = self._build_native_responses_request_params(
            processed_messages=processed_messages,
            max_output_tokens=max_output_tokens,
            temperature=temp_val,
            reasoning_config=reasoning_config,
            instructions=instructions,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            service_tier=service_tier,
        )

        self._start_request_lifecycle(
            request_id=f"openai-{int(time.time() * 1000)}",
            model_id=self.model_config.model,
            payload=request_params,
            stream=stream,
            transport="sdk",
            model_fallback=False,
        )
        self._update_request_lifecycle(status=ProviderRequestStatus.RUNNING)

        if stream:
            # Note: `stream_options.include_usage` is a Chat Completions option and is
            # not supported by the Responses API. Additionally, some OpenAI SDK
            # versions don't accept `stream_options` on `responses.stream`, so we
            # intentionally ignore any user-provided `stream_options` here.
            try:
                result = await self._stream_with_sdk(request_params, stream_callback)
                self._update_request_lifecycle(
                    status=ProviderRequestStatus.COMPLETED,
                    finish_reason=self.get_last_finish_reason(),
                )
                return result
            except LLMProviderError:
                raise
            except Exception as e:
                partial_output = str(self._attempt_partial_output or "")
                partial_tool_call = self.has_pending_tool_call()
                can_fallback = (
                    not partial_output
                    and not partial_tool_call
                    and self.get_last_network_attempt_count()
                    < self._network_attempt_budget
                )
                if not can_fallback:
                    self._raise_responses_transport_error(
                        e,
                        stage="sdk_stream_transport",
                        partial_output=partial_output,
                    )
                logger.warning(
                    "SDK streaming failed before output; using the one bounded "
                    "HTTP fallback: %s",
                    e,
                )
                result = await self._stream_with_http(request_params, stream_callback)
                self._update_request_lifecycle(
                    status=ProviderRequestStatus.COMPLETED,
                    finish_reason=self.get_last_finish_reason(),
                )
                return result

        # Non-streaming
        try:
            self._record_network_attempt()
            watchdog = self._codex_watchdog_config()
            resp = await asyncio.wait_for(
                self.client.responses.create(**request_params),
                timeout=watchdog.total_seconds,
            )
        except asyncio.TimeoutError as exc:
            self._raise_responses_transport_error(
                exc,
                stage="request_total_timeout",
            )
        except Exception as exc:
            error = build_llm_error(
                message=str(exc),
                provider=self.provider,
                model=getattr(self.model_config, "model", None),
                finish_reason=FinishReason.ERROR,
                provider_data={
                    "network_attempts": self.get_last_network_attempt_count(),
                },
            )
            self._set_last_error(error)
            self._update_request_lifecycle(
                status=ProviderRequestStatus.FAILED,
                finish_reason=FinishReason.ERROR,
                error=error,
            )
            raise
        self._set_last_usage(getattr(resp, "usage", None))
        self._append_reasoning(self._extract_reasoning_from_response_object(resp))
        tool_calls = self._extract_function_calls_from_response_object(resp)
        if tool_calls:
            for tool_call in tool_calls:
                self._remember_tool_call(tool_call)
            self._set_last_finish_reason(FinishReason.TOOL_CALLS)
        else:
            self._set_last_finish_reason(FinishReason.STOP)

        output_text = getattr(resp, "output_text", None)
        self._update_request_lifecycle(
            status=ProviderRequestStatus.COMPLETED,
            finish_reason=self.get_last_finish_reason(),
        )
        if isinstance(output_text, str):
            return output_text
        return self._extract_text_from_response_object(resp) or ""

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """Unified interface expected by APIClient/BaseAdapter."""
        try:
            if stream:
                accumulated = await self.create_completion(
                    messages=messages,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    stream=True,
                    stream_callback=stream_callback,
                    **kwargs,
                )
                return accumulated or ""
            # Non-streaming path
            resp = await self.create_completion(
                messages=messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                stream=False,
                stream_callback=None,
                **kwargs,
            )
            # create_completion returns text for non-streaming
            if isinstance(resp, str):
                return resp
            return str(resp)
        except asyncio.CancelledError:
            self._reset_tool_call_state()
            error = build_llm_error(
                message="OpenAI request was cancelled",
                provider=self.provider,
                model=getattr(self.model_config, "model", None),
                category=ErrorCategory.RUNTIME,
                retryable=False,
                finish_reason=FinishReason.ERROR,
            )
            self._set_last_error(error)
            self._update_request_lifecycle(
                status=ProviderRequestStatus.CANCELLED,
                finish_reason=FinishReason.ERROR,
                error=error,
            )
            raise

    async def _resolve_oauth_record_for_request(self) -> Dict[str, Any] | None:
        record = get_provider_credential("openai")
        if isinstance(record, dict) and record.get("type") == "oauth":
            oauth_record = dict(record)
            flags = _oauth_trace_flags(oauth_record)
            _log_info(
                "openai.oauth.resolve source=store_oauth has_access=%s has_refresh=%s has_expires=%s has_account=%s",
                flags["has_access"],
                flags["has_refresh"],
                flags["has_expires"],
                flags["has_account"],
            )
        else:
            oauth_access = str(os.getenv("OPENAI_OAUTH_ACCESS_TOKEN") or "").strip()
            if not oauth_access:
                _log_info(
                    "openai.oauth.resolve source=none stored_type=%s env_oauth=%s env_api=%s",
                    record.get("type") if isinstance(record, dict) else None,
                    False,
                    bool(str(os.getenv("OPENAI_API_KEY") or "").strip()),
                )
                return None

            oauth_record = {
                "type": "oauth",
                "access": oauth_access,
            }
            refresh = str(os.getenv("OPENAI_OAUTH_REFRESH_TOKEN") or "").strip()
            if refresh:
                oauth_record["refresh"] = refresh
            expires_raw = str(os.getenv("OPENAI_OAUTH_EXPIRES_AT_MS") or "").strip()
            if expires_raw:
                try:
                    oauth_record["expires"] = int(expires_raw)
                except ValueError:
                    logger.warning(
                        "Ignoring invalid OPENAI_OAUTH_EXPIRES_AT_MS during OAuth resolution"
                    )
            account_id = str(os.getenv("OPENAI_ACCOUNT_ID") or "").strip()
            if account_id:
                oauth_record["accountId"] = account_id
            flags = _oauth_trace_flags(oauth_record)
            _log_info(
                "openai.oauth.resolve source=env_oauth has_access=%s has_refresh=%s has_expires=%s has_account=%s",
                flags["has_access"],
                flags["has_refresh"],
                flags["has_expires"],
                flags["has_account"],
            )

        try:
            refresh_needed = oauth_record_needs_refresh(
                oauth_record,
                refresh_window_ms=_OPENAI_OAUTH_REFRESH_BUFFER_MS,
            )
        except Exception:
            refresh_needed = False

        if refresh_needed:
            refresh = oauth_record.get("refresh")
            if isinstance(refresh, str) and refresh.strip():
                try:
                    oauth_record = await refresh_provider_oauth(
                        "openai",
                        credential_record=oauth_record,
                    )
                except ProviderOAuthError as exc:
                    raise RuntimeError(
                        f"OpenAI OAuth reauth required: refresh failed ({exc})"
                    ) from exc
                except Exception as exc:
                    raise RuntimeError(
                        f"OpenAI OAuth reauth required: refresh failed ({exc})"
                    ) from exc
            elif oauth_record_expired(oauth_record):
                raise RuntimeError(
                    "OpenAI OAuth reauth required: access token expired and no "
                    "refresh token is available"
                )

        access = oauth_record.get("access")
        if not isinstance(access, str) or not access.strip():
            raise RuntimeError("OpenAI OAuth reauth required: missing access token")

        self._apply_oauth_record_to_runtime(oauth_record)
        return oauth_record

    def _peek_oauth_record_for_prepare(self) -> Dict[str, Any] | None:
        """Read OAuth route metadata for request preparation without refresh."""

        record = get_provider_credential("openai")
        if isinstance(record, dict) and record.get("type") == "oauth":
            access = record.get("access")
            if isinstance(access, str) and access.strip():
                return dict(record)

        oauth_access = str(os.getenv("OPENAI_OAUTH_ACCESS_TOKEN") or "").strip()
        if not oauth_access:
            return None

        oauth_record: Dict[str, Any] = {
            "type": "oauth",
            "access": oauth_access,
        }
        refresh = str(os.getenv("OPENAI_OAUTH_REFRESH_TOKEN") or "").strip()
        if refresh:
            oauth_record["refresh"] = refresh
        expires_raw = str(os.getenv("OPENAI_OAUTH_EXPIRES_AT_MS") or "").strip()
        if expires_raw:
            try:
                oauth_record["expires"] = int(expires_raw)
            except ValueError:
                pass
        account_id = str(os.getenv("OPENAI_ACCOUNT_ID") or "").strip()
        if account_id:
            oauth_record["accountId"] = account_id
        return oauth_record

    def _apply_oauth_record_to_runtime(self, oauth_record: Dict[str, Any]) -> None:
        access = oauth_record.get("access")
        if isinstance(access, str) and access.strip():
            os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] = access.strip()
            self.model_config.api_key = access.strip()

        account_id = oauth_record.get("accountId")
        if isinstance(account_id, str) and account_id.strip():
            os.environ["OPENAI_ACCOUNT_ID"] = account_id.strip()

    def _new_codex_diag_id(self) -> str:
        return f"oaoc_{os.urandom(5).hex()}"

    def _trace_headers(self, response: httpx.Response | None) -> Dict[str, str]:
        if response is None:
            return {}

        trace: Dict[str, str] = {}
        for key in _OPENAI_CODEX_TRACE_HEADER_KEYS:
            value = response.headers.get(key)
            if isinstance(value, str) and value.strip():
                trace[key] = value.strip()
        return trace

    def _codex_watchdog_config(self) -> _CodexWatchdogConfig:
        """Resolve bounded Codex attempt phases from operator overrides."""

        return _CodexWatchdogConfig(
            connect_seconds=_positive_timeout_from_env(
                "PENGUIN_CODEX_CONNECT_TIMEOUT_SECONDS",
                _OPENAI_CODEX_CONNECT_TIMEOUT_SECONDS,
            ),
            header_seconds=_positive_timeout_from_env(
                "PENGUIN_CODEX_HEADER_TIMEOUT_SECONDS",
                _OPENAI_CODEX_HEADER_TIMEOUT_SECONDS,
            ),
            idle_seconds=_positive_timeout_from_env(
                "PENGUIN_CODEX_IDLE_TIMEOUT_SECONDS",
                _OPENAI_CODEX_IDLE_TIMEOUT_SECONDS,
            ),
            total_seconds=_positive_timeout_from_env(
                "PENGUIN_CODEX_TOTAL_TIMEOUT_SECONDS",
                _OPENAI_CODEX_TOTAL_TIMEOUT_SECONDS,
            ),
            callback_seconds=_positive_timeout_from_env(
                "PENGUIN_STREAM_CALLBACK_TIMEOUT_SECONDS",
                _OPENAI_STREAM_CALLBACK_TIMEOUT_SECONDS,
            ),
            cleanup_seconds=_positive_timeout_from_env(
                "PENGUIN_STREAM_CLEANUP_TIMEOUT_SECONDS",
                _OPENAI_STREAM_CLEANUP_TIMEOUT_SECONDS,
            ),
        )

    def _codex_http_timeout(self) -> httpx.Timeout:
        """Use finite connect/read/write/pool limits beneath explicit watchdogs."""

        watchdog = self._codex_watchdog_config()
        return httpx.Timeout(
            connect=watchdog.connect_seconds,
            read=watchdog.idle_seconds,
            write=min(60.0, watchdog.total_seconds),
            pool=watchdog.connect_seconds,
        )

    def _codex_total_remaining(
        self,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> float:
        """Return remaining seconds in this attempt's absolute deadline."""

        return watchdog.total_seconds - (time.monotonic() - started)

    async def _await_with_codex_total_deadline(
        self,
        operation: Awaitable[Any],
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> Any:
        """Await one attempt phase without extending the absolute deadline."""

        remaining = self._codex_total_remaining(
            started=started,
            watchdog=watchdog,
        )
        if remaining <= 0:
            close = getattr(operation, "close", None)
            if callable(close):
                close()
            raise _CodexWatchdogTimeout(
                "stream_total_timeout",
                watchdog.total_seconds,
            )
        try:
            return await asyncio.wait_for(operation, timeout=remaining)
        except asyncio.TimeoutError as exc:
            raise _CodexWatchdogTimeout(
                "stream_total_timeout",
                watchdog.total_seconds,
            ) from exc

    async def _exit_codex_context(
        self,
        context: Any,
        exc_type: Any,
        exc: BaseException | None,
        traceback: Any,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> bool:
        """Close one context within a short cleanup-only deadline."""

        cleanup_task = asyncio.ensure_future(
            context.__aexit__(exc_type, exc, traceback)
        )
        del started

        def consume_cleanup_result(task: asyncio.Future[Any]) -> None:
            """Retrieve a late cleanup result without leaking task warnings."""

            try:
                task.result()
            except asyncio.CancelledError:
                pass
            except Exception:
                logger.debug("Late OpenAI stream cleanup failed", exc_info=True)

        async def cancel_and_drain_cleanup() -> None:
            """Request cancellation and observe it for one finite interval."""

            cleanup_task.cancel()
            done, _ = await asyncio.wait(
                {cleanup_task},
                timeout=watchdog.cleanup_seconds,
            )
            if cleanup_task in done:
                consume_cleanup_result(cleanup_task)
                return
            logger.error(
                "OpenAI stream cleanup ignored cancellation for %.3fs",
                watchdog.cleanup_seconds,
            )
            cleanup_task.add_done_callback(consume_cleanup_result)

        try:
            done, _ = await asyncio.wait(
                {cleanup_task},
                timeout=watchdog.cleanup_seconds,
            )
            if cleanup_task in done:
                return bool(cleanup_task.result())
            await cancel_and_drain_cleanup()
            raise _CodexWatchdogTimeout(
                "stream_cleanup_timeout",
                watchdog.cleanup_seconds,
            )
        except asyncio.CancelledError:
            await cancel_and_drain_cleanup()
            raise

    @asynccontextmanager
    async def _codex_client_context(
        self,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> AsyncIterator[httpx.AsyncClient]:
        """Enter and close the HTTP client within the absolute deadline."""

        context = httpx.AsyncClient(timeout=self._codex_http_timeout())
        client = await self._await_with_codex_total_deadline(
            context.__aenter__(),
            started=started,
            watchdog=watchdog,
        )
        try:
            yield client
        except BaseException as exc:
            try:
                suppress_error = await self._exit_codex_context(
                    context,
                    type(exc),
                    exc,
                    exc.__traceback__,
                    started=started,
                    watchdog=watchdog,
                )
            except _CodexWatchdogTimeout:
                raise exc
            if not suppress_error:
                raise
        else:
            await self._exit_codex_context(
                context,
                None,
                None,
                None,
                started=started,
                watchdog=watchdog,
            )

    @asynccontextmanager
    async def _codex_stream_context(
        self,
        client: httpx.AsyncClient,
        *,
        headers: Dict[str, str],
        payload: Dict[str, Any],
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> AsyncIterator[httpx.Response]:
        """Enter an HTTP stream with explicit header and total-attempt bounds."""

        context = client.stream(
            "POST",
            _OPENAI_CODEX_RESPONSES_URL,
            headers=headers,
            json=payload,
        )
        remaining = self._codex_total_remaining(
            started=started,
            watchdog=watchdog,
        )
        if remaining <= 0:
            raise _CodexWatchdogTimeout(
                "stream_total_timeout",
                watchdog.total_seconds,
            )
        enter_timeout = min(watchdog.header_seconds, remaining)
        try:
            response = await asyncio.wait_for(
                context.__aenter__(),
                timeout=enter_timeout,
            )
        except asyncio.TimeoutError as exc:
            stage = (
                "stream_total_timeout"
                if remaining <= watchdog.header_seconds
                else "stream_header_timeout"
            )
            timeout_seconds = (
                watchdog.total_seconds
                if stage == "stream_total_timeout"
                else watchdog.header_seconds
            )
            raise _CodexWatchdogTimeout(stage, timeout_seconds) from exc

        try:
            yield response
        except BaseException as exc:
            try:
                suppress_error = await self._exit_codex_context(
                    context,
                    type(exc),
                    exc,
                    exc.__traceback__,
                    started=started,
                    watchdog=watchdog,
                )
            except _CodexWatchdogTimeout:
                raise exc
            if not suppress_error:
                raise
        else:
            await self._exit_codex_context(
                context,
                None,
                None,
                None,
                started=started,
                watchdog=watchdog,
            )

    @asynccontextmanager
    async def _bounded_openai_stream_context(
        self,
        context: Any,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> AsyncIterator[Any]:
        """Enter an existing SDK/HTTP stream with header and cleanup bounds."""

        remaining = self._codex_total_remaining(
            started=started,
            watchdog=watchdog,
        )
        if remaining <= 0:
            raise _CodexWatchdogTimeout(
                "stream_total_timeout",
                watchdog.total_seconds,
            )
        enter_timeout = min(watchdog.header_seconds, remaining)
        try:
            stream = await asyncio.wait_for(
                context.__aenter__(),
                timeout=enter_timeout,
            )
        except asyncio.TimeoutError as exc:
            stage = (
                "stream_total_timeout"
                if remaining <= watchdog.header_seconds
                else "stream_header_timeout"
            )
            raise _CodexWatchdogTimeout(
                stage,
                watchdog.total_seconds
                if stage == "stream_total_timeout"
                else watchdog.header_seconds,
            ) from exc

        try:
            yield stream
        except BaseException as exc:
            try:
                suppress_error = await self._exit_codex_context(
                    context,
                    type(exc),
                    exc,
                    exc.__traceback__,
                    started=started,
                    watchdog=watchdog,
                )
            except _CodexWatchdogTimeout:
                raise exc
            if not suppress_error:
                raise
        else:
            await self._exit_codex_context(
                context,
                None,
                None,
                None,
                started=started,
                watchdog=watchdog,
            )

    async def _iter_openai_stream_with_watchdog(
        self,
        iterator: Any,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> AsyncIterator[Any]:
        """Iterate SDK/HTTP stream items under idle and total deadlines."""

        async_iterator = iterator.__aiter__()
        while True:
            remaining = self._codex_total_remaining(
                started=started,
                watchdog=watchdog,
            )
            if remaining <= 0:
                raise _CodexWatchdogTimeout(
                    "stream_total_timeout",
                    watchdog.total_seconds,
                )
            wait_seconds = min(watchdog.idle_seconds, remaining)
            try:
                item = await asyncio.wait_for(
                    async_iterator.__anext__(),
                    timeout=wait_seconds,
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                stage = (
                    "stream_total_timeout"
                    if remaining <= watchdog.idle_seconds
                    else "stream_idle_timeout"
                )
                raise _CodexWatchdogTimeout(
                    stage,
                    watchdog.total_seconds
                    if stage == "stream_total_timeout"
                    else watchdog.idle_seconds,
                ) from exc
            yield item

    async def _iter_codex_lines_with_watchdog(
        self,
        response: httpx.Response,
        *,
        started: float,
        watchdog: _CodexWatchdogConfig,
    ) -> AsyncIterator[str]:
        """Yield stream lines while enforcing chunk-idle and total deadlines."""

        iterator = response.aiter_lines().__aiter__()
        while True:
            remaining = self._codex_total_remaining(
                started=started,
                watchdog=watchdog,
            )
            if remaining <= 0:
                raise _CodexWatchdogTimeout(
                    "stream_total_timeout",
                    watchdog.total_seconds,
                )
            wait_seconds = min(watchdog.idle_seconds, remaining)
            try:
                line = await asyncio.wait_for(
                    iterator.__anext__(),
                    timeout=wait_seconds,
                )
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError as exc:
                stage = (
                    "stream_total_timeout"
                    if remaining <= watchdog.idle_seconds
                    else "stream_idle_timeout"
                )
                timeout_seconds = (
                    watchdog.total_seconds
                    if stage == "stream_total_timeout"
                    else watchdog.idle_seconds
                )
                raise _CodexWatchdogTimeout(stage, timeout_seconds) from exc
            yield line

    def _codex_payload_hash(self, payload: Dict[str, Any]) -> str:
        return stable_payload_hash(payload)

    def _start_request_lifecycle(
        self,
        *,
        request_id: str,
        model_id: str,
        payload: Dict[str, Any],
        stream: bool,
        transport: str,
        model_fallback: bool,
    ) -> None:
        now = time.time()
        input_payload = payload.get("input")
        self._last_request_lifecycle = LLMRequestLifecycle(
            request_id=request_id,
            provider=self.provider,
            model=model_id,
            status=ProviderRequestStatus.PENDING,
            stream=stream,
            transport=transport,
            request_payload_hash=self._codex_payload_hash(payload),
            started_at=now,
            last_event_at=now,
            provider_data={
                "model_fallback": model_fallback,
                "input_items": len(input_payload)
                if isinstance(input_payload, list)
                else 0,
                "store": payload.get("store"),
                "service_tier": payload.get("service_tier"),
            },
        )

    def _update_request_lifecycle(
        self,
        *,
        status: ProviderRequestStatus,
        event_type: str | None = None,
        provider_response_id: str | None = None,
        finish_reason: FinishReason | None = None,
        error: LLMError | None = None,
        provider_data: Dict[str, Any] | None = None,
    ) -> None:
        lifecycle = getattr(self, "_last_request_lifecycle", None)
        if lifecycle is None:
            return
        now = time.time()
        lifecycle.status = status
        lifecycle.last_event_at = now
        if status in {
            ProviderRequestStatus.COMPLETED,
            ProviderRequestStatus.DISCONNECTED,
            ProviderRequestStatus.FAILED,
            ProviderRequestStatus.CANCELLED,
        }:
            lifecycle.ended_at = now
        if event_type:
            lifecycle.last_event_type = event_type
        if provider_response_id:
            lifecycle.provider_response_id = provider_response_id
        if finish_reason is not None:
            lifecycle.finish_reason = finish_reason
        if error is not None:
            lifecycle.error = error
        if provider_data:
            lifecycle.provider_data.update(dict(provider_data))

    def _codex_model_for_oauth(self, model_id: str) -> tuple[str, bool]:
        value = str(model_id or "").strip()
        if "/" in value:
            prefix, remainder = value.split("/", 1)
            if prefix.strip().lower() == "openai" and remainder.strip():
                value = remainder.strip()

        if not value:
            raise RuntimeError(
                "OpenAI OAuth Codex model resolution failed: model id is empty"
            )
        if value.upper().startswith("GPT-"):
            value = value.lower()
        return value, False

    def _extract_codex_text_content(self, content: Any) -> str:
        if isinstance(content, str) and content.strip():
            return content.strip()

        if not isinstance(content, list):
            return ""

        chunks: List[str] = []
        for part in content:
            if isinstance(part, dict) and part.get("type") == "text":
                text_value = part.get("text")
                if isinstance(text_value, str) and text_value.strip():
                    chunks.append(text_value.strip())
                continue
            if isinstance(part, str) and part.strip():
                chunks.append(part.strip())

        return "\n".join(chunks)

    def _dedupe_instruction_parts(self, parts: List[str]) -> List[str]:
        deduped: List[str] = []
        seen: set[str] = set()
        for part in parts:
            value = part.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            deduped.append(value)
        return deduped

    def _normalize_codex_role(self, role: str) -> str:
        value = str(role or "user").strip().lower()
        if value in {"assistant", "developer", "user"}:
            return value
        return "user"

    def _codex_text_part_type_for_role(self, role: str) -> str:
        return "output_text" if role == "assistant" else "input_text"

    def _prepare_codex_messages_and_instructions(
        self,
        explicit_instructions: str | None,
        messages: List[Dict[str, Any]],
    ) -> tuple[str, List[Dict[str, Any]]]:
        normalized_messages = self.format_messages(messages)
        instruction_parts: List[str] = []
        if isinstance(explicit_instructions, str) and explicit_instructions.strip():
            instruction_parts.append(explicit_instructions.strip())

        transformed_messages: List[Dict[str, Any]] = []
        saw_non_system_message = False

        for message in normalized_messages:
            role = str(message.get("role", "user") or "user").strip().lower()

            if role == "system":
                system_text = self._extract_codex_text_content(message.get("content"))
                if not saw_non_system_message:
                    if system_text:
                        instruction_parts.append(system_text)
                    continue

                if system_text:
                    transformed_messages.append(
                        {
                            "role": "user",
                            "content": f"[SYSTEM NOTE]\n{system_text}",
                        }
                    )
                continue

            saw_non_system_message = True

            if role == "tool":
                transformed_messages.append({**message, "role": "tool"})
                continue

            transformed_messages.append(
                {
                    **message,
                    "role": self._normalize_codex_role(role),
                }
            )

        deduped_instructions = self._dedupe_instruction_parts(instruction_parts)
        resolved_instructions = (
            "\n\n".join(deduped_instructions)
            if deduped_instructions
            else "You are Penguin."
        )
        return resolved_instructions, transformed_messages

    def _build_codex_input_items(
        self,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        seen_function_call_ids: set[str] = set()
        for message in sanitize_native_tool_messages(messages):
            if not isinstance(message, dict):
                continue
            raw_role = str(message.get("role", "user") or "user")
            role = self._normalize_codex_role(raw_role)

            if raw_role.strip().lower() == "tool":
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                output_text = self._extract_codex_text_content(message.get("content"))
                if tool_call_id in seen_function_call_ids:
                    items.append(
                        {
                            "type": "function_call_output",
                            "call_id": tool_call_id,
                            "output": output_text,
                        }
                    )
                continue

            function_call_items: List[Dict[str, Any]] = []
            tool_calls = message.get("tool_calls")
            if role == "assistant" and isinstance(tool_calls, list):
                for tool_call in tool_calls:
                    if not isinstance(tool_call, dict):
                        continue
                    function_payload = tool_call.get("function")
                    if not isinstance(function_payload, dict):
                        continue
                    call_id = str(tool_call.get("id") or "").strip()
                    name = str(function_payload.get("name") or "").strip()
                    arguments = function_payload.get("arguments") or "{}"
                    if call_id and name:
                        function_call_items.append(
                            {
                                "type": "function_call",
                                "call_id": call_id,
                                "name": name,
                                "arguments": str(arguments),
                            }
                        )

            text_part_type = self._codex_text_part_type_for_role(role)
            content = message.get("content", "")
            parts: List[Dict[str, Any]] = []

            if isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        part_type = str(part.get("type") or "").strip().lower()

                        if part_type in {"text", "input_text", "output_text"}:
                            text_value = str(part.get("text", ""))
                            if text_value:
                                parts.append(
                                    {"type": text_part_type, "text": text_value}
                                )
                            continue

                        if role == "assistant" and part_type == "refusal":
                            refusal = part.get("refusal")
                            if isinstance(refusal, str) and refusal:
                                parts.append({"type": "refusal", "refusal": refusal})
                            continue

                        if part_type == "image_url" and role != "assistant":
                            image_url = None
                            url_obj = part.get("image_url")
                            if isinstance(url_obj, dict):
                                maybe_url = url_obj.get("url")
                                if isinstance(maybe_url, str) and maybe_url:
                                    image_url = maybe_url
                            elif isinstance(url_obj, str) and url_obj:
                                image_url = url_obj

                            if image_url:
                                parts.append(
                                    {
                                        "type": "input_image",
                                        "image_url": image_url,
                                    }
                                )
                                continue

                        parts.append({"type": text_part_type, "text": str(part)})
                        continue

                    if isinstance(part, str):
                        text_value = part
                        if text_value:
                            parts.append({"type": text_part_type, "text": text_value})
                        continue

                    parts.append({"type": text_part_type, "text": str(part)})
            elif str(content):
                parts.append({"type": text_part_type, "text": str(content)})

            if parts:
                items.append({"type": "message", "role": role, "content": parts})
            # Responses input requires calls to sit immediately beside their
            # corresponding output items.  Keep assistant prose before the
            # call batch rather than accidentally inserting it between calls
            # and tool outputs.
            if function_call_items:
                items.extend(function_call_items)
                seen_function_call_ids.update(
                    str(item["call_id"]) for item in function_call_items
                )

        return self._sanitize_codex_input_items(items)

    def _sanitize_codex_input_items(
        self, items: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Keep only immediate, complete Codex function-call/output batches."""

        seen_function_call_ids: set[str] = set()
        sanitized: List[Dict[str, Any]] = []
        dropped_function_calls = 0
        dropped_outputs = 0
        index = 0
        while index < len(items):
            item = items[index]
            item_type = str(item.get("type") or "").strip()
            if item_type == "function_call":
                call_items: List[Dict[str, Any]] = []
                call_ids: List[str] = []
                batch_is_valid = True
                while index < len(items):
                    call_item = items[index]
                    if str(call_item.get("type") or "").strip() != "function_call":
                        break
                    call_id = str(call_item.get("call_id") or "").strip()
                    name = str(call_item.get("name") or "").strip()
                    if (
                        not call_id
                        or not name
                        or call_id in seen_function_call_ids
                        or call_id in call_ids
                    ):
                        batch_is_valid = False
                    call_items.append(call_item)
                    call_ids.append(call_id)
                    index += 1

                output_items: List[Dict[str, Any]] = []
                output_ids: List[str] = []
                while index < len(items):
                    output_item = items[index]
                    if (
                        str(output_item.get("type") or "").strip()
                        != "function_call_output"
                    ):
                        break
                    output_items.append(output_item)
                    output_ids.append(str(output_item.get("call_id") or "").strip())
                    index += 1

                if (
                    not call_items
                    or len(output_items) != len(call_items)
                    or any(not call_id for call_id in output_ids)
                    or len(output_ids) != len(set(output_ids))
                    or set(output_ids) != set(call_ids)
                ):
                    batch_is_valid = False

                if batch_is_valid:
                    sanitized.extend(call_items)
                    sanitized.extend(output_items)
                    seen_function_call_ids.update(call_ids)
                else:
                    dropped_function_calls += len(call_items)
                    dropped_outputs += len(output_items)
                continue

            if item_type == "function_call_output":
                # Outputs that do not immediately follow their declaration
                # batch are never safe to replay.
                dropped_outputs += 1
                index += 1
                continue

            sanitized.append(item)
            index += 1

        if dropped_function_calls or dropped_outputs:
            logger.warning(
                "Sanitized Codex replay items: dropped_function_calls=%s dropped_outputs=%s",
                dropped_function_calls,
                dropped_outputs,
            )

        return sanitized

    def _build_codex_oauth_payload(
        self,
        *,
        processed_messages: List[Dict[str, Any]],
        temperature: float,
        reasoning_config: Dict[str, Any] | None,
        instructions: str | None,
        previous_response_id: str | None,
        conversation_id: str | None,
        response_format: Dict[str, Any] | None,
        tools: List[Dict[str, Any]] | None,
        tool_choice: Union[str, Dict[str, Any]] | None,
        service_tier: str | None,
    ) -> tuple[Dict[str, Any], str, bool]:
        """Build the Codex OAuth Responses payload without sending it."""

        model_id, model_fallback = self._codex_model_for_oauth(self.model_config.model)
        resolved_instructions, codex_messages = (
            self._prepare_codex_messages_and_instructions(
                instructions,
                processed_messages,
            )
        )
        input_items = self._build_codex_input_items(codex_messages)

        payload: Dict[str, Any] = {
            "model": model_id,
            "input": input_items,
            "instructions": resolved_instructions,
            "store": False,
        }
        if isinstance(reasoning_config, dict) and reasoning_config:
            payload["reasoning"] = reasoning_config
            include_items = payload.get("include")
            resolved_include = (
                [item for item in include_items if isinstance(item, str)]
                if isinstance(include_items, list)
                else []
            )
            if "reasoning.encrypted_content" not in resolved_include:
                resolved_include.append("reasoning.encrypted_content")
            payload["include"] = resolved_include
        if previous_response_id:
            payload["previous_response_id"] = previous_response_id
        if conversation_id:
            payload["conversation"] = conversation_id
        if response_format:
            payload["response_format"] = response_format
        normalized_tools = normalize_openai_responses_tools(tools)
        normalized_tool_choice = normalize_openai_responses_tool_choice(tool_choice)
        if normalized_tools:
            payload["tools"] = normalized_tools
        if normalized_tool_choice:
            payload["tool_choice"] = normalized_tool_choice
        if service_tier:
            payload["service_tier"] = service_tier

        try:
            uses_effort_style = bool(self.model_config._uses_effort_style())
        except Exception:
            uses_effort_style = False
        if not uses_effort_style:
            payload["temperature"] = temperature

        return payload, model_id, model_fallback

    async def _create_oauth_codex_completion(
        self,
        *,
        processed_messages: List[Dict[str, Any]],
        oauth_record: Dict[str, Any],
        max_output_tokens: int | None,
        temperature: float,
        stream: bool,
        stream_callback: Optional[Callable[[str], None]],
        reasoning_config: Dict[str, Any] | None,
        instructions: str | None,
        previous_response_id: str | None,
        conversation_id: str | None,
        response_format: Dict[str, Any] | None,
        tools: List[Dict[str, Any]] | None,
        tool_choice: Union[str, Dict[str, Any]] | None,
        service_tier: str | None,
    ) -> str:
        diag_id = self._new_codex_diag_id()
        payload, model_id, model_fallback = self._build_codex_oauth_payload(
            processed_messages=processed_messages,
            temperature=temperature,
            reasoning_config=reasoning_config,
            instructions=instructions,
            previous_response_id=previous_response_id,
            conversation_id=conversation_id,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            service_tier=service_tier,
        )

        access = str(oauth_record.get("access") or "").strip()
        account_id = str(oauth_record.get("accountId") or "").strip()
        headers: Dict[str, str] = {
            "Authorization": f"Bearer {access}",
            "Content-Type": "application/json",
            "originator": "penguin",
            "User-Agent": "penguin-openai-adapter",
        }
        if account_id:
            headers["ChatGPT-Account-Id"] = account_id

        _log_info(
            "openai.oauth.codex.request_start diag_id=%s requested_stream=%s "
            "transport_stream=%s model=%s "
            "model_fallback=%s input_items=%s instructions_present=%s "
            "store=%s service_tier=%s has_account_id=%s has_reasoning=%s",
            diag_id,
            stream,
            True,
            model_id,
            model_fallback,
            len(payload.get("input", []))
            if isinstance(payload.get("input"), list)
            else 0,
            bool(payload.get("instructions")),
            payload.get("store"),
            service_tier,
            bool(account_id),
            isinstance(reasoning_config, dict) and bool(reasoning_config),
        )
        self._start_reasoning_debug_snapshot(
            provider=self.provider,
            model=model_id,
            diag_id=diag_id,
            stage="stream" if stream else "request",
            requested_stream=bool(stream),
            reasoning_requested=bool(
                isinstance(reasoning_config, dict) and reasoning_config
            ),
            reasoning_config=dict(reasoning_config or {}),
            visible_reasoning_chars=0,
            visible_reasoning_summary_returned=False,
        )

        return await self._stream_codex_oauth(
            payload,
            headers,
            stream_callback if stream else None,
            model_id=model_id,
            model_fallback=model_fallback,
            diag_id=diag_id,
            requested_stream=stream,
        )

    async def _request_codex_oauth(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        *,
        model_id: str,
        model_fallback: bool,
        diag_id: str,
    ) -> str:
        self._record_network_attempt()
        started = time.monotonic()
        watchdog = self._codex_watchdog_config()
        response: httpx.Response | None = None
        if self._last_request_lifecycle is None:
            self._start_request_lifecycle(
                request_id=diag_id,
                model_id=model_id,
                payload=payload,
                stream=False,
                transport="http",
                model_fallback=model_fallback,
            )
        self._update_request_lifecycle(
            status=ProviderRequestStatus.RUNNING,
            provider_data={
                "requested_stream": False,
                "transport_stream": False,
            },
        )
        try:
            async with self._codex_client_context(
                started=started,
                watchdog=watchdog,
            ) as client:
                response = await self._await_with_codex_total_deadline(
                    client.post(
                        _OPENAI_CODEX_RESPONSES_URL,
                        headers=headers,
                        json=payload,
                    ),
                    started=started,
                    watchdog=watchdog,
                )
        except _CodexWatchdogTimeout as exc:
            self._raise_codex_transport_error(
                error=exc,
                payload=payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="request_total_timeout",
                diag_id=diag_id,
                watchdog=watchdog,
            )
        except httpx.TimeoutException as exc:
            self._raise_codex_transport_error(
                error=exc,
                payload=payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="request_timeout",
                diag_id=diag_id,
                watchdog=watchdog,
            )
        except httpx.HTTPError as exc:
            self._raise_codex_transport_error(
                error=exc,
                payload=payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="request_transport",
                diag_id=diag_id,
                watchdog=watchdog,
            )

        if response is None:
            self._raise_codex_transport_error(
                error=RuntimeError("Missing HTTP response from Codex endpoint"),
                payload=payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="request_response",
                diag_id=diag_id,
                watchdog=watchdog,
            )
        assert response is not None

        latency_ms = int((time.monotonic() - started) * 1000)
        trace = self._trace_headers(response)

        if response.status_code >= 400:
            self._raise_codex_error(
                status_code=response.status_code,
                detail=self._codex_error_detail(response=response),
                payload=payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="request",
                diag_id=diag_id,
                trace=trace,
                latency_ms=latency_ms,
                retry_after_seconds=extract_retry_after_seconds(response.headers),
            )

        _log_info(
            "openai.oauth.codex.request_success diag_id=%s stage=request "
            "status=%s latency_ms=%s model=%s model_fallback=%s "
            "service_tier=%s trace=%s",
            diag_id,
            response.status_code,
            latency_ms,
            model_id,
            model_fallback,
            payload.get("service_tier"),
            trace,
        )

        body: Any = {}
        if response.content:
            try:
                body = response.json()
            except Exception:
                body = response.text

        if isinstance(body, str):
            self._set_last_finish_reason(FinishReason.STOP)
            self._update_request_lifecycle(
                status=ProviderRequestStatus.COMPLETED,
                finish_reason=FinishReason.STOP,
            )
            self._finalize_reasoning_debug_snapshot(
                visible_reasoning_chars=len(self.get_last_reasoning()),
                visible_reasoning_summary_returned=bool(self.get_last_reasoning()),
                usage=self.get_last_usage(),
                finish_reason=self.get_last_finish_reason().value,
            )
            return body
        if isinstance(body, dict):
            self._record_reasoning_debug_event("response.completed", body)
            response_id = body.get("id")
            if isinstance(response_id, str) and response_id.strip():
                self._update_request_lifecycle(
                    status=ProviderRequestStatus.RUNNING,
                    provider_response_id=response_id.strip(),
                )
            self._set_last_usage(body.get("usage"))
            self._append_reasoning(self._extract_reasoning_from_response_object(body))
        tool_calls = self._extract_function_calls_from_response_object(body)
        if tool_calls:
            for tool_call in tool_calls:
                self._remember_tool_call(tool_call)
            self._set_last_finish_reason(FinishReason.TOOL_CALLS)
        else:
            self._set_last_finish_reason(FinishReason.STOP)
        self._update_request_lifecycle(
            status=ProviderRequestStatus.COMPLETED,
            finish_reason=self.get_last_finish_reason(),
        )
        self._finalize_reasoning_debug_snapshot(
            visible_reasoning_chars=len(self.get_last_reasoning()),
            visible_reasoning_summary_returned=bool(self.get_last_reasoning()),
            usage=self.get_last_usage(),
            finish_reason=self.get_last_finish_reason().value,
        )
        return self._extract_text_from_response_object(body) or ""

    async def _stream_codex_oauth(
        self,
        payload: Dict[str, Any],
        headers: Dict[str, str],
        stream_callback: Optional[Callable[[str], None]],
        *,
        model_id: str,
        model_fallback: bool,
        diag_id: str,
        requested_stream: bool = True,
    ) -> str:
        self._record_network_attempt()
        stream_payload = dict(payload)
        stream_payload["stream"] = True

        accumulated_content: List[str] = []
        completed_text = ""
        accumulated_reasoning = ""
        started = time.monotonic()
        watchdog = self._codex_watchdog_config()
        event_counts: Dict[str, int] = {}
        first_event_ms: Optional[int] = None
        first_text_ms: Optional[int] = None
        first_tool_args_ms: Optional[int] = None
        completed_ms: Optional[int] = None
        max_event_gap_ms = 0
        last_event_at: Optional[float] = None
        text_delta_count = 0
        text_delta_chars = 0
        tool_arg_delta_count = 0
        tool_arg_chars = 0
        tool_arg_chars_by_item: Dict[str, int] = {}
        response: httpx.Response | None = None
        stream_entered_at: float | None = None
        setup_recorded = False
        saw_done_marker = False
        saw_completed_event = False
        self._start_request_lifecycle(
            request_id=diag_id,
            model_id=model_id,
            payload=stream_payload,
            stream=True,
            transport="sse",
            model_fallback=model_fallback,
        )
        self._update_request_lifecycle(
            status=ProviderRequestStatus.RUNNING,
            provider_data={
                "requested_stream": bool(requested_stream),
                "transport_stream": True,
            },
        )
        try:
            async with self._codex_client_context(
                started=started,
                watchdog=watchdog,
            ) as client:
                async with self._codex_stream_context(
                    client,
                    headers=headers,
                    payload=stream_payload,
                    started=started,
                    watchdog=watchdog,
                ) as response:
                    stream_entered_at = time.monotonic()
                    record_runtime_duration(
                        "provider.setup",
                        (stream_entered_at - started) * 1000,
                    )
                    setup_recorded = True
                    if response.status_code >= 400:
                        response_body = await self._await_with_codex_total_deadline(
                            response.aread(),
                            started=started,
                            watchdog=watchdog,
                        )
                        response_text = response_body.decode(
                            "utf-8",
                            errors="replace",
                        )
                        latency_ms = int((time.monotonic() - started) * 1000)
                        self._raise_codex_error(
                            status_code=response.status_code,
                            detail=self._codex_error_detail(
                                response_text=response_text
                            ),
                            payload=stream_payload,
                            model_id=model_id,
                            model_fallback=model_fallback,
                            stage="stream_request",
                            diag_id=diag_id,
                            trace=self._trace_headers(response),
                            latency_ms=latency_ms,
                            retry_after_seconds=extract_retry_after_seconds(
                                response.headers
                            ),
                        )

                    async for line in self._iter_codex_lines_with_watchdog(
                        response,
                        started=started,
                        watchdog=watchdog,
                    ):
                        if not line or not line.strip():
                            continue
                        if not line.startswith("data: "):
                            continue
                        data_str = line[6:]
                        if data_str.strip() == "[DONE]":
                            saw_done_marker = True
                            self._update_request_lifecycle(
                                status=ProviderRequestStatus.STREAMING,
                                event_type="[DONE]",
                            )
                            break

                        try:
                            data = json.loads(data_str)
                        except Exception:
                            continue

                        if not isinstance(data, dict):
                            continue

                        etype = data.get("type")
                        event_type = str(etype or "").strip()
                        event_now = time.monotonic()
                        event_elapsed_ms = int((event_now - started) * 1000)
                        if first_event_ms is None:
                            first_event_ms = event_elapsed_ms
                            record_runtime_duration(
                                "provider.wait_first_event",
                                (event_now - (stream_entered_at or started)) * 1000,
                            )
                        mark_runtime_progress("provider")
                        if last_event_at is not None:
                            max_event_gap_ms = max(
                                max_event_gap_ms,
                                int((event_now - last_event_at) * 1000),
                            )
                        last_event_at = event_now
                        if event_type:
                            event_counts[event_type] = (
                                event_counts.get(event_type, 0) + 1
                            )
                        response_obj_for_lifecycle = data.get("response")
                        provider_response_id = None
                        if isinstance(response_obj_for_lifecycle, dict):
                            raw_response_id = response_obj_for_lifecycle.get("id")
                            if isinstance(raw_response_id, str):
                                provider_response_id = raw_response_id.strip() or None
                        self._update_request_lifecycle(
                            status=ProviderRequestStatus.STREAMING,
                            event_type=event_type or None,
                            provider_response_id=provider_response_id,
                        )

                        self._record_reasoning_debug_event(data.get("type"), data)

                        if etype in {"error", "response.failed", "response.error"}:
                            error_payload = data.get("error")
                            response_payload = data.get("response")
                            detail_payload = (
                                error_payload
                                if error_payload is not None
                                else response_payload
                                if response_payload is not None
                                else data
                            )
                            detail = json.dumps(detail_payload, default=str)[:500]
                            error_category, retryable = (
                                self._responses_stream_error_taxonomy(data)
                            )
                            self._raise_codex_transport_error(
                                error=RuntimeError(detail),
                                payload=stream_payload,
                                model_id=model_id,
                                model_fallback=model_fallback,
                                stage="stream_event_error",
                                diag_id=diag_id,
                                partial_output=completed_text
                                or "".join(accumulated_content),
                                partial_tool_call=self.has_pending_tool_call(),
                                watchdog=watchdog,
                                error_category=error_category,
                                retryable=retryable,
                            )

                        if self._capture_responses_tool_event(data):
                            self._set_last_finish_reason(FinishReason.TOOL_CALLS)
                        if (
                            self.has_pending_tool_call()
                            and self._interrupt_on_tool_call()
                        ):
                            self._set_last_finish_reason(FinishReason.TOOL_CALLS)

                        if etype == "response.output_text.delta":
                            delta = data.get("delta", "")
                            if delta:
                                if first_text_ms is None:
                                    first_text_ms = event_elapsed_ms
                                text_delta_count += 1
                                text_delta_chars += len(str(delta))
                                accumulated_content.append(delta)
                                if stream_callback:
                                    await self._safe_invoke_callback(
                                        stream_callback,
                                        str(delta),
                                        "assistant",
                                        deadline=started + watchdog.total_seconds,
                                        total_timeout_seconds=watchdog.total_seconds,
                                    )
                            continue

                        if etype == "response.function_call_arguments.delta":
                            delta = data.get("delta")
                            if isinstance(delta, str) and delta:
                                if first_tool_args_ms is None:
                                    first_tool_args_ms = event_elapsed_ms
                                tool_arg_delta_count += 1
                                tool_arg_chars += len(delta)
                                raw_item_id = data.get("item_id") or data.get(
                                    "output_index"
                                )
                                item_id = str(raw_item_id or "unknown")
                                tool_arg_chars_by_item[item_id] = (
                                    tool_arg_chars_by_item.get(item_id, 0) + len(delta)
                                )
                            continue

                        if etype == "response.output_text.done":
                            done_text = data.get("text", "")
                            if isinstance(done_text, str) and done_text:
                                completed_text = done_text
                            continue

                        if etype == "response.completed":
                            saw_completed_event = True
                            completed_ms = event_elapsed_ms
                            response_obj = data.get("response")
                            if isinstance(response_obj, dict):
                                self._set_last_usage(response_obj.get("usage"))
                                reasoning_text = (
                                    self._extract_reasoning_from_response_object(
                                        response_obj
                                    )
                                )
                                if reasoning_text and not accumulated_reasoning.strip():
                                    accumulated_reasoning += reasoning_text
                                    self._append_reasoning(reasoning_text)
                                    if stream_callback:
                                        await self._safe_invoke_callback(
                                            stream_callback,
                                            reasoning_text,
                                            "reasoning",
                                            deadline=started + watchdog.total_seconds,
                                            total_timeout_seconds=watchdog.total_seconds,
                                        )
                            extracted = self._extract_text_from_response_object(
                                response_obj
                            )
                            if extracted:
                                completed_text = extracted
                            # response.completed is the Responses API terminal
                            # event. Some transports omit the optional [DONE]
                            # sentinel or leave the connection open afterward.
                            break

                        reasoning_delta = (
                            self._extract_reasoning_delta_from_sse_payload(data)
                        )
                        if (
                            reasoning_delta
                            and etype == "response.output_item.done"
                            and accumulated_reasoning.strip()
                        ):
                            reasoning_delta = ""
                        if reasoning_delta:
                            accumulated_reasoning += reasoning_delta
                            self._append_reasoning(reasoning_delta)
                        if reasoning_delta and stream_callback:
                            await self._safe_invoke_callback(
                                stream_callback,
                                reasoning_delta,
                                "reasoning",
                                deadline=started + watchdog.total_seconds,
                                total_timeout_seconds=watchdog.total_seconds,
                            )
        except _CodexWatchdogTimeout as exc:
            partial_tool_call = self.has_pending_tool_call()
            if partial_tool_call:
                self._reset_tool_call_state()
            self._raise_codex_transport_error(
                error=exc,
                payload=stream_payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage=exc.stage,
                diag_id=diag_id,
                partial_output=completed_text or "".join(accumulated_content),
                partial_tool_call=partial_tool_call,
                watchdog=watchdog,
            )
        except httpx.TimeoutException as exc:
            partial_tool_call = self.has_pending_tool_call()
            if partial_tool_call:
                self._reset_tool_call_state()
            self._raise_codex_transport_error(
                error=exc,
                payload=stream_payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="stream_timeout",
                diag_id=diag_id,
                partial_output=completed_text or "".join(accumulated_content),
                partial_tool_call=partial_tool_call,
                watchdog=watchdog,
            )
        except httpx.HTTPError as exc:
            partial_tool_call = self.has_pending_tool_call()
            if partial_tool_call:
                self._reset_tool_call_state()
            self._raise_codex_transport_error(
                error=exc,
                payload=stream_payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="stream_transport",
                diag_id=diag_id,
                partial_output=completed_text or "".join(accumulated_content),
                partial_tool_call=partial_tool_call,
                watchdog=watchdog,
            )
        finally:
            finished_at = time.monotonic()
            if not setup_recorded:
                record_runtime_duration(
                    "provider.setup",
                    (finished_at - started) * 1000,
                )
            if stream_entered_at is not None:
                record_runtime_duration(
                    "provider.stream",
                    (finished_at - stream_entered_at) * 1000,
                )

        if response is None:
            self._raise_codex_transport_error(
                error=RuntimeError("Missing HTTP stream response from Codex endpoint"),
                payload=stream_payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="stream_response",
                diag_id=diag_id,
                partial_output=completed_text or "".join(accumulated_content),
                partial_tool_call=self.has_pending_tool_call(),
                watchdog=watchdog,
            )
        assert response is not None

        pending_tool_call = self.has_pending_tool_call()
        if not saw_completed_event:
            latency_ms = int((time.monotonic() - started) * 1000)
            output_state = (
                "tool_call"
                if pending_tool_call
                else "text"
                if completed_text or accumulated_content
                else "empty"
            )
            detail = (
                "Codex stream ended before response.completed "
                f"(output_state={output_state}, saw_done_marker={saw_done_marker})"
            )
            _log_info(
                "openai.oauth.codex.stream_breakdown diag_id=%s model=%s "
                "latency_ms=%s incomplete=True first_event_ms=%s first_text_ms=%s "
                "first_tool_args_ms=%s max_event_gap_ms=%s text_delta_count=%s "
                "text_delta_chars=%s tool_arg_delta_count=%s tool_arg_chars=%s "
                "event_counts=%s",
                diag_id,
                model_id,
                latency_ms,
                first_event_ms,
                first_text_ms,
                first_tool_args_ms,
                max_event_gap_ms,
                text_delta_count,
                text_delta_chars,
                tool_arg_delta_count,
                tool_arg_chars,
                dict(sorted(event_counts.items())),
            )
            if pending_tool_call:
                self._reset_tool_call_state()
            self._raise_codex_transport_error(
                error=RuntimeError(detail),
                payload=stream_payload,
                model_id=model_id,
                model_fallback=model_fallback,
                stage="stream_incomplete",
                diag_id=diag_id,
                partial_output=completed_text or "".join(accumulated_content),
                partial_tool_call=pending_tool_call,
                watchdog=watchdog,
            )

        latency_ms = int((time.monotonic() - started) * 1000)
        trace = self._trace_headers(response)
        output_chars = len(completed_text) or len("".join(accumulated_content))
        stream_breakdown = {
            "latency_ms": latency_ms,
            "first_event_ms": first_event_ms,
            "first_text_ms": first_text_ms,
            "first_tool_args_ms": first_tool_args_ms,
            "completed_ms": completed_ms,
            "max_event_gap_ms": max_event_gap_ms,
            "text_delta_count": text_delta_count,
            "text_delta_chars": text_delta_chars,
            "tool_arg_delta_count": tool_arg_delta_count,
            "tool_arg_chars": tool_arg_chars,
            "tool_arg_chars_by_item": dict(tool_arg_chars_by_item),
            "saw_done_marker": saw_done_marker,
            "saw_completed_event": saw_completed_event,
            "event_counts": dict(sorted(event_counts.items())),
        }
        _log_info(
            "openai.oauth.codex.request_success diag_id=%s stage=stream status=%s "
            "latency_ms=%s model=%s model_fallback=%s service_tier=%s "
            "output_chars=%s trace=%s",
            diag_id,
            response.status_code if response is not None else 0,
            latency_ms,
            model_id,
            model_fallback,
            stream_payload.get("service_tier"),
            output_chars,
            trace,
        )
        _log_info(
            "openai.oauth.codex.stream_breakdown diag_id=%s model=%s latency_ms=%s "
            "first_event_ms=%s first_text_ms=%s first_tool_args_ms=%s "
            "completed_ms=%s max_event_gap_ms=%s text_delta_count=%s "
            "text_delta_chars=%s tool_arg_delta_count=%s tool_arg_chars=%s "
            "tool_arg_chars_by_item=%s event_counts=%s",
            diag_id,
            model_id,
            latency_ms,
            first_event_ms,
            first_text_ms,
            first_tool_args_ms,
            completed_ms,
            max_event_gap_ms,
            text_delta_count,
            text_delta_chars,
            tool_arg_delta_count,
            tool_arg_chars,
            dict(tool_arg_chars_by_item),
            dict(sorted(event_counts.items())),
        )
        self._update_request_lifecycle(
            status=ProviderRequestStatus.STREAMING,
            provider_data={"stream_breakdown": stream_breakdown},
        )
        self._finalize_reasoning_debug_snapshot(
            visible_reasoning_chars=len(self.get_last_reasoning()),
            visible_reasoning_summary_returned=bool(self.get_last_reasoning()),
            usage=self.get_last_usage(),
            finish_reason=self.get_last_finish_reason().value,
        )
        _log_info(
            "openai.oauth.codex.reasoning_debug diag_id=%s model=%s visible_reasoning_chars=%s summary_returned=%s reasoning_tokens=%s reasoning_events=%s event_types=%s",
            diag_id,
            model_id,
            self._last_reasoning_debug.get("visible_reasoning_chars", 0),
            self._last_reasoning_debug.get("visible_reasoning_summary_returned", False),
            self.get_last_usage().get("reasoning_tokens", 0),
            self._last_reasoning_debug.get("reasoning_event_types", []),
            self._last_reasoning_debug.get("event_types", []),
        )

        if pending_tool_call:
            self._set_last_finish_reason(FinishReason.TOOL_CALLS)

        if completed_text:
            if not pending_tool_call:
                self._set_last_finish_reason(FinishReason.STOP)
            self._update_request_lifecycle(
                status=ProviderRequestStatus.COMPLETED,
                finish_reason=self.get_last_finish_reason(),
            )
            if not accumulated_content and stream_callback:
                try:
                    await self._safe_invoke_callback(
                        stream_callback,
                        completed_text,
                        "assistant",
                        deadline=started + watchdog.total_seconds,
                        total_timeout_seconds=watchdog.total_seconds,
                    )
                except _CodexWatchdogTimeout as exc:
                    self._raise_codex_transport_error(
                        error=exc,
                        payload=stream_payload,
                        model_id=model_id,
                        model_fallback=model_fallback,
                        stage=exc.stage,
                        diag_id=diag_id,
                        partial_output=completed_text,
                        partial_tool_call=pending_tool_call,
                        watchdog=watchdog,
                    )
            return completed_text

        if not pending_tool_call:
            self._set_last_finish_reason(FinishReason.STOP)
        self._update_request_lifecycle(
            status=ProviderRequestStatus.COMPLETED,
            finish_reason=self.get_last_finish_reason(),
        )
        return "".join(accumulated_content)

    def _codex_error_detail(
        self,
        *,
        response: httpx.Response | None = None,
        response_text: str | None = None,
    ) -> str:
        if isinstance(response_text, str) and response_text.strip():
            return response_text.strip()[:500]

        if response is None:
            return "No response body"

        try:
            payload = response.json()
            if isinstance(payload, dict):
                raw_error = payload.get("error")
                if isinstance(raw_error, str) and raw_error.strip():
                    return raw_error.strip()[:500]
                if isinstance(raw_error, dict):
                    message = raw_error.get("message")
                    error_type = raw_error.get("type")
                    code = raw_error.get("code")
                    param = raw_error.get("param")
                    description = raw_error.get("description")
                    values = [
                        str(item)
                        for item in (
                            message,
                            error_type,
                            code,
                            param,
                            description,
                        )
                        if item
                    ]
                    if values:
                        return " | ".join(values)[:500]

                fallback_values = [
                    payload.get("message"),
                    payload.get("type"),
                    payload.get("code"),
                    payload.get("param"),
                    payload.get("detail"),
                ]
                compact = [str(item) for item in fallback_values if item]
                if compact:
                    return " | ".join(compact)[:500]
                return json.dumps(payload)[:500]
            if payload is not None:
                return str(payload)[:500]
        except Exception:
            pass

        try:
            text = response.text
            if isinstance(text, str) and text.strip():
                return text.strip()[:500]
        except Exception:
            pass

        return "No response body"

    def _raise_codex_error(
        self,
        *,
        status_code: int,
        detail: str,
        payload: Dict[str, Any],
        model_id: str,
        model_fallback: bool,
        stage: str,
        diag_id: str,
        trace: Dict[str, str] | None = None,
        latency_ms: int | None = None,
        retry_after_seconds: float | None = None,
    ) -> None:
        input_payload = payload.get("input")
        input_is_list = isinstance(input_payload, list)
        input_items = len(input_payload) if isinstance(input_payload, list) else 0
        instructions_present = bool(
            isinstance(payload.get("instructions"), str)
            and str(payload.get("instructions")).strip()
        )
        store_flag = payload.get("store")
        service_tier = payload.get("service_tier")

        error_message = (
            f"OpenAI OAuth Codex {stage} failed "
            f"(diag_id={diag_id}, status={status_code}, model={model_id}, "
            f"model_fallback={model_fallback}, input_is_list={input_is_list}, "
            f"input_items={input_items}, instructions_present={instructions_present}, "
            f"store={store_flag}, service_tier={service_tier}, "
            f"latency_ms={latency_ms}) detail={detail}, "
            f"trace={trace or {}}"
        )
        _log_error(error_message)
        prefix = "OpenAI OAuth reauth required: " if status_code in {401, 403} else ""
        llm_error = build_llm_error(
            message=f"{prefix}{error_message}",
            provider=self.provider,
            model=model_id,
            status_code=status_code,
            retry_after_seconds=retry_after_seconds,
            provider_data={
                "diag_id": diag_id,
                "trace": trace or {},
                "stage": stage,
                "model_fallback": model_fallback,
                "detail": detail,
                "network_attempts": self.get_last_network_attempt_count(),
            },
        )
        self._set_last_error(llm_error)
        self._update_request_lifecycle(
            status=ProviderRequestStatus.FAILED,
            event_type=stage,
            finish_reason=llm_error.finish_reason or FinishReason.ERROR,
            error=llm_error,
        )
        self._finalize_reasoning_debug_snapshot(
            status="error",
            visible_reasoning_chars=len(self.get_last_reasoning()),
            visible_reasoning_summary_returned=bool(self.get_last_reasoning()),
            usage=self.get_last_usage(),
            finish_reason=llm_error.finish_reason.value
            if llm_error.finish_reason
            else None,
            error=llm_error.message,
        )
        raise LLMProviderError(llm_error)

    def _raise_codex_transport_error(
        self,
        *,
        error: Exception,
        payload: Dict[str, Any],
        model_id: str,
        model_fallback: bool,
        stage: str,
        diag_id: str,
        partial_output: str | None = None,
        partial_tool_call: bool = False,
        watchdog: _CodexWatchdogConfig | None = None,
        error_category: ErrorCategory | str | None = None,
        retryable: bool | None = None,
    ) -> None:
        if partial_tool_call:
            self._reset_tool_call_state()
        raw_partial_output = str(partial_output or "")
        preserved_partial_output = raw_partial_output[:_OPENAI_PARTIAL_OUTPUT_MAX_CHARS]
        provider_data: Dict[str, Any] = {
            "diag_id": diag_id,
            "stage": stage,
            "model_fallback": model_fallback,
            "partial_output": preserved_partial_output,
            "partial_output_chars": len(raw_partial_output),
            "partial_output_truncated": (
                len(raw_partial_output) > len(preserved_partial_output)
            ),
            "partial_tool_call": bool(partial_tool_call),
            "network_attempts": self.get_last_network_attempt_count(),
        }
        if watchdog is not None:
            provider_data["watchdog"] = {
                "connect_seconds": watchdog.connect_seconds,
                "header_seconds": watchdog.header_seconds,
                "idle_seconds": watchdog.idle_seconds,
                "total_seconds": watchdog.total_seconds,
                "cleanup_seconds": watchdog.cleanup_seconds,
            }
        input_payload = payload.get("input")
        input_is_list = isinstance(input_payload, list)
        input_items = len(input_payload) if isinstance(input_payload, list) else 0
        instructions_present = bool(
            isinstance(payload.get("instructions"), str)
            and str(payload.get("instructions")).strip()
        )
        store_flag = payload.get("store")

        error_message = (
            f"OpenAI OAuth Codex {stage} failed "
            f"(diag_id={diag_id}, model={model_id}, "
            f"model_fallback={model_fallback}, input_is_list={input_is_list}, "
            f"input_items={input_items}, instructions_present={instructions_present}, "
            f"store={store_flag}, error_type={type(error).__name__}) detail={error}"
        )
        _log_error(error_message, exc_info=True)
        resolved_error_category: ErrorCategory | str = error_category or "network"
        if error_category is None and (
            "timeout" in stage.lower() or isinstance(error, httpx.TimeoutException)
        ):
            resolved_error_category = "timeout"
        llm_error = build_llm_error(
            message=error_message,
            provider=self.provider,
            model=model_id,
            category=resolved_error_category,
            finish_reason=FinishReason.ERROR,
            retryable=True if retryable is None else retryable,
            provider_data=provider_data,
        )
        self._set_last_error(llm_error)
        stream_disconnect_stages = {
            "stream_incomplete",
            "stream_response",
            "stream_timeout",
            "stream_transport",
            "stream_header_timeout",
            "stream_idle_timeout",
            "stream_total_timeout",
            "stream_cleanup_timeout",
        }
        lifecycle_status = (
            ProviderRequestStatus.DISCONNECTED
            if stage in stream_disconnect_stages
            else ProviderRequestStatus.FAILED
        )
        self._update_request_lifecycle(
            status=lifecycle_status,
            event_type=stage,
            finish_reason=FinishReason.ERROR,
            error=llm_error,
            provider_data=provider_data,
        )
        self._finalize_reasoning_debug_snapshot(
            status="error",
            visible_reasoning_chars=len(self.get_last_reasoning()),
            visible_reasoning_summary_returned=bool(self.get_last_reasoning()),
            usage=self.get_last_usage(),
            finish_reason=llm_error.finish_reason.value
            if llm_error.finish_reason
            else None,
            error=llm_error.message,
        )
        raise LLMProviderError(llm_error) from error

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Pass-through for OpenAI chat format with minimal normalization.

        The Responses API accepts ``messages`` similar to Chat Completions.
        This method keeps strings intact and ensures multimodal list content
        items conform to expected shapes.
        """
        normalized: List[Dict[str, Any]] = []
        for m in sanitize_native_tool_messages(messages):
            if not isinstance(m, dict):
                continue
            role = m.get("role", "user")
            content = m.get("content", "")
            if isinstance(content, list):
                fixed_parts: List[Dict[str, Any]] = []
                for part in content:
                    if isinstance(part, dict):
                        if part.get("type") == "image_url" and "image_url" in part:
                            # Keep as-is; _process_messages_for_vision will encode local
                            # files.
                            fixed_parts.append(part)
                        elif part.get("type") == "text":
                            fixed_parts.append(
                                {"type": "text", "text": str(part.get("text", ""))}
                            )
                        else:
                            fixed_parts.append(part)
                    else:
                        fixed_parts.append({"type": "text", "text": str(part)})
                item = dict(m)
                item["role"] = role
                item["content"] = fixed_parts
                normalized.append(item)
            else:
                item = dict(m)
                item["role"] = role
                item["content"] = str(content)
                normalized.append(item)
        return normalized

    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Extract assistant text and return with empty tool list for now."""
        if isinstance(response, str):
            return response, []
        text = self._extract_text_from_response_object(response)
        return (text or ""), []

    # Duplicate function?
    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """Count tokens using tiktoken with a default GPT-4o encoding.

        Falls back to ``cl100k_base`` and rough estimates when needed.
        """
        if not self.model_config.enable_token_counting:
            return 0
        model_for_counting = "gpt-4o"
        try:
            encoding = tiktoken.encoding_for_model(model_for_counting)
        except Exception:
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception:
                return len(str(content)) // 4

        if isinstance(content, str):
            return len(encoding.encode(content))
        if isinstance(content, dict):
            return len(encoding.encode(str(content)))
        if isinstance(content, list):
            # Approximate chat tokenization
            tokens = 3
            for m in content:
                tokens += 3
                if isinstance(m, dict):
                    for k, v in m.items():
                        if k == "content" and isinstance(v, list):
                            for item in v:
                                if (
                                    isinstance(item, dict)
                                    and item.get("type") == "text"
                                ):
                                    tokens += len(encoding.encode(item.get("text", "")))
                                elif (
                                    isinstance(item, dict)
                                    and item.get("type") == "image_url"
                                ):
                                    # Skip exact accounting for images
                                    tokens += 1300
                        else:
                            tokens += len(encoding.encode(str(v)))
                else:
                    tokens += len(encoding.encode(str(m)))
            tokens += 3
            return tokens
        return len(encoding.encode(str(content)))

    def supports_system_messages(self) -> bool:
        return True

    def supports_vision(self) -> bool:
        return True

    async def _process_messages_for_vision(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Encode local image paths in content lists into data URIs."""
        processed: List[Dict[str, Any]] = []
        for message in self.format_messages(messages):
            content = message.get("content")
            if isinstance(content, list):
                new_content: List[Dict[str, Any]] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url_obj = item.get("image_url")
                        path: Optional[str] = None
                        if isinstance(url_obj, dict) and "image_path" in url_obj:
                            path = url_obj.get("image_path")
                        elif (
                            isinstance(url_obj, dict)
                            and "url" in url_obj
                            and str(url_obj["url"]).startswith("file://")
                        ):
                            path = str(url_obj["url"])[7:]
                        # Back-compat: sometimes we get
                        # {type:"image_url", image_path:"..."}
                        if not path and "image_path" in item:
                            path = item.get("image_path")
                        if path and os.path.exists(path):
                            data_uri = await self._encode_image(path)
                            if data_uri:
                                new_content.append(
                                    {
                                        "type": "image_url",
                                        "image_url": {"url": data_uri},
                                    }
                                )
                                continue
                    new_content.append(item)
                processed.append({**message, "content": new_content})
            else:
                processed.append(message)
        return processed

    async def _encode_image(self, image_path: str) -> Optional[str]:
        """Encode an image file to a base64 data URI suitable for OpenAI."""
        try:
            from PIL import Image as PILImage  # type: ignore

            with PILImage.open(image_path) as img:
                max_size = (1024, 1024)
                resampling_namespace = getattr(PILImage, "Resampling", PILImage)
                resample_filter = getattr(
                    PILImage,
                    "LANCZOS",
                    getattr(resampling_namespace, "LANCZOS"),
                )
                img.thumbnail(max_size, resample_filter)
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG")
                image_bytes = buffer.getvalue()
            b64 = base64.b64encode(image_bytes).decode("utf-8")
            return f"data:image/jpeg;base64,{b64}"
        except Exception as e:
            logger.error(f"Failed to encode image '{image_path}': {e}")
            return None

    async def _stream_with_sdk(
        self,
        request_params: Dict[str, Any],
        stream_callback: Optional[Callable[[str], None]],
    ) -> str:
        """Stream using the official OpenAI SDK responses.stream API."""
        self._record_network_attempt()
        accumulated_content: List[str] = []
        accumulated_reasoning = ""
        completed_text = ""
        saw_completed_event = False
        started = time.monotonic()
        watchdog = self._codex_watchdog_config()
        try:
            context = self.client.responses.stream(**request_params)  # type: ignore[attr-defined]
            async with self._bounded_openai_stream_context(
                context,
                started=started,
                watchdog=watchdog,
            ) as stream:
                async for event in self._iter_openai_stream_with_watchdog(
                    stream,
                    started=started,
                    watchdog=watchdog,
                ):
                    tool_call = self._capture_responses_tool_event(event)
                    if tool_call and self._interrupt_on_tool_call():
                        self._set_last_finish_reason(FinishReason.TOOL_CALLS)

                    etype = getattr(event, "type", None)
                    provider_response_id = None
                    response_payload = getattr(event, "response", None)
                    if response_payload is not None:
                        provider_response_id = getattr(response_payload, "id", None)
                    self._update_request_lifecycle(
                        status=ProviderRequestStatus.STREAMING,
                        event_type=str(etype) if etype else None,
                        provider_response_id=provider_response_id,
                    )
                    if etype in {"error", "response.failed", "response.error"}:
                        self._raise_responses_stream_error(event)
                    if etype == "response.completed":
                        saw_completed_event = True
                        response_payload = getattr(event, "response", None)
                        self._set_last_usage(getattr(response_payload, "usage", None))
                        final_reasoning = self._extract_reasoning_from_response_object(
                            response_payload
                        )
                        if final_reasoning and not accumulated_reasoning.strip():
                            accumulated_reasoning += final_reasoning
                            self._append_reasoning(final_reasoning)
                            if stream_callback:
                                await self._safe_invoke_callback(
                                    stream_callback,
                                    final_reasoning,
                                    "reasoning",
                                    deadline=started + watchdog.total_seconds,
                                    total_timeout_seconds=watchdog.total_seconds,
                                )
                        completed_text = (
                            self._extract_text_from_response_object(response_payload)
                            or ""
                        )
                        break
                    if etype == "response.output_text.delta":
                        delta = getattr(event, "delta", "")
                        if delta:
                            accumulated_content.append(delta)
                            self._attempt_partial_output = "".join(accumulated_content)
                            if stream_callback:
                                await self._safe_invoke_callback(
                                    stream_callback,
                                    delta,
                                    "assistant",
                                    deadline=started + watchdog.total_seconds,
                                    total_timeout_seconds=watchdog.total_seconds,
                                )
                    else:
                        reasoning_delta = self._extract_reasoning_delta_from_sdk_event(
                            event
                        )
                        if (
                            reasoning_delta
                            and etype == "response.output_item.done"
                            and accumulated_reasoning.strip()
                        ):
                            reasoning_delta = ""
                        if reasoning_delta:
                            accumulated_reasoning += reasoning_delta
                            self._append_reasoning(reasoning_delta)
                        if reasoning_delta and stream_callback:
                            await self._safe_invoke_callback(
                                stream_callback,
                                reasoning_delta,
                                "reasoning",
                                deadline=started + watchdog.total_seconds,
                                total_timeout_seconds=watchdog.total_seconds,
                            )
                if not saw_completed_event:
                    output_state = (
                        "tool_call"
                        if self.has_pending_tool_call()
                        else "text"
                        if accumulated_content
                        else "empty"
                    )
                    self._raise_responses_stream_incomplete(
                        output_state,
                        partial_output="".join(accumulated_content),
                    )
        except _CodexWatchdogTimeout as exc:
            self._raise_responses_transport_error(
                exc,
                stage=exc.stage,
                partial_output="".join(accumulated_content),
            )
        except AttributeError:
            # Older SDK without responses.stream async support
            raise

        pending_tool_call = self.has_pending_tool_call()
        self._set_last_finish_reason(
            FinishReason.TOOL_CALLS if pending_tool_call else FinishReason.STOP
        )
        if completed_text and not accumulated_content and stream_callback:
            try:
                await self._safe_invoke_callback(
                    stream_callback,
                    completed_text,
                    "assistant",
                    deadline=started + watchdog.total_seconds,
                    total_timeout_seconds=watchdog.total_seconds,
                )
            except _CodexWatchdogTimeout as exc:
                self._raise_responses_transport_error(
                    exc,
                    stage=exc.stage,
                    partial_output=completed_text,
                )
        return completed_text or "".join(accumulated_content)

    async def _stream_with_http(
        self,
        request_params: Dict[str, Any],
        stream_callback: Optional[Callable[[str], None]],
    ) -> str:
        """HTTP SSE streaming fallback for the Responses API."""
        self._record_network_attempt()
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
        }
        base_url_str = (
            str(self.client.base_url)
            if self.client.base_url
            else "https://api.openai.com/v1"
        )
        url = base_url_str.rstrip("/") + "/responses"
        payload = dict(request_params)
        payload["stream"] = True

        accumulated_content: List[str] = []
        completed_text = ""
        saw_completed_event = False
        started = time.monotonic()
        watchdog = self._codex_watchdog_config()

        try:
            # Pool acquisition is part of the physical attempt and must not sit
            # outside its absolute deadline.
            pool = ConnectionPoolManager.get_instance()
            http = await self._await_with_codex_total_deadline(
                pool.get_client(base_url_str.rstrip("/")),
                started=started,
                watchdog=watchdog,
            )
            context = http.stream("POST", url, headers=headers, json=payload)
            async with self._bounded_openai_stream_context(
                context,
                started=started,
                watchdog=watchdog,
            ) as resp:
                if resp.status_code != 200:
                    body = await self._await_with_codex_total_deadline(
                        resp.aread(),
                        started=started,
                        watchdog=watchdog,
                    )
                    text = body.decode("utf-8", errors="replace")
                    error = build_llm_error(
                        message=f"Responses SSE failed {resp.status_code}: {text}",
                        provider=self.provider,
                        model=self.model_config.model,
                        status_code=resp.status_code,
                        retry_after_seconds=extract_retry_after_seconds(resp.headers),
                        provider_data={
                            "network_attempts": self.get_last_network_attempt_count(),
                        },
                    )
                    self._set_last_error(error)
                    raise LLMProviderError(error)
                async for line in self._iter_openai_stream_with_watchdog(
                    resp.aiter_lines(),
                    started=started,
                    watchdog=watchdog,
                ):
                    if not line or not line.strip():
                        continue
                    if not line.startswith("data: "):
                        continue
                    data_str = line[6:]
                    if data_str.strip() == "[DONE]":
                        break
                    try:
                        data = json.loads(data_str)
                        tool_call = self._capture_responses_tool_event(data)
                        if tool_call and self._interrupt_on_tool_call():
                            self._set_last_finish_reason(FinishReason.TOOL_CALLS)

                        etype = data.get("type")
                        if etype in {"error", "response.failed", "response.error"}:
                            self._raise_responses_stream_error(data)
                        if etype == "response.output_text.delta":
                            delta = data.get("delta", "")
                            if delta:
                                accumulated_content.append(delta)
                                self._attempt_partial_output = "".join(
                                    accumulated_content
                                )
                                if stream_callback:
                                    await self._safe_invoke_callback(
                                        stream_callback,
                                        delta,
                                        "assistant",
                                        deadline=started + watchdog.total_seconds,
                                        total_timeout_seconds=watchdog.total_seconds,
                                    )
                        elif etype == "response.output_text.done":
                            done_text = data.get("text", "")
                            if isinstance(done_text, str) and done_text:
                                completed_text = done_text
                        elif etype == "response.completed":
                            saw_completed_event = True
                            response_obj = data.get("response")
                            if isinstance(response_obj, dict):
                                self._set_last_usage(response_obj.get("usage"))
                                self._append_reasoning(
                                    self._extract_reasoning_from_response_object(
                                        response_obj
                                    )
                                )
                            extracted = self._extract_text_from_response_object(
                                response_obj
                            )
                            if extracted:
                                completed_text = extracted
                            break
                        else:
                            reasoning_delta = (
                                self._extract_reasoning_delta_from_sse_payload(data)
                            )
                            if reasoning_delta:
                                self._append_reasoning(reasoning_delta)
                            if reasoning_delta and stream_callback:
                                await self._safe_invoke_callback(
                                    stream_callback,
                                    reasoning_delta,
                                    "reasoning",
                                    deadline=started + watchdog.total_seconds,
                                    total_timeout_seconds=watchdog.total_seconds,
                                )
                    except LLMProviderError:
                        raise
                    except (json.JSONDecodeError, TypeError, ValueError):
                        continue
        except _CodexWatchdogTimeout as exc:
            self._raise_responses_transport_error(
                exc,
                stage=exc.stage,
                partial_output=completed_text or "".join(accumulated_content),
            )
        except httpx.HTTPError as exc:
            self._raise_responses_transport_error(
                exc,
                stage="stream_transport",
                partial_output=completed_text or "".join(accumulated_content),
            )
        pending_tool_call = self.has_pending_tool_call()
        if not saw_completed_event:
            output_state = (
                "tool_call"
                if pending_tool_call
                else "text"
                if completed_text or accumulated_content
                else "empty"
            )
            self._raise_responses_stream_incomplete(
                output_state,
                partial_output=completed_text or "".join(accumulated_content),
            )
        if pending_tool_call:
            self._set_last_finish_reason(FinishReason.TOOL_CALLS)
            if self._interrupt_on_tool_call():
                return completed_text or "".join(accumulated_content)
        if completed_text:
            if not pending_tool_call:
                self._set_last_finish_reason(FinishReason.STOP)
            if not accumulated_content and stream_callback:
                try:
                    await self._safe_invoke_callback(
                        stream_callback,
                        completed_text,
                        "assistant",
                        deadline=started + watchdog.total_seconds,
                        total_timeout_seconds=watchdog.total_seconds,
                    )
                except _CodexWatchdogTimeout as exc:
                    self._raise_responses_transport_error(
                        exc,
                        stage=exc.stage,
                        partial_output=completed_text,
                    )
            return completed_text
        if not pending_tool_call:
            self._set_last_finish_reason(FinishReason.STOP)
        return "".join(accumulated_content)

    async def _safe_invoke_callback(
        self,
        cb: Callable[..., Any],
        chunk: str,
        message_type: str,
        *,
        deadline: float | None = None,
        total_timeout_seconds: float | None = None,
    ) -> None:
        """Invoke provided callback safely with support for legacy signatures."""
        callback_started_at = time.monotonic()
        callback_completed = False
        callback_timeout = self._codex_watchdog_config().callback_seconds
        total_deadline_is_limit = False
        if deadline is not None:
            remaining = deadline - callback_started_at
            if remaining <= 0:
                raise _CodexWatchdogTimeout(
                    "stream_total_timeout",
                    float(total_timeout_seconds or 0.0),
                )
            total_deadline_is_limit = remaining <= callback_timeout
            callback_timeout = min(callback_timeout, remaining)
        try:
            import inspect

            if asyncio.iscoroutinefunction(cb):
                params = list(inspect.signature(cb).parameters.keys())
                callback = cast(Callable[..., Any], cb)
                if len(params) >= 2:
                    await asyncio.wait_for(
                        callback(chunk, message_type),
                        timeout=callback_timeout,
                    )
                else:
                    await asyncio.wait_for(
                        callback(chunk),
                        timeout=callback_timeout,
                    )
            else:
                loop = asyncio.get_event_loop()
                params = []
                try:
                    import inspect as _insp

                    params = list(_insp.signature(cb).parameters.keys())
                except Exception:
                    params = []
                if len(params) >= 2:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: cast(Callable[..., Any], cb)(chunk, message_type),
                        ),
                        timeout=callback_timeout,
                    )
                else:
                    await asyncio.wait_for(
                        loop.run_in_executor(
                            None,
                            lambda: cast(Callable[..., Any], cb)(chunk),
                        ),
                        timeout=callback_timeout,
                    )
            callback_completed = True
        except asyncio.TimeoutError as exc:
            if total_deadline_is_limit:
                raise _CodexWatchdogTimeout(
                    "stream_total_timeout",
                    float(total_timeout_seconds or callback_timeout),
                ) from exc
            logger.error("Stream callback exceeded %.3fs", callback_timeout)
        except Exception as e:
            logger.error(f"Error in stream callback: {e}")
        finally:
            record_runtime_duration(
                "stream.callback",
                (time.monotonic() - callback_started_at) * 1000,
            )
        if callback_completed:
            mark_runtime_progress("ui")

    def _prepare_reasoning_config(
        self,
        reasoning_config: Optional[Dict[str, Any]],
        *,
        stream: bool,
    ) -> Optional[Dict[str, Any]]:
        """Add OpenAI-specific reasoning options needed for streamed summaries."""
        if not isinstance(reasoning_config, dict):
            return reasoning_config

        prepared = dict(reasoning_config)
        effort = prepared.get("effort")
        if isinstance(effort, str) and effort.strip().lower() == "ultra":
            prepared["effort"] = "max"

        if bool(getattr(self.model_config, "reasoning_exclude", False)):
            return prepared

        if "summary" not in prepared and "generate_summary" not in prepared:
            prepared["summary"] = "auto"
        return prepared

    def _extract_reasoning_texts(self, payload: Any) -> List[str]:
        """Extract reasoning summary text from nested Responses payload shapes."""

        texts: List[str] = []
        seen: set[str] = set()

        def append(value: Any) -> None:
            text = self._coerce_reasoning_text(value)
            if not text or text in seen:
                return
            seen.add(text)
            texts.append(text)

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                append(value.get("text"))
                append(value.get("delta"))

                summary = value.get("summary")
                if isinstance(summary, list):
                    for item in summary:
                        walk(item)
                else:
                    walk(summary)

                content = value.get("content")
                if isinstance(content, list):
                    for item in content:
                        walk(item)
                else:
                    walk(content)
                return

            if isinstance(value, list):
                for item in value:
                    walk(item)
                return

            append(value)

        walk(payload)
        return texts

    def _extract_reasoning_delta_from_sdk_event(self, event: Any) -> str:
        """Extract reasoning text from OpenAI SDK stream events."""
        etype = getattr(event, "type", None)
        if etype in {
            "response.thinking.delta",
            "response.reasoning.delta",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary.delta",
        }:
            return self._coerce_reasoning_text(getattr(event, "delta", ""))

        if etype in {
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_part.done",
        }:
            return ""

        if etype == "response.output_item.done":
            item = getattr(event, "item", None)
            item_payload = self._to_dict(item)
            if item_payload.get("type") in {
                "reasoning",
                "summary",
                "reasoning_summary",
            }:
                return "".join(self._extract_reasoning_texts(item_payload))

        return ""

    def _extract_reasoning_delta_from_sse_payload(self, payload: Any) -> str:
        """Extract reasoning text from OpenAI HTTP SSE payloads."""
        if not isinstance(payload, dict):
            return ""

        etype = payload.get("type")
        if etype in {
            "response.thinking.delta",
            "response.reasoning.delta",
            "response.reasoning_summary_text.delta",
            "response.reasoning_summary.delta",
        }:
            return self._coerce_reasoning_text(payload.get("delta", ""))

        if etype in {
            "response.reasoning_summary_part.added",
            "response.reasoning_summary_part.done",
        }:
            return ""

        if etype == "response.output_item.done":
            item = payload.get("item")
            if isinstance(item, dict) and item.get("type") in {
                "reasoning",
                "summary",
                "reasoning_summary",
            }:
                return "".join(self._extract_reasoning_texts(item))

        return ""

    def _coerce_reasoning_text(self, value: Any) -> str:
        """Convert provider reasoning payloads to displayable text."""
        if isinstance(value, str):
            return value
        if isinstance(value, dict):
            for key in ("text", "summary", "content", "delta"):
                candidate = value.get(key)
                if isinstance(candidate, str) and candidate:
                    return candidate
            return ""
        if value is None:
            return ""
        text = str(value)
        return "" if text in {"", "None", "{}"} else text

    def _extract_text_from_response_object(self, resp: Any) -> str:
        """Best-effort extraction of text from a Responses API object/dict."""
        try:
            text = getattr(resp, "output_text", None)
            if isinstance(text, str):
                return text
        except Exception:
            pass
        try:
            # Handle raw dict JSON shape
            if isinstance(resp, dict):
                if "output_text" in resp and isinstance(resp["output_text"], str):
                    return resp["output_text"]
                # Attempt to drill into output/message/content
                out = resp.get("output") or resp.get("choices")
                if isinstance(out, list) and out:
                    first = out[0]
                    # message.content -> list of parts with
                    # {type:"output_text","text":...}
                    content = None
                    if isinstance(first, dict):
                        content = first.get("message", {}).get("content") or first.get(
                            "content"
                        )
                    if isinstance(content, list):
                        texts = [
                            p.get("text", "")
                            for p in content
                            if isinstance(p, dict)
                            and p.get("type") in ("output_text", "text")
                        ]
                        if texts:
                            return "".join(texts)
        except Exception:
            pass
        return ""

    def _extract_reasoning_from_response_object(self, resp: Any) -> str:
        """Best-effort extraction of reasoning text from a Responses API object/dict."""

        payload = self._to_dict(resp)
        output = payload.get("output")
        if not isinstance(output, list):
            return ""

        reasoning_parts: List[str] = []
        for item in output:
            item_payload = self._to_dict(item)
            item_type = item_payload.get("type")
            if item_type not in {"reasoning", "summary", "reasoning_summary"}:
                continue

            reasoning_parts.extend(self._extract_reasoning_texts(item_payload))

        return "".join(reasoning_parts)

    def _build_transcript_input(self, messages: List[Dict[str, Any]]) -> str:
        """Flatten chat messages to a single textual transcript for input."""
        parts: List[str] = []
        for m in self.format_messages(messages):
            role = m.get("role", "user")
            content = m.get("content", "")
            text = ""
            if isinstance(content, list):
                texts: List[str] = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        texts.append(str(item.get("text", "")))
                    elif isinstance(item, dict) and item.get("type") == "image_url":
                        texts.append("[image]")
                    else:
                        texts.append(str(item))
                text = " ".join(texts)
            else:
                text = str(content)
            prefix = (
                "User"
                if role == "user"
                else ("Assistant" if role == "assistant" else role.capitalize())
            )
            parts.append(f"{prefix}: {text}")
        return "\n".join(parts)

    def _build_input_parts(
        self, messages: List[Dict[str, Any]]
    ) -> Optional[List[Dict[str, Any]]]:
        """Return input as structured parts when images are present; otherwise None.

        Output shape example:
        [
          {
            "type": "message",
            "role": "user",
            "content": [
              {"type": "input_text", "text": "..."},
              {"type": "input_image", "image_url": "data:..."}
            ]
          }
        ]
        """
        any_image = False
        input_items: List[Dict[str, Any]] = []

        for m in self.format_messages(messages):
            role = m.get("role", "user")
            content = m.get("content", "")
            msg_parts: List[Dict[str, Any]] = []
            text_part_type = (
                "output_text"
                if str(role).strip().lower() == "assistant"
                else "input_text"
            )

            if isinstance(content, list):
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "image_url":
                        url_obj = item.get("image_url")
                        url_val = None
                        if isinstance(url_obj, dict):
                            url_val = url_obj.get("url")
                        elif isinstance(url_obj, str):
                            url_val = url_obj
                        if url_val:
                            any_image = True
                            msg_parts.append(
                                {"type": "input_image", "image_url": url_val}
                            )
                    elif isinstance(item, dict) and item.get("type") == "text":
                        txt = str(item.get("text", ""))
                        if txt:
                            msg_parts.append({"type": text_part_type, "text": txt})
                    else:
                        msg_parts.append({"type": text_part_type, "text": str(item)})
            else:
                if str(content):
                    msg_parts.append({"type": text_part_type, "text": str(content)})

            if msg_parts:
                input_items.append(
                    {"type": "message", "role": role, "content": msg_parts}
                )

        if not any_image:
            return None

        return input_items
