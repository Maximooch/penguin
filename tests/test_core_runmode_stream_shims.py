"""Core shim coverage for extracted RunMode stream callback helpers."""

from __future__ import annotations

from typing import Any

import pytest

from penguin.core import PenguinCore


def test_prepare_runmode_stream_callback_delegates_to_stream_events(
    monkeypatch,
) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []
    prepared = object()

    def _prepare(*args: Any, **kwargs: Any) -> object:
        calls.append((args, kwargs))
        return prepared

    monkeypatch.setattr(
        "penguin.core.core_stream_events.prepare_runmode_stream_callback",
        _prepare,
    )

    callback = object()

    assert core._prepare_runmode_stream_callback(callback) is prepared
    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (callback,)
    assert sorted(kwargs) == ["adapter_factory"]


@pytest.mark.asyncio
async def test_invoke_runmode_stream_callback_delegates_to_stream_events(
    monkeypatch,
) -> None:
    core = PenguinCore.__new__(PenguinCore)
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    async def _invoke(*args: Any, **kwargs: Any) -> None:
        calls.append((args, kwargs))

    monkeypatch.setattr(
        "penguin.core.core_stream_events.invoke_runmode_stream_callback",
        _invoke,
    )

    callback = object()

    await core._invoke_runmode_stream_callback(
        "chunk",
        "assistant",
        callback=callback,
    )

    assert len(calls) == 1
    args, kwargs = calls[0]
    assert args == (core, "chunk", "assistant")
    assert kwargs["callback"] is callback
    assert "logger" in kwargs
