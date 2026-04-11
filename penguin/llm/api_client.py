import asyncio
import base64
import io
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, Dict, List, Optional, Callable, Union

import httpx
import yaml  # type: ignore
import tiktoken  # type: ignore

# TODO: decouple litellm from api_client. # Been done for quite a while.
# TODO: greatly simplify api_client while maintaining full functionality
# TODO: add streaming support # Done for quite a while.
# TODO: add support for images, files, audio, and video
# Lazy import litellm to avoid 1+ second import time overhead
# from litellm import acompletion, completion, token_counter, cost_per_token, completion_cost
from PIL import Image  # type: ignore

from .contracts import ErrorCategory, LLMError, LLMProviderError
from .model_config import ModelConfig
from .provider_registry import ProviderRegistry
from .provider_transform import apply_model_config_transforms, build_llm_error
from penguin.constants import get_default_max_history_tokens
from penguin.utils.callbacks import adapt_stream_callback
from .adapters import get_adapter  # Keep for native preference
from .litellm_support import load_litellm_gateway_class, load_litellm_module
# Lazy import gateways to avoid import overhead
# from .litellm_gateway import LiteLLMGateway
# from .openrouter_gateway import OpenRouterGateway
# from penguin.llm.provider_adapters import get_provider_adapter # Seems unused

logger = logging.getLogger(__name__)


def _log_error(message: str, *args: Any, exc_info: bool = False) -> None:
    logger.error(message, *args, exc_info=exc_info)
    uvicorn_logger = logging.getLogger("uvicorn.error")
    if uvicorn_logger is not logger:
        uvicorn_logger.error(message, *args, exc_info=exc_info)


# ==============================================================================
# Connection Pool Management for Parallel LLM Calls
# ==============================================================================


class ConnectionPoolConfig:
    """Configuration for HTTP connection pools."""

    def __init__(
        self,
        max_keepalive_connections: int = 20,
        max_connections: int = 100,
        keepalive_expiry: float = 30.0,
        connect_timeout: float = 10.0,
        read_timeout: float = 300.0,  # Long for cold-start models
        write_timeout: float = 10.0,
    ):
        self.max_keepalive_connections = max_keepalive_connections
        self.max_connections = max_connections
        self.keepalive_expiry = keepalive_expiry
        self.connect_timeout = connect_timeout
        self.read_timeout = read_timeout
        self.write_timeout = write_timeout

    def to_limits(self) -> httpx.Limits:
        return httpx.Limits(
            max_keepalive_connections=self.max_keepalive_connections,
            max_connections=self.max_connections,
            keepalive_expiry=self.keepalive_expiry,
        )

    def to_timeout(self) -> httpx.Timeout:
        return httpx.Timeout(
            timeout=self.read_timeout,  # Default for unspecified values
            connect=self.connect_timeout,
            read=self.read_timeout,
            write=self.write_timeout,
        )


class ConnectionPoolManager:
    """Manages shared HTTP connection pools per provider/base_url.

    Singleton pattern ensures connection reuse across all LLM clients.
    This enables efficient parallel LLM calls by reusing connections.

    Usage:
        # Get the global pool instance
        pool = ConnectionPoolManager.get_instance()

        # Get a pooled client for a specific base URL
        client = await pool.get_client("https://openrouter.ai/api/v1")

        # Or use the context manager
        async with pool.client_context("https://openrouter.ai/api/v1") as client:
            response = await client.post(url, json=payload)

        # On shutdown, close all pools
        await pool.close_all()
    """

    _instance: Optional["ConnectionPoolManager"] = None
    _lock: asyncio.Lock = asyncio.Lock()

    @classmethod
    def get_instance(
        cls, config: Optional[ConnectionPoolConfig] = None
    ) -> "ConnectionPoolManager":
        """Get the singleton instance (sync accessor).

        Args:
            config: Optional configuration for new instances

        Returns:
            The global ConnectionPoolManager instance
        """
        if cls._instance is None:
            cls._instance = cls(config or ConnectionPoolConfig())
        return cls._instance

    @classmethod
    async def get_instance_async(
        cls, config: Optional[ConnectionPoolConfig] = None
    ) -> "ConnectionPoolManager":
        """Get the singleton instance (async accessor with lock).

        Args:
            config: Optional configuration for new instances

        Returns:
            The global ConnectionPoolManager instance
        """
        if cls._instance is None:
            async with cls._lock:
                if cls._instance is None:
                    cls._instance = cls(config or ConnectionPoolConfig())
        return cls._instance

    def __init__(self, config: Optional[ConnectionPoolConfig] = None):
        """Initialize the connection pool manager.

        Args:
            config: Configuration for pool limits and timeouts
        """
        self._config = config or ConnectionPoolConfig()
        self._clients: Dict[str, httpx.AsyncClient] = {}
        self._client_locks: Dict[str, asyncio.Lock] = {}

    async def get_client(self, base_url: str) -> httpx.AsyncClient:
        """Get or create a pooled client for the given base URL.

        Args:
            base_url: The base URL for the API (e.g., "https://openrouter.ai/api/v1")

        Returns:
            Shared AsyncClient with connection pooling
        """
        if base_url not in self._clients:
            # Create lock for this base_url if needed
            if base_url not in self._client_locks:
                self._client_locks[base_url] = asyncio.Lock()

            async with self._client_locks[base_url]:
                # Double-check after acquiring lock
                if base_url not in self._clients:
                    self._clients[base_url] = httpx.AsyncClient(
                        limits=self._config.to_limits(),
                        timeout=self._config.to_timeout(),
                    )
                    logger.info(f"Created connection pool for {base_url}")

        return self._clients[base_url]

    @asynccontextmanager
    async def client_context(self, base_url: str):
        """Context manager for using a pooled client.

        Unlike the per-request pattern, this reuses connections:

        Old (inefficient):
            async with httpx.AsyncClient() as client:
                response = await client.post(...)

        New (connection pooling):
            pool = ConnectionPoolManager.get_instance()
            async with pool.client_context(base_url) as client:
                response = await client.post(...)

        Args:
            base_url: The base URL for the API

        Yields:
            Shared AsyncClient instance
        """
        client = await self.get_client(base_url)
        try:
            yield client
        except httpx.PoolTimeout:
            logger.warning(
                f"Connection pool timeout for {base_url}, request may be delayed"
            )
            raise

    async def close_all(self) -> None:
        """Close all pooled clients. Call during shutdown."""
        for base_url, client in list(self._clients.items()):
            try:
                await client.aclose()
                logger.info(f"Closed connection pool for {base_url}")
            except Exception as e:
                logger.warning(f"Error closing client for {base_url}: {e}")
        self._clients.clear()
        self._client_locks.clear()

    def get_stats(self) -> Dict[str, Dict]:
        """Get connection pool statistics for monitoring.

        Returns:
            Dict mapping base_url to pool stats
        """
        stats = {}
        for base_url in self._clients:
            stats[base_url] = {
                "active": True,
                "limits": {
                    "max_keepalive": self._config.max_keepalive_connections,
                    "max_connections": self._config.max_connections,
                },
            }
        return stats


def load_config() -> Dict[str, Any]:
    """Load Penguin config using central resolver, with safe fallback.

    Delegates to penguin.config.load_config, which already checks:
    - PENGUIN_CONFIG_PATH
    - ~/.config/penguin/config.yml (or platform equivalent)
    - dev/repo defaults
    Returns an empty dict on failure instead of raising during import.
    """
    try:
        from penguin.config import load_config as core_load_config

        data = core_load_config()
        return data if isinstance(data, dict) else {}
    except Exception as e:
        logger.warning(f"api_client.load_config fallback: {e}")
        return {}


# Load the model configurations from the config file
MODEL_CONFIGS = load_config().get("model_configs", {})


class APIClient:
    """
    A client for interacting with various AI model APIs, routing requests
    to either a native adapter or the LiteLLM gateway based on configuration.

    Attributes:
        model_config (ModelConfig): Configuration for the AI model.
        system_prompt (str): The system prompt to be sent with each request.
        client_handler (Any): The actual handler instance (native adapter or LiteLLMGateway).
        logger (logging.Logger): Logger for this class.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        base_url: Optional[str] = None,
        extra_headers: Optional[Dict[str, str]] = None,
    ):
        """
        Initialize the APIClient.

        Args:
            model_config (ModelConfig): Configuration for the AI model, including
                                        the 'client_preference'.
        """
        self.model_config = model_config
        self._canonicalize_native_model_id()
        self.system_prompt = None
        self.logger = logging.getLogger(__name__)
        self.client_handler = None  # Will be set based on preference
        self._last_error: Optional[LLMError] = None
        self._base_url = base_url
        self._extra_headers = dict(extra_headers or {})
        self.provider_registry = ProviderRegistry(
            native_adapter_factory=get_adapter,
            litellm_gateway_loader=load_litellm_gateway_class,
        )

        self.logger.info(
            f"Initializing APIClient for model: {model_config.model}, "
            f"Provider: {model_config.provider}, "
            f"Preference: {model_config.client_preference}"
        )

        # --- Instantiate the correct handler via the shared registry ---
        try:
            self.client_handler = self.provider_registry.create_handler(
                model_config,
                base_url=self._base_url,
                extra_headers=self._extra_headers,
            )
            self.logger.info(
                "Using %s for %s (provider=%s, preference=%s)",
                type(self.client_handler).__name__,
                model_config.model,
                model_config.provider,
                model_config.client_preference,
            )
        except RuntimeError as e:
            self.logger.error("Provider handler unavailable: %s", e)
            raise RuntimeError(str(e)) from e
        except Exception as e:
            self.logger.error(
                "Failed to initialize provider handler for %s/%s: %s",
                model_config.provider,
                model_config.model,
                e,
                exc_info=True,
            )
            raise ValueError(f"Could not initialize provider handler: {e}") from e

        # Common properties (potentially less relevant now?)
        self.max_history_tokens = (
            model_config.max_history_tokens or get_default_max_history_tokens()
        )

        # Clean up old logging/prints
        # print("\n=== API Client Initialization ===")
        # print(f"Model: {model_config.model}") # Logged above
        # print(f"Provider: {model_config.provider}") # Logged above
        # print(f"Client Handler: {type(self.client_handler).__name__}") # Logged above
        # print(f"API Key Present: {bool(model_config.api_key)}") # Less direct control now
        # print("===============================\n")

        # OpenAI Assistants API handling - needs review
        # This seems tied to OpenAI native implementation. How does it fit with LiteLLM?
        # LiteLLM has its own proxy endpoint for assistants. If using that, this logic is wrong.
        # If using OpenAI native adapter, this might still be relevant.
        # Let's comment it out for now, needs rethinking based on how Assistants are used.
        # if model_config.use_assistants_api and model_config.provider == 'openai' and model_config.client_preference == 'native':
        #     self.logger.info("Attempting to use OpenAI Assistants API via native adapter")
        #     # Logic for Assistants API tied to native adapter needs confirmation
        #     if hasattr(self.client_handler, 'assistant_manager'):
        #          self.logger.info("Native adapter has assistant manager.")
        #     else:
        #          self.logger.warning("Native adapter selected with use_assistants_api=True, but adapter lacks assistant_manager.")
        # else:
        #      pass # Not using assistants or not using OpenAI native

    def _canonicalize_native_model_id(self) -> None:
        """Normalize provider-prefixed native model IDs before adapter creation."""
        apply_model_config_transforms(self.model_config)

    def set_system_prompt(self, prompt: str) -> None:
        """Set the system prompt."""
        self.system_prompt = prompt
        # TODO: How to pass system prompt?
        # Native adapters might have specific methods.
        # LiteLLM expects it in the messages list.
        # We might need to handle this within get_response based on handler type.
        self.logger.debug(f"System prompt set. Length: {len(prompt)}")
        # Commenting out assistant-specific update for now
        # if self.model_config.use_assistants_api and hasattr(self.client_handler, 'assistant_manager'):
        #     self.client_handler.assistant_manager.update_system_prompt(prompt)

    def _prepare_messages_with_system_prompt(
        self, messages: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Inject the system prompt while preserving other system‑role
        messages (e.g. action results, iteration markers).
        """
        if not self.system_prompt:
            return messages[:]  # nothing to do

        processed = []
        prompt_already_present = False

        for msg in messages:
            if msg.get("role") == "system":
                if msg.get("content") == self.system_prompt:
                    # Drop existing duplicate of the global prompt
                    prompt_already_present = True
                else:
                    # KEEP other system messages (action results, etc.)
                    processed.append(msg)
            else:
                processed.append(msg)

        # Ensure the global system prompt is in slot‑0
        if not prompt_already_present:
            processed.insert(0, {"role": "system", "content": self.system_prompt})
        else:
            # If some other message grabbed index‑0, still enforce the prompt first
            if processed and processed[0].get("content") != self.system_prompt:
                processed.insert(0, {"role": "system", "content": self.system_prompt})

        return processed

    def _extract_diagnostic_id(self, message: str) -> Optional[str]:
        marker = "diag_id="
        start = message.find(marker)
        if start < 0:
            return None

        raw = message[start + len(marker) :]
        chars: List[str] = []
        for char in raw:
            if char.isalnum() or char in {"_", "-"}:
                chars.append(char)
                continue
            break

        value = "".join(chars).strip()
        return value or None

    def _classify_handler_exception(self, error: Exception) -> str:
        if isinstance(error, LLMProviderError):
            return error.category.value
        if isinstance(
            error, (asyncio.TimeoutError, TimeoutError, httpx.TimeoutException)
        ):
            return "timeout"
        if isinstance(error, httpx.HTTPError):
            return "network"

        detail = str(error).lower()
        if "reauth required" in detail or "missing access token" in detail:
            return "auth"
        if "access token expired" in detail:
            return "auth"
        if "status=401" in detail or "status=403" in detail:
            return "auth"
        if "status=400" in detail or "status=404" in detail or "status=422" in detail:
            return "upstream_request"
        if "error code: 400" in detail:
            return "upstream_request"
        if "maximum context length" in detail or "requested about" in detail:
            return "upstream_request"
        if "status=429" in detail:
            return "rate_limit"
        if "status=500" in detail or "status=502" in detail or "status=503" in detail:
            return "upstream_unavailable"
        if "request_timeout" in detail or "stream_timeout" in detail:
            return "timeout"
        return "runtime"

    def _coerce_handler_error(self, error: Exception) -> LLMError:
        if isinstance(error, LLMProviderError):
            return error.error

        return build_llm_error(
            message=str(error),
            provider=getattr(self.model_config, "provider", None),
            model=getattr(self.model_config, "model", None),
            category=self._classify_handler_exception(error),
        )

    def _get_handler_error(self) -> Optional[LLMError]:
        handler = getattr(self, "client_handler", None)
        getter = getattr(handler, "get_last_error", None)
        if not callable(getter):
            return None
        try:
            error = getter()
        except Exception:
            self.logger.debug("Failed to get handler error", exc_info=True)
            return None
        return error if isinstance(error, LLMError) else None

    def get_last_error(self) -> Optional[LLMError]:
        """Return canonical error metadata from the latest request."""

        if not isinstance(self._last_error, LLMError):
            return None
        return self._last_error

    def get_reasoning_debug_snapshot(self) -> Dict[str, Any]:
        """Return handler-provided reasoning debug details when available."""

        handler = getattr(self, "client_handler", None)
        getter = getattr(handler, "get_reasoning_debug_snapshot", None)
        if callable(getter):
            try:
                snapshot = getter()
            except Exception:
                self.logger.debug(
                    "Failed to get handler reasoning debug snapshot", exc_info=True
                )
                return {}
            if isinstance(snapshot, dict):
                return dict(snapshot)
        return {}

    def _format_user_error_message(self, *, error: LLMError, diag_id: str) -> str:
        category = error.category.value
        if category == ErrorCategory.AUTH.value:
            reason = "Provider authentication failed. Reconnect and retry"
        elif category == ErrorCategory.TIMEOUT.value:
            reason = "LLM request timed out"
        elif category == ErrorCategory.NETWORK.value:
            reason = "LLM network request failed"
        elif category in {"upstream_request", ErrorCategory.BAD_REQUEST.value}:
            reason = "LLM upstream rejected the request, likely due to context or output token limits"
        elif category == ErrorCategory.RATE_LIMIT.value:
            reason = "LLM upstream rate-limited this request"
        elif category in {
            "upstream_unavailable",
            ErrorCategory.PROVIDER_UNAVAILABLE.value,
        }:
            reason = "LLM upstream is unavailable"
        else:
            reason = "LLM request failed"

        if error.retry_after_seconds and error.retry_after_seconds > 0:
            reason = f"{reason}. Retry after {int(error.retry_after_seconds)}s"

        return f"Error: {reason}. Diagnostic ID: {diag_id}."

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: Optional[bool] = None,
        stream_callback: Optional[Callable[[str, str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """
        Get a response from the configured AI model, using the chosen client handler.

        Args:
            messages: List of message dictionaries (OpenAI format).
            max_output_tokens: Optional max output tokens to generate.
            temperature: Optional temperature parameter.
            stream: Optional override for streaming preference.
            stream_callback: Callback for handling streaming chunks. Should accept (chunk: str, message_type: str).
            **kwargs: Additional parameters to pass to the handler (e.g., reasoning config).

        Returns:
            The complete response text from the model.
        """
        if not self.client_handler:
            raise RuntimeError("APIClient handler not initialized.")

        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        use_streaming = (
            stream if stream is not None else self.model_config.streaming_enabled
        )
        prepared_messages = self._prepare_messages_with_system_prompt(messages)
        estimated_input_tokens: Optional[int] = None

        try:
            from penguin.system.execution_context import get_current_execution_context

            execution_context = get_current_execution_context()
            request_id_ctx = execution_context.request_id if execution_context else None
            session_id_ctx = (
                execution_context.session_id or execution_context.conversation_id
                if execution_context
                else None
            )
        except Exception:
            request_id_ctx = None
            session_id_ctx = None

        request_id_api = request_id_ctx or os.urandom(4).hex()
        self._last_error = None
        self.logger.info(
            f"[Request:{request_id_api}] APIClient calling handler {type(self.client_handler).__name__}.get_response session={session_id_ctx} model={getattr(self.model_config, 'model', None)} stream={use_streaming}"
        )
        try:
            safe_msgs_for_log = []
            for msg in prepared_messages:
                role = msg.get("role", "unknown")
                content_log = "[omitted]"
                if isinstance(msg.get("content"), str):
                    content_log = msg["content"][:100] + (
                        "..." if len(msg["content"]) > 100 else ""
                    )
                elif isinstance(msg.get("content"), list):
                    content_log = (
                        f"[{len(msg['content'])} parts: "
                        + ", ".join([p.get("type", "unknown") for p in msg["content"]])
                        + "]"
                    )
                safe_msgs_for_log.append({"role": role, "content": content_log})
            self.logger.debug(
                f"[Request:{request_id_api}] Messages passed to handler (summary): {safe_msgs_for_log}"
            )

            # <<<--- Add Token Count Logging ---<<<
            try:
                final_token_count = self.count_tokens(prepared_messages)
                estimated_input_tokens = final_token_count
                self.logger.info(
                    f"[Request:{request_id_api}] Estimated token count for prepared messages: {final_token_count}"
                )
                if final_token_count > (
                    self.max_history_tokens * 0.95
                ):  # Warn if close to limit
                    self.logger.warning(
                        f"[Request:{request_id_api}] Prepared message token count ({final_token_count}) is close to limit ({self.max_history_tokens})."
                    )
            except Exception as count_err:
                self.logger.warning(
                    f"[Request:{request_id_api}] Failed to count tokens for prepared messages: {count_err}"
                )
            # >>> --- End Token Count Logging --- >>>

        except Exception as log_err:
            self.logger.warning(
                f"[Request:{request_id_api}] Error creating safe log/counting tokens for prepared_messages: {log_err}"
            )
        # >>>------------------------------------------- >>>

        try:
            # --- Ideal Flow (Enforce Interface - See Step 2) ---
            if not hasattr(self.client_handler, "get_response"):
                # This should ideally not happen if Step 2 is done.
                self.logger.error(
                    f"CRITICAL: Client handler {type(self.client_handler).__name__} missing required 'get_response' method!"
                )
                return f"[Error: Handler {type(self.client_handler).__name__} interface mismatch]"

            # Normalize callback to async (chunk, message_type) signature
            effective_callback = (
                adapt_stream_callback(stream_callback) if use_streaming else None
            )
            self.logger.debug(
                f"[APIClient:{request_id_api}] Calling {type(self.client_handler).__name__}.get_response. Streaming: {use_streaming}. Callback: {effective_callback is not None}"
            )

            self.logger.info(
                f"[APIClient:{request_id_api}] PRE-CALL TO HANDLER: use_streaming={use_streaming}, effective_callback is {effective_callback}"
            )

            effective_max_output_tokens = (
                max_output_tokens or self.model_config.max_output_tokens
            )
            raw_context_limit = getattr(
                self.model_config, "max_context_window_tokens", None
            )
            try:
                context_limit_int = (
                    int(raw_context_limit)
                    if raw_context_limit is not None and int(raw_context_limit) > 0
                    else None
                )
            except Exception:
                context_limit_int = None
            if (
                context_limit_int is not None
                and estimated_input_tokens is not None
                and estimated_input_tokens > 0
            ):
                available_output_tokens = max(
                    context_limit_int - estimated_input_tokens - 512,
                    1,
                )
                if (
                    effective_max_output_tokens is None
                    or effective_max_output_tokens > available_output_tokens
                ):
                    self.logger.warning(
                        "[APIClient:%s] Clamping max_output_tokens from %s to %s "
                        "based on context_limit=%s estimated_input_tokens=%s",
                        request_id_api,
                        effective_max_output_tokens,
                        available_output_tokens,
                        context_limit_int,
                        estimated_input_tokens,
                    )
                    effective_max_output_tokens = available_output_tokens

            response_text = await self.client_handler.get_response(
                messages=prepared_messages,
                max_output_tokens=effective_max_output_tokens,
                temperature=temperature
                if temperature is not None
                else self.model_config.temperature,
                stream=use_streaming,
                stream_callback=effective_callback,  # Pass the potentially wrapped async callback
                **kwargs,  # Pass through additional parameters like reasoning config
            )

            handler_error = self._get_handler_error()
            if isinstance(handler_error, LLMError):
                self._last_error = handler_error
                is_error_like = isinstance(
                    response_text, str
                ) and response_text.lstrip().startswith(
                    ("[Error:", "Error:", "[Model finished")
                )
                if is_error_like or not str(response_text or "").strip():
                    diag_id = (
                        self._extract_diagnostic_id(response_text or "")
                        or self._extract_diagnostic_id(handler_error.message)
                        or f"llm_{os.urandom(5).hex()}"
                    )
                    return self._format_user_error_message(
                        error=handler_error,
                        diag_id=diag_id,
                    )

            # If streaming, the callback handled output. Return minimal response.
            # The response_text here is the final accumulated text from the gateway.
            if use_streaming:
                logger.info(
                    f"[APIClient:{request_id_api}] Stream finished. Returning accumulated text (length: {len(response_text or '')})."
                )
                # In streaming mode, we rely on the callback for output.
                # We return the final accumulated text, but core.py might ignore it.
                return response_text or ""  # Return accumulated string

            # <<<--- ADD Check for Error/Placeholder Strings ---<<<
            if isinstance(response_text, str):
                if response_text.startswith("[Error:") or response_text.startswith(
                    "[Model finished"
                ):
                    self.logger.warning(
                        f"[Request:{request_id_api}] Handler returned non-content string: {response_text}"
                    )
                    # Propagate this specific info instead of just empty?
                    # Maybe core.py needs to check for these specific strings too.
                    # For now, returning it might still trigger core's retry loop if core only checks for "" or None.
                    # Let's return it as is for now, core needs adjustment later if this is the case.

                elif not response_text.strip() and not use_streaming:
                    # Log if we get an empty string in non-streaming mode
                    self.logger.warning(
                        f"[Request:{request_id_api}] Handler returned empty string in non-streaming mode."
                    )
            # >>>----------------------------------------------->>>

            return response_text
            # --- End Ideal Flow ---

        except Exception as e:
            handler_name = type(self.client_handler).__name__
            upstream_diag_id = self._extract_diagnostic_id(str(e))
            diag_id = upstream_diag_id or f"llm_{os.urandom(5).hex()}"
            error_payload = self._coerce_handler_error(e)
            self._last_error = error_payload

            _log_error(
                "[Request:%s] llm.handler.failure diag_id=%s category=%s "
                "handler=%s provider=%s model=%s detail=%s",
                request_id_api,
                diag_id,
                error_payload.category.value,
                handler_name,
                getattr(self.model_config, "provider", "unknown"),
                getattr(self.model_config, "model", "unknown"),
                str(e),
                exc_info=True,
            )
            return self._format_user_error_message(error=error_payload, diag_id=diag_id)

    # --- Methods below might be simplified or removed if get_response handles all ---

    # process_response is likely no longer needed here, as the handler should return processed text
    # def process_response(self, response: Any) -> tuple[str, List[Any]]:
    #     """Process the raw response (delegated to handler if possible)."""
    #     # This logic is now likely within the handler's get_response or internal methods
    #     logger.warning("APIClient.process_response called - this might be deprecated.")
    #     if hasattr(self.client_handler, 'process_response'):
    #         try:
    #              # Assuming native adapter style response processing
    #              content, tool_uses = self.client_handler.process_response(response)
    #              return content, tool_uses
    #         except Exception as e:
    #              logger.error(f"Error in handler's process_response: {e}", exc_info=True)
    #              return f"[Error processing response: {e}]", []
    #     else:
    #          # LiteLLM gateway handles processing internally in its get_response
    #          logger.info("Handler does not have process_response, assuming processed result already handled.")
    #          # We expect get_response to return the final string now
    #          if isinstance(response, str):
    #               return response, [] # Assume response *is* the content string
    #          else:
    #               return "[Error: Unexpected response type after handler call]", []

    # create_message might be replaced by get_response logic
    # async def create_message(
    #     self,
    #     messages: List[Dict[str, Any]],
    #     max_tokens: Optional[int] = None,
    #     temperature: Optional[float] = None,
    # ) -> Any:
    #     """ Deprecated: Use get_response instead """
    #     logger.warning("APIClient.create_message called - this is likely deprecated. Use get_response.")
    #     # This logic should be part of the get_response implementation or the handler itself
    #     response_text = await self.get_response(
    #         messages=messages,
    #         max_tokens=max_tokens,
    #         temperature=temperature,
    #         stream=False # create_message implies non-streaming
    #     )
    #     # Need to return something compatible with old flow if called?
    #     # This is problematic. Better to refactor callers to use get_response.
    #     return {"choices": [{"message": {"content": response_text}}]} # Simulate OpenAI structure

    # create_streaming_completion might be replaced by get_response logic
    # async def create_streaming_completion(
    #     self,
    #     messages: List[Dict[str, Any]],
    #     max_tokens: Optional[int] = None,
    #     temperature: Optional[float] = None,
    #     stream_callback: Optional[Callable[[str], None]] = None
    # ) -> str:
    #     """ Deprecated: Use get_response with stream=True instead """
    #     logger.warning("APIClient.create_streaming_completion called - this is likely deprecated. Use get_response.")
    #     return await self.get_response(
    #          messages=messages,
    #          max_tokens=max_tokens,
    #          temperature=temperature,
    #          stream=True,
    #          stream_callback=stream_callback
    #     )

    # Token counting delegated
    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """
        Count tokens for content, using the chosen client handler.

        Args:
            content: Text or structured content to count tokens for

        Returns:
            Token count as integer
        """
        if not self.client_handler:
            self.logger.error("Cannot count tokens, client handler not initialized.")
            return len(str(content)) // 4  # Very rough fallback

        if not self.model_config.enable_token_counting:
            self.logger.debug("Token counting disabled in ModelConfig.")
            return 0

        if hasattr(self.client_handler, "count_tokens"):
            try:
                # Use the handler's count_tokens method
                return self.client_handler.count_tokens(content)
            except Exception as e:
                self.logger.warning(
                    f"Token counting failed using {type(self.client_handler).__name__}: {e}"
                )
                # Fallback to LiteLLM's generic counter if handler fails?
                try:
                    logger.info(
                        f"Falling back to LiteLLM generic token counter for model {self.model_config.model}"
                    )
                    token_counter = load_litellm_module(
                        "LiteLLM token counting fallback"
                    ).token_counter
                    # Ensure model name is suitable for LiteLLM counter
                    model_for_counting = self.model_config.model
                    if isinstance(content, str):
                        return token_counter(model=model_for_counting, text=content)
                    elif isinstance(content, list):
                        # Assume OpenAI message format for LiteLLM counter
                        return token_counter(model=model_for_counting, messages=content)
                    else:
                        return len(str(content)) // 4  # Rough fallback
                except Exception as litellm_e:
                    self.logger.error(
                        f"LiteLLM generic token counter also failed: {litellm_e}"
                    )
                    return len(str(content)) // 4  # Final rough fallback
        else:
            self.logger.warning(
                f"Client handler {type(self.client_handler).__name__} does not implement count_tokens."
            )
            # Fallback to LiteLLM generic counter?
            try:
                logger.info(
                    f"Falling back to LiteLLM generic token counter for model {self.model_config.model}"
                )
                token_counter = load_litellm_module(
                    "LiteLLM token counting fallback"
                ).token_counter
                model_for_counting = self.model_config.model
                if isinstance(content, str):
                    return token_counter(model=model_for_counting, text=content)
                elif isinstance(content, list):
                    return token_counter(model=model_for_counting, messages=content)
                else:
                    return len(str(content)) // 4
            except Exception as litellm_e:
                self.logger.error(
                    f"LiteLLM generic token counter also failed: {litellm_e}"
                )
                return len(str(content)) // 4

    def _truncate_history(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Truncate the conversation history to fit within the maximum token limit,
        using the handler's token counting method.
        """
        total_tokens = 0
        truncated_messages = []
        # Ensure system prompt is preserved if present (should be first)
        system_msg = None
        processed_messages = messages[:]  # Copy
        if processed_messages and processed_messages[0].get("role") == "system":
            system_msg = processed_messages.pop(0)
            # Count system prompt tokens separately
            system_tokens = (
                self.count_tokens(system_msg["content"]) if system_msg else 0
            )
            total_tokens += system_tokens

        # Iterate through remaining messages in reverse
        for message in reversed(processed_messages):
            # Count tokens for the current message
            message_tokens = self.count_tokens(
                message
            )  # Use the central count_tokens method

            if total_tokens + message_tokens > self.max_history_tokens:
                self.logger.warning(
                    f"Truncating history: Limit {self.max_history_tokens}, "
                    f"Current total {total_tokens}, "
                    f"Next msg tokens {message_tokens}. Stopping."
                )
                break
            total_tokens += message_tokens
            truncated_messages.insert(0, message)  # Add to the beginning

        # Re-add system prompt if it existed
        if system_msg:
            truncated_messages.insert(0, system_msg)

        num_truncated = len(messages) - len(truncated_messages)
        if num_truncated > 0:
            self.logger.info(
                f"Truncated {num_truncated} messages from history. "
                f"Final token count (approx): {total_tokens}"
            )

        return truncated_messages

    def encode_image_to_base64(self, image_path: str) -> str:
        """
        Encode an image file to a base64 string. (Moved to gateway, keep here for compatibility?)
        This might only be relevant for native adapters that don't handle it.
        LiteLLM gateway handles encoding internally. Let's keep it for now.
        """
        # ... (encode_image_to_base64 remains the same) ...
        try:
            with Image.open(image_path) as img:
                max_size = (1024, 1024)
                resampling_namespace = getattr(Image, "Resampling", Image)
                img.thumbnail(
                    max_size,
                    getattr(Image, "LANCZOS", getattr(resampling_namespace, "LANCZOS")),
                )
                if img.mode != "RGB":
                    img = img.convert("RGB")
                img_byte_arr = io.BytesIO()
                img.save(img_byte_arr, format="JPEG")
                return base64.b64encode(img_byte_arr.getvalue()).decode("utf-8")
        except Exception as e:
            self.logger.error(f"Error encoding image {image_path}: {str(e)}")
            return f"Error encoding image: {str(e)}"

    def reset(self):
        """Reset the client state (primarily the system prompt)."""
        # self.messages = [] # History is managed by the caller (e.g., Core)
        # Resetting the handler might be complex, just clear the prompt for now
        self.system_prompt = None
        self.logger.info("APIClient state reset (system prompt cleared).")
        # Re-applying system prompt might require calling set_system_prompt again by caller
