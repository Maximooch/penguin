from __future__ import annotations

from typing import TYPE_CHECKING, Any, Dict, Iterable, List, Optional, Union, cast

from .contracts import ErrorCategory, FinishReason, LLMError

if TYPE_CHECKING:
    from .model_config import ModelConfig


OPENAI_COMPATIBLE_PROVIDER = "openai_compatible"
OPENAI_COMPATIBLE_PROVIDER_ALIASES = {
    "openai_compatible",
    "openai-compatible",
    "openai_compat",
}
VALID_CLIENT_PREFERENCES = {"native", "litellm", "openrouter"}


def normalize_provider_name(provider: str) -> str:
    """Return a canonical internal provider identifier."""

    normalized = str(provider or "").strip().lower().replace("-", "_")
    if normalized in OPENAI_COMPATIBLE_PROVIDER_ALIASES:
        return OPENAI_COMPATIBLE_PROVIDER
    return normalized


def is_openai_compatible_provider(provider: str) -> bool:
    """Return whether the provider should use the OpenAI-compatible path."""

    return normalize_provider_name(provider) == OPENAI_COMPATIBLE_PROVIDER


def normalize_client_preference(client_preference: str) -> str:
    """Return a canonical client preference with safe defaulting."""

    normalized = str(client_preference or "").strip().lower()
    if normalized in VALID_CLIENT_PREFERENCES:
        return normalized
    return "openrouter"


def canonicalize_native_model_name(
    model: str,
    provider: str,
    client_preference: str,
) -> str:
    """Strip redundant provider prefixes for native-compatible adapters."""

    model_value = str(model or "").strip()
    if not model_value:
        return model_value

    if normalize_client_preference(client_preference) != "native":
        return model_value

    provider_name = normalize_provider_name(provider)
    if provider_name not in {"openai", "anthropic", OPENAI_COMPATIBLE_PROVIDER}:
        return model_value

    if "/" not in model_value:
        return model_value

    prefix, remainder = model_value.split("/", 1)
    remainder = remainder.strip()
    if not remainder:
        return model_value

    prefix_name = normalize_provider_name(prefix)
    if provider_name == OPENAI_COMPATIBLE_PROVIDER:
        if prefix_name in {"openai", OPENAI_COMPATIBLE_PROVIDER}:
            return remainder
        return model_value

    if prefix_name == provider_name:
        return remainder
    return model_value


def apply_model_config_transforms(model_config: "ModelConfig") -> "ModelConfig":
    """Normalize provider/client/model fields in place for handler resolution."""

    setattr(
        model_config,
        "provider",
        normalize_provider_name(str(getattr(model_config, "provider", "") or "")),
    )
    setattr(
        model_config,
        "client_preference",
        normalize_client_preference(
            str(
                getattr(model_config, "client_preference", "openrouter") or "openrouter"
            )
        ),
    )
    setattr(
        model_config,
        "model",
        canonicalize_native_model_name(
            str(getattr(model_config, "model", "") or ""),
            model_config.provider,
            model_config.client_preference,
        ),
    )
    return model_config


def normalize_finish_reason(finish_reason: Any) -> FinishReason:
    """Map provider-specific finish reasons onto the canonical enum."""

    if isinstance(finish_reason, FinishReason):
        return finish_reason

    value = str(finish_reason or "").strip().lower().replace("-", "_")
    if not value:
        return FinishReason.UNKNOWN
    if value in {"stop", "end_turn", "end", "completed", "message_stop"}:
        return FinishReason.STOP
    if value in {
        "length",
        "max_tokens",
        "max_output_tokens",
        "model_context_window_exceeded",
    }:
        return FinishReason.LENGTH
    if value in {"tool_calls", "tool_call", "tool_use"}:
        return FinishReason.TOOL_CALLS
    if value in {"content_filter", "safety", "refusal"}:
        return FinishReason.CONTENT_FILTER
    if value in {"error", "errored"}:
        return FinishReason.ERROR
    return FinishReason.UNKNOWN


def extract_retry_after_seconds(source: Any) -> Optional[float]:
    """Extract retry-after timing from headers or payload-like objects."""

    if source is None:
        return None

    if hasattr(source, "headers"):
        source = getattr(source, "headers")

    getter = getattr(source, "get", None)
    if callable(getter):
        for key in ("retry-after", "Retry-After", "x-ratelimit-reset-after"):
            raw = getter(key)
            if raw is None:
                continue
            try:
                raw_text = str(raw)
                value = float(raw_text)
            except Exception:
                continue
            if value >= 0:
                return value
    return None


def normalize_error_category(
    *,
    status_code: Optional[int] = None,
    detail: str = "",
) -> ErrorCategory:
    """Infer canonical error category from HTTP status and freeform detail."""

    detail_lower = str(detail or "").lower()

    if status_code in {401, 403}:
        return ErrorCategory.AUTH
    if status_code == 429:
        return ErrorCategory.RATE_LIMIT
    if status_code in {408, 504}:
        return ErrorCategory.TIMEOUT
    if status_code in {400, 404, 409, 422}:
        return ErrorCategory.BAD_REQUEST
    if status_code in {500, 502, 503}:
        return ErrorCategory.PROVIDER_UNAVAILABLE

    if any(
        token in detail_lower for token in {"reauth required", "missing access token"}
    ):
        return ErrorCategory.AUTH
    if "access token expired" in detail_lower:
        return ErrorCategory.AUTH
    if any(
        token in detail_lower
        for token in {"rate limit", "rate-limited", "too many requests"}
    ):
        return ErrorCategory.RATE_LIMIT
    if "request_timeout" in detail_lower or "stream_timeout" in detail_lower:
        return ErrorCategory.TIMEOUT
    if "timed out" in detail_lower or "timeout" in detail_lower:
        return ErrorCategory.TIMEOUT
    if any(
        token in detail_lower
        for token in {"connection error", "network", "could not connect"}
    ):
        return ErrorCategory.NETWORK
    if any(
        token in detail_lower for token in {"maximum context length", "requested about"}
    ):
        return ErrorCategory.BAD_REQUEST
    if "invalid_request_error" in detail_lower:
        return ErrorCategory.BAD_REQUEST
    return ErrorCategory.RUNTIME


def build_llm_error(
    *,
    message: str,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    status_code: Optional[int] = None,
    retry_after_seconds: Optional[float] = None,
    finish_reason: Optional[Union[FinishReason, str]] = None,
    provider_data: Optional[Dict[str, Any]] = None,
    category: Optional[Union[ErrorCategory, str]] = None,
    retryable: Optional[bool] = None,
) -> LLMError:
    """Build a canonical error payload with inferred defaults."""

    if isinstance(category, ErrorCategory):
        resolved_category = category
    elif isinstance(category, str) and category:
        category_aliases = {
            "upstream_request": ErrorCategory.BAD_REQUEST,
            "upstream_unavailable": ErrorCategory.PROVIDER_UNAVAILABLE,
        }
        resolved_category = category_aliases.get(category)
        if resolved_category is None:
            try:
                resolved_category = ErrorCategory(category)
            except Exception:
                resolved_category = normalize_error_category(
                    status_code=status_code,
                    detail=message,
                )
    else:
        resolved_category = normalize_error_category(
            status_code=status_code,
            detail=message,
        )

    resolved_finish_reason = (
        finish_reason
        if isinstance(finish_reason, FinishReason)
        else normalize_finish_reason(finish_reason)
        if finish_reason is not None
        else None
    )
    resolved_retryable = (
        retryable
        if retryable is not None
        else resolved_category
        in {
            ErrorCategory.RATE_LIMIT,
            ErrorCategory.TIMEOUT,
            ErrorCategory.NETWORK,
            ErrorCategory.PROVIDER_UNAVAILABLE,
        }
    )

    return LLMError(
        message=message,
        category=resolved_category,
        retryable=resolved_retryable,
        retry_after_seconds=retry_after_seconds,
        status_code=status_code,
        provider=provider,
        model=model,
        finish_reason=resolved_finish_reason,
        provider_data=dict(provider_data or {}),
    )


def normalize_openai_responses_tools(
    tools: Optional[Iterable[Dict[str, Any]]],
) -> List[Dict[str, Any]]:
    """Canonicalize Responses API tools to OpenAI's top-level function schema."""

    normalized: List[Dict[str, Any]] = []
    for raw_tool in list(tools or []):
        if not isinstance(raw_tool, dict):
            continue
        tool_type = str(raw_tool.get("type") or "").strip()
        if tool_type != "function":
            normalized.append(dict(raw_tool))
            continue

        function_payload = raw_tool.get("function")
        if isinstance(function_payload, dict):
            normalized.append(
                {
                    "type": "function",
                    "name": function_payload.get("name") or raw_tool.get("name"),
                    "description": function_payload.get("description")
                    or raw_tool.get("description", ""),
                    "parameters": function_payload.get("parameters")
                    or raw_tool.get("parameters")
                    or {"type": "object", "properties": {}},
                }
            )
            continue

        normalized.append(
            {
                "type": "function",
                "name": raw_tool.get("name"),
                "description": raw_tool.get("description", ""),
                "parameters": raw_tool.get("parameters")
                or {"type": "object", "properties": {}},
            }
        )
    return normalized


def normalize_openai_responses_tool_choice(
    tool_choice: Optional[Union[str, Dict[str, Any]]],
) -> Optional[Union[str, Dict[str, Any]]]:
    """Canonicalize Responses API tool_choice payloads."""

    if not isinstance(tool_choice, dict):
        return tool_choice

    if str(tool_choice.get("type") or "").strip() != "function":
        return dict(tool_choice)

    function_payload = tool_choice.get("function")
    if isinstance(function_payload, dict):
        normalized = dict(tool_choice)
        normalized.pop("function", None)
        normalized["name"] = function_payload.get("name") or tool_choice.get("name")
        return normalized
    return dict(tool_choice)


def should_use_openai_responses_tools(model_config: Any) -> bool:
    """Return whether the runtime should pass Responses-style tools."""

    if model_config is None:
        return False
    provider = normalize_provider_name(str(getattr(model_config, "provider", "") or ""))
    preference = normalize_client_preference(
        str(getattr(model_config, "client_preference", "") or "")
    )
    return bool(
        preference == "native" and provider in {"openai", OPENAI_COMPATIBLE_PROVIDER}
    )


__all__ = [
    "OPENAI_COMPATIBLE_PROVIDER",
    "OPENAI_COMPATIBLE_PROVIDER_ALIASES",
    "VALID_CLIENT_PREFERENCES",
    "apply_model_config_transforms",
    "build_llm_error",
    "canonicalize_native_model_name",
    "extract_retry_after_seconds",
    "is_openai_compatible_provider",
    "normalize_error_category",
    "normalize_finish_reason",
    "normalize_client_preference",
    "normalize_openai_responses_tool_choice",
    "normalize_openai_responses_tools",
    "normalize_provider_name",
    "should_use_openai_responses_tools",
]
