from __future__ import annotations

import asyncio
import logging
from typing import Any

import pytest

from penguin.llm.openrouter_gateway import OpenRouterGateway


class DelayedAsyncIterator:
    def __init__(self, values: list[Any], *, delay_seconds: float = 0.0) -> None:
        self._values = list(values)
        self._delay_seconds = delay_seconds

    def __aiter__(self) -> "DelayedAsyncIterator":
        return self

    async def __anext__(self) -> Any:
        if not self._values:
            raise StopAsyncIteration
        if self._delay_seconds:
            await asyncio.sleep(self._delay_seconds)
        return self._values.pop(0)


def _gateway() -> OpenRouterGateway:
    gateway = OpenRouterGateway.__new__(OpenRouterGateway)
    gateway.logger = logging.getLogger("test.openrouter.watchdog")
    return gateway


@pytest.mark.asyncio
async def test_openrouter_stream_watchdog_times_out_stalled_chunk() -> None:
    gateway = _gateway()
    started_at = asyncio.get_running_loop().time()

    with pytest.raises(TimeoutError):
        await gateway._next_stream_item(
            DelayedAsyncIterator(["chunk"], delay_seconds=0.05),
            wait_timeout=0.001,
            total_timeout=1.0,
            started_at=started_at,
            phase="test stream",
        )


@pytest.mark.asyncio
async def test_openrouter_stream_watchdog_times_out_total_budget() -> None:
    gateway = _gateway()
    started_at = asyncio.get_running_loop().time() - 10.0

    with pytest.raises(TimeoutError, match="total timeout"):
        await gateway._next_stream_item(
            DelayedAsyncIterator(["chunk"]),
            wait_timeout=1.0,
            total_timeout=0.001,
            started_at=started_at,
            phase="test stream",
        )


@pytest.mark.asyncio
async def test_openrouter_stream_watchdog_allows_active_chunk() -> None:
    gateway = _gateway()
    started_at = asyncio.get_running_loop().time()

    chunk = await gateway._next_stream_item(
        DelayedAsyncIterator(["chunk"]),
        wait_timeout=1.0,
        total_timeout=1.0,
        started_at=started_at,
        phase="test stream",
    )

    assert chunk == "chunk"


def test_openrouter_stream_watchdog_reads_provider_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()

    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "0.25")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_TOTAL_TIMEOUT_SECONDS", "2.5")

    assert gateway._stream_chunk_timeout_seconds() == 0.25
    assert gateway._stream_total_timeout_seconds() == 2.5


def test_openrouter_stream_watchdog_rejects_invalid_timeout_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    gateway = _gateway()

    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_CHUNK_TIMEOUT_SECONDS", "-1")
    monkeypatch.setenv("PENGUIN_OPENROUTER_STREAM_TOTAL_TIMEOUT_SECONDS", "bad")

    assert gateway._stream_chunk_timeout_seconds() == 75.0
    assert gateway._stream_total_timeout_seconds() == 300.0
