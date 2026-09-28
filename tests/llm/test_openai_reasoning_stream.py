"""Exercise reasoning delivery through every native OpenAI stream transport."""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncIterator
from unittest.mock import AsyncMock

import pytest

from penguin.llm.adapters.openai import OpenAIAdapter
from penguin.llm.model_config import ModelConfig

from .codex_oauth_fixtures import (
    FakeCodexTransport,
    FakeResponse,
    codex_sse,
    install_oauth_codex_test_auth,
)


def _item(text: str, item_id: str = "rs_1") -> dict[str, Any]:
    return {
        "id": item_id,
        "type": "reasoning",
        "summary": [{"type": "summary_text", "text": text}],
    }


def _delta(text: str, index: int = 0) -> dict[str, Any]:
    return {
        "type": "response.reasoning_summary_text.delta",
        "item_id": "rs_1",
        "summary_index": index,
        "delta": text,
    }


HEADING = "**Checking sources**"
FULL = HEADING + "\n\nThe complete summary body."
ITEM = _item(FULL)


@pytest.mark.asyncio
@pytest.mark.parametrize("transport_name", ["oauth", "sdk", "http"])
@pytest.mark.parametrize(
    ("events", "output", "expected"),
    [
        ([], [_item("")], ""),
        ([_delta(FULL)], [ITEM], FULL),
        (
            [_delta(HEADING), {"type": "response.output_item.done", "item": ITEM}],
            [ITEM],
            FULL,
        ),
        ([_delta(HEADING)], [ITEM], FULL),
        (
            [
                _delta("ha"),
                _delta("ha"),
                {
                    "type": "response.reasoning_summary_part.done",
                    "item_id": "rs_1",
                    "summary_index": 0,
                    "part": {"text": "haha!"},
                },
            ],
            [_item("haha!")],
            "haha!",
        ),
        (
            [
                {
                    "type": "response.reasoning_summary_text.delta",
                    "output_index": 0,
                    "delta": HEADING,
                },
                {
                    "type": "response.output_item.done",
                    "item": {"id": "msg_1", "type": "message"},
                },
                {
                    "type": "response.reasoning_summary_text.done",
                    "item_id": "rs_1",
                    "summary_index": 0,
                    "text": FULL,
                },
            ],
            [ITEM],
            FULL,
        ),
        (
            [
                {"type": "response.output_item.done", "item": _item("Same.")},
                {"type": "response.output_item.done", "item": _item("Same.", "rs_2")},
            ],
            [_item("Same."), _item("Same.", "rs_2")],
            "Same.Same.",
        ),
        (
            [
                {
                    "type": "response.reasoning_summary_text.done",
                    "item_id": "rs_1",
                    "summary_index": 0,
                    "text": FULL,
                }
            ],
            [],
            FULL,
        ),
        (
            [_delta("Same."), _delta("Same.", 1)],
            [
                {
                    **_item("Same."),
                    "summary": [{"type": "summary_text", "text": "Same."}] * 2,
                }
            ],
            "Same.Same.",
        ),
        (
            [
                {
                    "type": "response.reasoning_text.delta",
                    "item_id": "rs_1",
                    "content_index": 0,
                    "delta": "Visible content.",
                }
            ],
            [
                {
                    "type": "reasoning",
                    "id": "rs_1",
                    "content": [{"type": "reasoning_text", "text": "Visible content."}],
                }
            ],
            "Visible content.",
        ),
    ],
    ids=[
        "empty",
        "duplicate-final",
        "heading-item",
        "heading-final",
        "repeated-deltas-part-done",
        "index-to-id",
        "two-items",
        "done-only",
        "two-parts",
        "reasoning-content",
    ],
)
async def test_reasoning_survives_stream_snapshots(
    monkeypatch: pytest.MonkeyPatch,
    transport_name: str,
    events: list[dict[str, Any]],
    output: list[dict[str, Any]],
    expected: str,
) -> None:
    install_oauth_codex_test_auth(monkeypatch)
    adapter = OpenAIAdapter(
        ModelConfig(
            model="gpt-6-astra",
            provider="openai",
            api_key="sk-test",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )
    final = {
        "id": "resp_test",
        "output": output,
        "output_text": "ok",
        "usage": {
            "input_tokens": 10,
            "output_tokens": 20,
            "output_tokens_details": {"reasoning_tokens": 18},
        },
    }
    stream_events = [
        *events,
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": final},
    ]
    transport = FakeCodexTransport(
        [FakeResponse(200, lines=[codex_sse(event) for event in stream_events])]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", transport.async_client_class()
    )

    class SDKStream:
        async def __aenter__(self) -> SDKStream:
            return self

        async def __aexit__(self, *args: Any) -> None:
            pass

        async def __aiter__(self) -> AsyncIterator[SimpleNamespace]:
            for event in stream_events:
                yield SimpleNamespace(**event)

        async def get_final_response(self) -> SimpleNamespace:
            return SimpleNamespace(**final)

    chunks: list[str] = []

    async def on_chunk(text: str, kind: str) -> None:
        if kind == "reasoning":
            chunks.append(text)

    if transport_name == "oauth":
        result = await adapter.get_response(
            [{"role": "user", "content": "test"}], stream=True, stream_callback=on_chunk
        )
        payload = transport.requests[0]["json"]
        assert payload["reasoning"] == {"effort": "medium", "summary": "auto"}
        assert payload["include"] == ["reasoning.encrypted_content"]
        assert "stream_options" not in payload
    elif transport_name == "sdk":
        adapter.client.responses = SimpleNamespace(stream=lambda **kwargs: SDKStream())
        result = await adapter._stream_with_sdk({}, on_chunk)
    else:
        pool = SimpleNamespace(
            get_client=AsyncMock(return_value=transport.async_client_class()(timeout=1))
        )
        monkeypatch.setattr(
            "penguin.llm.adapters.openai.ConnectionPoolManager.get_instance",
            lambda: pool,
        )
        result = await adapter._stream_with_http({}, on_chunk)

    assert result == "ok"
    assert "".join(chunks) == expected
    assert adapter.get_last_reasoning() == expected


@pytest.mark.asyncio
async def test_oauth_reasoning_resets_and_diagnostics_omit_content(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    install_oauth_codex_test_auth(monkeypatch)
    adapter = OpenAIAdapter(
        ModelConfig(
            model="gpt-6-astra",
            provider="openai",
            api_key="sk-test",
            reasoning_enabled=True,
            reasoning_effort="medium",
        )
    )
    output = [{**ITEM, "encrypted_content": "private-ciphertext"}]
    events = [
        {"type": "response.output_text.delta", "delta": "ok"},
        {"type": "response.completed", "response": {"output": output}},
    ]
    transport = FakeCodexTransport(
        [
            FakeResponse(200, lines=[codex_sse(event) for event in events])
            for _ in range(2)
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", transport.async_client_class()
    )
    with caplog.at_level(logging.INFO):
        for _ in range(2):
            await adapter.get_response(
                [{"role": "user", "content": "private-prompt"}], stream=True
            )
            assert adapter.get_last_reasoning() == FULL

    debug = adapter.get_reasoning_debug_snapshot()
    assert debug["request_options"] == {
        "effort": "medium",
        "summary": "auto",
        "summary_delivery": None,
        "encrypted_content": True,
    }
    assert debug["reasoning_parts"] == [
        {"item_id": "rs_1", "summary_chars": [len(FULL)]}
    ]
    diagnostic_logs = "\n".join(
        record.getMessage()
        for record in caplog.records
        if "openai.oauth.codex.request_start" in record.getMessage()
        or "openai.oauth.codex.reasoning_debug" in record.getMessage()
    )
    assert "'summary': 'auto'" in diagnostic_logs
    assert "summary_chars" in diagnostic_logs
    for private in (
        "private-prompt",
        "private-ciphertext",
        "oauth-access",
        "The complete summary body",
    ):
        assert private not in diagnostic_logs
