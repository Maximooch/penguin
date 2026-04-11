from __future__ import annotations

import json
import os
from typing import Any

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig
from penguin.web.services.provider_auth import ProviderOAuthError


class _SDKClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_headers = default_headers


class _FakeResponse:
    def __init__(
        self,
        status_code: int,
        payload: dict[str, Any] | None = None,
        *,
        headers: dict[str, str] | None = None,
        lines: list[str] | None = None,
    ) -> None:
        self.status_code = status_code
        self._payload = payload if payload is not None else {}
        self.headers = dict(headers or {})
        self._lines = list(lines or [])
        self.content = (
            json.dumps(self._payload).encode("utf-8") if payload is not None else b""
        )
        self.text = json.dumps(self._payload)

    def json(self) -> dict[str, Any]:
        return dict(self._payload)

    async def aread(self) -> bytes:
        return self.content

    async def aiter_lines(self):
        for line in self._lines:
            yield line


class _FakeStreamContext:
    def __init__(self, response: _FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> _FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return False


@pytest.mark.asyncio
async def test_oauth_request_routes_to_codex_with_required_headers(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "acct-1")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 9_999_999_999_000,
            "accountId": "acct-1",
        }
        if provider_id == "openai"
        else None,
    )

    seen: dict[str, Any] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            seen["method"] = method
            seen["url"] = url
            seen["headers"] = dict(headers or {})
            seen["json"] = dict(json or {})
            response = _FakeResponse(
                200,
                lines=[
                    (
                        'data: {"type":"response.output_text.delta",'
                        '"delta":"codex-answer"}'
                    ),
                    "data: [DONE]",
                ],
            )
            return _FakeStreamContext(response)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        max_output_tokens=321,
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)

    result = await adapter.get_response(
        [
            {"role": "system", "content": "SYSTEM POLICY"},
            {"role": "user", "content": "hello"},
            {"role": "assistant", "content": "previous assistant reply"},
            {"role": "system", "content": "dynamic runtime note"},
        ],
        stream=False,
    )

    assert result == "codex-answer"
    assert seen["method"] == "POST"
    assert seen["url"] == "https://chatgpt.com/backend-api/codex/responses"
    assert seen["headers"]["Authorization"] == "Bearer oauth-access"
    assert seen["headers"]["ChatGPT-Account-Id"] == "acct-1"
    assert seen["json"]["store"] is False
    assert seen["json"]["stream"] is True
    assert "max_output_tokens" not in seen["json"]
    assert isinstance(seen["json"]["input"], list)
    assert all(item.get("role") != "system" for item in seen["json"]["input"])
    assistant_items = [
        item for item in seen["json"]["input"] if item.get("role") == "assistant"
    ]
    assert assistant_items
    assert all(
        part.get("type") in {"output_text", "refusal"}
        for item in assistant_items
        for part in item.get("content", [])
        if isinstance(part, dict)
    )
    assert any(
        "[SYSTEM NOTE]" in part.get("text", "")
        for item in seen["json"]["input"]
        for part in item.get("content", [])
        if isinstance(part, dict)
    )
    assert isinstance(seen["json"]["instructions"], str)
    assert seen["json"]["instructions"]
    assert "SYSTEM POLICY" in seen["json"]["instructions"]


@pytest.mark.asyncio
async def test_oauth_request_preserves_requested_model_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 9_999_999_999_000,
        }
        if provider_id == "openai"
        else None,
    )

    seen: dict[str, Any] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url, headers
            seen["model"] = (json or {}).get("model")
            response = _FakeResponse(
                200,
                lines=[
                    'data: {"type":"response.output_text.delta","delta":"ok"}',
                    "data: [DONE]",
                ],
            )
            return _FakeStreamContext(response)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)
    result = await adapter.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result == "ok"
    assert seen["model"] == "gpt-5.4"


@pytest.mark.asyncio
async def test_oauth_request_normalizes_responses_function_tools(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "acct-1")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 9_999_999_999_000,
            "accountId": "acct-1",
        }
        if provider_id == "openai"
        else None,
    )

    seen: dict[str, Any] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url, headers
            seen["json"] = dict(json or {})
            response = _FakeResponse(
                200,
                lines=[
                    'data: {"type":"response.output_text.delta","delta":"ok"}',
                    "data: [DONE]",
                ],
            )
            return _FakeStreamContext(response)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)
    result = await adapter.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
        tools=[
            {
                "type": "function",
                "function": {
                    "name": "read_file",
                    "description": "Read a file",
                    "parameters": {"type": "object", "properties": {}},
                },
            }
        ],
        tool_choice={"type": "function", "function": {"name": "read_file"}},
    )

    assert result == "ok"
    assert seen["json"]["tools"] == [
        {
            "type": "function",
            "name": "read_file",
            "description": "Read a file",
            "parameters": {"type": "object", "properties": {}},
        }
    ]
    assert seen["json"]["tool_choice"] == {
        "type": "function",
        "name": "read_file",
    }


@pytest.mark.asyncio
async def test_oauth_stream_records_reasoning_debug_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "acct-1")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 9_999_999_999_000,
            "accountId": "acct-1",
        }
        if provider_id == "openai"
        else None,
    )

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url, headers, json
            response = _FakeResponse(
                200,
                lines=[
                    'data: {"type":"response.reasoning_summary_text.delta","delta":"thinking..."}',
                    'data: {"type":"response.output_text.delta","delta":"ok"}',
                    'data: {"type":"response.completed","response":{"usage":{"input_tokens":10,"output_tokens":2,"output_tokens_details":{"reasoning_tokens":5},"total_tokens":12}}}',
                    "data: [DONE]",
                ],
            )
            return _FakeStreamContext(response)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
        reasoning_enabled=True,
        reasoning_effort="xhigh",
    )
    adapter = OpenAIAdapter(model_config)
    chunks: list[tuple[str, str]] = []

    async def on_chunk(chunk: str, message_type: str) -> None:
        chunks.append((chunk, message_type))

    result = await adapter.get_response(
        [{"role": "user", "content": "hello"}],
        stream=True,
        stream_callback=on_chunk,  # type: ignore[arg-type]
    )

    assert result == "ok"
    assert chunks == [("thinking...", "reasoning"), ("ok", "assistant")]
    debug_snapshot = adapter.get_reasoning_debug_snapshot()
    assert debug_snapshot["reasoning_config"] == {
        "effort": "xhigh",
        "summary": "concise",
    }
    assert debug_snapshot["visible_reasoning_summary_returned"] is True
    assert debug_snapshot["visible_reasoning_chars"] == len("thinking...")
    assert (
        "response.reasoning_summary_text.delta"
        in debug_snapshot["reasoning_event_types"]
    )
    assert "response.completed" in debug_snapshot["event_types"]


def test_codex_input_items_include_function_call_and_output_for_tool_history() -> None:
    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
    )
    adapter = OpenAIAdapter(model_config)

    _, transformed = adapter._prepare_codex_messages_and_instructions(
        None,
        [
            {
                "role": "assistant",
                "content": "Running a tiny Python function now.",
                "tool_calls": [
                    {
                        "id": "call_123",
                        "type": "function",
                        "function": {
                            "name": "code_execution",
                            "arguments": '{"code":"print(13)"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_123",
                "content": "13\nRESULT=13",
                "name": "code_execution",
            },
        ],
    )

    items = adapter._build_codex_input_items(transformed)

    assert {
        "type": "function_call",
        "call_id": "call_123",
        "name": "code_execution",
        "arguments": '{"code":"print(13)"}',
    } in items
    assert {
        "type": "function_call_output",
        "call_id": "call_123",
        "output": "13\nRESULT=13",
    } in items


def test_codex_input_items_synthesize_function_call_from_tool_message_when_needed() -> (
    None
):
    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
    )
    adapter = OpenAIAdapter(model_config)

    items = adapter._build_codex_input_items(
        [
            {
                "role": "tool",
                "tool_call_id": "call_456",
                "name": "code_execution",
                "tool_arguments": '{"code":"print(44)"}',
                "content": "44\nRESULT=44",
            }
        ]
    )

    assert items == [
        {
            "type": "function_call",
            "call_id": "call_456",
            "name": "code_execution",
            "arguments": '{"code":"print(44)"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_456",
            "output": "44\nRESULT=44",
        },
    ]


@pytest.mark.asyncio
async def test_oauth_request_refreshes_before_codex_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-stale")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-stale",
            "refresh": "oauth-refresh",
            "expires": 1,
            "accountId": "acct-before",
        }
        if provider_id == "openai"
        else None,
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.oauth_record_needs_refresh",
        lambda *_args, **_kwargs: True,
    )

    refresh_calls: list[str] = []

    async def _refresh(provider_id: str, **kwargs: Any) -> dict[str, Any]:
        refresh_calls.append(provider_id)
        return {
            "type": "oauth",
            "access": "oauth-fresh",
            "refresh": "oauth-refresh-new",
            "expires": 9_999_999_999_000,
            "accountId": "acct-after",
        }

    monkeypatch.setattr("penguin.llm.adapters.openai.refresh_provider_oauth", _refresh)

    seen: dict[str, Any] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url
            seen["auth"] = dict(headers or {}).get("Authorization")
            seen["account"] = dict(headers or {}).get("ChatGPT-Account-Id")
            seen["stream"] = bool((json or {}).get("stream"))
            response = _FakeResponse(
                200,
                lines=[
                    'data: {"type":"response.output_text.delta","delta":"refreshed"}',
                    "data: [DONE]",
                ],
            )
            return _FakeStreamContext(response)

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)

    result = await adapter.get_response(
        [{"role": "user", "content": "refresh now"}],
        stream=False,
    )

    assert result == "refreshed"
    assert refresh_calls == ["openai"]
    assert seen["auth"] == "Bearer oauth-fresh"
    assert seen["account"] == "acct-after"
    assert seen["stream"] is True
    assert os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] == "oauth-fresh"
    assert os.environ["OPENAI_ACCOUNT_ID"] == "acct-after"
    assert adapter.model_config.api_key == "oauth-fresh"


@pytest.mark.asyncio
async def test_oauth_refresh_failure_raises_reauth_required(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-stale")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-stale",
            "refresh": "oauth-refresh",
            "expires": 1,
        }
        if provider_id == "openai"
        else None,
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.oauth_record_needs_refresh",
        lambda *_args, **_kwargs: True,
    )

    async def _refresh(provider_id: str, **kwargs: Any) -> dict[str, Any]:
        del provider_id, kwargs
        raise ProviderOAuthError(
            stage="refresh.token_exchange",
            detail="refresh failed",
            provider_id="openai",
            method_index=1,
            status_code=401,
        )

    monkeypatch.setattr("penguin.llm.adapters.openai.refresh_provider_oauth", _refresh)

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)

    with pytest.raises(RuntimeError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "refresh now"}],
            stream=False,
        )

    assert "reauth required" in str(exc.value).lower()


@pytest.mark.asyncio
async def test_oauth_codex_status_error_emits_diag_and_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "oauth-access",
            "refresh": "oauth-refresh",
            "expires": 9_999_999_999_000,
            "accountId": "acct-1",
        }
        if provider_id == "openai"
        else None,
    )

    class _FakeAsyncClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url, headers, json
            return _FakeStreamContext(
                _FakeResponse(
                    503,
                    {
                        "error": {
                            "message": "service unavailable",
                            "type": "server_error",
                            "code": "internal_error",
                        }
                    },
                    headers={"x-request-id": "req_123", "cf-ray": "ray_456"},
                )
            )

    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", _FakeAsyncClient
    )

    model_config = ModelConfig(
        model="gpt-5.2",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
        streaming_enabled=False,
    )
    adapter = OpenAIAdapter(model_config)

    with pytest.raises(RuntimeError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

    message = str(exc.value)
    assert "diag_id=oaoc_" in message
    assert "status=503" in message
    assert "service unavailable" in message
    assert "trace={'x-request-id': 'req_123', 'cf-ray': 'ray_456'}" in message
