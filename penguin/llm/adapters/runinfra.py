"""RunInfra gateway adapter for OpenAI Chat Completions inference.

Wraps the RunInfra Inference API (https://runinfra.ai) behind the standard
OpenAI SDK so that DeepSeek V4 Flash and other models can be used through
Penguin's native adapter path.
"""

from __future__ import annotations

import os
from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from openai import AsyncOpenAI  # type: ignore

from penguin.llm.contracts import LLMPreparedRequest, LLMProviderCapabilities

from .openrouter import OpenRouterGateway

if TYPE_CHECKING:
    from ..model_config import ModelConfig


_DEFAULT_BASE_URL = "https://api.runinfra.ai/v1"
_RUNINFRA_GATEWAY_KEY_ENV = "RUNINFRA_GATEWAY_KEY"


class RunInfraAdapter(OpenRouterGateway):
    """Native adapter for RunInfra Inference API.

    RunInfra exposes an OpenAI-compatible Chat Completions endpoint at
    ``/v1`` authenticated via a Bearer API key.  This adapter reuses the
    mature Chat Completions stream parser while owning RunInfra URL/auth
    semantics.
    """

    def __init__(
        self,
        model_config: ModelConfig,
        *,
        api_key: str | None = None,
    ) -> None:
        self.model_config = model_config
        self.base_url = self._normalize_endpoint(
            model_config.api_base or _DEFAULT_BASE_URL
        )
        self.logger = __import__("logging").getLogger(__name__)
        self.site_url = None
        self.site_title = "Penguin"
        self._telemetry: dict[str, Any] = {"interrupts": 0, "streamed_bytes": 0}
        self._tool_call_acc: dict[str, Any] = {"name": None, "arguments": ""}
        self._tool_call_accs: dict[int, dict[str, Any]] = {}
        self._pending_tool_calls: list[dict[str, Any]] = []
        self._last_tool_call = None
        self._last_usage: dict[str, Any] = {}
        self._last_error = None
        self._last_finish_reason = __import__(
            "penguin.llm.contracts", fromlist=["FinishReason"]
        ).FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._last_request_lifecycle = None
        self.extra_headers: dict[str, str] = {}

        resolved_key = (
            api_key
            or model_config.api_key
            or os.getenv(_RUNINFRA_GATEWAY_KEY_ENV)
        )
        if not isinstance(resolved_key, str) or not resolved_key.strip():
            raise ValueError(
                "RunInfra requires an API key. Set RUNINFRA_GATEWAY_KEY, "
                "model_config.api_key, or pass api_key= to the adapter."
            )

        self.client = AsyncOpenAI(
            base_url=self.base_url,
            api_key=resolved_key.strip(),
            timeout=None,
        )

    @staticmethod
    def _normalize_endpoint(value: str | None) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("RunInfra endpoint URL is required")
        parsed = urlparse(value.strip())
        if parsed.scheme != "https":
            raise ValueError("RunInfra endpoint must be an HTTPS URL")
        path = parsed.path.rstrip("/")
        if path not in {"", "/v1"} or parsed.query or parsed.fragment:
            raise ValueError("RunInfra endpoint URL must be its root or /v1")
        return f"https://{parsed.netloc}/v1"

    @property
    def provider(self) -> str:
        return "runinfra"

    def get_capabilities(self) -> LLMProviderCapabilities:
        reasoning_efforts = self.model_config.supported_reasoning_levels
        return LLMProviderCapabilities(
            provider="runinfra",
            model=str(self.model_config.model),
            native_tools=bool(self.model_config.native_tools),
            streaming=bool(self.model_config.streaming_enabled),
            reasoning=bool(self.model_config.supports_reasoning),
            vision=bool(self.model_config.vision_enabled),
            reasoning_efforts=(tuple(reasoning_efforts) if reasoning_efforts else None),
            max_context_tokens=self.model_config.max_context_window_tokens,
            max_output_tokens=self.model_config.max_output_tokens,
            provider_data={"api": "chat_completions", "base_url": self.base_url},
        )

    def _apply_reasoning_request_params(
        self,
        request_params: dict[str, Any],
        reasoning_config: dict[str, Any],
    ) -> None:
        """Apply RunInfra DeepSeek's OpenAI-compatible reasoning_effort."""
        effort = reasoning_config.get("effort")
        if effort:
            request_params["reasoning_effort"] = effort

    def _uses_direct_reasoning_transport(
        self,
        reasoning_config: dict[str, Any] | None,
    ) -> bool:
        """Use the SDK, which natively accepts reasoning_effort."""
        del reasoning_config
        return False

    def prepare_request_sync(
        self,
        messages: list[dict[str, Any]],
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool | None = None,
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        """Prepare a RunInfra request without network traffic."""
        use_streaming = (
            stream if stream is not None else self.model_config.streaming_enabled
        )
        request_body: dict[str, Any] = {
            "model": self.model_config.model,
            "messages": messages,
            "max_tokens": max_output_tokens or self.model_config.max_output_tokens,
            "temperature": (
                temperature
                if temperature is not None
                else self.model_config.temperature
            ),
            "stream": use_streaming,
            **kwargs,
        }
        reasoning_config = self.model_config.get_reasoning_config()
        if reasoning_config:
            self._apply_reasoning_request_params(request_body, reasoning_config)
        if use_streaming:
            request_body["stream_options"] = {"include_usage": True}
        request_body = {
            key: value for key, value in request_body.items() if value is not None
        }
        return LLMPreparedRequest(
            provider=self.provider,
            model=str(self.model_config.model),
            protocol="openai_chat_completions",
            route="runinfra.chat_completions",
            url=f"{self.base_url}/chat/completions",
            body=request_body,
            transport="sdk_stream" if use_streaming else "sdk",
            headers={},
            capabilities=self.get_capabilities(),
            diagnostics={"message_count": len(messages), "stream": bool(use_streaming)},
            provider_data={"base_url": self.base_url},
        )

    async def prepare_request(
        self,
        messages: list[dict[str, Any]],
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        return self.prepare_request_sync(messages, **kwargs)
