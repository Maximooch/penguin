"""First-class Link-owned inference provider for Penguin."""

from __future__ import annotations

import asyncio
import inspect
import json
import os
import time
import uuid
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal, cast

import httpx

from ...contracts import (
    ErrorCategory,
    FinishReason,
    LLMError,
    LLMPreparedRequest,
    LLMProviderCapabilities,
    LLMProviderError,
    LLMRequestLifecycle,
    LLMToolCall,
    LLMUsage,
    ProviderRequestStatus,
    StreamCallback,
)
from ...provider_transform import build_llm_error, extract_retry_after_seconds
from .chat_completions_protocol import (
    build_chat_completions_body,
    normalize_chat_usage,
    parse_chat_completions_body,
)
from .responses_protocol import (
    build_responses_body,
    normalize_responses_usage,
    parse_responses_body,
)

if TYPE_CHECKING:
    from .context import LinkInferenceContext

LinkProtocol = Literal["responses", "chat_completions"]


@dataclass(frozen=True)
class LinkProviderConfig:
    """Static Link transport configuration; never carries user attribution."""

    base_url: str
    service_token: str
    service_name: str = "penguin"
    protocol: LinkProtocol = "responses"
    idle_timeout_seconds: float = 300.0

    @classmethod
    def from_env(cls, *, base_url: str | None = None) -> LinkProviderConfig:
        protocol = os.getenv("LINK_INFERENCE_PROTOCOL", "responses").strip().lower()
        if protocol not in {"responses", "chat_completions"}:
            raise ValueError(
                "LINK_INFERENCE_PROTOCOL must be 'responses' or 'chat_completions'."
            )
        resolved_base_url = (
            base_url
            or os.getenv("LINK_INFERENCE_BASE_URL")
            or os.getenv("LINK_INFERENCE_URL")
            or "http://localhost:3001/api/v1"
        ).rstrip("/")
        service_token = (
            os.getenv("LINK_INFERENCE_SERVICE_TOKEN")
            or os.getenv("LINK_INTERNAL_SERVICE_SECRET")
            or ""
        ).strip()
        if not service_token:
            raise ValueError("LINK_INFERENCE_SERVICE_TOKEN is required.")
        return cls(
            base_url=resolved_base_url,
            service_token=service_token,
            service_name=os.getenv("LINK_INFERENCE_SERVICE_NAME", "penguin"),
            protocol=cast("LinkProtocol", protocol),
        )


class LinkProvider:
    """Send one Penguin model invocation through Link's authorized broker."""

    provider = "link"

    def __init__(
        self,
        *,
        model_config: Any,
        context: LinkInferenceContext,
        config: LinkProviderConfig,
        http_client: httpx.AsyncClient | None = None,
    ) -> None:
        if context.provider_state_owner != "link_managed":
            raise ValueError("LinkProvider requires provider_state_owner=link_managed.")
        if context.execution_source != "link_gateway":
            raise ValueError("LinkProvider requires execution_source=link_gateway.")
        if context.settlement_mode != "debit_link_credits":
            raise ValueError(
                "LinkProvider requires settlement_mode=debit_link_credits."
            )
        self.model_config = model_config
        self.context = context
        self.config = config
        self._http_client = http_client
        self._last_usage = LLMUsage()
        self._last_error: LLMError | None = None
        self._last_lifecycle: LLMRequestLifecycle | None = None
        self._last_finish_reason = FinishReason.UNKNOWN
        self._last_reasoning = ""
        self._pending_tool_calls: list[LLMToolCall] = []
        self._last_provider_data: dict[str, Any] = {}

    def get_capabilities(self) -> LLMProviderCapabilities:
        return LLMProviderCapabilities(
            provider="link",
            model=str(self.model_config.model),
            native_tools=True,
            streaming=True,
            reasoning=bool(getattr(self.model_config, "supports_reasoning", False)),
            vision=False,
            max_context_tokens=getattr(
                self.model_config, "max_context_window_tokens", None
            ),
            max_output_tokens=getattr(self.model_config, "max_output_tokens", None),
            provider_data={"protocol": self.config.protocol},
        )

    async def prepare_request(
        self,
        messages: list[dict[str, Any]],
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        **kwargs: Any,
    ) -> LLMPreparedRequest:
        invocation_id = str(kwargs.pop("invocation_id", "") or uuid.uuid4())
        protocol, route, body = self._build_request(
            messages=messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            stream=stream,
            kwargs=kwargs,
        )
        return LLMPreparedRequest(
            provider="link",
            model=str(self.model_config.model),
            protocol=protocol,
            route=route,
            body=body,
            transport="link_sse" if stream else "link_http",
            headers=self._headers(invocation_id, include_secret=False),
            capabilities=self.get_capabilities(),
            diagnostics={"invocation_id": invocation_id},
            provider_data={"execution_source": "link_gateway"},
        )

    async def get_response(
        self,
        messages: list[dict[str, Any]],
        max_output_tokens: int | None = None,
        temperature: float | None = None,
        stream: bool = False,
        stream_callback: StreamCallback | None = None,
        **kwargs: Any,
    ) -> str:
        invocation_id = str(kwargs.pop("invocation_id", "") or uuid.uuid4())
        protocol, route, body = self._build_request(
            messages=messages,
            max_output_tokens=max_output_tokens,
            temperature=temperature,
            stream=stream,
            kwargs=kwargs,
        )
        lifecycle = LLMRequestLifecycle(
            request_id=invocation_id,
            provider="link",
            model=str(self.model_config.model),
            status=ProviderRequestStatus.RUNNING,
            stream=stream,
            transport="link_sse" if stream else "link_http",
            started_at=time.time(),
            last_event_at=time.time(),
            provider_data={"protocol": protocol, "route": route},
        )
        self._last_lifecycle = lifecycle
        self._last_error = None
        self._pending_tool_calls = []

        try:
            client = await self._client()
            if stream:
                result = await self._stream_response(
                    client=client,
                    route=route,
                    body=body,
                    headers=self._headers(invocation_id),
                    protocol=protocol,
                    callback=stream_callback,
                    lifecycle=lifecycle,
                )
            else:
                response = await client.post(
                    f"{self.config.base_url}/{route}",
                    json=body,
                    headers=self._headers(invocation_id),
                    timeout=self.config.idle_timeout_seconds,
                )
                await self._raise_for_link_error(response, lifecycle)
                payload = response.json()
                if not isinstance(payload, dict):
                    raise ValueError("Link returned a non-object inference response.")
                result = self._parse_buffered(protocol, payload)
                self._capture_response_headers(response.headers)

            text, reasoning, tool_calls, usage, finish, provider_data = result
            self._last_usage = usage
            self._last_reasoning = reasoning
            self._pending_tool_calls = list(tool_calls)
            self._last_finish_reason = finish
            self._last_provider_data.update(provider_data)
            lifecycle.status = ProviderRequestStatus.COMPLETED
            lifecycle.finish_reason = finish
            lifecycle.provider_response_id = _optional_str(
                provider_data.get("response_id")
            )
            lifecycle.ended_at = time.time()
            lifecycle.last_event_at = lifecycle.ended_at
            lifecycle.provider_data.update(self._last_provider_data)
            return text
        except asyncio.CancelledError:
            lifecycle.status = ProviderRequestStatus.CANCELLED
            lifecycle.ended_at = time.time()
            raise
        except LLMProviderError as error:
            self._last_error = error.error
            lifecycle.error = error.error
            lifecycle.status = (
                ProviderRequestStatus.DISCONNECTED
                if error.error.category
                in {ErrorCategory.NETWORK, ErrorCategory.TIMEOUT}
                else ProviderRequestStatus.FAILED
            )
            lifecycle.ended_at = time.time()
            raise
        except (httpx.HTTPError, asyncio.TimeoutError) as error:
            llm_error = build_llm_error(
                message=f"Link inference transport outcome is uncertain: {error}",
                provider="link",
                model=str(self.model_config.model),
                category=(
                    ErrorCategory.TIMEOUT
                    if isinstance(error, (httpx.TimeoutException, asyncio.TimeoutError))
                    else ErrorCategory.NETWORK
                ),
                retryable=False,
                provider_data={"dispatch_outcome": "uncertain"},
            )
            self._last_error = llm_error
            lifecycle.error = llm_error
            lifecycle.status = ProviderRequestStatus.DISCONNECTED
            lifecycle.ended_at = time.time()
            raise LLMProviderError(llm_error) from error
        except Exception as error:
            llm_error = build_llm_error(
                message=f"Link inference response handling failed: {error}",
                provider="link",
                model=str(self.model_config.model),
                category=ErrorCategory.RUNTIME,
                retryable=False,
                provider_data={"dispatch_outcome": "uncertain"},
            )
            self._last_error = llm_error
            lifecycle.error = llm_error
            lifecycle.status = ProviderRequestStatus.FAILED
            lifecycle.ended_at = time.time()
            raise LLMProviderError(llm_error) from error

    def count_tokens(self, content: Any) -> int:
        """Return a conservative local estimate; Link owns billing counts."""

        text = content if isinstance(content, str) else json.dumps(content, default=str)
        return max((len(text) + 3) // 4, 1)

    def get_last_usage(self) -> dict[str, Any]:
        return self._last_usage.to_dict()

    def get_last_error(self) -> LLMError | None:
        return self._last_error

    def get_last_request_lifecycle(self) -> LLMRequestLifecycle | None:
        return self._last_lifecycle

    def get_last_finish_reason(self) -> FinishReason:
        return self._last_finish_reason

    def get_last_reasoning(self) -> str:
        return self._last_reasoning

    def has_pending_tool_call(self) -> bool:
        return bool(self._pending_tool_calls)

    def get_and_clear_last_tool_call(self) -> dict[str, Any] | None:
        calls = self.get_and_clear_pending_tool_calls()
        return calls[-1] if calls else None

    def get_and_clear_pending_tool_calls(self) -> list[dict[str, Any]]:
        calls = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {"name": call.name, "arguments": call.arguments},
            }
            for call in self._pending_tool_calls
        ]
        self._pending_tool_calls = []
        return calls

    async def _client(self) -> httpx.AsyncClient:
        if self._http_client is not None:
            return self._http_client
        # Import lazily to avoid api_client -> registry -> provider cycles.
        from ...api_client import ConnectionPoolManager

        return await ConnectionPoolManager.get_instance().get_client(
            self.config.base_url
        )

    def _build_request(
        self,
        *,
        messages: list[dict[str, Any]],
        max_output_tokens: int | None,
        temperature: float | None,
        stream: bool,
        kwargs: dict[str, Any],
    ) -> tuple[LinkProtocol, str, dict[str, Any]]:
        maximum = max_output_tokens or getattr(
            self.model_config, "max_output_tokens", None
        )
        if not isinstance(maximum, int) or maximum <= 0:
            raise ValueError(
                "Link-managed inference requires a positive bounded maximum output."
            )
        tools = kwargs.pop("tools", None)
        tool_choice = kwargs.pop("tool_choice", None)
        reasoning = kwargs.pop("reasoning", None)
        if reasoning is None:
            effort = getattr(self.model_config, "reasoning_effort", None)
            reasoning = {"effort": effort} if effort else None
        if kwargs:
            # Do not forward provider-specific knobs across the Link boundary.
            unsupported = ", ".join(sorted(kwargs))
            raise ValueError(f"Unsupported Link inference options: {unsupported}")
        if self.config.protocol == "responses":
            return (
                "responses",
                "responses",
                build_responses_body(
                    model=str(self.model_config.model),
                    messages=messages,
                    max_output_tokens=maximum,
                    temperature=temperature,
                    stream=stream,
                    tools=tools,
                    tool_choice=tool_choice,
                    reasoning=reasoning,
                ),
            )
        return (
            "chat_completions",
            "chat/completions",
            build_chat_completions_body(
                model=str(self.model_config.model),
                messages=messages,
                max_output_tokens=maximum,
                temperature=temperature,
                stream=stream,
                tools=tools,
                tool_choice=tool_choice,
                reasoning=reasoning,
            ),
        )

    def _headers(
        self, invocation_id: str, *, include_secret: bool = True
    ) -> dict[str, str]:
        headers = {
            "Accept": "text/event-stream, application/json",
            "Content-Type": "application/json",
            **self.context.headers(invocation_id),
        }
        if include_secret:
            headers["X-Link-Service-Name"] = self.config.service_name
            headers["X-Link-Service-Auth"] = self.config.service_token
        return headers

    async def _stream_response(
        self,
        *,
        client: httpx.AsyncClient,
        route: str,
        body: dict[str, Any],
        headers: dict[str, str],
        protocol: LinkProtocol,
        callback: StreamCallback | None,
        lifecycle: LLMRequestLifecycle,
    ) -> tuple[str, str, list[LLMToolCall], LLMUsage, FinishReason, dict[str, Any]]:
        text_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_calls: dict[int, dict[str, str]] = {}
        usage = LLMUsage()
        finish = FinishReason.UNKNOWN
        response_id: str | None = None
        async with client.stream(
            "POST",
            f"{self.config.base_url}/{route}",
            json=body,
            headers=headers,
            timeout=httpx.Timeout(self.config.idle_timeout_seconds),
        ) as response:
            await self._raise_for_link_error(response, lifecycle)
            self._capture_response_headers(response.headers)
            lifecycle.status = ProviderRequestStatus.STREAMING
            async for line in response.aiter_lines():
                lifecycle.last_event_at = time.time()
                if not line.startswith("data:"):
                    continue
                data = line[5:].strip()
                if not data or data == "[DONE]":
                    continue
                try:
                    event = json.loads(data)
                except json.JSONDecodeError:
                    # Link preserves provider SSE delivery even when an
                    # optional metadata frame is malformed. Ignore that frame
                    # rather than converting completed provider work into a
                    # retryable Penguin turn.
                    continue
                if not isinstance(event, dict):
                    continue
                if protocol == "responses":
                    delta = _optional_str(event.get("delta"))
                    event_type = str(event.get("type") or "")
                    response_payload = event.get("response")
                    if isinstance(response_payload, dict):
                        response_id = response_id or _optional_str(
                            response_payload.get("id")
                        )
                        if isinstance(response_payload.get("usage"), dict):
                            usage = normalize_responses_usage(
                                response_payload.get("usage")
                            )
                    if (
                        event_type
                        in {
                            "response.output_text.delta",
                            "response.refusal.delta",
                        }
                        and delta
                    ):
                        text_parts.append(delta)
                        await _emit(callback, delta, "assistant")
                    elif "reasoning" in event_type and delta:
                        reasoning_parts.append(delta)
                        await _emit(callback, delta, "reasoning")
                    elif event_type == "response.output_item.done":
                        item = event.get("item")
                        if (
                            isinstance(item, dict)
                            and item.get("type") == "function_call"
                        ):
                            index = len(tool_calls)
                            tool_calls[index] = {
                                "id": str(item.get("call_id") or ""),
                                "name": str(item.get("name") or ""),
                                "arguments": str(item.get("arguments") or "{}"),
                            }
                    elif event_type == "response.completed":
                        finish = FinishReason.STOP
                else:
                    response_id = response_id or _optional_str(event.get("id"))
                    if isinstance(event.get("usage"), dict):
                        usage = normalize_chat_usage(event.get("usage"))
                    choices = event.get("choices")
                    choice = choices[0] if isinstance(choices, list) and choices else {}
                    choice = choice if isinstance(choice, dict) else {}
                    delta_payload = choice.get("delta")
                    delta_payload = (
                        delta_payload if isinstance(delta_payload, dict) else {}
                    )
                    text_delta = _optional_str(delta_payload.get("content"))
                    reasoning_delta = _optional_str(delta_payload.get("reasoning"))
                    if text_delta:
                        text_parts.append(text_delta)
                        await _emit(callback, text_delta, "assistant")
                    if reasoning_delta:
                        reasoning_parts.append(reasoning_delta)
                        await _emit(callback, reasoning_delta, "reasoning")
                    raw_tools = delta_payload.get("tool_calls")
                    if isinstance(raw_tools, list):
                        for raw in raw_tools:
                            if not isinstance(raw, dict):
                                continue
                            index = int(raw.get("index") or 0)
                            current = tool_calls.setdefault(
                                index, {"id": "", "name": "", "arguments": ""}
                            )
                            current["id"] = str(raw.get("id") or current["id"])
                            function = raw.get("function")
                            if isinstance(function, dict):
                                current["name"] += str(function.get("name") or "")
                                current["arguments"] += str(
                                    function.get("arguments") or ""
                                )
                    from ...provider_transform import normalize_finish_reason

                    candidate_finish = normalize_finish_reason(
                        choice.get("finish_reason")
                    )
                    if candidate_finish != FinishReason.UNKNOWN:
                        finish = candidate_finish

        normalized_tools = [
            LLMToolCall(
                name=value["name"],
                arguments=value["arguments"] or "{}",
                call_id=value["id"] or None,
            )
            for _, value in sorted(tool_calls.items())
        ]
        if normalized_tools:
            finish = FinishReason.TOOL_CALLS
        elif finish == FinishReason.UNKNOWN:
            finish = FinishReason.STOP
        return (
            "".join(text_parts),
            "".join(reasoning_parts),
            normalized_tools,
            usage,
            finish,
            {"response_id": response_id},
        )

    def _parse_buffered(
        self, protocol: LinkProtocol, payload: dict[str, Any]
    ) -> tuple[str, str, list[LLMToolCall], LLMUsage, FinishReason, dict[str, Any]]:
        if protocol == "responses":
            return parse_responses_body(payload)
        return parse_chat_completions_body(payload)

    async def _raise_for_link_error(
        self,
        response: httpx.Response,
        lifecycle: LLMRequestLifecycle,
    ) -> None:
        if response.is_success:
            return
        try:
            payload = response.json()
        except Exception:
            payload = {}
        error_payload = payload.get("error") if isinstance(payload, dict) else None
        error_payload = error_payload if isinstance(error_payload, dict) else {}
        detail = str(
            error_payload.get("message") or response.text or response.reason_phrase
        )
        dispatch_state = response.headers.get("x-link-dispatch-state", "unknown")
        retryable = bool(
            response.status_code >= 500 and dispatch_state == "not_started"
        )
        error = build_llm_error(
            message=detail,
            provider="link",
            model=str(self.model_config.model),
            status_code=response.status_code,
            retry_after_seconds=extract_retry_after_seconds(response),
            retryable=retryable,
            provider_data={
                "dispatch_state": dispatch_state,
                "link_error": error_payload,
            },
        )
        lifecycle.provider_data["dispatch_state"] = dispatch_state
        raise LLMProviderError(error)

    def _capture_response_headers(self, headers: httpx.Headers) -> None:
        names = {
            "x-link-inference-request-id": "request_id",
            "x-link-execution-source": "execution_source",
            "x-link-settlement-mode": "settlement_mode",
            "x-link-meter-event-key": "meter_event_key",
        }
        for header, key in names.items():
            value = headers.get(header)
            if value:
                self._last_provider_data[key] = value


async def _emit(
    callback: StreamCallback | None, text: str, message_type: str
) -> None:
    if callback is None or not text:
        return
    result = callback(text, message_type)
    if inspect.isawaitable(result):
        await result


def _optional_str(value: Any) -> str | None:
    return value if isinstance(value, str) and value else None


__all__ = ["LinkProtocol", "LinkProvider", "LinkProviderConfig"]
