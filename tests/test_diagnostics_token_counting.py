"""Tests for diagnostics token counting fallback behavior."""

from __future__ import annotations

import importlib
from typing import Any

diagnostics_module = importlib.import_module("penguin.utils.diagnostics")


def test_diagnostics_token_counting_falls_back_when_tiktoken_unavailable(
    monkeypatch,
) -> None:
    calls = 0

    def fail_get_encoding(_name: str) -> Any:
        nonlocal calls
        calls += 1
        raise RuntimeError("network unavailable")

    monkeypatch.setattr(diagnostics_module.tiktoken, "get_encoding", fail_get_encoding)
    diagnostics = diagnostics_module.Diagnostics()

    assert diagnostics.count_tokens("abcd") == 2
    assert diagnostics.count_tokens("abcd") == 2
    assert calls == 1


def test_diagnostics_token_counting_fallback_handles_multimodal_content(
    monkeypatch,
) -> None:
    monkeypatch.setattr(
        diagnostics_module.tiktoken,
        "get_encoding",
        lambda _name: (_ for _ in ()).throw(RuntimeError("offline")),
    )
    diagnostics = diagnostics_module.Diagnostics()

    count = diagnostics.count_tokens(
        [
            {"type": "text", "text": "abcdefgh"},
            {"type": "image_url", "image_url": "memory://image"},
        ]
    )

    assert count == 4003
