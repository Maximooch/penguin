import asyncio
import base64
import inspect
import json
import logging
import os
import time
import traceback
from typing import Any, Callable, Dict, List, Optional, Set, Tuple, Union

import anthropic
from anthropic import AsyncAnthropic

from penguin.constants import get_default_max_output_tokens
from penguin.system.native_tool_history import sanitize_native_tool_messages

from ..contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMPreparedRequest,
    LLMProviderCapabilities,
    LLMRequestLifecycle,
    LLMUsage,
    ProviderRequestStatus,
)
from ..model_config import ModelConfig
from ..provider_transform import build_llm_error, normalize_finish_reason
from ..reasoning_variants import anthropic_reasoning_efforts
from .base import BaseAdapter

logger = logging.getLogger(__name__)


class AnthropicAdapter(BaseAdapter):
    """Direct Anthropic SDK adapter"""

    def __init__(self, model_config: ModelConfig):
        self.model_config = model_config
        self.api_key = os.getenv("ANTHROPIC_API_KEY")

        if not self.api_key:
            raise ValueError("ANTHROPIC_API_KEY environment variable is required")

        # Initialize synchronous client for token counting
        self.sync_client = anthropic.Anthropic(api_key=self.api_key)

        # Initialize async client for message creation
        # Runtime owns the one safe replay. Disable the SDK's hidden retries so
        # one logical Penguin request cannot issue more than two physical sends.
        self.async_client = AsyncAnthropic(api_key=self.api_key, max_retries=0)
        self._last_usage: Dict[str, Any] = {}
        self._last_error: Optional[LLMError] = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_tool_call: Optional[Dict[str, Any]] = None
        self._pending_tool_calls: List[Dict[str, Any]] = []
        self._tool_use_accs: Dict[int, Dict[str, Any]] = {}
        self._last_request_lifecycle: Optional[LLMRequestLifecycle] = None

        # Add a logger for the adapter
        self.logger = logging.getLogger(__name__)

    @property
    def provider(self) -> str:
        return "anthropic"

    def _reset_response_state(self) -> None:
        self._last_usage = {}
        self._last_error = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_tool_call = None
        self._pending_tool_calls = []
        self._tool_use_accs = {}

    def _set_last_error(self, error: Optional[LLMError]) -> None:
        self._last_error = error

    def get_last_error(self) -> Optional[LLMError]:
        return self._last_error if isinstance(self._last_error, LLMError) else None

    def get_last_request_lifecycle(self) -> Optional[LLMRequestLifecycle]:
        return self._last_request_lifecycle

    def _start_request_lifecycle(
        self,
        *,
        stream: bool,
        messages: List[Dict[str, Any]],
    ) -> None:
        now = time.time()
        self._last_request_lifecycle = LLMRequestLifecycle(
            request_id=f"anthropic-{int(now * 1000)}",
            provider=self.provider,
            model=getattr(self.model_config, "model", ""),
            status=ProviderRequestStatus.RUNNING,
            stream=stream,
            transport="sdk",
            started_at=now,
            last_event_at=now,
            provider_data={"message_count": len(messages)},
        )

    def _update_request_lifecycle(
        self,
        *,
        status: ProviderRequestStatus,
        finish_reason: Optional[FinishReason] = None,
        error: Optional[LLMError] = None,
        event_type: Optional[str] = None,
        provider_response_id: Optional[str] = None,
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
        if finish_reason is not None:
            lifecycle.finish_reason = finish_reason
        if error is not None:
            lifecycle.error = error
        if event_type:
            lifecycle.last_event_type = event_type
        if provider_response_id:
            lifecycle.provider_response_id = provider_response_id

    def _finish_request_lifecycle_from_state(self) -> None:
        error = self.get_last_error()
        if error is not None:
            status = (
                ProviderRequestStatus.DISCONNECTED
                if error.category in {ErrorCategory.NETWORK, ErrorCategory.TIMEOUT}
                else ProviderRequestStatus.FAILED
            )
            self._update_request_lifecycle(
                status=status,
                finish_reason=error.finish_reason or self.get_last_finish_reason(),
                error=error,
            )
            return
        self._update_request_lifecycle(
            status=ProviderRequestStatus.COMPLETED,
            finish_reason=self.get_last_finish_reason(),
        )

    def _set_last_finish_reason(self, finish_reason: Any) -> FinishReason:
        self._last_finish_reason = normalize_finish_reason(finish_reason)
        return self._last_finish_reason

    def get_last_finish_reason(self) -> FinishReason:
        return self._last_finish_reason

    def _anthropic_stream_error_detail(self, chunk: Any) -> str:
        error_payload = getattr(chunk, "error", None)
        if isinstance(error_payload, dict):
            message = error_payload.get("message")
            if isinstance(message, str) and message.strip():
                return message.strip()
            return str(error_payload)[:500]
        message = getattr(error_payload, "message", None)
        if isinstance(message, str) and message.strip():
            return message.strip()
        return str(error_payload or chunk)[:500]

    def _record_anthropic_stream_error(self, chunk: Any) -> LLMError:
        partial_tool_call = self.has_pending_tool_call()
        error = build_llm_error(
            message=self._anthropic_stream_error_detail(chunk),
            provider=self.provider,
            model=getattr(self.model_config, "model", None),
            finish_reason=FinishReason.ERROR,
            provider_data={"partial_tool_call": partial_tool_call},
        )
        self._set_last_error(error)
        self._set_last_finish_reason(FinishReason.ERROR)
        if partial_tool_call:
            self._pending_tool_calls = []
            self._last_tool_call = None
            self._tool_use_accs = {}
        return error

    def _record_anthropic_stream_incomplete(self, output_state: str) -> LLMError:
        partial_tool_call = output_state == "tool_call" or self.has_pending_tool_call()
        error = build_llm_error(
            message=(
                "Anthropic stream ended before message_stop "
                f"(output_state={output_state})"
            ),
            provider=self.provider,
            model=getattr(self.model_config, "model", None),
            category=ErrorCategory.NETWORK,
            retryable=True,
            finish_reason=FinishReason.ERROR,
            provider_data={"partial_tool_call": partial_tool_call},
        )
        self._set_last_error(error)
        self._set_last_finish_reason(FinishReason.ERROR)
        self._pending_tool_calls = []
        self._last_tool_call = None
        self._tool_use_accs = {}
        return error

    def _append_reasoning(self, text: str) -> None:
        if text:
            self._last_reasoning += text

    def get_last_reasoning(self) -> str:
        return self._last_reasoning

    def _usage_to_dict(self, usage: Any) -> Dict[str, Any]:
        if isinstance(usage, dict):
            return usage
        if hasattr(usage, "model_dump"):
            try:
                dumped = usage.model_dump()
                if isinstance(dumped, dict):
                    return dumped
            except Exception:
                pass
        try:
            dumped = vars(usage)
            if isinstance(dumped, dict):
                return dumped
        except Exception:
            pass
        return {}

    def _set_last_usage(self, usage: Any) -> None:
        payload = self._usage_to_dict(usage)
        if not payload:
            return
        normalized = LLMUsage.from_dict(
            {
                "input_tokens": payload.get("input_tokens"),
                "output_tokens": payload.get("output_tokens"),
                "cache_read_tokens": payload.get("cache_read_input_tokens"),
                "cache_write_tokens": payload.get("cache_creation_input_tokens"),
                "total_tokens": payload.get("total_tokens"),
            }
        )
        self._last_usage = normalized.to_dict()

    def get_last_usage(self) -> Dict[str, Any]:
        """Return normalized usage from the most recent Anthropic request."""
        if not isinstance(getattr(self, "_last_usage", None), dict):
            return {}
        return dict(self._last_usage)

    def get_capabilities(self) -> LLMProviderCapabilities:
        """Return Anthropic Messages capability metadata."""

        return LLMProviderCapabilities(
            provider=self.provider,
            model=str(getattr(self.model_config, "model", "") or ""),
            native_tools=True,
            streaming=bool(getattr(self.model_config, "streaming_enabled", True)),
            reasoning=bool(
                getattr(self.model_config, "reasoning_enabled", False)
                or self.model_config.get_reasoning_config()
            ),
            reasoning_efforts=anthropic_reasoning_efforts(self.model_config.model),
            vision=self.supports_vision(),
            max_context_tokens=getattr(
                self.model_config,
                "max_context_window_tokens",
                None,
            ),
            max_output_tokens=getattr(self.model_config, "max_output_tokens", None),
            provider_data={"api": "messages"},
        )

    async def prepare_request(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        """Prepare an Anthropic Messages request without sending it."""

        legacy_max_tokens = kwargs.pop("max_tokens", None)
        if max_output_tokens is None and legacy_max_tokens is not None:
            max_output_tokens = legacy_max_tokens

        formatted_messages = self.format_messages(messages)
        system_message = None
        for msg in messages:
            if msg.get("role") == "system":
                system_message = msg.get("content", "")
                if system_message:
                    system_message = str(system_message).rstrip()
                break

        request_params: Dict[str, Any] = {
            "model": self.model_config.model,
            "messages": formatted_messages,
            "max_tokens": max_output_tokens
            or self.model_config.max_output_tokens
            or 4096,
            "temperature": temperature or self.model_config.temperature or 0.7,
            "stream": stream,
        }
        if system_message:
            request_params["system"] = system_message
        if kwargs.get("tools"):
            request_params["tools"] = kwargs["tools"]
        if kwargs.get("tool_choice"):
            request_params["tool_choice"] = kwargs["tool_choice"]

        reasoning_config = self.model_config.get_reasoning_config()
        self._apply_output_effort(request_params, reasoning_config)
        self._ensure_no_trailing_whitespace(request_params)

        return LLMPreparedRequest(
            provider=self.provider,
            model=str(self.model_config.model),
            protocol="anthropic_messages",
            route="anthropic.messages",
            body={
                key: value for key, value in request_params.items() if value is not None
            },
            transport="sdk_stream" if stream else "sdk",
            capabilities=self.get_capabilities(),
            diagnostics={
                "message_count": len(messages),
                "formatted_message_count": len(formatted_messages),
                "stream": stream,
            },
        )

    def has_pending_tool_call(self) -> bool:
        return bool(
            isinstance(getattr(self, "_last_tool_call", None), dict)
            and self._last_tool_call.get("name")
        ) or any(
            isinstance(tool_call, dict) and bool(tool_call.get("name"))
            for tool_call in getattr(self, "_pending_tool_calls", [])
        )

    def get_and_clear_last_tool_call(self) -> Optional[Dict[str, Any]]:
        pending = self.get_and_clear_pending_tool_calls()
        return pending[-1] if pending else None

    def get_and_clear_pending_tool_calls(self) -> List[Dict[str, Any]]:
        pending = [
            dict(tool_call)
            for tool_call in getattr(self, "_pending_tool_calls", [])
            if isinstance(tool_call, dict) and tool_call.get("name")
        ]
        if not pending and isinstance(getattr(self, "_last_tool_call", None), dict):
            pending = [dict(self._last_tool_call)]
        self._pending_tool_calls = []
        self._last_tool_call = None
        self._tool_use_accs = {}
        return pending

    def _remember_tool_use(
        self,
        *,
        tool_id: Optional[str],
        name: Optional[str],
        arguments: str,
    ) -> None:
        if not name:
            return
        if not hasattr(self, "_pending_tool_calls"):
            self._pending_tool_calls = []
        remembered = {
            "item_id": tool_id,
            "call_id": tool_id,
            "name": name,
            "arguments": arguments or "{}",
        }
        existing_index = next(
            (
                index
                for index, pending in enumerate(self._pending_tool_calls)
                if tool_id and pending.get("call_id") == tool_id
            ),
            None,
        )
        if existing_index is None:
            self._pending_tool_calls.append(remembered)
        else:
            self._pending_tool_calls[existing_index] = remembered
        self._last_tool_call = remembered
        self._set_last_finish_reason(FinishReason.TOOL_CALLS)

    def _record_tool_use_start(self, chunk: Any) -> None:
        if not hasattr(self, "_tool_use_accs"):
            self._tool_use_accs = {}
        content_block = getattr(chunk, "content_block", None)
        if content_block is None:
            return
        try:
            index = int(getattr(chunk, "index", len(self._tool_use_accs)))
        except Exception:
            index = len(self._tool_use_accs)
        tool_input = getattr(content_block, "input", {}) or {}
        arguments = json.dumps(tool_input, separators=(",", ":")) if tool_input else ""
        acc = {
            "tool_id": getattr(content_block, "id", None),
            "name": getattr(content_block, "name", None),
            "arguments": arguments,
        }
        self._tool_use_accs[index] = acc
        self._remember_tool_use(
            tool_id=acc.get("tool_id"),
            name=acc.get("name"),
            arguments=arguments or "{}",
        )

    def _record_tool_use_delta(self, chunk: Any) -> None:
        if not hasattr(self, "_tool_use_accs"):
            self._tool_use_accs = {}
        delta = getattr(chunk, "delta", None)
        if delta is None or getattr(delta, "type", None) != "input_json_delta":
            return
        try:
            index = int(getattr(chunk, "index", 0))
        except Exception:
            index = 0
        acc = self._tool_use_accs.setdefault(
            index, {"tool_id": None, "name": None, "arguments": ""}
        )
        partial_json = getattr(delta, "partial_json", "")
        if isinstance(partial_json, str):
            acc["arguments"] = str(acc.get("arguments") or "") + partial_json
        self._remember_tool_use(
            tool_id=acc.get("tool_id"),
            name=acc.get("name"),
            arguments=str(acc.get("arguments") or "{}"),
        )

    async def create_message(
        self,
        messages: List[Dict[str, Any]],
        max_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        system_prompt: Optional[str] = None,
        **kwargs,
    ) -> Any:
        """Create a message using Anthropic's API directly"""
        try:
            # Format messages for Anthropic
            formatted_messages = self.format_messages(messages)

            # Prepare request parameters
            request_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_tokens
                or self.model_config.max_tokens
                or get_default_max_output_tokens(),
                "temperature": temperature or self.model_config.temperature or 0.4,
            }

            # Add system prompt if provided (strip trailing whitespace)
            if system_prompt:
                request_params["system"] = system_prompt.rstrip()

            if kwargs.get("tools"):
                request_params["tools"] = kwargs["tools"]
            if kwargs.get("tool_choice"):
                request_params["tool_choice"] = kwargs["tool_choice"]

            reasoning_config = self.model_config.get_reasoning_config()
            self._apply_output_effort(request_params, reasoning_config)

            # Make the API call
            # logger.warning(f"FINAL REQUEST TO ANTHROPIC: {safe_params}")

            # Log estimated input tokens before call
            try:
                input_tokens = self.count_tokens(messages)  # Count original messages
                self.logger.debug(
                    f"Estimated input tokens for Anthropic call: {input_tokens}"
                )
            except Exception as tk_err:
                self.logger.warning(
                    f"Could not estimate input tokens before call: {tk_err}"
                )

            # Add double-check for trailing whitespace in all text content
            self._ensure_no_trailing_whitespace(request_params)

            self.logger.debug(
                f"Sending non-streaming request to Anthropic: Model={request_params['model']}, MaxTokens={request_params['max_tokens']}, Temp={request_params['temperature']}, SystemPromptLength={len(request_params.get('system', ''))}, NumMessages={len(request_params['messages'])}"
            )

            response = await self.async_client.messages.create(**request_params)

            # Log the raw response object
            try:
                # Use pformat for potentially large/complex objects
                import pprint

                raw_response_str = pprint.pformat(
                    response.model_dump()
                )  # Convert pydantic model to dict for logging
                self.logger.debug(
                    f"Raw Anthropic non-streaming response object:\n{raw_response_str}"
                )
            except Exception as log_err:
                self.logger.warning(f"Error logging raw Anthropic response: {log_err}")

            return response

        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
            # Add detailed error information
            logger.error(f"Error details: {traceback.format_exc()}")
            # Check if specific Anthropic error
            if hasattr(e, "status_code"):
                logger.error(f"Anthropic API error code: {getattr(e, 'status_code')}")
            if hasattr(e, "response"):
                # Log raw error response if available
                try:
                    import pprint

                    error_response_str = pprint.pformat(getattr(e, "response"))
                    logger.error(f"Raw error response data:\n{error_response_str}")
                except Exception as log_err:
                    logger.warning(f"Error logging raw error response data: {log_err}")
            raise

    async def create_completion(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> Any:
        """Create a completion request with optional streaming"""
        try:
            legacy_max_tokens = kwargs.pop("max_tokens", None)
            if max_output_tokens is None and legacy_max_tokens is not None:
                max_output_tokens = legacy_max_tokens

            # Format messages for Anthropic
            formatted_messages = self.format_messages(messages)

            # Extract system message if present
            system_message = None
            for msg in messages:
                if msg.get("role") == "system":
                    system_message = msg.get("content", "")
                    # Strip trailing whitespace from system message
                    if system_message:
                        system_message = system_message.rstrip()
                    break

            # Prepare request parameters
            request_params = {
                "model": self.model_config.model,
                "messages": formatted_messages,
                "max_tokens": max_output_tokens
                or self.model_config.max_output_tokens
                or 4096,
                "temperature": temperature or self.model_config.temperature or 0.7,
                "stream": stream,
            }

            # Add system message if found
            if system_message:
                request_params["system"] = system_message

            if kwargs.get("tools"):
                request_params["tools"] = kwargs["tools"]
            if kwargs.get("tool_choice"):
                request_params["tool_choice"] = kwargs["tool_choice"]

            reasoning_config = self.model_config.get_reasoning_config()
            self._apply_output_effort(request_params, reasoning_config)

            # Make sure no trailing whitespace in any message
            self._ensure_no_trailing_whitespace(request_params)

            # Log estimated input tokens before call
            try:
                input_tokens = self.count_tokens(messages)  # Count original messages
                self.logger.debug(
                    f"Estimated input tokens for Anthropic call: {input_tokens}"
                )
            except Exception as tk_err:
                self.logger.warning(
                    f"Could not estimate input tokens before call: {tk_err}"
                )

            # Make the API call
            self.logger.debug(
                f"Sending request to Anthropic: Model={request_params['model']}, MaxTokens={request_params['max_tokens']}, Temp={request_params['temperature']}, SystemPromptLength={len(request_params.get('system', ''))}, NumMessages={len(request_params['messages'])}, Stream={stream}"
            )

            if stream:
                return await self._handle_streaming(request_params, stream_callback)
            else:
                response = await self.async_client.messages.create(**request_params)
                # Log the raw response object for non-streaming completion as well
                try:
                    import pprint

                    raw_response_str = pprint.pformat(response.model_dump())
                    self.logger.debug(
                        f"Raw Anthropic non-streaming completion response object:\n{raw_response_str}"
                    )
                except Exception as log_err:
                    self.logger.warning(
                        f"Error logging raw Anthropic non-streaming completion response: {log_err}"
                    )
                return response

        except Exception as e:
            logger.error(f"Error in Anthropic API call: {str(e)}")
            raise

    async def get_response(
        self,
        messages: List[Dict[str, Any]],
        max_output_tokens: Optional[int] = None,
        temperature: Optional[float] = None,
        stream: bool = False,
        stream_callback: Optional[Callable[[str], None]] = None,
        **kwargs: Any,
    ) -> str:
        """Unified entrypoint to satisfy BaseAdapter interface.

        - Streams via create_completion when stream=True and returns accumulated text
        - Non-streaming: calls create_completion and processes the response
        """
        self._reset_response_state()
        self._start_request_lifecycle(stream=stream, messages=messages)
        try:
            if stream:
                # Ensure callback is callable; pass through directly
                final_text = await self.create_completion(
                    messages=messages,
                    max_output_tokens=max_output_tokens,
                    temperature=temperature,
                    stream=True,
                    stream_callback=stream_callback,
                    **kwargs,
                )
                self._finish_request_lifecycle_from_state()
                # create_completion returns a string when streaming
                return final_text or ""

            # Non-streaming path
            response = await self.create_completion(
                messages=messages,
                max_output_tokens=max_output_tokens,
                temperature=temperature,
                stream=False,
                stream_callback=None,
                **kwargs,
            )
            content, _ = self.process_response(response)
            self._finish_request_lifecycle_from_state()
            return content or ""
        except asyncio.CancelledError:
            error = self.get_last_error() or build_llm_error(
                message="Anthropic request was cancelled",
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
        except Exception as exc:
            error = self.get_last_error() or build_llm_error(
                message=str(exc),
                provider=self.provider,
                model=getattr(self.model_config, "model", None),
                finish_reason=FinishReason.ERROR,
            )
            self._set_last_error(error)
            self._update_request_lifecycle(
                status=ProviderRequestStatus.FAILED,
                finish_reason=error.finish_reason or FinishReason.ERROR,
                error=error,
            )
            raise

    async def _handle_streaming(
        self,
        params: Dict[str, Any],
        callback: Optional[Callable[..., Any]] = None,
    ) -> str:
        """Handle streaming response from Anthropic API with enhanced error handling"""
        self._reset_response_state()
        accumulated_response = []
        stream_start_time = time.time()
        streaming_timeout = 30  # seconds
        final_response_object = None  # To store the final message object
        stream_error = None  # To store any exception during streaming
        stop_reason = None  # To store the stop reason if available
        usage_info = None  # To store usage info if available
        chunk_count = 0
        received_content = False
        saw_message_stop = False

        try:
            # Create the streaming response
            stream = await self.async_client.messages.create(**params)

            # Track content reception
            last_chunk_time = time.time()
            chunk_timeout = 10  # seconds

            # Process each chunk as it comes in
            async for chunk in stream:
                last_chunk_time = time.time()
                chunk_count += 1
                self._update_request_lifecycle(
                    status=ProviderRequestStatus.STREAMING,
                    event_type=str(getattr(chunk, "type", "")) or None,
                )

                # Extract text content based on chunk type
                content = None

                try:
                    # Handle different event types
                    self.logger.debug(
                        f"Received chunk type: {chunk.type} (Chunk {chunk_count})"
                    )
                    if hasattr(chunk, "type"):
                        if chunk.type == "message_stop":
                            saw_message_stop = True
                            # Capture the final response object from the stream if possible
                            # Note: The structure might vary, need to check Anthropic docs/examples
                            # For now, just log that we stopped. The final object might not be in the chunk itself.
                            self.logger.debug(
                                "Stream processing stopped due to 'message_stop' event."
                            )
                            # We might get the final message object *after* the loop, see below
                        elif chunk.type == "error":
                            stream_error = self._record_anthropic_stream_error(chunk)
                            self.logger.error(
                                "Anthropic stream error event: %s",
                                stream_error.message,
                            )
                            break

                        elif chunk.type == "content_block_delta" and hasattr(
                            chunk, "delta"
                        ):
                            if chunk.delta.type == "text_delta" and hasattr(
                                chunk.delta, "text"
                            ):
                                content = chunk.delta.text
                            elif chunk.delta.type == "thinking_delta" and hasattr(
                                chunk.delta, "thinking"
                            ):
                                content = chunk.delta.thinking
                                if content:
                                    self._append_reasoning(content)
                                    if callback:
                                        await self._safe_invoke_callback(
                                            callback, content, "reasoning"
                                        )
                                    continue
                            elif chunk.delta.type == "input_json_delta":
                                self._record_tool_use_delta(chunk)
                                continue

                        elif chunk.type == "content_block_start" and hasattr(
                            chunk, "content_block"
                        ):
                            if chunk.content_block.type == "text" and hasattr(
                                chunk.content_block, "text"
                            ):
                                content = chunk.content_block.text
                            elif chunk.content_block.type == "tool_use":
                                self._record_tool_use_start(chunk)

                        elif (
                            chunk.type == "message_delta"
                            and hasattr(chunk, "usage")
                            and hasattr(chunk, "stop_reason")
                        ):
                            # Capture usage and stop reason from message_delta if available
                            stop_reason = chunk.stop_reason
                            self._set_last_finish_reason(stop_reason)
                            usage_info = chunk.usage
                            self.logger.debug(
                                f"Received message_delta: stop_reason={stop_reason}, usage={usage_info}"
                            )

                    # Process extracted content
                    if content:
                        received_content = True
                        # self.logger.debug(f"Extracted content from chunk {chunk_count}: {content[:20]}...") # Less verbose logging
                        # Call the callback with the content
                        if callback:
                            await self._safe_invoke_callback(
                                callback, content, "assistant"
                            )
                        # Add to accumulated response
                        accumulated_response.append(content)

                except Exception as e:
                    error_msg = f"Error processing chunk {chunk_count}: {str(e)}"
                    self.logger.error(f"{error_msg}\n{traceback.format_exc()}")

                # Check for chunk timeout
                current_time = time.time()
                if current_time - last_chunk_time > chunk_timeout:
                    self.logger.warning(
                        f"No chunks received for {chunk_timeout} seconds, stopping stream"
                    )
                    stream_error = TimeoutError(f"Chunk timeout after {chunk_timeout}s")
                    break

                # Check for overall timeout
                if current_time - stream_start_time > streaming_timeout:
                    self.logger.warning(
                        f"Streaming exceeded timeout of {streaming_timeout} seconds, stopping"
                    )
                    stream_error = TimeoutError(
                        f"Streaming timeout after {streaming_timeout}s"
                    )
                    break

            # ---- After the loop ----
            # Try to get the final message object AFTER the stream completes
            try:
                final_response_object = await stream.get_final_message()
                if final_response_object:
                    # Log the raw final message object from the stream
                    import pprint

                    final_object_str = pprint.pformat(
                        final_response_object.model_dump()
                    )
                    self.logger.debug(
                        f"Raw Anthropic final message object from stream:\n{final_object_str}"
                    )
                    # Extract final stop reason and usage if not already captured
                    if not stop_reason:
                        stop_reason = final_response_object.stop_reason
                    self._update_request_lifecycle(
                        status=ProviderRequestStatus.STREAMING,
                        provider_response_id=getattr(final_response_object, "id", None),
                    )
                    self._set_last_finish_reason(stop_reason)
                    if not usage_info:
                        usage_info = final_response_object.usage
            except Exception as e:
                self.logger.warning(
                    f"Could not get final message object from stream: {e}"
                )

            self._set_last_usage(usage_info)

            # Log streaming stats
            total_stream_time = time.time() - stream_start_time
            self.logger.info(
                f"Streaming complete: {chunk_count} chunks in {total_stream_time:.2f}s. Received content: {received_content}. Stop Reason: {stop_reason}. Usage: {usage_info}. Error: {stream_error}"
            )

            # Join all chunks to get the complete response
            complete_response = "".join(accumulated_response)

            if not saw_message_stop and stream_error is None:
                output_state = (
                    "tool_call"
                    if self.has_pending_tool_call()
                    else "text"
                    if complete_response
                    else "empty"
                )
                stream_error = self._record_anthropic_stream_incomplete(output_state)

            if stream_error:
                error_message = str(stream_error)
                if isinstance(stream_error, LLMError):
                    error_message = stream_error.message
                    self._set_last_error(stream_error)
                else:
                    partial_tool_call = self.has_pending_tool_call()
                    stream_error = build_llm_error(
                        message=error_message,
                        provider=self.provider,
                        model=getattr(self.model_config, "model", None),
                        category=(
                            ErrorCategory.TIMEOUT
                            if isinstance(stream_error, TimeoutError)
                            else ErrorCategory.NETWORK
                        ),
                        retryable=True,
                        finish_reason=FinishReason.ERROR,
                        provider_data={
                            "partial_tool_call": partial_tool_call,
                            "partial_output": complete_response,
                        },
                    )
                    self._set_last_error(stream_error)
                    if partial_tool_call:
                        self._pending_tool_calls = []
                        self._last_tool_call = None
                        self._tool_use_accs = {}
                self._set_last_finish_reason(FinishReason.ERROR)
                if complete_response:
                    return (
                        f"{complete_response}\n\n"
                        f"[Error: Stream interrupted by Anthropic: {error_message}]"
                    )
                return f"Error during response generation: {error_message}"

            if not complete_response.strip() and self.has_pending_tool_call():
                self._set_last_finish_reason(FinishReason.TOOL_CALLS)
                return ""

            # Validate the response
            if not received_content or len(complete_response.strip()) <= 5:
                # Handle suspiciously short responses
                self.logger.warning(
                    f"Suspiciously short response received: '{complete_response}'. Stop Reason: {stop_reason}, Usage: {usage_info}"
                )

                # Check if it's effectively empty (just whitespace or minimal punctuation)
                if (
                    complete_response.strip() in ["", ".", "?", "!", ","]
                    or len(complete_response.strip()) <= 1
                ):
                    error_message = f"I encountered an issue generating a response. The connection may have been interrupted or the response filtered. Stop Reason: {stop_reason}"
                    self.logger.error(
                        f"Empty response detected: '{complete_response}'. Stop Reason: {stop_reason}, Usage: {usage_info}"
                    )
                    self._set_last_error(
                        build_llm_error(
                            message=error_message,
                            provider=self.provider,
                            model=getattr(self.model_config, "model", None),
                            finish_reason=stop_reason,
                        )
                    )

                    # If we got nothing but have some chunks, try to salvage
                    if chunk_count > 0:
                        return error_message
                    else:
                        # Truly empty - raise exception to trigger retry
                        raise ValueError(
                            f"Stream produced no content. Stop Reason: {stop_reason}"
                        )

            # Add detailed debugging for very short responses
            if 1 < len(complete_response.strip()) <= 5:
                self.logger.warning(
                    f"Very short but non-empty response: '{complete_response}', from {chunk_count} chunks. Stop Reason: {stop_reason}"
                )

            self.logger.debug(
                f"Returning final accumulated streaming response (length {len(complete_response)} chars)"
            )
            self._set_last_finish_reason(stop_reason or FinishReason.STOP)
            return complete_response

        except asyncio.CancelledError:
            self.logger.warning("Anthropic streaming was cancelled")
            partial_output = "".join(accumulated_response)
            partial_tool_call = self.has_pending_tool_call()
            error = build_llm_error(
                message="Anthropic streaming request was cancelled",
                provider=self.provider,
                model=getattr(self.model_config, "model", None),
                category=ErrorCategory.RUNTIME,
                retryable=False,
                finish_reason=FinishReason.ERROR,
                provider_data={
                    "partial_output": partial_output,
                    "partial_tool_call": partial_tool_call,
                },
            )
            self._set_last_error(error)
            self._set_last_finish_reason(FinishReason.ERROR)
            if partial_tool_call:
                self._pending_tool_calls = []
                self._last_tool_call = None
                self._tool_use_accs = {}
            self._update_request_lifecycle(
                status=ProviderRequestStatus.CANCELLED,
                finish_reason=FinishReason.ERROR,
                error=error,
            )
            raise

        except Exception as e:
            stream_error = e
            error_msg = f"Error during Anthropic streaming: {str(e)}"
            self.logger.error(f"{error_msg}\n{traceback.format_exc()}")

            # Log more details about the streaming state
            elapsed_time = time.time() - stream_start_time
            self.logger.error(
                f"Stream error details: elapsed_time={elapsed_time:.2f}s, chunks_received={chunk_count}, stop_reason={stop_reason}, usage={usage_info}"
            )
            partial_tool_call = self.has_pending_tool_call()
            self._set_last_error(
                build_llm_error(
                    message=error_msg,
                    provider=self.provider,
                    model=getattr(self.model_config, "model", None),
                    finish_reason=stop_reason,
                    provider_data={
                        "partial_tool_call": partial_tool_call,
                        "partial_output": "".join(accumulated_response),
                    },
                )
            )
            if partial_tool_call:
                self._pending_tool_calls = []
                self._last_tool_call = None
                self._tool_use_accs = {}

            if callback:
                await self._safe_invoke_callback(
                    callback,
                    f"\n[Streaming Error: {str(e)}]",
                    "assistant",
                )

            # Return partial response if we have any content
            if accumulated_response:
                self.logger.info(
                    f"Returning partial response despite error ({chunk_count} chunks)"
                )
                return "".join(accumulated_response)

            # Otherwise return an error message including stop reason if available
            return f"Error during response generation: {str(e)}. Stop Reason: {stop_reason}"
        finally:
            # Log final state regardless of how we exited
            total_stream_time = time.time() - stream_start_time
            self.logger.info(
                f"Exiting _handle_streaming: Time={total_stream_time:.2f}s, Chunks={chunk_count}, ReceivedContent={received_content}, StopReason={stop_reason}, Usage={usage_info}, Error={stream_error}"
            )

    async def _safe_invoke_callback(
        self,
        callback: Callable[..., Any],
        chunk: str,
        message_type: str,
    ) -> None:
        """Invoke callback safely supporting sync/async and legacy signatures."""
        try:
            params = []
            try:
                params = list(inspect.signature(callback).parameters.keys())
            except Exception:
                params = []

            if asyncio.iscoroutinefunction(callback):
                if len(params) >= 2:
                    await callback(chunk, message_type)
                else:
                    await callback(chunk)
            else:
                loop = asyncio.get_running_loop()
                if len(params) >= 2:
                    await loop.run_in_executor(None, callback, chunk, message_type)
                else:
                    await loop.run_in_executor(None, callback, chunk)
        except Exception as exc:
            self.logger.error("Error in Anthropic stream callback: %s", exc)

    def _apply_output_effort(
        self,
        request_params: Dict[str, Any],
        reasoning_config: Optional[Dict[str, Any]],
    ) -> None:
        """Apply Anthropic output_config.effort when supported by request config."""
        if not isinstance(reasoning_config, dict):
            return

        effort = reasoning_config.get("effort")
        if not isinstance(effort, str) or not effort.strip():
            return
        effort_value = effort.strip().lower()
        if effort_value not in {"low", "medium", "high", "max"}:
            return

        extra_body = request_params.get("extra_body")
        extra_payload: Dict[str, Any]
        if isinstance(extra_body, dict):
            extra_payload = dict(extra_body)
        else:
            extra_payload = {}

        output_config = extra_payload.get("output_config")
        output_payload: Dict[str, Any]
        if isinstance(output_config, dict):
            output_payload = dict(output_config)
        else:
            output_payload = {}

        output_payload["effort"] = effort_value
        extra_payload["output_config"] = output_payload
        request_params["extra_body"] = extra_payload

    def process_response(self, response: Any) -> Tuple[str, List[Any]]:
        """Process Anthropic API response into standardized format"""
        try:
            # Log the raw response object being processed
            self.logger.debug(
                f"Processing Anthropic response of type: {type(response)}"
            )
            if hasattr(response, "model_dump"):  # Check if pydantic model
                try:
                    import pprint

                    raw_response_str = pprint.pformat(response.model_dump())
                    self.logger.debug(
                        f"Raw response object received by process_response:\n{raw_response_str}"
                    )
                except Exception as log_err:
                    self.logger.warning(
                        f"Error logging raw response in process_response: {log_err}"
                    )
            else:
                self.logger.debug(
                    f"Response object received by process_response (non-pydantic): {str(response)[:500]}..."
                )  # Log snippet if not easily dumpable

            # Handle AsyncAnthropic Message object (from non-streaming calls)
            if hasattr(response, "content") and hasattr(response, "stop_reason"):
                stop_reason = response.stop_reason
                self._set_last_finish_reason(stop_reason)
                usage = getattr(response, "usage", None)
                self._set_last_usage(usage)

                # Extract text from content blocks
                text_content = []
                if response.content:  # Ensure content is not None or empty
                    for block in response.content:
                        # Check if block is a ContentBlock pydantic model or dict
                        block_type = getattr(block, "type", None) or (
                            isinstance(block, dict) and block.get("type")
                        )
                        block_text = getattr(block, "text", None) or (
                            isinstance(block, dict) and block.get("text")
                        )

                        if block_type == "text" and block_text is not None:
                            text_content.append(block_text)
                        elif block_type == "tool_use":
                            tool_input = (
                                getattr(block, "input", None)
                                or (isinstance(block, dict) and block.get("input"))
                                or {}
                            )
                            tool_name = getattr(block, "name", None) or (
                                isinstance(block, dict) and block.get("name")
                            )
                            tool_id = getattr(block, "id", None) or (
                                isinstance(block, dict) and block.get("id")
                            )
                            self._remember_tool_use(
                                tool_id=tool_id,
                                name=tool_name,
                                arguments=json.dumps(
                                    tool_input,
                                    separators=(",", ":"),
                                ),
                            )
                        else:
                            self.logger.warning(
                                f"Skipping non-text or empty text block in response content: type={block_type}"
                            )
                else:
                    # Content is empty, log the reason
                    self.logger.warning(
                        f"Response object has no content blocks. Stop Reason: {stop_reason}, Usage: {usage}"
                    )

                final_text = "\n".join(text_content)
                self.logger.debug(
                    f"Extracted text from non-streaming response (Length: {len(final_text)}): '{final_text[:100]}...' Stop Reason: {stop_reason}, Usage: {usage}"
                )

                # Check stop reason - handle empty content with normal stop_reason
                if not final_text.strip() and stop_reason in [
                    "end_turn",
                    "stop_sequence",
                ]:
                    self.logger.warning(
                        f"Empty content extracted despite normal stop_reason: {stop_reason}. Returning specific message."
                    )
                    # Return a more informative message instead of just empty string
                    info_message = f"[Model finished ({stop_reason}) but produced no text content. Input Tokens: {usage.input_tokens if usage else 'N/A'}, Output Tokens: {usage.output_tokens if usage else 'N/A'}]"
                    self._set_last_error(
                        build_llm_error(
                            message=info_message,
                            provider=self.provider,
                            model=getattr(self.model_config, "model", None),
                            finish_reason=stop_reason,
                        )
                    )
                    return info_message, []
                elif not final_text.strip():
                    if self.has_pending_tool_call():
                        return "", []
                    # Handle empty content due to other stop reasons (like max_tokens)
                    self.logger.warning(
                        f"Empty content extracted, likely due to stop_reason: {stop_reason}. Returning empty string."
                    )
                    # Could return specific messages based on other stop_reasons if needed
                    # e.g., if stop_reason == 'max_tokens': return "[Response truncated due to token limit]", []

                # TODO: Add tool use extraction if Anthropic starts returning tool calls here
                tool_uses = []
                return final_text, tool_uses

            # Fallback for string response (likely from streaming completion or error handling)
            if isinstance(response, str):
                # Check if the string indicates an error or specific state from streaming
                if (
                    "[Model finished" in response
                    and "produced no text content" in response
                ):
                    # Pass through the informative message from streaming
                    self.logger.debug(
                        f"Processing informative string response from streaming: '{response[:100]}...'"
                    )
                else:
                    self.logger.debug(
                        f"Processing generic string response (Length: {len(response)}): '{response[:100]}...'"
                    )
                return response, []

            # Last resort - handle unexpected types
            self.logger.warning(
                f"Processing unexpected response type: {type(response)}. Converting to string."
            )
            return str(response), []

        except Exception as e:
            self.logger.error(f"Error processing Anthropic response: {str(e)}")
            self.logger.error(f"Processing error details: {traceback.format_exc()}")
            return f"Error processing response: {str(e)}", []

    def _parse_tool_input(self, raw_arguments: Any) -> Dict[str, Any]:
        if isinstance(raw_arguments, dict):
            return raw_arguments
        if not isinstance(raw_arguments, str):
            return {}
        try:
            parsed = json.loads(raw_arguments or "{}")
        except Exception:
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _tool_use_block_from_tool_call(
        self, tool_call: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        function_payload = tool_call.get("function")
        if not isinstance(function_payload, dict):
            return None
        name = function_payload.get("name")
        if not name:
            return None
        return {
            "type": "tool_use",
            "id": tool_call.get("id"),
            "name": name,
            "input": self._parse_tool_input(function_payload.get("arguments")),
        }

    def _tool_use_block_from_tool_message(
        self, tool_msg: Dict[str, Any]
    ) -> Optional[Dict[str, Any]]:
        tool_call_id = str(tool_msg.get("tool_call_id") or "").strip()
        if not tool_call_id:
            return None
        name = str(
            tool_msg.get("name") or tool_msg.get("action_type") or "tool"
        ).strip()
        if not name:
            return None
        return {
            "type": "tool_use",
            "id": tool_call_id,
            "name": name,
            "input": self._parse_tool_input(tool_msg.get("tool_arguments")),
        }

    def _following_tool_result_ids(
        self, messages: List[Dict[str, Any]], start_index: int
    ) -> Set[str]:
        tool_result_ids: Set[str] = set()
        index = start_index
        while index < len(messages) and messages[index].get("role") == "tool":
            tool_call_id = str(messages[index].get("tool_call_id") or "").strip()
            if tool_call_id:
                tool_result_ids.add(tool_call_id)
            index += 1
        return tool_result_ids

    def _formatted_tool_use_ids(self, message: Dict[str, Any]) -> Set[str]:
        if message.get("role") != "assistant":
            return set()
        content = message.get("content")
        if not isinstance(content, list):
            return set()
        return {
            str(part.get("id"))
            for part in content
            if isinstance(part, dict) and part.get("type") == "tool_use"
        }

    @staticmethod
    def _raw_anthropic_tool_use_blocks(message: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Return provider-shaped tool declarations embedded in one message."""

        content = message.get("content")
        if not isinstance(content, list):
            return []
        return [
            part
            for part in content
            if isinstance(part, dict) and part.get("type") == "tool_use"
        ]

    @staticmethod
    def _raw_anthropic_tool_result_blocks(
        message: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """Return provider-shaped tool results embedded in one user message."""

        content = message.get("content")
        if not isinstance(content, list):
            return []
        return [
            part
            for part in content
            if isinstance(part, dict) and part.get("type") == "tool_result"
        ]

    @classmethod
    def _sanitize_raw_anthropic_tool_blocks(
        cls,
        messages: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Keep raw Anthropic tool blocks only as complete adjacent units.

        ConversationSystem normally stores canonical OpenAI-shaped declarations,
        but checkpoint/import paths can supply already Anthropic-shaped content.
        Treat that content with the same strict replay rules: an assistant's
        ``tool_use`` blocks need the immediately following user ``tool_result``
        blocks with the exact same unique ids.  All orphaned or interleaved
        provider blocks are stripped before the SDK boundary.
        """

        sanitized: List[Dict[str, Any]] = []
        reserved_tool_use_ids: Set[str] = set()
        index = 0
        while index < len(messages):
            message = messages[index]
            role = message.get("role")
            raw_tool_uses = cls._raw_anthropic_tool_use_blocks(message)

            if role == "assistant" and raw_tool_uses:
                tool_use_ids = [
                    str(block.get("id") or "").strip() for block in raw_tool_uses
                ]
                valid_declaration = (
                    all(tool_use_ids)
                    and len(tool_use_ids) == len(set(tool_use_ids))
                    and not reserved_tool_use_ids.intersection(tool_use_ids)
                    and all(
                        str(block.get("name") or "").strip() for block in raw_tool_uses
                    )
                )
                # Reserve declaration ids even when the unit is invalid, so a
                # later message cannot re-use an ambiguous provider identity.
                reserved_tool_use_ids.update(
                    tool_use_id for tool_use_id in tool_use_ids if tool_use_id
                )

                next_message = (
                    messages[index + 1] if index + 1 < len(messages) else None
                )
                raw_tool_results = (
                    cls._raw_anthropic_tool_result_blocks(next_message)
                    if isinstance(next_message, dict)
                    and next_message.get("role") == "user"
                    else []
                )
                result_ids = [
                    str(block.get("tool_use_id") or "").strip()
                    for block in raw_tool_results
                ]
                next_content = (
                    next_message.get("content")
                    if isinstance(next_message, dict)
                    else None
                )
                valid_results = (
                    isinstance(next_content, list)
                    and bool(raw_tool_results)
                    and len(raw_tool_results) == len(next_content)
                    and all(result_ids)
                    and len(result_ids) == len(set(result_ids))
                    and set(result_ids) == set(tool_use_ids)
                )
                if valid_declaration and valid_results:
                    sanitized.append(dict(message))
                    sanitized.append(dict(next_message))
                    index += 2
                    continue

                cleaned = dict(message)
                content = message.get("content")
                if isinstance(content, list):
                    cleaned_content = [
                        part
                        for part in content
                        if not (
                            isinstance(part, dict) and part.get("type") == "tool_use"
                        )
                    ]
                    cleaned["content"] = cleaned_content or ""
                sanitized.append(cleaned)
                index += 1
                continue

            if raw_tool_uses:
                # Only assistant messages can declare an Anthropic tool use.
                cleaned = dict(message)
                content = message.get("content")
                if isinstance(content, list):
                    cleaned["content"] = [
                        part
                        for part in content
                        if not (
                            isinstance(part, dict) and part.get("type") == "tool_use"
                        )
                    ]
                sanitized.append(cleaned)
                index += 1
                continue

            raw_tool_results = cls._raw_anthropic_tool_result_blocks(message)
            if raw_tool_results:
                # A valid raw result was consumed together with its declaration
                # above. Any remaining one is orphaned or interleaved.
                cleaned = dict(message)
                content = message.get("content")
                if isinstance(content, list):
                    cleaned_content = [
                        part
                        for part in content
                        if not (
                            isinstance(part, dict) and part.get("type") == "tool_result"
                        )
                    ]
                    if cleaned_content:
                        cleaned["content"] = cleaned_content
                        sanitized.append(cleaned)
                index += 1
                continue

            sanitized.append(dict(message))
            index += 1

        return sanitized

    def format_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Format messages for Anthropic API, properly handling images"""
        formatted_messages = []
        messages = self._sanitize_raw_anthropic_tool_blocks(
            [
                message
                for message in sanitize_native_tool_messages(messages)
                if isinstance(message, dict)
            ]
        )

        # Second pass - handle regular messages
        index = 0
        while index < len(messages):
            msg = messages[index]
            role = msg.get("role", "user")
            content = msg.get("content", "")

            # Skip all system messages (handled separately)
            if role == "system":
                index += 1
                continue

            if role == "tool":
                tool_result_blocks = []
                preceding_tool_use_ids = (
                    self._formatted_tool_use_ids(formatted_messages[-1])
                    if formatted_messages
                    else set()
                )
                while index < len(messages) and messages[index].get("role") == "tool":
                    tool_msg = messages[index]
                    tool_call_id = str(tool_msg.get("tool_call_id") or "").strip()
                    tool_result_content = str(tool_msg.get("content", ""))
                    if tool_call_id:
                        if tool_call_id not in preceding_tool_use_ids:
                            # Raw canonical history must contain the matching
                            # assistant declaration.  Never synthesize one from
                            # an orphaned result during provider replay.
                            index += 1
                            continue
                        block: Dict[str, Any] = {
                            "type": "tool_result",
                            "tool_use_id": tool_call_id,
                            "content": tool_result_content,
                        }
                        status = str(tool_msg.get("status") or "").lower()
                        if status in {"error", "failed", "cancelled", "interrupted"}:
                            block["is_error"] = True
                        tool_result_blocks.append(block)
                    # Malformed result ids are not provider-replayable.
                    index += 1
                if tool_result_blocks:
                    formatted_messages.append(
                        {"role": "user", "content": tool_result_blocks}
                    )
                continue

            # Map roles for Anthropic
            if role == "assistant":
                role = "assistant"
            else:
                role = "user"

            # Handle different content formats
            formatted_content = []

            # Handle string content
            if isinstance(content, str):
                # Strip trailing whitespace for assistant messages to avoid API errors
                if role == "assistant":
                    content = content.rstrip()
                formatted_content.append({"type": "text", "text": content})

            # Handle list content (multimodal)
            elif isinstance(content, list):
                for part in content:
                    if isinstance(part, dict):
                        # Handle image parts - with more flexible field detection
                        if part.get("type") in ["image_url", "image"]:
                            try:
                                # Extract image URL from various possible formats
                                image_url = None
                                image_path = None

                                # Handle direct image_url format (most common in your codebase)
                                if "image_url" in part:
                                    # Handle both string and dict variants
                                    if (
                                        isinstance(part["image_url"], dict)
                                        and "url" in part["image_url"]
                                    ):
                                        image_url = part["image_url"]["url"]
                                    else:
                                        image_url = part["image_url"]

                                # Also check for direct path
                                elif "image_path" in part:
                                    image_path = part["image_path"]
                                # Check for direct url field
                                elif "url" in part:
                                    image_url = part["url"]
                                # Also check for source.url pattern
                                elif (
                                    "source" in part
                                    and isinstance(part["source"], dict)
                                    and "url" in part["source"]
                                ):
                                    image_url = part["source"]["url"]

                                # Process the image source appropriately
                                if image_url and image_url.startswith(
                                    ("http://", "https://")
                                ):
                                    # For web URLs, use URL source type
                                    formatted_content.append(
                                        {
                                            "type": "image",
                                            "source": {"type": "url", "url": image_url},
                                        }
                                    )
                                elif image_path and os.path.exists(image_path):
                                    # For local files, read and encode as base64
                                    import io

                                    from PIL import Image  # type: ignore

                                    # Open and process the image
                                    with Image.open(image_path) as img:
                                        # Resize if needed
                                        max_size = (1024, 1024)
                                        resampling_namespace = getattr(
                                            Image, "Resampling", Image
                                        )
                                        img.thumbnail(
                                            max_size,
                                            getattr(
                                                Image,
                                                "LANCZOS",
                                                getattr(
                                                    resampling_namespace, "LANCZOS"
                                                ),
                                            ),
                                        )

                                        # Convert to RGB if necessary
                                        if img.mode != "RGB":
                                            img = img.convert("RGB")

                                        # Determine media type based on file extension
                                        ext = os.path.splitext(image_path)[1].lower()
                                        media_type = {
                                            ".jpg": "image/jpeg",
                                            ".jpeg": "image/jpeg",
                                            ".png": "image/png",
                                            ".gif": "image/gif",
                                            ".webp": "image/webp",
                                        }.get(ext, "image/jpeg")

                                        # Encode to base64
                                        buffer = io.BytesIO()
                                        img.save(
                                            buffer,
                                            format=media_type.split("/")[1].upper(),
                                        )
                                        base64_data = base64.b64encode(
                                            buffer.getvalue()
                                        ).decode("utf-8")

                                        # Format for Anthropic API using base64
                                        formatted_content.append(
                                            {
                                                "type": "image",
                                                "source": {
                                                    "type": "base64",
                                                    "media_type": media_type,
                                                    "data": base64_data,
                                                },
                                            }
                                        )
                                elif image_url:
                                    # For other URLs (like file:// or unsupported), try to load and convert to base64
                                    try:
                                        # Import base64 again in this scope to avoid the variable shadowing issue
                                        import base64 as image_base64
                                        import io

                                        from PIL import Image  # type: ignore

                                        # Try to open as local file by removing file:// prefix if present
                                        local_path = image_url
                                        if image_url.startswith("file://"):
                                            local_path = image_url[7:]

                                        if os.path.exists(local_path):
                                            with Image.open(local_path) as img:
                                                # Same processing as above
                                                max_size = (1024, 1024)
                                                resampling_namespace = getattr(
                                                    Image, "Resampling", Image
                                                )
                                                img.thumbnail(
                                                    max_size,
                                                    getattr(
                                                        Image,
                                                        "LANCZOS",
                                                        getattr(
                                                            resampling_namespace,
                                                            "LANCZOS",
                                                        ),
                                                    ),
                                                )
                                                if img.mode != "RGB":
                                                    img = img.convert("RGB")

                                                # Determine media type
                                                ext = os.path.splitext(local_path)[
                                                    1
                                                ].lower()
                                                media_type = {
                                                    ".jpg": "image/jpeg",
                                                    ".jpeg": "image/jpeg",
                                                    ".png": "image/png",
                                                    ".gif": "image/gif",
                                                    ".webp": "image/webp",
                                                }.get(ext, "image/jpeg")

                                                # Encode to base64 using the renamed import
                                                buffer = io.BytesIO()
                                                img.save(
                                                    buffer,
                                                    format=media_type.split("/")[
                                                        1
                                                    ].upper(),
                                                )
                                                base64_data = image_base64.b64encode(
                                                    buffer.getvalue()
                                                ).decode("utf-8")

                                                # Format for Anthropic API using base64
                                                formatted_content.append(
                                                    {
                                                        "type": "image",
                                                        "source": {
                                                            "type": "base64",
                                                            "media_type": media_type,
                                                            "data": base64_data,
                                                        },
                                                    }
                                                )
                                        else:
                                            self.logger.error(
                                                f"Image not found at path: {local_path}"
                                            )
                                            formatted_content.append(
                                                {
                                                    "type": "text",
                                                    "text": "[Failed to process image: File not found]",
                                                }
                                            )
                                    except Exception as e:
                                        self.logger.error(
                                            f"Error processing image URL {image_url}: {str(e)}"
                                        )
                                        formatted_content.append(
                                            {
                                                "type": "text",
                                                "text": f"[Failed to process image: {str(e)}]",
                                            }
                                        )
                                else:
                                    # No valid image source found
                                    self.logger.error(
                                        f"Invalid image format in message: {part}"
                                    )
                                    formatted_content.append(
                                        {
                                            "type": "text",
                                            "text": "[Failed to process image: Invalid format]",
                                        }
                                    )
                            except Exception as e:
                                self.logger.error(f"Error formatting image: {str(e)}")
                                formatted_content.append(
                                    {
                                        "type": "text",
                                        "text": f"[Failed to process image: {str(e)}]",
                                    }
                                )
                        elif part.get("type") == "text":
                            # Text content in a list
                            text = part.get("text", "")
                            # Strip trailing whitespace for assistant messages
                            if role == "assistant":
                                text = text.rstrip()
                            formatted_content.append({"type": "text", "text": text})
                        else:
                            # Unknown content type
                            formatted_content.append(part)
                    else:
                        # Plain strings in a list
                        # Strip trailing whitespace if needed
                        content_str = str(part)
                        if role == "assistant":
                            content_str = content_str.rstrip()
                        formatted_content.append({"type": "text", "text": content_str})
            else:
                # Fallback for any other content type
                content_str = str(content)
                if role == "assistant":
                    content_str = content_str.rstrip()
                formatted_content.append({"type": "text", "text": content_str})

            # Create the formatted message with proper content array
            if role == "assistant":
                tool_calls = msg.get("tool_calls")
                if isinstance(tool_calls, list) and tool_calls:
                    following_tool_ids = self._following_tool_result_ids(
                        messages, index + 1
                    )
                    valid_tool_uses = []
                    for tool_call in tool_calls:
                        if not isinstance(tool_call, dict):
                            continue
                        tool_use = self._tool_use_block_from_tool_call(tool_call)
                        if not tool_use:
                            continue
                        tool_call_id = str(tool_use.get("id") or "").strip()
                        if tool_call_id not in following_tool_ids:
                            continue
                        valid_tool_uses.append(tool_use)
                    if valid_tool_uses:
                        if formatted_content == [{"type": "text", "text": ""}]:
                            formatted_content = []
                        formatted_content.extend(valid_tool_uses)

            formatted_messages.append({"role": role, "content": formatted_content})
            index += 1

        return formatted_messages

    def count_tokens(self, content: Union[str, List, Dict]) -> int:
        """Count tokens using Anthropic's dedicated token counting endpoint"""
        try:
            # Convert to simplest possible format for count_tokens endpoint
            simple_messages = []

            # Handle different content types
            if isinstance(content, str):
                # Simple string
                simple_messages.append(
                    {"role": "user", "content": [{"type": "text", "text": content}]}
                )
            elif isinstance(content, list):
                # Convert list to simple text-only content
                text_parts = []
                for item in content:
                    if isinstance(item, dict) and item.get("type") == "text":
                        # Add just the text content without other fields
                        text_parts.append(
                            {"type": "text", "text": item.get("text", "")}
                        )
                    elif isinstance(item, dict) and item.get("type") in [
                        "image",
                        "image_url",
                    ]:
                        # Replace images with text placeholder
                        text_parts.append(
                            {"type": "text", "text": "[Image: ~1300 tokens]"}
                        )
                    else:
                        # Convert anything else to simple text
                        text_parts.append({"type": "text", "text": str(item)})

                simple_messages.append({"role": "user", "content": text_parts})
            elif isinstance(content, dict):
                if "role" in content and "content" in content:
                    # It's a message, extract role and convert content to simple format
                    role = "assistant" if content["role"] == "assistant" else "user"

                    if isinstance(content["content"], list):
                        # Process list content
                        text_parts = []
                        for item in content["content"]:
                            if isinstance(item, dict) and item.get("type") == "text":
                                text_parts.append(
                                    {"type": "text", "text": item.get("text", "")}
                                )
                            elif isinstance(item, dict) and item.get("type") in [
                                "image",
                                "image_url",
                            ]:
                                text_parts.append(
                                    {"type": "text", "text": "[Image: ~1300 tokens]"}
                                )
                            else:
                                text_parts.append({"type": "text", "text": str(item)})

                        simple_messages.append({"role": role, "content": text_parts})
                    else:
                        # Convert to simple text
                        simple_messages.append(
                            {
                                "role": role,
                                "content": [
                                    {"type": "text", "text": str(content["content"])}
                                ],
                            }
                        )
                else:
                    # Treat as generic content
                    simple_messages.append(
                        {
                            "role": "user",
                            "content": [{"type": "text", "text": str(content)}],
                        }
                    )
            else:
                # Fallback for any other type
                simple_messages.append(
                    {
                        "role": "user",
                        "content": [{"type": "text", "text": str(content)}],
                    }
                )

            # Call token counting API with simplified messages
            logger.debug(f"Counting tokens with simplified format: {simple_messages}")
            response = self.sync_client.messages.count_tokens(
                model=self.model_config.model, messages=simple_messages
            )

            logger.debug(f"Token count from Anthropic API: {response.input_tokens}")
            return response.input_tokens

        except Exception as e:
            logger.error(f"Error counting tokens via Anthropic API: {str(e)}")
            # Fall back to approximate counting
            token_count = self._approximate_token_count(content)
            logger.debug(f"Using approximate token count: {token_count}")
            return token_count

    def _approximate_token_count(self, content) -> int:
        """Fallback method for token counting when API fails"""
        try:
            # Try tiktoken first
            import tiktoken  # type: ignore

            encoder = tiktoken.get_encoding("cl100k_base")

            if isinstance(content, str):
                return len(encoder.encode(content))
            elif isinstance(content, list):
                # Handle content array with images
                text_content = ""
                image_count = 0
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            text_content += item.get("text", "")
                        elif item.get("type") in ["image", "image_url"]:
                            image_count += 1
                    else:
                        text_content += str(item)

                # Count text tokens + estimate for images
                text_tokens = len(encoder.encode(text_content))
                image_tokens = image_count * 1300  # Claude's approx for images
                return text_tokens + image_tokens
            else:
                return len(encoder.encode(str(content)))

        except Exception:
            # Ultimate fallback - character-based estimation
            if isinstance(content, str):
                return len(content) // 4 + 1
            elif isinstance(content, list):
                # Estimate with images
                char_count = 0
                image_count = 0
                for item in content:
                    if isinstance(item, dict):
                        if item.get("type") == "text":
                            char_count += len(item.get("text", ""))
                        elif item.get("type") in ["image", "image_url"]:
                            image_count += 1
                    else:
                        char_count += len(str(item))

                return (char_count // 4 + 1) + (image_count * 1300)
            else:
                return len(str(content)) // 4 + 1

    def supports_system_messages(self) -> bool:
        """Whether this provider supports system messages"""
        return True

    def supports_vision(self) -> bool:
        """Whether this provider supports vision/images"""
        return "claude-3" in self.model_config.model

    def _safe_log_content(self, content):
        """Create a safe version of content for logging, removing base64 data"""
        if isinstance(content, list):
            return [self._safe_log_content(item) for item in content]
        elif isinstance(content, dict):
            result = {}
            for k, v in content.items():
                if k == "data" and isinstance(v, str) and len(v) > 100:
                    result[k] = f"[BASE64 DATA REDACTED: {len(v)} bytes]"
                elif isinstance(v, dict) or isinstance(v, list):
                    result[k] = self._safe_log_content(v)
                else:
                    result[k] = v
            return result
        return content

    def _ensure_no_trailing_whitespace(self, request_params: Dict[str, Any]) -> None:
        """Ensure no trailing whitespace in any text content to avoid API errors"""
        # Check system prompt
        if "system" in request_params and isinstance(request_params["system"], str):
            request_params["system"] = request_params["system"].rstrip()

        # Check all messages
        if "messages" in request_params and isinstance(
            request_params["messages"], list
        ):
            for msg in request_params["messages"]:
                if not isinstance(msg, dict):
                    continue

                # Check content list
                if "content" in msg and isinstance(msg["content"], list):
                    for item in msg["content"]:
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "text"
                            and "text" in item
                        ):
                            # Strip trailing whitespace from all text content
                            item["text"] = item["text"].rstrip()


Adapter = AnthropicAdapter  # Alias for consistent imports
