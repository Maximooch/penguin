"""An Anthropic stream timeout is recorded as an error, not returned as an answer."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.llm.adapters import anthropic as anthropic_adapter
from penguin.llm.contracts import ErrorCategory, FinishReason
from tests.llm.test_anthropic_stream_callback_contract import (
    _build_adapter,
    _Chunk,
    _Delta,
    _FakeStream,
)


@pytest.mark.asyncio
async def test_stream_timeout_is_recorded_as_a_retryable_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The clock reads 0 while the stream is set up and 100 s afterwards, which
    # is past the adapter's overall streaming limit.
    readings = iter([0.0, 0.0])
    monkeypatch.setattr(
        anthropic_adapter,
        "time",
        SimpleNamespace(time=lambda: next(readings, 100.0)),
    )
    adapter = _build_adapter(
        _FakeStream(
            [
                _Chunk("content_block_delta", _Delta("text_delta", text="partial")),
                _Chunk("content_block_delta", _Delta("text_delta", text=" more")),
                _Chunk("message_stop"),
            ]
        )
    )
    adapter.model_config = SimpleNamespace(model="claude-test")

    await adapter._handle_streaming({"stream": True}, None)

    error = adapter.get_last_error()
    assert error is not None
    assert error.category == ErrorCategory.TIMEOUT
    assert error.retryable is True
    assert adapter.get_last_finish_reason() == FinishReason.ERROR
