"""Exercise Codex adapter with the real pool and an offline HTTP transport."""

import httpx
import pytest

from penguin.llm.api_client import ConnectionPoolManager
from penguin.llm.codex_routing import CURRENT_CODEX_ROUTING, CodexRouting

from .codex_oauth_fixtures import (
    codex_adapter,
    codex_completed_text,
    install_oauth_codex_test_auth,
)


@pytest.mark.asyncio
async def test_real_pool_reuses_client_and_closes_at_shutdown(monkeypatch):
    install_oauth_codex_test_auth(monkeypatch)
    requests = []

    async def handle(request):
        requests.append(request)
        return httpx.Response(
            200,
            headers={
                "x-codex-turn-state": "sticky",
                "content-type": "text/event-stream",
            },
            text="\n\n".join(codex_completed_text("ok")) + "\n\n",
        )

    client = httpx.AsyncClient(transport=httpx.MockTransport(handle))
    pool = ConnectionPoolManager()
    url = "https://chatgpt.com/backend-api/codex/responses"
    pool._clients[url] = client
    monkeypatch.setattr(ConnectionPoolManager, "get_instance", lambda: pool)
    adapter = codex_adapter()
    token = CURRENT_CODEX_ROUTING.set(CodexRouting("session-pool"))
    try:
        for _ in range(2):
            assert (
                await adapter.get_response(
                    [{"role": "user", "content": "hi"}], stream=False
                )
                == "ok"
            )
            assert await pool.get_client(url) is client
            assert not client.is_closed
        assert requests[0].headers["session-id"] == "session-pool"
        assert "x-codex-turn-state" not in requests[0].headers
        assert requests[1].headers["x-codex-turn-state"] == "sticky"
        assert requests[1].extensions["timeout"]["read"] is None
    finally:
        CURRENT_CODEX_ROUTING.reset(token)
        await pool.close_all()
    assert client.is_closed
    assert pool._clients == {}
