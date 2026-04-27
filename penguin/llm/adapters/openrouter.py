import os
import logging
import asyncio
import json
from typing import List, Dict, Optional, Any, Union, Callable, AsyncIterator

# --- Added Imports for Vision Handling ---
import base64
import io
import mimetypes
from PIL import Image as PILImage  # Use alias for PIL Image # type: ignore
# --- End Added Imports ---

import httpx  # type: ignore
import tiktoken  # type: ignore
from openai import AsyncOpenAI, APIError  # type: ignore

# Connection pooling for parallel LLM calls
from penguin.llm.api_client import ConnectionPoolManager
from penguin.llm.contracts import FinishReason, LLMError
from penguin.llm.provider_transform import (
    build_llm_error,
    extract_retry_after_seconds,
    normalize_finish_reason,
)

from ..model_config import ModelConfig

logger = logging.getLogger(__name__)

_PLACEHOLDER_OPENROUTER_KEYS = {"sk-test", "sk-or-test", "sk-or-catalog"}


class OpenRouterGateway:
    """
    A gateway to interact with the OpenRouter API using the OpenAI SDK compatibility.
    Supports configurable base_url for Link proxy integration:
    - Default: https://openrouter.ai/api/v1 (direct OpenRouter)
    - Link proxy: http://localhost:3001/api/v1 (local dev)
    - Production: https://linkplatform.ai/api/v1
    Extra headers (X-Link-*) can be injected for billing attribution.

    Handles chat completions (streaming and non-streaming) and token counting.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        site_url: Optional[str] = None,
        site_title: Optional[str] = None,
        base_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
        **kwargs: Any,
    ):
        """
        Initializes the OpenRouterGateway.

        Args:
            model_config: Configuration object for the model.
            site_url: Optional site URL for OpenRouter leaderboards ('HTTP-Referer').
            site_title: Optional site title for OpenRouter leaderboards ('X-Title').
            base_url: Optional base URL override. Defaults to OpenRouter.
                      Set to Link proxy URL for billing integration.
            extra_headers: Optional additional headers to include in requests.
                           Used for X-Link-* headers for billing attribution.
            **kwargs: Additional keyword arguments.
        """
        self.model_config = model_config
        self.logger = logging.getLogger(__name__)
        self.site_url = site_url or os.getenv("OPENROUTER_SITE_URL")
        self.site_title = site_title or os.getenv("OPENROUTER_SITE_TITLE", "Penguin")

        # Simple telemetry counters
        self._telemetry: Dict[str, Any] = {
            "interrupts": 0,
            "streamed_bytes": 0,
        }
        # Tool-call accumulation for SSE
        self._tool_call_acc: Dict[str, Any] = {"name": None, "arguments": ""}
        self._tool_call_accs: Dict[int, Dict[str, Any]] = {}
        self._pending_tool_calls: List[Dict[str, Any]] = []
        self._last_tool_call: Optional[Dict[str, Any]] = None
        self._last_usage: Dict[str, Any] = {}
        self._last_error: Optional[LLMError] = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""

        # --- Determine Base URL (before API key check) ---
        # Priority: explicit param > model_config > OpenRouter env override >
        # default OpenRouter. Do not inherit OPENAI_BASE_URL here: that can
        # point at native OpenAI/Codex or Link endpoints and break OpenRouter
        # authentication/header semantics.
        self.base_url = (
            base_url
            or model_config.api_base
            or os.getenv("OPENROUTER_BASE_URL")
            or os.getenv("PENGUIN_OPENROUTER_BASE_URL")
            or "https://openrouter.ai/api/v1"
        )

        # Check if we're using Link proxy (localhost:3001 or contains 'link')
        is_link_proxy = (
            "localhost:3001" in self.base_url
            or "127.0.0.1:3001" in self.base_url
            or "link" in self.base_url.lower()
        )

        if self.base_url != "https://openrouter.ai/api/v1":
            self.logger.info(f"Using custom base URL: {self.base_url}")

        # --- API Key Handling ---
        api_key = model_config.api_key or os.getenv("OPENROUTER_API_KEY")
        if (
            isinstance(api_key, str)
            and api_key.strip().lower() in _PLACEHOLDER_OPENROUTER_KEYS
        ):
            self.logger.warning(
                "Ignoring placeholder OpenRouter API key from runtime configuration"
            )
            api_key = None
        if not api_key and not is_link_proxy:
            # Only require API key for direct OpenRouter access
            self.logger.error(
                "OpenRouter API key not found in model_config or OPENROUTER_API_KEY env var."
            )
            raise ValueError("Missing OpenRouter API Key.")

        # For Link proxy without API key, use a placeholder (Link handles auth)
        if not api_key and is_link_proxy:
            api_key = "link-proxy-placeholder"

        # --- Initialize OpenAI Client for OpenRouter ---
        try:
            self.client = AsyncOpenAI(
                base_url=self.base_url,
                api_key=api_key,
            )
            self.logger.info(
                f"OpenRouterGateway initialized for model: {model_config.model} at {self.base_url}"
            )
            self.logger.info(
                f"Site URL: {self.site_url}, Site Title: {self.site_title}"
            )

        except Exception as e:
            self.logger.error(
                f"Failed to initialize AsyncOpenAI client for OpenRouter: {e}",
                exc_info=True,
            )
            raise ValueError(f"Could not initialize OpenRouter client: {e}") from e

        # --- Prepare Headers ---
        self.extra_headers: Dict[str, str] = {}

        # Add site headers for OpenRouter leaderboards
        if self.site_url:
            self.extra_headers["HTTP-Referer"] = self.site_url
        if self.site_title:
            self.extra_headers["X-Title"] = self.site_title

        # Merge in any additional headers (e.g., X-Link-* for billing)
        if extra_headers:
            self.extra_headers.update(extra_headers)
            self.logger.info(f"Added {len(extra_headers)} extra headers for requests")

        if self.extra_headers:
            self.logger.debug(
                f"Request headers configured: {list(self.extra_headers.keys())}"
            )

    def _stream_timeout_seconds(self, env_name: str, default: float) -> float:
        """Read a positive streaming timeout from the environment."""
        raw_value = os.getenv(env_name)
        if not isinstance(raw_value, str) or not raw_value.strip():
            return default
        try:
            parsed = float(raw_value.strip())
        except Exception:
            self.logger.warning(
                "Invalid %s=%r; using default timeout %ss",
                env_name,
                raw_value,
                default,
            )
            return default
        if parsed <= 0:
            self.logger.warning(
                "Non-positive %s=%r; using default timeout %ss",
                env_name,
                raw_value,
                default,
            )
            return default
        return parsed

    def _stream_chunk_timeout_seconds(self) -> float:
        """Return maximum wait for the next streaming chunk."""
        return self._stream_timeout_seconds(
            "PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS",
            75.0,
        )

    def _stream_total_timeout_seconds(self) -> float:
        """Return maximum total duration for one streaming response."""
        return self._stream_timeout_seconds(
            "PENGUIN_OPENROUTER_STREAM_TOTAL_TIMEOUT_SECONDS",
            300.0,
        )

    async def _next_stream_item(
        self,
        iterator: AsyncIterator[Any],
        *,
        wait_timeout: float,
        total_timeout: float,
        started_at: float,
        phase: str,
    ) -> Any:
        """Wait for the next stream item with chunk and total timeout guards."""
        elapsed = asyncio.get_running_loop().time() - started_at
        remaining_total = max(total_timeout - elapsed, 0.0)
        if remaining_total <= 0:
            raise TimeoutError(
                f"{phase} exceeded total timeout after {total_timeout:.1f}s"
            )
        effective_timeout = min(wait_timeout, remaining_total)
        return await asyncio.wait_for(iterator.__anext__(), timeout=effective_timeout)

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

    def _to_int(self, value: Any) -> int:
        try:
            parsed = int(value)
        except Exception:
            return 0
        return max(parsed, 0)

    def _to_float(self, value: Any) -> float:
        try:
            parsed = float(value)
        except Exception:
            return 0.0
        return parsed if parsed > 0 else 0.0

    def _normalize_usage(self, usage: Any) -> Dict[str, Any]:
        payload = self._to_dict(usage)
        if not payload:
            return {}

        prompt_details = self._to_dict(payload.get("prompt_tokens_details"))
        completion_details = self._to_dict(payload.get("completion_tokens_details"))
        cache_read = self._to_int(
            prompt_details.get("cached_tokens")
            or payload.get("input_cache_read_tokens")
        )
        cache_write = self._to_int(payload.get("input_cache_write_tokens"))
        reasoning_tokens = self._to_int(
            completion_details.get("reasoning_tokens")
            or payload.get("reasoning_tokens")
        )
        cost = self._to_float(
            payload.get("cost")
            or payload.get("total_cost")
            or payload.get("total_cost_usd")
            or payload.get("usd")
        )
        return {
            "input_tokens": self._to_int(payload.get("prompt_tokens")),
            "output_tokens": self._to_int(payload.get("completion_tokens")),
            "reasoning_tokens": reasoning_tokens,
            "cache_read_tokens": cache_read,
            "cache_write_tokens": cache_write,
            "total_tokens": self._to_int(payload.get("total_tokens")),
            "cost": cost,
        }

    def _set_last_usage(self, usage: Any) -> None:
        normalized = self._normalize_usage(usage)
        if normalized:
            self._last_usage = normalized

    def _log_last_usage(self, phase: str) -> None:
        usage = self._last_usage if isinstance(self._last_usage, dict) else {}
        uvicorn_logger = logging.getLogger("uvicorn.error")
        if not usage:
            message = "[OpenRouterGateway] No usage data captured (%s)"
            args = (phase,)
            self.logger.info(message, *args)
            if uvicorn_logger is not self.logger:
                uvicorn_logger.info(message, *args)
            return
        message = (
            "[OpenRouterGateway] Usage (%s): input=%s output=%s reasoning=%s "
            "cache_read=%s cache_write=%s total=%s cost=%s"
        )
        args = (
            phase,
            usage.get("input_tokens", 0),
            usage.get("output_tokens", 0),
            usage.get("reasoning_tokens", 0),
            usage.get("cache_read_tokens", 0),
            usage.get("cache_write_tokens", 0),
            usage.get("total_tokens", 0),
            usage.get("cost", 0.0),
        )
        self.logger.info(message, *args)
        if uvicorn_logger is not self.logger:
            uvicorn_logger.info(message, *args)

    def _set_last_error(self, error: Optional[LLMError]) -> None:
        self._last_error = error

    def get_last_error(self) -> Optional[LLMError]:
        return self._last_error if isinstance(self._last_error, LLMError) else None

    def _set_last_finish_reason(self, finish_reason: Any) -> FinishReason:
        self._last_finish_reason = normalize_finish_reason(finish_reason)
        return self._last_finish_reason

    def get_last_finish_reason(self) -> FinishReason:
        return self._last_finish_reason

    def _append_reasoning(self, text: Any) -> None:
        if isinstance(text, str) and text:
            self._last_reasoning += text

    def get_last_reasoning(self) -> str:
        return self._last_reasoning

    def _record_error(
        self,
        *,
        message: str,
        status_code: Optional[int] = None,
        retry_after_seconds: Optional[float] = None,
        finish_reason: Any = None,
        provider_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._set_last_error(
            build_llm_error(
                message=message,
                provider="openrouter",
                model=self.model_config.model,
                status_code=status_code,
                retry_after_seconds=retry_after_seconds,
                finish_reason=finish_reason,
                provider_data=provider_data,
            )
        )

    def _tool_call_payload(self, tool_call: Any) -> Dict[str, Any]:
        payload = tool_call if isinstance(tool_call, dict) else {}
        if not payload and tool_call is not None:
            try:
                payload = vars(tool_call)
            except Exception:
                payload = {}
        return payload if isinstance(payload, dict) else {}

    def _function_payload(self, tool_call: Any) -> Dict[str, Any]:
        payload = self._tool_call_payload(tool_call)
        function_payload = payload.get("function")
        if function_payload is None and tool_call is not None:
            function_payload = getattr(tool_call, "function", None)
        if isinstance(function_payload, dict):
            return function_payload
        try:
            return vars(function_payload) if function_payload is not None else {}
        except Exception:
            return {}

    def _remember_tool_call(
        self,
        *,
        call_id: Optional[str],
        name: Optional[str],
        arguments: str,
        item_id: Optional[str] = None,
    ) -> None:
        if not name:
            return
        if not hasattr(self, "_pending_tool_calls"):
            self._pending_tool_calls = []
        remembered = {
            "item_id": item_id,
            "call_id": call_id,
            "name": name,
            "arguments": arguments or "",
        }
        existing_index = next(
            (
                index
                for index, pending in enumerate(self._pending_tool_calls)
                if call_id and pending.get("call_id") == call_id
            ),
            None,
        )
        if existing_index is None:
            self._pending_tool_calls.append(remembered)
        else:
            self._pending_tool_calls[existing_index] = remembered
        self._last_tool_call = remembered
        self._set_last_finish_reason(FinishReason.TOOL_CALLS)

    def _store_tool_call(self, tool_call: Any) -> None:
        tool_calls = (
            list(tool_call)
            if isinstance(tool_call, (list, tuple))
            else [tool_call]
            if tool_call is not None
            else []
        )
        for current_call in tool_calls:
            payload = self._tool_call_payload(current_call)
            function_payload = self._function_payload(current_call)
            name = function_payload.get("name")
            arguments = function_payload.get("arguments") or ""
            call_id = payload.get("id")
            if not call_id and current_call is not None:
                call_id = getattr(current_call, "id", None)
            item_id = payload.get("id") if isinstance(payload, dict) else None
            self._remember_tool_call(
                call_id=call_id,
                item_id=item_id,
                name=name,
                arguments=arguments,
            )
            if name:
                self._tool_call_acc = {
                    "name": name,
                    "arguments": arguments,
                    "call_id": call_id,
                }

    def _record_tool_call_delta(self, tool_calls_delta: Any) -> None:
        if not hasattr(self, "_tool_call_accs"):
            self._tool_call_accs = {}
        tool_calls = (
            list(tool_calls_delta)
            if isinstance(tool_calls_delta, (list, tuple))
            else [tool_calls_delta]
            if tool_calls_delta is not None
            else []
        )
        for offset, current_call in enumerate(tool_calls):
            payload = self._tool_call_payload(current_call)
            index = payload.get("index")
            if index is None and current_call is not None:
                index = getattr(current_call, "index", None)
            try:
                call_index = int(index)
            except Exception:
                call_index = offset

            acc = self._tool_call_accs.setdefault(
                call_index, {"name": None, "arguments": "", "call_id": None}
            )
            function_payload = self._function_payload(current_call)
            name = function_payload.get("name")
            arguments_delta = function_payload.get("arguments")
            call_id = payload.get("id")
            if not call_id and current_call is not None:
                call_id = getattr(current_call, "id", None)
            if call_id:
                acc["call_id"] = call_id
            if name:
                acc["name"] = name
            if isinstance(arguments_delta, str):
                acc["arguments"] = str(acc.get("arguments") or "") + arguments_delta

            if acc.get("name"):
                self._remember_tool_call(
                    call_id=acc.get("call_id"),
                    name=acc.get("name"),
                    arguments=str(acc.get("arguments") or ""),
                )

    def _finalize_stream_tool_calls(self) -> None:
        for acc in self._tool_call_accs.values():
            self._remember_tool_call(
                call_id=acc.get("call_id"),
                name=acc.get("name"),
                arguments=str(acc.get("arguments") or ""),
            )

    def _extract_generation_id_from_headers(self, headers: Any) -> Optional[str]:
        """Extract OpenRouter generation id from response headers."""
        if headers is None:
            return None
        key_candidates = {
            "x-openrouter-generation-id",
            "openrouter-generation-id",
            "x-generation-id",
            "generation-id",
        }
        getter = getattr(headers, "get", None)
        if callable(getter):
            for key in key_candidates:
                for probe in (key, key.upper(), key.title()):
                    raw_value = getter(probe)
                    if isinstance(raw_value, str) and raw_value.strip():
                        return raw_value.strip()
        return None

    def _extract_generation_id_from_chunk(self, data: Any) -> Optional[str]:
        """Extract OpenRouter generation id from streamed chunk payload."""
        payload = self._to_dict(data)
        if not payload:
            return None
        for key in ("generation_id", "generationID", "id"):
            raw_value = payload.get(key)
            if not isinstance(raw_value, str):
                continue
            value = raw_value.strip()
            if value.startswith("gen-"):
                return value
        metadata = self._to_dict(payload.get("metadata"))
        raw_meta_generation = metadata.get("generation_id")
        if isinstance(raw_meta_generation, str):
            value = raw_meta_generation.strip()
            if value.startswith("gen-"):
                return value
        return None

    def _usage_from_generation_payload(self, payload: Any) -> Dict[str, Any]:
        """Normalize usage payload from OpenRouter GET /generation response."""
        root = self._to_dict(payload)
        data = self._to_dict(root.get("data"))
        if not data:
            return {}

        input_tokens = self._to_int(
            data.get("tokens_prompt") or data.get("native_tokens_prompt")
        )
        output_tokens = self._to_int(
            data.get("tokens_completion") or data.get("native_tokens_completion")
        )
        reasoning_tokens = self._to_int(data.get("native_tokens_reasoning"))
        cache_read_tokens = self._to_int(data.get("native_tokens_cached"))
        total_tokens = self._to_int(data.get("total_tokens"))
        if total_tokens <= 0:
            total_tokens = input_tokens + output_tokens

        raw_cost = data.get("usage")
        if raw_cost is None:
            raw_cost = data.get("total_cost")

        usage_payload = {
            "prompt_tokens": input_tokens,
            "completion_tokens": output_tokens,
            "reasoning_tokens": reasoning_tokens,
            "input_cache_read_tokens": cache_read_tokens,
            "input_cache_write_tokens": 0,
            "total_tokens": total_tokens,
            "cost": raw_cost,
        }
        has_signal = (
            input_tokens > 0
            or output_tokens > 0
            or reasoning_tokens > 0
            or cache_read_tokens > 0
            or total_tokens > 0
            or raw_cost is not None
        )
        return usage_payload if has_signal else {}

    async def _recover_usage_from_generation(
        self,
        client: httpx.AsyncClient,
        headers: Dict[str, str],
        generation_id: Optional[str],
        phase: str,
    ) -> bool:
        """Recover usage metadata after intentional early stream interruption."""
        generation = (
            generation_id.strip()
            if isinstance(generation_id, str) and generation_id.strip()
            else ""
        )
        if not generation:
            self.logger.info(
                "[OpenRouterGateway] Usage recovery skipped (%s): missing generation id",
                phase,
            )
            return False

        authorization = headers.get("Authorization", "")
        if not isinstance(authorization, str) or not authorization.strip():
            self.logger.info(
                "[OpenRouterGateway] Usage recovery skipped (%s): missing authorization",
                phase,
            )
            return False

        request_headers = {"Authorization": authorization.strip()}
        for header_name in ("HTTP-Referer", "X-Title"):
            header_value = headers.get(header_name)
            if isinstance(header_value, str) and header_value.strip():
                request_headers[header_name] = header_value.strip()

        endpoint = f"{self.base_url}/generation"
        for attempt in (1, 2):
            try:
                timeout = httpx.Timeout(0.25, connect=0.1, read=0.2, write=0.1)
                response = await client.get(
                    endpoint,
                    headers=request_headers,
                    params={"id": generation},
                    timeout=timeout,
                )
            except Exception as exc:
                self.logger.debug(
                    "[OpenRouterGateway] Usage recovery request failed (%s attempt=%s generation=%s): %s",
                    phase,
                    attempt,
                    generation,
                    exc,
                    exc_info=True,
                )
                if attempt == 1:
                    await asyncio.sleep(0.05)
                continue

            if response.status_code != 200:
                self.logger.debug(
                    "[OpenRouterGateway] Usage recovery response not ready (%s attempt=%s generation=%s status=%s)",
                    phase,
                    attempt,
                    generation,
                    response.status_code,
                )
                if attempt == 1:
                    await asyncio.sleep(0.05)
                continue

            try:
                payload = response.json() if response.content else {}
            except Exception as exc:
                self.logger.debug(
                    "[OpenRouterGateway] Usage recovery JSON parse failed (%s attempt=%s generation=%s): %s",
                    phase,
                    attempt,
                    generation,
                    exc,
                    exc_info=True,
                )
                if attempt == 1:
                    await asyncio.sleep(0.05)
                continue
            usage_payload = self._usage_from_generation_payload(payload)
            if usage_payload:
                self._set_last_usage(usage_payload)
                if self._last_usage:
                    self._log_last_usage(f"{phase}-recovered")
                    return True

            if attempt == 1:
                await asyncio.sleep(0.05)

        self.logger.info(
            "[OpenRouterGateway] Usage recovery unavailable (%s generation=%s)",
            phase,
            generation,
        )
        return False

    def _parse_openrouter_error(
        self,
        error_text: str,
        status_code: int,
        *,
        retry_after_seconds: Optional[float] = None,
    ) -> str:
        """
        Parse OpenRouter error response and return a user-friendly message.

        OpenRouter errors typically come as JSON with structure:
        {"error": {"message": "...", "code": ..., "metadata": {"provider_name": "..."}}}
        """
        try:
            error_data = json.loads(error_text)
            error_info = error_data.get("error", {})

            # Extract error details
            error_message = error_info.get("message", "Unknown error")
            error_code = error_info.get("code", status_code)
            metadata = error_info.get("metadata", {})
            provider_name = metadata.get("provider_name", "unknown provider")

            # Build user-friendly message based on error type
            if status_code == 400:
                # Bad request - often model/parameter issues
                if (
                    "context" in error_message.lower()
                    or "token" in error_message.lower()
                ):
                    message = f"[Error: Context too large for {provider_name}. {error_message}]"
                elif "model" in error_message.lower():
                    message = f"[Error: Model issue ({provider_name}). {error_message}]"
                else:
                    message = (
                        f"[Error: Bad request to {provider_name}. {error_message}]"
                    )

            elif status_code == 401:
                message = f"[Error: Authentication failed. Check your API key. {error_message}]"

            elif status_code == 402:
                message = (
                    f"[Error: Insufficient credits/payment required. {error_message}]"
                )

            elif status_code == 403:
                message = f"[Error: Access denied to {provider_name}. {error_message}]"

            elif status_code == 404:
                message = f"[Error: Model not found. {error_message}]"

            elif status_code == 429:
                # Rate limit - include retry info if available
                message = (
                    f"[Error: Rate limit exceeded ({provider_name}). {error_message}]"
                )

            elif status_code == 502 or status_code == 503:
                message = f"[Error: {provider_name} is temporarily unavailable. {error_message}]"

            elif status_code == 504:
                message = f"[Error: Request to {provider_name} timed out. Try again or use a different model.]"

            else:
                # Generic error with all available info
                message = (
                    f"[Error: {provider_name} returned {error_code}. {error_message}]"
                )

            self._record_error(
                message=error_message,
                status_code=status_code,
                retry_after_seconds=retry_after_seconds,
                provider_data={
                    "provider_name": provider_name,
                    "error_code": error_code,
                },
            )
            return message

        except json.JSONDecodeError:
            # Not JSON, return raw text (truncated)
            truncated = (
                error_text[:200] + "..." if len(error_text) > 200 else error_text
            )
            self._record_error(
                message=truncated,
                status_code=status_code,
                retry_after_seconds=retry_after_seconds,
            )
            return f"[Error: API returned status {status_code}. {truncated}]"
        except Exception as e:
            self.logger.warning(f"Failed to parse error response: {e}")
            self._record_error(
                message=f"API call failed with status {status_code}",
                status_code=status_code,
                retry_after_seconds=retry_after_seconds,
            )
            return f"[Error: API call failed with status {status_code}]"

    async def _encode_image(self, image_path: str) -> Optional[str]:
        """Encodes an image file to a base64 data URI."""
        if not os.path.exists(image_path):
            self.logger.error(f"Image path does not exist: {image_path}")
            return None
        try:
            logger.debug(f"Encoding image from path: {image_path}")
            with PILImage.open(image_path) as img:
                max_size = (1024, 1024)  # Configurable?
                resampling_namespace = getattr(PILImage, "Resampling", PILImage)
                img.thumbnail(
                    max_size,
                    getattr(
                        PILImage, "LANCZOS", getattr(resampling_namespace, "LANCZOS")
                    ),
                )
                if img.mode != "RGB":
                    img = img.convert("RGB")
                buffer = io.BytesIO()
                img.save(buffer, format="JPEG")  # Use JPEG for efficiency
                image_bytes = buffer.getvalue()

            base64_image = base64.b64encode(image_bytes).decode("utf-8")
            mime_type, _ = mimetypes.guess_type(image_path)
            if not mime_type or not mime_type.startswith("image"):
                mime_type = "image/jpeg"
            data_uri = f"data:{mime_type};base64,{base64_image}"
            self.logger.debug(f"Encoded image to data URI (length: {len(data_uri)})")
            return data_uri
        except FileNotFoundError:
            self.logger.error(f"Image file not found during encoding: {image_path}")
            return None
        except Exception as e:
            self.logger.error(f"Error encoding image {image_path}: {e}", exc_info=True)
            return None

    async def _process_messages_for_vision(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """Processes messages to encode images specified by 'image_path'."""
        processed_messages = []
        for message in messages:
            if isinstance(message.get("content"), list):
                new_content = []
                image_processed = False
                for item in message["content"]:
                    if (
                        isinstance(item, dict)
                        and item.get("type") == "image_url"
                        and "image_path" in item
                    ):
                        image_path = item["image_path"]
                        data_uri = await self._encode_image(image_path)
                        if data_uri:
                            # Replace item with OpenAI format
                            new_content.append(
                                {"type": "image_url", "image_url": {"url": data_uri}}
                            )
                            image_processed = True
                        else:
                            # Failed to encode, maybe add a text note?
                            new_content.append(
                                {
                                    "type": "text",
                                    "text": f"[Error: Could not load image at {image_path}]",
                                }
                            )
                    else:
                        # Keep other content parts as is
                        new_content.append(item)

                # If an image was processed, update the message content
                if image_processed:
                    processed_messages.append({**message, "content": new_content})
                else:
                    # No image processed, keep original message
                    processed_messages.append(message)
            else:
                # Not a list content, keep message as is
                processed_messages.append(message)
        return processed_messages

    def _contains_penguin_action_tags(self, content: str) -> bool:
        """
        Check if content contains any Penguin action tags using the same logic as parser.py
        """
        try:
            # Import here to avoid circular imports
            from penguin.utils.parser import ActionType
            import re

            # Generate pattern from ActionType enum (exactly like parser.py does)
            action_tag_pattern = "|".join(
                [action_type.value for action_type in ActionType]
            )
            # Use same regex pattern as parser: full tag pairs only, case-insensitive but strict
            action_tag_regex = f"<({action_tag_pattern})>.*?</\\1>"

            return bool(re.search(action_tag_regex, content, re.DOTALL | re.IGNORECASE))
        except ImportError:
            # Fallback to basic check if import fails
            return any(
                f"<{tag}>" in content.lower() and f"</{tag}>" in content.lower()
                for tag in ["execute", "search", "memory_search"]
            )

    def _clean_conversation_format(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Reformat conversation to be compatible with OpenAI SDK while preserving all content.

        Preserve valid tool continuity for OpenRouter while repairing obviously
        malformed tool context that can trigger SDK validation errors.
        """
        reformatted_messages = []

        for message in messages:
            reformatted_message = message.copy()

            # Handle content field
            if isinstance(message.get("content"), str):
                content = message["content"]

                # Clean up orphaned tool call references that could cause validation errors
                if "call_" in content and ("tool_calls" not in message):
                    # Replace call_id references with plain text to avoid SDK validation
                    import re

                    content = re.sub(
                        r"call_[a-zA-Z0-9_-]+", "[tool-call-reference]", content
                    )
                    self.logger.debug("Reformatted tool call references in message")

                # Check for XML action tags - they're Penguin's tool system and should be preserved
                if self._contains_penguin_action_tags(content):
                    self.logger.debug(
                        f"Preserving Penguin XML action tags in message: {content[:100]}..."
                    )

                reformatted_message["content"] = content

            if message.get("role") == "assistant" and "tool_calls" in message:
                tool_calls = message.get("tool_calls")
                valid_tool_calls = isinstance(tool_calls, list) and all(
                    isinstance(tool_call, dict)
                    and isinstance(tool_call.get("function"), dict)
                    and str(tool_call.get("id") or "").strip()
                    and str(tool_call.get("function", {}).get("name") or "").strip()
                    for tool_call in tool_calls
                )
                if valid_tool_calls:
                    self.logger.debug(
                        "Preserving assistant tool_calls for OpenRouter continuity"
                    )
                    reformatted_message = {
                        "role": "assistant",
                        "content": message.get("content", ""),
                        "tool_calls": tool_calls,
                    }
                    for key, value in message.items():
                        if key not in ["role", "content", "tool_calls"]:
                            reformatted_message[key] = value
                else:
                    self.logger.debug(
                        "Flattening malformed assistant tool_calls to plain text"
                    )
                    reformatted_message = {
                        "role": "assistant",
                        "content": message.get("content", ""),
                    }
                    for key, value in message.items():
                        if key not in ["role", "content", "tool_calls"]:
                            reformatted_message[key] = value

            elif message.get("role") == "tool":
                tool_call_id = str(message.get("tool_call_id") or "").strip()
                if tool_call_id:
                    self.logger.debug(
                        "Preserving tool message with tool_call_id for OpenRouter continuity"
                    )
                    reformatted_message = {
                        "role": "tool",
                        "tool_call_id": tool_call_id,
                        "content": message.get("content", ""),
                    }
                else:
                    self.logger.debug(
                        "Flattening malformed tool message without tool_call_id"
                    )
                    reformatted_message = {
                        "role": "user",
                        "content": message.get("content", ""),
                    }
                    for key, value in message.items():
                        if key not in ["role", "content", "tool_call_id"]:
                            reformatted_message[key] = value

            reformatted_messages.append(reformatted_message)

        self.logger.debug(
            f"Reformatted conversation: {len(messages)} messages processed for OpenRouter compatibility"
        )
        return reformatted_messages

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: Optional[bool] = None,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,  # Allow passing other params like tools, tool_choice
    ) -> str:
        """
        Gets a chat completion response from OpenRouter.

        Args:
            messages: List of message dictionaries (OpenAI format).
            max_output_tokens: Optional max output tokens for the response.
            temperature: Optional sampling temperature.
            stream: Whether to stream the response. If None, uses model_config default.
            stream_callback: Callback function for handling streaming chunks (required if stream=True).
            **kwargs: Additional parameters to pass to the OpenAI `create` call (e.g., 'tools', 'tool_choice').

        Returns:
            The complete response text content.
            Returns an error string "[Error: ...]" if an API call fails.
        """
        # # Initialize debug session
        # debug_config = {
        #     'model': self.model_config.model,
        #     'provider': 'openrouter',
        #     'streaming': stream if stream is not None else self.model_config.streaming_enabled,
        #     'reasoning_enabled': bool(self.model_config.get_reasoning_config()),
        #     'temperature': temperature if temperature is not None else self.model_config.temperature,
        #     'max_tokens': max_tokens or self.model_config.max_tokens
        # }
        # request_id = debug_request(messages, debug_config, "openrouter_completion")

        # self.logger.info(f"[OpenRouterGateway] ENTERING get_response [{request_id}]: stream_arg={stream}, stream_callback_arg={stream_callback}, model_config_streaming={self.model_config.streaming_enabled}")
        self._last_usage = {}
        self._last_error = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_tool_call = None
        self._tool_call_acc = {"name": None, "arguments": ""}
        self._tool_call_accs = {}
        self._pending_tool_calls = []

        # Determine if streaming should be used *based on the passed flag first*
        # If stream is explicitly False, don't stream, even if config says yes.
        # If stream is explicitly True, try to stream.
        # If stream is None, fall back to config.
        use_streaming = (
            stream if stream is not None else self.model_config.streaming_enabled
        )

        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        # If streaming is decided but no callback is provided, log warning and disable
        if use_streaming and stream_callback is None:
            self.logger.warning(
                "Streaming requested/configured but no stream_callback provided. Falling back to non-streaming mode."
            )
            use_streaming = False

        # --- Process messages for vision and reformat conversation ---
        try:
            processed_messages = await self._process_messages_for_vision(messages)
            # Reformat conversation to be compatible with OpenAI SDK while preserving content
            processed_messages = self._clean_conversation_format(processed_messages)
        except Exception as e:
            # error_context = {'request_id': request_id, 'phase': 'vision_processing', 'messages_count': len(messages)}
            # debug_error(e, error_context)
            self.logger.error(
                f"Error processing messages for vision and conversation format: {e}",
                exc_info=True,
            )
            self._record_error(
                message=f"Failed to process message content - {str(e)}",
            )
            return f"[Error: Failed to process message content - {str(e)}]"
        # --- End vision and conversation processing ---

        # --- Reasoning tokens configuration ---
        reasoning_config = self.model_config.get_reasoning_config()

        request_params = {
            "model": self.model_config.model,
            "messages": processed_messages,  # Use processed messages
            "max_tokens": max_output_tokens or self.model_config.max_output_tokens,
            "temperature": temperature
            if temperature is not None
            else self.model_config.temperature,
            "stream": use_streaming,
            "extra_headers": self.extra_headers,
            **kwargs,  # Pass through other arguments like tools
        }

        if use_streaming:
            raw_stream_options = request_params.get("stream_options")
            stream_options = (
                dict(raw_stream_options) if isinstance(raw_stream_options, dict) else {}
            )
            stream_options["include_usage"] = True
            request_params["stream_options"] = stream_options

        # Add new unified reasoning parameter if reasoning is enabled
        if reasoning_config:
            # Use new unified reasoning format instead of include_reasoning
            if isinstance(reasoning_config, dict):
                request_params["reasoning"] = reasoning_config
                self.logger.info(
                    f"[OpenRouterGateway] Using new reasoning config: {reasoning_config}"
                )
            else:
                # Fallback to simple enabled format for backwards compatibility
                request_params["reasoning"] = {"enabled": True}
                self.logger.info(
                    "[OpenRouterGateway] Using basic reasoning config with enabled=True"
                )

        # Handle reasoning configuration - always use direct API for reasoning
        use_direct_api = bool(reasoning_config)
        if reasoning_config:
            self.logger.info(
                "[OpenRouterGateway] Reasoning enabled, will use direct API call to bypass SDK limitations"
            )

        # Filter out None values for cleaner API calls
        request_params = {k: v for k, v in request_params.items() if v is not None}

        self.logger.debug(
            f"Calling OpenRouter chat completion with params: "
            f"model={request_params.get('model')}, "
            f"stream={use_streaming}, "
            f"max_tokens={request_params.get('max_tokens')}, "
            f"temp={request_params.get('temperature')}, "
            f"headers={request_params.get('extra_headers')}, "
            f"reasoning={request_params.get('reasoning')}, "
            f"other_keys={list(kwargs.keys())}"
        )
        reasoning_payload = request_params.get("reasoning")
        reasoning_log = (
            "[OpenRouterGateway] Reasoning payload model=%s stream=%s payload=%s "
            "enabled=%s supports=%s effort=%s max_tokens=%s exclude=%s"
        )
        reasoning_args = (
            request_params.get("model"),
            use_streaming,
            reasoning_payload if isinstance(reasoning_payload, dict) else None,
            bool(getattr(self.model_config, "reasoning_enabled", False)),
            getattr(self.model_config, "supports_reasoning", None),
            getattr(self.model_config, "reasoning_effort", None),
            getattr(self.model_config, "reasoning_max_tokens", None),
            bool(getattr(self.model_config, "reasoning_exclude", False)),
        )
        self.logger.info(reasoning_log, *reasoning_args)
        uvicorn_logger = logging.getLogger("uvicorn.error")
        if uvicorn_logger is not self.logger:
            uvicorn_logger.info(reasoning_log, *reasoning_args)

        full_response_content = ""
        full_reasoning_content = ""

        # Use direct API call if reasoning is enabled to avoid SDK compatibility issues
        if use_direct_api:
            self.logger.debug(
                "[OpenRouterGateway] Using direct API call for reasoning support"
            )
            return await self._direct_api_call_with_reasoning(
                request_params, reasoning_config, use_streaming, stream_callback
            )

        # Use OpenAI SDK for non-reasoning requests
        try:
            completion = await self.client.chat.completions.create(**request_params)
        except Exception:
            raise

        try:
            if use_streaming:
                # self.logger.info(f"[OpenRouterGateway] Starting stream processing loop [{request_id}].")
                # debug_stream_start(request_id, debug_config)
                chunk_index = 0
                stream_started_at = asyncio.get_running_loop().time()
                chunk_timeout_seconds = self._stream_chunk_timeout_seconds()
                total_timeout_seconds = self._stream_total_timeout_seconds()
                # Separate accumulators for reasoning and content
                _gateway_accumulated_reasoning = ""
                _gateway_accumulated_content = ""
                reasoning_phase_complete = False
                # Track finish_reason for error and truncation detection
                sdk_last_finish_reason: Optional[str] = None
                sdk_stream_error: Optional[Dict[str, Any]] = None
                completion_iter = completion.__aiter__()

                while True:
                    try:
                        chunk = await self._next_stream_item(
                            completion_iter,
                            wait_timeout=chunk_timeout_seconds,
                            total_timeout=total_timeout_seconds,
                            started_at=stream_started_at,
                            phase="OpenRouter SDK stream",
                        )
                    except StopAsyncIteration:
                        break
                    except TimeoutError as exc:
                        self.logger.warning(
                            "[OpenRouterGateway] SDK stream stalled model=%s chunk_timeout=%ss total_timeout=%ss detail=%s",
                            self.model_config.model,
                            chunk_timeout_seconds,
                            total_timeout_seconds,
                            exc,
                        )
                        return (
                            f"[Error: OpenRouter stream stalled for {self.model_config.model}. "
                            "No chunks were received before timeout. Try again or switch models.]"
                        )

                    self._set_last_usage(getattr(chunk, "usage", None))
                    raw_choices = getattr(chunk, "choices", None)
                    choice = (
                        raw_choices[0]
                        if isinstance(raw_choices, (list, tuple)) and raw_choices
                        else None
                    )
                    if choice is None:
                        self.logger.debug(
                            "[OpenRouterGateway] SDK chunk %s had no choices payload",
                            chunk_index,
                        )
                        chunk_index += 1
                        continue

                    chunk_finish_reason = (
                        choice.get("finish_reason")
                        if isinstance(choice, dict)
                        else getattr(choice, "finish_reason", None)
                    )
                    if chunk_finish_reason:
                        sdk_last_finish_reason = chunk_finish_reason
                        self._set_last_finish_reason(chunk_finish_reason)
                        self.logger.debug(
                            f"[OpenRouterGateway] SDK stream finish_reason: {chunk_finish_reason}"
                        )

                        # Handle mid-stream errors (finish_reason: 'error')
                        if chunk_finish_reason == "error":
                            # Try to extract error info from the chunk
                            error_info = getattr(chunk, "error", None)
                            if error_info:
                                error_message = (
                                    getattr(error_info, "message", None)
                                    or "Unknown streaming error"
                                )
                                provider_name = (
                                    getattr(
                                        getattr(error_info, "metadata", None),
                                        "provider_name",
                                        None,
                                    )
                                    or "unknown provider"
                                )
                            else:
                                error_message = "Unknown streaming error"
                                provider_name = "unknown provider"
                            sdk_stream_error = {
                                "message": error_message,
                                "provider": provider_name,
                            }
                            self._record_error(
                                message=error_message,
                                finish_reason=chunk_finish_reason,
                                provider_data={"provider_name": provider_name},
                            )
                            self.logger.error(
                                f"[OpenRouterGateway] SDK mid-stream error from {provider_name}: {error_message}"
                            )
                            break

                    delta_obj = (
                        choice.get("delta")
                        if isinstance(choice, dict)
                        else getattr(choice, "delta", None)
                    )
                    if delta_obj is None:
                        self.logger.debug(
                            "[OpenRouterGateway] SDK chunk %s had no delta payload",
                            chunk_index,
                        )
                        chunk_index += 1
                        continue

                    # ChoiceDelta objects expose attributes but not dict methods; fall back to dict check.
                    content_delta = getattr(delta_obj, "content", None)
                    if content_delta is None and isinstance(delta_obj, dict):
                        content_delta = delta_obj.get("content")

                    reasoning_delta = getattr(delta_obj, "reasoning", None)
                    if reasoning_delta is None and isinstance(delta_obj, dict):
                        reasoning_delta = delta_obj.get("reasoning")
                    tool_calls_delta = (
                        delta_obj.get("tool_calls")
                        if isinstance(delta_obj, dict)
                        else getattr(delta_obj, "tool_calls", None)
                    )

                    try:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index}: ID={chunk.id}, Model={chunk.model}, FinishReason={chunk_finish_reason}, DeltaContent='{content_delta}', DeltaReasoning='{reasoning_delta}', DeltaTools='{tool_calls_delta}'"
                    except Exception:
                        chunk_log = f"[OpenRouterGateway] Raw Chunk {chunk_index} (Minimal Log): DeltaContent='{content_delta}', DeltaReasoning='{reasoning_delta}'"
                    self.logger.debug(chunk_log)
                    chunk_index += 1

                    # Handle reasoning tokens
                    if reasoning_delta and not reasoning_phase_complete:
                        new_reasoning_segment = ""
                        if reasoning_delta.startswith(_gateway_accumulated_reasoning):
                            new_reasoning_segment = reasoning_delta[
                                len(_gateway_accumulated_reasoning) :
                            ]
                        else:
                            new_reasoning_segment = reasoning_delta

                        if new_reasoning_segment:
                            _gateway_accumulated_reasoning += new_reasoning_segment
                            self._append_reasoning(new_reasoning_segment)
                            # debug_stream_chunk(request_id, {'chunk': new_reasoning_segment, 'type': 'reasoning'}, "reasoning")
                            if stream_callback:
                                try:
                                    self.logger.debug(
                                        "[OpenRouterGateway] Calling stream_callback with reasoning segment: %r",
                                        new_reasoning_segment,
                                    )
                                    # Preserve whitespace-only segments to avoid collapsing words.
                                    await stream_callback(
                                        new_reasoning_segment, "reasoning"
                                    )
                                except Exception as cb_err:
                                    self.logger.error(
                                        "[OpenRouterGateway] Error in reasoning stream_callback: %s",
                                        cb_err,
                                        exc_info=True,
                                    )

                        full_reasoning_content = _gateway_accumulated_reasoning

                    # Handle content tokens
                    # BUGFIX: Changed from 'elif' to 'if' to handle chunks that have BOTH
                    # reasoning_delta AND content_delta simultaneously (common during transitions).
                    # With 'elif', content was dropped when both were present in the same chunk.
                    if content_delta:
                        # Log transition chunks (debugging abrupt terminations)
                        if reasoning_delta and content_delta:
                            self.logger.info(
                                f"[OpenRouterGateway] TRANSITION CHUNK: Both reasoning ({len(reasoning_delta)} chars) "
                                f"and content ({len(content_delta)} chars) in same chunk. "
                                f"Reasoning preview: '{reasoning_delta[:50]}...'"
                            )

                        # Mark reasoning phase as complete when we start getting content
                        if (
                            not reasoning_phase_complete
                            and _gateway_accumulated_reasoning
                        ):
                            reasoning_phase_complete = True
                            self.logger.debug(
                                "[OpenRouterGateway] Reasoning phase complete, switching to content phase"
                            )

                        new_content_segment = ""
                        if content_delta.startswith(_gateway_accumulated_content):
                            new_content_segment = content_delta[
                                len(_gateway_accumulated_content) :
                            ]
                        else:
                            new_content_segment = content_delta

                        if new_content_segment:
                            _gateway_accumulated_content += new_content_segment
                            try:
                                self._telemetry["streamed_bytes"] += len(
                                    new_content_segment.encode("utf-8")
                                )
                            except Exception:
                                pass
                            # debug_stream_chunk(request_id, {'chunk': new_content_segment, 'type': 'content'}, "content")
                            # WALLET_GUARD FIX: Always call stream_callback, even for whitespace
                            # The downstream handle_streaming_chunk has WALLET_GUARD logic to handle it
                            # Previously: `if new_content_segment.strip():` skipped whitespace, bypassing fixes
                            if stream_callback:
                                try:
                                    self.logger.debug(
                                        f"[OpenRouterGateway] Calling stream_callback with content segment: '{new_content_segment}'"
                                    )
                                    await stream_callback(
                                        new_content_segment, "assistant"
                                    )
                                except Exception as cb_err:
                                    self.logger.error(
                                        f"[OpenRouterGateway] Error in content stream_callback: {cb_err}",
                                        exc_info=True,
                                    )

                        full_response_content = _gateway_accumulated_content

                        # Interrupt streaming when a complete Penguin action tag is detected
                        try:
                            if getattr(self.model_config, "interrupt_on_action", False):
                                if self._contains_penguin_action_tags(
                                    full_response_content
                                ):
                                    self.logger.info(
                                        "[OpenRouterGateway] Interrupting stream on detected Penguin action tag (SDK path)"
                                    )
                                    try:
                                        self._telemetry["interrupts"] += 1
                                    except Exception:
                                        pass
                                    # Strip any incomplete action tags that were buffered after the complete one
                                    from penguin.utils.parser import (
                                        strip_incomplete_action_tags,
                                    )

                                    cleaned = strip_incomplete_action_tags(
                                        full_response_content
                                    )
                                    self.logger.debug(
                                        f"[OpenRouterGateway] Stripped incomplete tags: {len(full_response_content)} -> {len(cleaned)} chars"
                                    )
                                    return cleaned
                        except Exception as _int_err:
                            self.logger.debug(
                                f"[OpenRouterGateway] interrupt_on_action check failed: {_int_err}"
                            )

                    # Handle tool_calls deltas
                    # BUGFIX: Changed from 'elif' to 'if' to allow tool_calls with content in same chunk
                    if tool_calls_delta:
                        self.logger.debug(
                            f"[OpenRouterGateway] Received tool_calls delta: {tool_calls_delta}."
                        )
                        try:
                            self._record_tool_call_delta(tool_calls_delta)
                        except Exception as _acc_err:
                            self.logger.debug(
                                f"[OpenRouterGateway] tool_call accumulation failed: {_acc_err}"
                            )

                    # Log if no delta was found (all three types were empty)
                    if (
                        not reasoning_delta
                        and not content_delta
                        and not tool_calls_delta
                    ):
                        self.logger.debug(
                            f"[OpenRouterGateway] Chunk {chunk_index - 1} had no text/reasoning/tool delta."
                        )

                # self.logger.info(f"[OpenRouterGateway] Finished stream [{request_id}]. Accumulated reasoning length: {len(full_reasoning_content)}, content length: {len(full_response_content)}")
                # debug_stream_complete(request_id, full_response_content)

                self.logger.info(
                    f"[OpenRouterGateway] SDK streaming completed. Content: {len(full_response_content)} chars, finish_reason: {sdk_last_finish_reason}"
                )
                self._finalize_stream_tool_calls()
                self._log_last_usage("sdk-stream")

                # Handle mid-stream error if one occurred
                if sdk_stream_error:
                    error_msg = sdk_stream_error.get("message", "Unknown error")
                    provider = sdk_stream_error.get("provider", "unknown provider")
                    if full_response_content:
                        return f"{full_response_content}\n\n[Error: Stream interrupted by {provider}: {error_msg}]"
                    return f"[Error: {provider} returned mid-stream error: {error_msg}]"

                # For streaming responses, we return only the content part
                # The reasoning was already streamed via callback
                if not full_response_content:
                    if self.has_pending_tool_call():
                        return ""
                    self.logger.warning(
                        f"Streaming response completed with no content. Model: {self.model_config.model}"
                    )
                    # If we have reasoning but no content, the model may have only produced thinking
                    if full_reasoning_content:
                        self._record_error(
                            message="Model produced reasoning but no final response",
                            finish_reason=sdk_last_finish_reason,
                        )
                        return "[Note: Model produced reasoning tokens but no final response. This may indicate the model is still processing or encountered an issue.]"
                    self._record_error(
                        message=(
                            f"Model {self.model_config.model} returned empty response. "
                            "The model may not support this request type or encountered an issue."
                        ),
                        finish_reason=sdk_last_finish_reason,
                    )
                    return f"[Error: Model {self.model_config.model} returned empty response. The model may not support this request type or encountered an issue.]"

                # Check for truncation (finish_reason: 'length')
                if sdk_last_finish_reason == "length":
                    self.logger.warning(
                        f"[OpenRouterGateway] SDK streaming response was truncated (finish_reason='length'). Model: {self.model_config.model}"
                    )
                    return f"{full_response_content}\n\n[Note: Response was truncated due to token limits. Consider increasing max_output_tokens or breaking your request into smaller parts.]"

                return full_response_content

            else:  # Not streaming
                # Extract content, reasoning, and finish_reason
                sdk_finish_reason: Optional[str] = None
                self._set_last_usage(getattr(completion, "usage", None))
                self._log_last_usage("sdk-non-stream")
                if completion.choices and completion.choices[0].message:
                    response_message = completion.choices[0].message
                    full_response_content = response_message.content or ""
                    sdk_finish_reason = completion.choices[0].finish_reason
                    self._set_last_finish_reason(sdk_finish_reason)

                    # Handle error finish_reason
                    if sdk_finish_reason == "error":
                        error_info = getattr(completion, "error", None)
                        if error_info:
                            error_message = (
                                getattr(error_info, "message", None) or "Unknown error"
                            )
                            provider_name = (
                                getattr(
                                    getattr(error_info, "metadata", None),
                                    "provider_name",
                                    None,
                                )
                                or "unknown provider"
                            )
                        else:
                            error_message = "Unknown error"
                            provider_name = "unknown provider"
                        self._record_error(
                            message=error_message,
                            finish_reason=sdk_finish_reason,
                            provider_data={"provider_name": provider_name},
                        )
                        if full_response_content:
                            return f"{full_response_content}\n\n[Error: {provider_name} returned error: {error_message}]"
                        return f"[Error: {provider_name} returned: {error_message}]"

                    # Extract reasoning if present
                    reasoning_content = getattr(response_message, "reasoning", None)
                    if reasoning_content:
                        full_reasoning_content = reasoning_content
                        self._append_reasoning(str(reasoning_content))
                        self.logger.info(
                            f"[OpenRouterGateway] Non-streaming response includes reasoning tokens: {len(reasoning_content)} chars"
                        )

                        # If reasoning is not excluded, we could prepend it to the response
                        # or handle it separately based on configuration
                        if (
                            not self.model_config.reasoning_exclude
                            and reasoning_content
                        ):
                            # For non-streaming, we can emit the reasoning via callback if provided
                            if stream_callback:
                                try:
                                    await stream_callback(
                                        reasoning_content, "reasoning"
                                    )
                                except Exception as cb_err:
                                    self.logger.error(
                                        f"[OpenRouterGateway] Error in non-streaming reasoning callback: {cb_err}",
                                        exc_info=True,
                                    )

                    # TODO: Handle tool calls in non-streaming response
                    if response_message.tool_calls:
                        self.logger.info(
                            f"Received tool calls: {response_message.tool_calls}"
                        )
                        self._store_tool_call(response_message.tool_calls)
                        # How should this be returned? The current interface expects only a string.
                        # This needs coordination with api_client and core.
                        # For now, we prioritize returning the text content if available.
                        if not full_response_content:
                            # Maybe return a placeholder or representation of the tool call?
                            full_response_content = ""

                if not full_response_content:
                    if self.has_pending_tool_call():
                        return ""
                    self.logger.warning(
                        f"OpenRouter non-streaming response had no text content. Response: {completion}"
                    )
                    # Check if there's an error in the response object
                    error_info = getattr(completion, "error", None)
                    if error_info:
                        error_code = error_info.get("code", "unknown")
                        error_message = error_info.get("message", "Unknown error")
                        provider_info = error_info.get("metadata", {}).get(
                            "provider_name", "unknown provider"
                        )
                        self._record_error(
                            message=error_message,
                            status_code=error_code
                            if isinstance(error_code, int)
                            else None,
                            finish_reason=sdk_finish_reason,
                            provider_data={"provider_name": provider_info},
                        )

                        # Handle provider-specific errors
                        if "quota" in error_message.lower() or error_code == 429:
                            return f"[Error: Provider quota exceeded ({provider_info}). {error_message}]"

                        return f"[Error: Provider error ({provider_info}, code {error_code}). {error_message}]"

                    # If no error but still empty content (common with some Gemini models)
                    # Check usage to see if it was actually completed
                    usage = getattr(completion, "usage", None)
                    completion_tokens = (
                        getattr(usage, "completion_tokens", 0) if usage else 0
                    )

                    if completion_tokens > 0:
                        # Something was generated but response is empty (happens with some models)
                        self.logger.info(
                            f"Model generated {completion_tokens} tokens but returned empty content"
                        )
                        self._record_error(
                            message="Model processed the request but returned empty content",
                            finish_reason=sdk_finish_reason,
                        )
                        return "[Note: Model processed the request but returned empty content. Try rephrasing your query.]"

                    # Check finish reason?
                    finish_reason = (
                        completion.choices[0].finish_reason
                        if completion.choices
                        else "unknown"
                    )
                    provider = getattr(completion, "provider", "Unknown")

                    # Return a placeholder message instead of empty string for debugging
                    self.logger.warning(
                        f"Model finished (reason: {finish_reason}) but returned no content and generated 0 completion tokens."
                    )
                    self._record_error(
                        message=f"Model finished with no content from {provider}",
                        finish_reason=finish_reason,
                    )
                    return f"[Model finished with no content from {provider}. Please try again or try with a different model.]"

                self.logger.debug(
                    f"Non-streaming response received. Content length: {len(full_response_content or '')}, finish_reason: {sdk_finish_reason}"
                )

                # Check for truncation (finish_reason: 'length')
                if sdk_finish_reason == "length":
                    self.logger.warning(
                        f"[OpenRouterGateway] SDK non-streaming response was truncated (finish_reason='length'). Model: {self.model_config.model}"
                    )
                    return f"{full_response_content}\n\n[Note: Response was truncated due to token limits. Consider increasing max_output_tokens or breaking your request into smaller parts.]"

                return full_response_content or ""  # Ensure string return

        except APIError as e:
            self.logger.error(f"OpenRouter API error: {e}", exc_info=True)
            # Safely extract attributes - OpenAI SDK APIError may have different structure
            status_code = getattr(e, "status_code", None) or getattr(e, "code", 500)
            message = getattr(e, "message", None) or str(e)
            # Try to extract detailed error from the response body
            error_body = getattr(e, "body", None)
            if error_body and isinstance(error_body, (str, dict)):
                error_text = (
                    error_body
                    if isinstance(error_body, str)
                    else json.dumps(error_body)
                )
                return self._parse_openrouter_error(error_text, status_code)
            # Fallback to basic error info - include full error message
            self._record_error(
                message=str(message),
                status_code=status_code if isinstance(status_code, int) else None,
            )
            return f"[Error: {message}]"
        except Exception as e:
            self.logger.error(
                f"Unexpected error during OpenRouter API call: {e}", exc_info=True
            )
            # Check if it's an httpx error with response details
            if hasattr(e, "response") and e.response is not None:
                try:
                    return self._parse_openrouter_error(
                        e.response.text, e.response.status_code
                    )
                except Exception:
                    pass
            self._record_error(
                message=f"Unexpected error communicating with OpenRouter - {str(e)}"
            )
            return f"[Error: Unexpected error communicating with OpenRouter - {str(e)}]"

    async def _direct_api_call_with_reasoning(
        self,
        request_params: Dict[str, Any],
        reasoning_config: Dict[str, Any],
        use_streaming: bool,
        stream_callback: Optional[Callable[[str, str], None]],
    ) -> str:
        """
        Make a direct HTTP call to OpenRouter API with reasoning support.

        This bypasses the OpenAI SDK when it doesn't support the reasoning parameter.
        """
        # Remove parameters that are SDK-specific
        direct_params = request_params.copy()
        extra_headers = direct_params.pop("extra_headers", {})

        # Add reasoning configuration using new unified format
        direct_params["reasoning"] = reasoning_config
        # Remove include_reasoning - now using unified reasoning parameter

        # Prepare headers
        headers = {
            "Authorization": f"Bearer {self.client.api_key}",
            "Content-Type": "application/json",
            **extra_headers,
        }

        url = f"{self.base_url}/chat/completions"

        try:
            # Use connection pool for efficient parallel LLM calls
            # The pool handles timeouts via ConnectionPoolConfig (default: 300s read timeout)
            pool = ConnectionPoolManager.get_instance()
            async with pool.client_context(self.base_url) as client:
                if use_streaming:
                    return await self._handle_streaming_response(
                        client, url, headers, direct_params, stream_callback
                    )
                else:
                    return await self._handle_non_streaming_response(
                        client, url, headers, direct_params, stream_callback
                    )

        except httpx.ReadTimeout:
            self.logger.error(f"Request timed out for model {self.model_config.model}")
            self._record_error(
                message=f"Request timed out for {self.model_config.model}",
            )
            return f"[Error: Request timed out. Model {self.model_config.model} may be cold-starting or experiencing high load. Try again in a moment.]"
        except httpx.ConnectTimeout:
            self.logger.error(
                f"Connection timed out for model {self.model_config.model}"
            )
            self._record_error(
                message="Connection timed out communicating with OpenRouter",
            )
            return "[Error: Connection timed out. OpenRouter may be experiencing issues. Try again later.]"
        except Exception as e:
            self.logger.error(f"Direct API call failed: {e}", exc_info=True)
            # Check for timeout-related errors in the exception
            if "timeout" in str(e).lower():
                self._record_error(
                    message=f"Request timed out for {self.model_config.model}",
                )
                return f"[Error: Request timed out for {self.model_config.model}. The model may need time to warm up. Try again.]"
            self._record_error(
                message=f"Direct API call failed - {str(e)}",
            )
            return f"[Error: Direct API call failed - {str(e)}]"

    async def _handle_streaming_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        stream_callback: Optional[Callable[[str, str], None]],
    ) -> str:
        """Handle streaming response from direct API call."""
        params["stream"] = True

        # Add debug mode if enabled (development only - echoes upstream request)
        if getattr(self.model_config, "debug_upstream", False):
            params["debug"] = {"echo_upstream_body": True}
            self.logger.info(
                "[OpenRouterGateway] Debug mode enabled - will echo upstream request body"
            )

        full_content = ""
        full_reasoning = ""
        reasoning_phase_complete = False
        last_finish_reason: Optional[str] = None
        stream_error: Optional[Dict[str, Any]] = None
        interrupted_reason: Optional[str] = None
        generation_id: Optional[str] = None
        stream_started_at = asyncio.get_running_loop().time()
        chunk_timeout_seconds = self._stream_chunk_timeout_seconds()
        total_timeout_seconds = self._stream_total_timeout_seconds()

        async with client.stream("POST", url, headers=headers, json=params) as response:
            if response.status_code != 200:
                error_text = (await response.aread()).decode()
                self.logger.error(
                    f"Direct API call failed with status {response.status_code}: {error_text}"
                )
                return self._parse_openrouter_error(
                    error_text,
                    response.status_code,
                    retry_after_seconds=extract_retry_after_seconds(response.headers),
                )

            generation_id = self._extract_generation_id_from_headers(response.headers)
            line_iter = response.aiter_lines().__aiter__()

            while True:
                try:
                    line = await self._next_stream_item(
                        line_iter,
                        wait_timeout=chunk_timeout_seconds,
                        total_timeout=total_timeout_seconds,
                        started_at=stream_started_at,
                        phase="OpenRouter direct stream",
                    )
                except StopAsyncIteration:
                    break
                except TimeoutError as exc:
                    self.logger.warning(
                        "[OpenRouterGateway] Direct stream stalled model=%s chunk_timeout=%ss total_timeout=%ss detail=%s",
                        self.model_config.model,
                        chunk_timeout_seconds,
                        total_timeout_seconds,
                        exc,
                    )
                    self._record_error(
                        message=f"OpenRouter stream stalled for {self.model_config.model}",
                    )
                    return (
                        f"[Error: OpenRouter stream stalled for {self.model_config.model}. "
                        "No chunks were received before timeout. Try again or switch models.]"
                    )

                if not line.strip():
                    continue

                # Handle OpenRouter SSE keep-alive comments (e.g., ": OPENROUTER PROCESSING")
                # These are sent to prevent connection timeouts during model cold-start/warmup
                if line.startswith(":"):
                    self.logger.debug(f"OpenRouter keep-alive: {line}")
                    continue

                if line.startswith("data: "):
                    data_str = line[6:]  # Remove "data: " prefix

                    if data_str.strip() == "[DONE]":
                        break

                    try:
                        data = json.loads(data_str)
                        if not generation_id:
                            generation_id = self._extract_generation_id_from_chunk(data)

                        # Handle debug chunks (first chunk with empty choices when debug mode is on)
                        # Debug chunks contain the transformed upstream request body
                        choices = data.get("choices", [])
                        if not choices and getattr(
                            self.model_config, "debug_upstream", False
                        ):
                            debug_body = data.get("debug", {}).get("upstream_body")
                            if debug_body:
                                self.logger.info(
                                    f"[OpenRouterGateway] Debug - Upstream request body: {json.dumps(debug_body, indent=2)[:2000]}"
                                )
                            continue

                        self._set_last_usage(data.get("usage"))

                        choice = choices[0] if choices else {}
                        delta = choice.get("delta", {})

                        # Track finish_reason for error and truncation detection
                        finish_reason = choice.get("finish_reason")
                        if finish_reason:
                            last_finish_reason = finish_reason
                            self._set_last_finish_reason(finish_reason)
                            self.logger.debug(
                                f"[OpenRouterGateway] Received finish_reason: {finish_reason}"
                            )

                            # Handle mid-stream errors (finish_reason: 'error')
                            # Per OpenRouter docs: errors during streaming come with finish_reason='error'
                            if finish_reason == "error":
                                error_info = data.get("error", {})
                                error_message = error_info.get(
                                    "message", "Unknown streaming error"
                                )
                                provider_name = error_info.get("metadata", {}).get(
                                    "provider_name", "unknown provider"
                                )
                                stream_error = {
                                    "message": error_message,
                                    "provider": provider_name,
                                    "code": error_info.get("code"),
                                }
                                self._record_error(
                                    message=error_message,
                                    finish_reason=finish_reason,
                                    provider_data={"provider_name": provider_name},
                                )
                                self.logger.error(
                                    f"[OpenRouterGateway] Mid-stream error from {provider_name}: {error_message}"
                                )
                                break

                        # Handle reasoning content
                        reasoning_delta = (
                            getattr(delta, "reasoning", None)
                            if hasattr(delta, "reasoning")
                            else delta.get("reasoning")
                        )
                        if reasoning_delta and not reasoning_phase_complete:
                            full_reasoning += reasoning_delta
                            self._append_reasoning(reasoning_delta)
                            if stream_callback:
                                try:
                                    await stream_callback(reasoning_delta, "reasoning")
                                except Exception as cb_err:
                                    self.logger.error(
                                        f"Error in reasoning callback: {cb_err}"
                                    )

                        # Handle regular content
                        content_delta = (
                            getattr(delta, "content", None)
                            if hasattr(delta, "content")
                            else delta.get("content")
                        )
                        if content_delta:
                            if not reasoning_phase_complete and full_reasoning:
                                reasoning_phase_complete = True
                                self.logger.debug(
                                    "Reasoning phase complete, switching to content"
                                )

                            full_content += content_delta
                            try:
                                self._telemetry["streamed_bytes"] += len(
                                    content_delta.encode("utf-8")
                                )
                            except Exception:
                                pass
                            if stream_callback:
                                try:
                                    await stream_callback(content_delta, "assistant")
                                except Exception as cb_err:
                                    self.logger.error(
                                        f"Error in content callback: {cb_err}"
                                    )
                            # Interrupt streaming when a complete Penguin action tag is detected
                            try:
                                if getattr(
                                    self.model_config, "interrupt_on_action", False
                                ):
                                    if self._contains_penguin_action_tags(full_content):
                                        self.logger.info(
                                            "[OpenRouterGateway] Interrupting stream on detected Penguin action tag (Direct API path)"
                                        )
                                        try:
                                            self._telemetry["interrupts"] += 1
                                        except Exception:
                                            pass
                                        # Strip any incomplete action tags that were buffered after the complete one
                                        from penguin.utils.parser import (
                                            strip_incomplete_action_tags,
                                        )

                                        full_content = strip_incomplete_action_tags(
                                            full_content
                                        )
                                        self.logger.debug(
                                            "[OpenRouterGateway] Stripped incomplete tags from direct API response"
                                        )
                                        interrupted_reason = "action"
                                        break
                            except Exception as _int_err:
                                self.logger.debug(
                                    f"[OpenRouterGateway] interrupt_on_action check failed: {_int_err}"
                                )
                        # Handle tool_calls in direct SSE (Responses/OpenAI compatible)
                        try:
                            tool_calls_delta = (
                                getattr(delta, "tool_calls", None)
                                if hasattr(delta, "tool_calls")
                                else delta.get("tool_calls")
                            )
                            if tool_calls_delta:
                                try:
                                    self._record_tool_call_delta(tool_calls_delta)
                                except Exception as _acc_err2:
                                    self.logger.debug(
                                        f"[OpenRouterGateway] tool_call accumulation failed: {_acc_err2}"
                                    )
                        except Exception as _tool_int_err2:
                            self.logger.debug(
                                f"[OpenRouterGateway] interrupt_on_tool_call check failed: {_tool_int_err2}"
                            )

                    except json.JSONDecodeError as e:
                        self.logger.warning(
                            f"Failed to parse SSE data: {data_str[:100]}... Error: {e}"
                        )
                        continue

        self.logger.info(
            f"Direct streaming call completed. Reasoning: {len(full_reasoning)} chars, Content: {len(full_content)} chars, finish_reason: {last_finish_reason}"
        )
        self._finalize_stream_tool_calls()
        if interrupted_reason and (
            not isinstance(self._last_usage, dict) or not self._last_usage
        ):
            await self._recover_usage_from_generation(
                client,
                headers,
                generation_id,
                f"direct-stream-{interrupted_reason}",
            )
        self._log_last_usage("direct-stream")

        # Handle mid-stream error if one occurred
        if stream_error:
            error_msg = stream_error.get("message", "Unknown error")
            provider = stream_error.get("provider", "unknown provider")
            # If we have partial content, include it with the error
            if full_content:
                return f"{full_content}\n\n[Error: Stream interrupted by {provider}: {error_msg}]"
            return f"[Error: {provider} returned mid-stream error: {error_msg}]"

        # Check for empty content and provide helpful message
        if not full_content:
            if self.has_pending_tool_call():
                return ""
            self.logger.debug(
                f"Direct streaming response completed with no content. Model: {self.model_config.model}"
            )
            if full_reasoning:
                self._record_error(
                    message="Model produced reasoning but no final response",
                    finish_reason=last_finish_reason,
                )
                return "[Note: Model produced reasoning tokens but no final response. This may indicate the model is still processing or encountered an issue.]"
            self._record_error(
                message=(
                    f"Model {self.model_config.model} returned empty response. "
                    "The model may not support this request type or encountered an issue."
                ),
                finish_reason=last_finish_reason,
            )
            return f"[Error: Model {self.model_config.model} returned empty response. The model may not support this request type or encountered an issue.]"

        # Check for truncation (finish_reason: 'length')
        # Per OpenRouter docs: token limit errors become successful responses with finish_reason='length'
        if last_finish_reason == "length":
            self.logger.warning(
                f"[OpenRouterGateway] Response was truncated (finish_reason='length'). Model: {self.model_config.model}"
            )
            return f"{full_content}\n\n[Note: Response was truncated due to token limits. Consider increasing max_output_tokens or breaking your request into smaller parts.]"

        return full_content

    def get_telemetry(self) -> Dict[str, Any]:
        """Return simple telemetry counters for diagnostics."""
        try:
            return dict(self._telemetry)
        except Exception:
            return {"interrupts": 0, "streamed_bytes": 0}

    def get_last_usage(self) -> Dict[str, Any]:
        """Return normalized usage/cost from the latest request."""
        if not isinstance(self._last_usage, dict):
            return {}
        return dict(self._last_usage)

    def has_pending_tool_call(self) -> bool:
        """Return whether a Responses/tool-call interrupt is waiting to execute."""
        return bool(
            isinstance(getattr(self, "_last_tool_call", None), dict)
            and self._last_tool_call.get("name")
        ) or any(
            isinstance(tool_call, dict) and bool(tool_call.get("name"))
            for tool_call in getattr(self, "_pending_tool_calls", [])
        )

    def get_and_clear_last_tool_call(self) -> Optional[Dict[str, Any]]:
        """Return last detected tool_call (name, arguments) and clear accumulators."""
        pending = self.get_and_clear_pending_tool_calls()
        if pending:
            return pending[0]
        data = getattr(self, "_last_tool_call", None)
        self._last_tool_call = None
        self._tool_call_acc = {"name": None, "arguments": ""}
        return dict(data) if isinstance(data, dict) else None

    def get_and_clear_pending_tool_calls(self) -> List[Dict[str, Any]]:
        """Return all detected tool calls and clear accumulators."""
        try:
            pending = [
                dict(tool_call)
                for tool_call in getattr(self, "_pending_tool_calls", [])
                if isinstance(tool_call, dict) and tool_call.get("name")
            ]
            if not pending and isinstance(
                getattr(self, "_last_tool_call", None), dict
            ):
                pending = [dict(self._last_tool_call)]
            self._pending_tool_calls = []
            self._last_tool_call = None
            self._tool_call_acc = {"name": None, "arguments": ""}
            self._tool_call_accs = {}
            return pending
        except Exception:
            return []

    async def _handle_non_streaming_response(
        self,
        client: httpx.AsyncClient,
        url: str,
        headers: Dict[str, str],
        params: Dict[str, Any],
        stream_callback: Optional[Callable[[str, str], None]],
    ) -> str:
        """Handle non-streaming response from direct API call."""
        params["stream"] = False

        response = await client.post(url, headers=headers, json=params)

        if response.status_code != 200:
            error_text = response.text
            self.logger.error(
                f"Direct API call failed with status {response.status_code}: {error_text}"
            )
            return self._parse_openrouter_error(
                error_text,
                response.status_code,
                retry_after_seconds=extract_retry_after_seconds(response.headers),
            )

        try:
            data = response.json()
            self._set_last_usage(data.get("usage"))
            self._log_last_usage("direct-non-stream")
            choice = data.get("choices", [{}])[0]
            message = choice.get("message", {})
            finish_reason = choice.get("finish_reason")
            self._set_last_finish_reason(finish_reason)

            # Some providers include keys with explicit None values; coalesce to empty strings
            content = message.get("content") or ""
            reasoning = message.get("reasoning") or ""
            tool_calls = message.get("tool_calls") or []
            if reasoning:
                self._append_reasoning(reasoning)
            if tool_calls:
                self._store_tool_call(tool_calls)

            # If we have reasoning and a callback, emit it
            if reasoning and stream_callback:
                try:
                    await stream_callback(reasoning, "reasoning")
                except Exception as cb_err:
                    self.logger.error(f"Error in reasoning callback: {cb_err}")

            self.logger.info(
                f"Direct non-streaming call completed. Reasoning: {len(reasoning)} chars, Content: {len(content)} chars, finish_reason: {finish_reason}"
            )

            # Handle error finish_reason (rare in non-streaming but possible)
            if finish_reason == "error":
                error_info = data.get("error", {})
                error_message = error_info.get("message", "Unknown error")
                provider_name = error_info.get("metadata", {}).get(
                    "provider_name", "unknown provider"
                )
                self._record_error(
                    message=error_message,
                    finish_reason=finish_reason,
                    provider_data={"provider_name": provider_name},
                )
                if content:
                    return f"{content}\n\n[Error: {provider_name} returned error: {error_message}]"
                return f"[Error: {provider_name} returned: {error_message}]"

            # Check for empty content and provide helpful message
            if not content:
                if self.has_pending_tool_call():
                    return ""
                self.logger.warning(
                    f"Direct non-streaming response had no content. Model: {self.model_config.model}"
                )
                # Check if there's an error embedded in the response
                error_info = data.get("error", {})
                if error_info:
                    error_message = error_info.get("message", "Unknown error")
                    provider_name = error_info.get("metadata", {}).get(
                        "provider_name", "unknown provider"
                    )
                    self._record_error(
                        message=error_message,
                        finish_reason=finish_reason,
                        provider_data={"provider_name": provider_name},
                    )
                    return f"[Error: {provider_name} returned: {error_message}]"
                if reasoning:
                    self._record_error(
                        message="Model produced reasoning but no final response",
                        finish_reason=finish_reason,
                    )
                    return "[Note: Model produced reasoning tokens but no final response. This may indicate the model is still processing or encountered an issue.]"
                self._record_error(
                    message=(
                        f"Model {self.model_config.model} returned empty response. "
                        "The model may not support this request type or encountered an issue."
                    ),
                    finish_reason=finish_reason,
                )
                return f"[Error: Model {self.model_config.model} returned empty response. The model may not support this request type or encountered an issue.]"

            # Check for truncation (finish_reason: 'length')
            if finish_reason == "length":
                self.logger.warning(
                    f"[OpenRouterGateway] Non-streaming response was truncated (finish_reason='length'). Model: {self.model_config.model}"
                )
                return f"{content}\n\n[Note: Response was truncated due to token limits. Consider increasing max_output_tokens or breaking your request into smaller parts.]"

            return content

        except json.JSONDecodeError as e:
            self.logger.error(f"Failed to parse response JSON: {e}")
            self._record_error(message=f"Failed to parse response - {str(e)}")
            return f"[Error: Failed to parse response - {str(e)}]"

    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """
        Counts tokens using tiktoken, assuming GPT-4o encoding as per OpenRouter's norm.

        Args:
            content: Text string, a list of message dicts, or a single message dict.

        Returns:
            The number of tokens.
        """
        if not self.model_config.enable_token_counting:
            self.logger.debug("Token counting disabled in ModelConfig.")
            return 0

        model_for_counting = (
            "gpt-4o"  # Use OpenRouter's standard for normalized counting
        )
        try:
            encoding = tiktoken.encoding_for_model(model_for_counting)
        except Exception as e:
            self.logger.warning(
                f"Failed to get tiktoken encoding for '{model_for_counting}', falling back to cl100k_base: {e}"
            )
            try:
                encoding = tiktoken.get_encoding("cl100k_base")
            except Exception as fallback_e:
                self.logger.error(
                    f"Failed to get cl100k_base encoding: {fallback_e}. Falling back to rough estimate."
                )
                return len(str(content)) // 4  # Very rough estimate

        num_tokens = 0
        if isinstance(content, str):
            num_tokens = len(encoding.encode(content))
        elif isinstance(content, list):  # Assume list of messages
            # Based on OpenAI cookbook examples for counting tokens for chat messages
            tokens_per_message = 3
            tokens_per_name = 1
            for message in content:
                num_tokens += tokens_per_message
                for key, value in message.items():
                    # Ensure value is a string before encoding
                    value_str = (
                        str(value) if not isinstance(value, (str, list)) else value
                    )  # Handle potential non-strings crudely

                    if isinstance(value_str, str):  # Encode strings
                        num_tokens += len(encoding.encode(value_str))
                    elif (
                        isinstance(value_str, list) and key == "content"
                    ):  # Handle multimodal content list
                        for item in value_str:
                            if isinstance(item, dict) and item.get("type") == "text":
                                num_tokens += len(encoding.encode(item.get("text", "")))
                            # Vision tokens are harder to count accurately here, skip for now
                            # elif isinstance(item, dict) and item.get('type') == 'image_url':
                            #      pass # Placeholder for vision token counting logic if needed

                    if key == "name":  # If there's a name associated with the message
                        num_tokens += tokens_per_name
            num_tokens += (
                3  # Every reply is primed with <|im_start|>assistant<|im_sep|>
            )
        elif isinstance(content, dict):  # Assume single message dict
            # Simplified count for single dict, better to use list format
            num_tokens = len(
                encoding.encode(str(content))
            )  # Rough estimate for single dict
        else:
            self.logger.warning(
                f"Unsupported type for token counting: {type(content)}. Using rough estimate."
            )
            num_tokens = len(encoding.encode(str(content)))

        return num_tokens

    def supports_system_messages(self) -> bool:
        """OpenRouter (via OpenAI SDK format) supports system messages."""
        return True

    def supports_vision(self) -> bool:
        """Check if the configured model likely supports vision based on ModelConfig."""
        # Rely on the determination made in ModelConfig
        return bool(self.model_config.vision_enabled)

    # --- Optional: Method to list models ---
    async def get_available_models(self) -> List[str]:
        """
        Fetches the list of available models from OpenRouter.

        Returns:
            A list of model ID strings. Returns empty list on failure.
        """
        try:
            models_response = await self.client.models.list()
            model_ids = [model.id for model in models_response.data]
            self.logger.info(f"Fetched {len(model_ids)} models from OpenRouter.")
            return model_ids
        except APIError as e:
            self.logger.error(
                f"Failed to list OpenRouter models (API Error): {e}", exc_info=True
            )
            return []
        except Exception as e:
            self.logger.error(
                f"Failed to list OpenRouter models (Unexpected Error): {e}",
                exc_info=True,
            )
            return []
