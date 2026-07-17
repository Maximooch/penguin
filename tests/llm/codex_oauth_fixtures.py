from __future__ import annotations

import json
from typing import Any

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig


class SDKClient:
    def __init__(
        self,
        *,
        api_key: str,
        base_url: str | None = None,
        default_headers: dict[str, str] | None = None,
        max_retries: int = 0,
    ) -> None:
        self.api_key = api_key
        self.base_url = base_url
        self.default_headers = default_headers
        self.max_retries = max_retries


class FakeResponse:
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

    async def aiter_lines(self):  # type: ignore[no-untyped-def]
        for line in self._lines:
            yield line


class FakeStreamContext:
    def __init__(self, response: FakeResponse) -> None:
        self._response = response

    async def __aenter__(self) -> FakeResponse:
        return self._response

    async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
        del exc_type, exc, tb
        return False


def codex_sse(payload: dict[str, Any]) -> str:
    return "data: " + json.dumps(payload, separators=(",", ":"))


def codex_text_delta(text: str) -> str:
    return codex_sse({"type": "response.output_text.delta", "delta": text})


def codex_completed(
    response_id: str = "resp_test",
    *,
    usage: dict[str, Any] | None = None,
) -> str:
    response: dict[str, Any] = {"id": response_id}
    if usage is not None:
        response["usage"] = usage
    return codex_sse({"type": "response.completed", "response": response})


def codex_completed_text(text: str, response_id: str = "resp_test") -> list[str]:
    return [
        codex_text_delta(text),
        codex_completed(response_id),
        "data: [DONE]",
    ]


def codex_function_call_lines(
    *,
    item_id: str = "item_1",
    call_id: str = "call_1",
    name: str = "read_file",
    arguments: str = '{"path":"README.md"}',
) -> list[str]:
    return [
        codex_sse(
            {
                "type": "response.output_item.added",
                "item": {
                    "type": "function_call",
                    "id": item_id,
                    "call_id": call_id,
                    "name": name,
                    "arguments": "",
                },
            }
        ),
        codex_sse(
            {
                "type": "response.function_call_arguments.delta",
                "item_id": item_id,
                "delta": arguments,
            }
        ),
        codex_sse(
            {
                "type": "response.output_item.done",
                "item": {
                    "type": "function_call",
                    "id": item_id,
                    "call_id": call_id,
                    "name": name,
                    "arguments": arguments,
                    "status": "completed",
                },
            }
        ),
    ]


class FakeCodexTransport:
    def __init__(self, responses: list[FakeResponse]) -> None:
        self.responses = list(responses)
        self.requests: list[dict[str, Any]] = []
        self.timeouts: list[Any] = []

    def async_client_class(self):  # type: ignore[no-untyped-def]
        transport = self

        class _FakeAsyncClient:
            def __init__(self, timeout: Any) -> None:
                self.timeout = timeout
                transport.timeouts.append(timeout)

            async def __aenter__(self) -> "_FakeAsyncClient":
                return self

            async def __aexit__(self, exc_type, exc, tb) -> bool:  # type: ignore[no-untyped-def]
                del exc_type, exc, tb
                return False

            def stream(self, method: str, url: str, headers=None, json=None):  # type: ignore[no-untyped-def]
                transport.requests.append(
                    {
                        "method": method,
                        "url": url,
                        "headers": dict(headers or {}),
                        "json": dict(json or {}),
                    }
                )
                return FakeStreamContext(transport.responses.pop(0))

        return _FakeAsyncClient


def install_oauth_codex_test_auth(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENAI_OAUTH_ACCESS_TOKEN", "oauth-access")
    monkeypatch.setenv("OPENAI_ACCOUNT_ID", "acct-1")
    monkeypatch.setattr("penguin.llm.adapters.openai.AsyncOpenAI", SDKClient)
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


def codex_adapter() -> OpenAIAdapter:
    return OpenAIAdapter(
        ModelConfig(
            model="gpt-5.2",
            provider="openai",
            client_preference="native",
            api_key="sk-test",
            streaming_enabled=False,
        )
    )
