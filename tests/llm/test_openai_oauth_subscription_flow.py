from __future__ import annotations

import logging
import os
from typing import Any

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.contracts import (
    ErrorCategory,
    LLMProviderError,
    ProviderRequestStatus,
)
from penguin.llm.model_config import ModelConfig
from penguin.web.services.provider_auth import ProviderOAuthError

from .codex_oauth_fixtures import (
    FakeCodexTransport as _FakeCodexTransport,
    FakeResponse as _FakeResponse,
    FakeStreamContext as _FakeStreamContext,
    SDKClient as _SDKClient,
    codex_adapter as _codex_adapter,
    codex_completed as _codex_completed,
    codex_completed_text as _codex_completed_text,
    codex_function_call_lines as _codex_function_call_lines,
    codex_sse as _codex_sse,
    codex_text_delta as _codex_text_delta,
    install_oauth_codex_test_auth as _install_oauth_codex_test_auth,
)


@pytest.mark.asyncio
async def test_oauth_request_uses_stored_record_without_env_access(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.delenv("OPENAI_OAUTH_ACCESS_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_REFRESH_TOKEN", raising=False)
    monkeypatch.delenv("OPENAI_OAUTH_EXPIRES_AT_MS", raising=False)
    monkeypatch.delenv("OPENAI_ACCOUNT_ID", raising=False)
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", _SDKClient)
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.get_provider_credential",
        lambda provider_id: {
            "type": "oauth",
            "access": "stored-oauth-access",
            "refresh": "stored-oauth-refresh",
            "expires": 9_999_999_999_000,
            "accountId": "acct-store",
        }
        if provider_id == "openai"
        else None,
    )

    seen: dict[str, Any] = {}

    class _FakeAsyncClient:
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout
            seen["timeout"] = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url
            seen["auth"] = dict(headers or {}).get("Authorization")
            seen["account"] = dict(headers or {}).get("ChatGPT-Account-Id")
            response = _FakeResponse(
                200,
                lines=_codex_completed_text("stored-oauth-answer"),
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

    with caplog.at_level(logging.INFO):
        result = await adapter.get_response(
            [{"role": "user", "content": "hello from stored oauth"}],
            stream=False,
        )

    assert result == "stored-oauth-answer"
    assert seen["auth"] == "Bearer stored-oauth-access"
    assert seen["account"] == "acct-store"
    assert os.environ["OPENAI_OAUTH_ACCESS_TOKEN"] == "stored-oauth-access"
    assert os.environ["OPENAI_ACCOUNT_ID"] == "acct-store"
    assert "openai.oauth.resolve source=store_oauth" in caplog.text
    assert "openai.request.route route=oauth_codex" in caplog.text


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
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout
            seen["timeout"] = timeout

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
                lines=_codex_completed_text("codex-answer"),
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
    assert getattr(seen["timeout"], "read", object()) is None
    assert getattr(seen["timeout"], "connect", None) == 30.0
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
                lines=_codex_completed_text("ok"),
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
                lines=_codex_completed_text("ok"),
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
                    (
                        'data: {"type":"response.reasoning_summary_part.added",'
                        '"part":{"text":"thinking..."}}'
                    ),
                    'data: {"type":"response.reasoning_summary_text.delta","delta":"thinking..."}',
                    (
                        'data: {"type":"response.reasoning_summary_part.done",'
                        '"part":{"text":"thinking..."}}'
                    ),
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
        "summary": "auto",
    }
    assert debug_snapshot["visible_reasoning_summary_returned"] is True
    assert debug_snapshot["visible_reasoning_chars"] == len("thinking...")
    assert (
        "response.reasoning_summary_text.delta"
        in debug_snapshot["reasoning_event_types"]
    )
    assert "response.completed" in debug_snapshot["event_types"]


@pytest.mark.asyncio
async def test_oauth_request_includes_reasoning_summary_auto_and_encrypted_content(
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
                lines=_codex_completed_text("ok"),
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
        reasoning_effort="high",
    )
    adapter = OpenAIAdapter(model_config)

    result = await adapter.get_response(
        [{"role": "user", "content": "hello"}],
        stream=False,
    )

    assert result == "ok"
    assert seen["json"]["reasoning"] == {"effort": "high", "summary": "auto"}
    assert seen["json"]["include"] == ["reasoning.encrypted_content"]


@pytest.mark.asyncio
async def test_oauth_stream_extracts_reasoning_from_output_item_done_summary(
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
                    'data: {"type":"response.output_text.delta","delta":"ok"}',
                    (
                        'data: {"type":"response.completed","response":{"output":['
                        '{"type":"reasoning","summary":['
                        '{"type":"summary_text","text":"Thinking from summary."}'
                        "]}"
                        '],"usage":{'
                        '"input_tokens":10,"output_tokens":2,'
                        '"output_tokens_details":{"reasoning_tokens":5},'
                        '"total_tokens":12}}}'
                    ),
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
        reasoning_effort="high",
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
    assert chunks == [("ok", "assistant"), ("Thinking from summary.", "reasoning")]
    assert adapter.get_last_reasoning() == "Thinking from summary."
    debug_snapshot = adapter.get_reasoning_debug_snapshot()
    assert debug_snapshot["visible_reasoning_summary_returned"] is True
    assert debug_snapshot["visible_reasoning_chars"] == len("Thinking from summary.")


def test_extract_reasoning_from_response_object_reads_summary_array() -> None:
    model_config = ModelConfig(
        model="gpt-5.4",
        provider="openai",
        client_preference="native",
        api_key="sk-test",
    )
    adapter = OpenAIAdapter(model_config)

    reasoning = adapter._extract_reasoning_from_response_object(
        {
            "output": [
                {
                    "type": "reasoning",
                    "summary": [
                        {
                            "type": "summary_text",
                            "text": "First summary.",
                        },
                        {
                            "type": "summary_text",
                            "text": "Second summary.",
                        },
                    ],
                }
            ]
        }
    )

    assert reasoning == "First summary.Second summary."


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


def test_codex_input_items_drop_orphaned_function_call_without_output() -> None:
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
                "role": "assistant",
                "content": "Checking git state, then I'll write the roadmap file.",
                "tool_calls": [
                    {
                        "id": "call_orphan",
                        "type": "function",
                        "function": {
                            "name": "write_file",
                            "arguments": '{"path":"context/todo.md"}',
                        },
                    }
                ],
            }
        ]
    )

    assert items == [
        {
            "type": "message",
            "role": "assistant",
            "content": [
                {
                    "type": "output_text",
                    "text": "Checking git state, then I'll write the roadmap file.",
                }
            ],
        }
    ]


def test_codex_input_items_drop_orphaned_function_call_output_without_call() -> None:
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
                "tool_call_id": "call_output_only",
                "content": "ok",
            }
        ]
    )

    assert items == []


def test_codex_input_items_drop_duplicate_function_call_ids() -> None:
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
                "role": "assistant",
                "content": "First attempt.",
                "tool_calls": [
                    {
                        "id": "call_dup",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "assistant",
                "content": "Duplicate metadata from old session.",
                "tool_calls": [
                    {
                        "id": "call_dup",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_dup",
                "name": "read_file",
                "tool_arguments": '{"path":"README.md"}',
                "content": "README contents",
            },
        ]
    )

    assert (
        items.count(
            {
                "type": "function_call",
                "call_id": "call_dup",
                "name": "read_file",
                "arguments": '{"path":"README.md"}',
            }
        )
        == 1
    )
    assert {
        "type": "function_call_output",
        "call_id": "call_dup",
        "output": "README contents",
    } in items


def test_codex_input_items_preserve_only_complete_tool_pairs_after_cwm_trimming() -> (
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
                "role": "assistant",
                "content": "This call lost its SYSTEM_OUTPUT result during trimming.",
                "tool_calls": [
                    {
                        "id": "call_trimmed_output",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_trimmed_call",
                "content": "tool output without enough metadata to replay",
            },
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_keep",
                        "type": "function",
                        "function": {
                            "name": "list_directory",
                            "arguments": '{"path":"."}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_keep",
                "name": "list_directory",
                "tool_arguments": '{"path":"."}',
                "content": "README.md\npenguin\n",
            },
        ]
    )

    function_items = [
        item
        for item in items
        if item.get("type") in {"function_call", "function_call_output"}
    ]

    assert function_items == [
        {
            "type": "function_call",
            "call_id": "call_keep",
            "name": "list_directory",
            "arguments": '{"path":"."}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_keep",
            "output": "README.md\npenguin",
        },
    ]


@pytest.mark.asyncio
async def test_oauth_codex_request_drops_tool_call_when_cwm_trims_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [_FakeResponse(200, lines=_codex_completed_text("ok"))]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    result = await adapter.get_response(
        [
            {"role": "user", "content": "continue"},
            {
                "role": "assistant",
                "content": "I'll inspect the file.",
                "tool_calls": [
                    {
                        "id": "call_without_output",
                        "type": "function",
                        "function": {
                            "name": "read_file",
                            "arguments": '{"path":"README.md"}',
                        },
                    }
                ],
            },
            {"role": "user", "content": "try again from here"},
        ],
        stream=False,
    )

    assert result == "ok"
    sent_items = transport.requests[0]["json"]["input"]
    assert all(item.get("call_id") != "call_without_output" for item in sent_items)
    assert not any(item.get("type") == "function_call" for item in sent_items)


@pytest.mark.asyncio
async def test_oauth_codex_request_replays_completed_tool_pair_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [_FakeResponse(200, lines=_codex_completed_text("ok"))]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    result = await adapter.get_response(
        [
            {"role": "user", "content": "list the workspace"},
            {
                "role": "assistant",
                "content": "",
                "tool_calls": [
                    {
                        "id": "call_complete",
                        "type": "function",
                        "function": {
                            "name": "list_directory",
                            "arguments": '{"path":"."}',
                        },
                    }
                ],
            },
            {
                "role": "tool",
                "tool_call_id": "call_complete",
                "name": "list_directory",
                "tool_arguments": '{"path":"."}',
                "content": "README.md\npenguin\n",
            },
            {"role": "user", "content": "summarize the result"},
        ],
        stream=False,
    )

    assert result == "ok"
    sent_items = transport.requests[0]["json"]["input"]
    function_items = [
        item
        for item in sent_items
        if item.get("type") in {"function_call", "function_call_output"}
    ]
    assert function_items == [
        {
            "type": "function_call",
            "call_id": "call_complete",
            "name": "list_directory",
            "arguments": '{"path":"."}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_complete",
            "output": "README.md\npenguin",
        },
    ]


@pytest.mark.asyncio
async def test_oauth_codex_request_synthesizes_call_when_only_tool_result_survives(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [_FakeResponse(200, lines=_codex_completed_text("ok"))]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    result = await adapter.get_response(
        [
            {"role": "user", "content": "continue"},
            {
                "role": "tool",
                "tool_call_id": "call_result_only",
                "name": "code_execution",
                "tool_arguments": '{"code":"print(7)"}',
                "content": "7\nRESULT=7",
            },
            {"role": "user", "content": "use that result"},
        ],
        stream=False,
    )

    assert result == "ok"
    sent_items = transport.requests[0]["json"]["input"]
    function_items = [
        item
        for item in sent_items
        if item.get("type") in {"function_call", "function_call_output"}
    ]
    assert function_items == [
        {
            "type": "function_call",
            "call_id": "call_result_only",
            "name": "code_execution",
            "arguments": '{"code":"print(7)"}',
        },
        {
            "type": "function_call_output",
            "call_id": "call_result_only",
            "output": "7\nRESULT=7",
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
                lines=_codex_completed_text("refreshed"),
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
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.FAILED
    assert lifecycle.error is not None
    assert lifecycle.error.category == ErrorCategory.PROVIDER_UNAVAILABLE


@pytest.mark.asyncio
async def test_oauth_codex_incomplete_empty_stream_records_disconnected_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [
            _FakeResponse(
                200,
                lines=["data: [DONE]"],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    with pytest.raises(LLMProviderError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

    assert "stream_incomplete" in str(exc.value)
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.DISCONNECTED
    assert lifecycle.stream is True
    assert lifecycle.transport == "sse"
    assert lifecycle.last_event_type == "stream_incomplete"
    assert lifecycle.request_payload_hash
    assert lifecycle.error is not None
    assert lifecycle.error.category == ErrorCategory.NETWORK
    assert lifecycle.error.retryable is True
    assert transport.requests[0]["json"]["stream"] is True


@pytest.mark.asyncio
async def test_oauth_codex_partial_text_without_completed_is_disconnected(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [
            _FakeResponse(
                200,
                lines=[
                    _codex_text_delta("partial"),
                    "data: [DONE]",
                ],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    with pytest.raises(LLMProviderError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

    assert "output_state=text" in str(exc.value)
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.DISCONNECTED
    assert lifecycle.last_event_type == "stream_incomplete"
    assert lifecycle.error is not None
    assert lifecycle.error.retryable is True


@pytest.mark.asyncio
async def test_oauth_codex_partial_tool_call_without_completed_is_not_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [
            _FakeResponse(
                200,
                lines=[
                    *_codex_function_call_lines(),
                    "data: [DONE]",
                ],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    with pytest.raises(LLMProviderError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "read README"}],
            stream=False,
        )

    assert "output_state=tool_call" in str(exc.value)
    assert adapter.has_pending_tool_call() is False
    assert adapter.get_and_clear_pending_tool_calls() == []
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.DISCONNECTED
    assert lifecycle.last_event_type == "stream_incomplete"


@pytest.mark.asyncio
async def test_oauth_codex_completed_tool_call_remains_pending(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [
            _FakeResponse(
                200,
                lines=[
                    *_codex_function_call_lines(call_id="call_done"),
                    _codex_completed("resp_tool"),
                    "data: [DONE]",
                ],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    result = await adapter.get_response(
        [{"role": "user", "content": "read README"}],
        stream=False,
    )

    assert result == ""
    assert adapter.has_pending_tool_call() is True
    pending = adapter.get_and_clear_pending_tool_calls()
    assert pending == [
        {
            "item_id": "item_1",
            "call_id": "call_done",
            "name": "read_file",
            "arguments": '{"path":"README.md"}',
        }
    ]
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.COMPLETED
    assert lifecycle.provider_response_id == "resp_tool"


@pytest.mark.asyncio
async def test_oauth_codex_stream_event_error_records_failed_lifecycle(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_oauth_codex_test_auth(monkeypatch)
    transport = _FakeCodexTransport(
        [
            _FakeResponse(
                200,
                lines=[
                    _codex_sse(
                        {
                            "type": "error",
                            "error": {
                                "type": "server_error",
                                "message": "synthetic stream error",
                            },
                        }
                    )
                ],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient",
        transport.async_client_class(),
    )
    adapter = _codex_adapter()

    with pytest.raises(LLMProviderError) as exc:
        await adapter.get_response(
            [{"role": "user", "content": "hello"}],
            stream=False,
        )

    assert "stream_event_error" in str(exc.value)
    assert "synthetic stream error" in str(exc.value)
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.FAILED
    assert lifecycle.last_event_type == "stream_event_error"


@pytest.mark.asyncio
async def test_oauth_codex_incomplete_stream_does_not_lock_next_turn(
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

    responses = [
        _FakeResponse(200, lines=["data: [DONE]"]),
        _FakeResponse(
            200,
            lines=[
                'data: {"type":"response.output_text.delta","delta":"recovered"}',
                (
                    'data: {"type":"response.completed","response":'
                    '{"id":"resp_recovered","usage":{"input_tokens":1,'
                    '"output_tokens":1,"total_tokens":2}}}'
                ),
                "data: [DONE]",
            ],
        ),
    ]

    class _FakeAsyncClient:
        def __init__(self, timeout: Any) -> None:
            self.timeout = timeout

        async def __aenter__(self) -> _FakeAsyncClient:
            return self

        async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
            del exc_type, exc, tb
            return False

        def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
            del method, url, headers, json
            return _FakeStreamContext(responses.pop(0))

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

    with pytest.raises(LLMProviderError):
        await adapter.get_response(
            [{"role": "user", "content": "first"}],
            stream=False,
        )

    result = await adapter.get_response(
        [{"role": "user", "content": "second"}],
        stream=False,
    )

    assert result == "recovered"
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle is not None
    assert lifecycle.status == ProviderRequestStatus.COMPLETED
    assert lifecycle.provider_response_id == "resp_recovered"
