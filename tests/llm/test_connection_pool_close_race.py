"""A pool being closed never hands out, or forgets, a client.

Covers SM-75 (connection pool ``close_all``): the clients stayed in the pool
while each was awaited closed, so ``get_client`` could return a client that
was being closed, and a client created meanwhile for a new URL was cleared
from the pool without being closed.
"""

from __future__ import annotations

import asyncio

import pytest

from penguin.llm.api_client import ConnectionPoolManager


@pytest.mark.asyncio
async def test_get_client_during_close_all_gets_a_live_client() -> None:
    pool = ConnectionPoolManager()
    old = await pool.get_client("https://a.example")
    closing = asyncio.Event()
    release = asyncio.Event()
    real_aclose = old.aclose

    async def slow_aclose() -> None:
        closing.set()
        await release.wait()
        await real_aclose()

    setattr(old, "aclose", slow_aclose)
    closer = asyncio.create_task(pool.close_all())
    await closing.wait()

    during = await pool.get_client("https://a.example")
    other = await pool.get_client("https://b.example")
    release.set()
    await closer

    try:
        assert during is not old
        assert pool._clients == {
            "https://a.example": during,
            "https://b.example": other,
        }
    finally:
        await pool.close_all()
