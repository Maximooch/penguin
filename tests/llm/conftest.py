"""Pytest configuration for LLM tests.

pytest-asyncio is loaded through its installed pytest entry point. Keeping a
``pytest_plugins`` declaration in this nested conftest breaks collection on
current pytest versions because it affects the whole suite.
"""

from contextlib import asynccontextmanager

import pytest


@pytest.fixture
def isolate_codex_pool(monkeypatch):
    """Keep legacy fake transports isolated; pool behavior has dedicated tests."""
    from penguin.llm.adapters import openai
    from penguin.llm.api_client import ConnectionPoolManager

    @asynccontextmanager
    async def context(self, base_url):
        if base_url == openai._OPENAI_CODEX_RESPONSES_URL:
            async with openai.httpx.AsyncClient(
                timeout=openai.httpx.Timeout(connect=30, read=None, write=60, pool=30)
            ) as client:
                yield client
        else:
            yield await self.get_client(base_url)

    monkeypatch.setattr(ConnectionPoolManager, "client_context", context)
