"""Deterministic routing, cache accounting and pooling contracts."""

from contextlib import asynccontextmanager

import pytest

from penguin.llm.api_client import ConnectionPoolManager
from penguin.llm.codex_routing import CURRENT_CODEX_ROUTING, CodexRouting

from .codex_oauth_fixtures import (
    FakeCodexTransport,
    FakeResponse,
    codex_adapter,
    codex_completed_text,
    install_oauth_codex_test_auth,
)

pytestmark = pytest.mark.usefixtures("isolate_codex_pool")


def test_owner_change_and_new_turn_clear_state():
    routing = CodexRouting("session-a")
    assert routing.headers("owner-a") == {"session-id": "session-a"}
    routing.capture("opaque")
    routing.capture("replacement")
    assert routing.headers("owner-a")["x-codex-turn-state"] == "opaque"
    assert "x-codex-turn-state" not in routing.headers("owner-b")
    assert CodexRouting("session-a").turn_state is None
    routing.capture("bad\r\nheader")
    assert routing.turn_state is None


@pytest.mark.asyncio
async def test_real_adapter_replays_only_within_turn(monkeypatch):
    install_oauth_codex_test_auth(monkeypatch)
    transport = FakeCodexTransport(
        [
            FakeResponse(
                200,
                headers={"x-codex-turn-state": "opaque"},
                lines=codex_completed_text("one"),
            ),
            FakeResponse(200, lines=codex_completed_text("two")),
            FakeResponse(200, lines=codex_completed_text("three")),
        ]
    )
    client = transport.async_client_class()(timeout=None)

    @asynccontextmanager
    async def pooled(self, url):
        yield client

    monkeypatch.setattr(ConnectionPoolManager, "client_context", pooled)
    adapter = codex_adapter()
    routing = CodexRouting("session-a")
    token = CURRENT_CODEX_ROUTING.set(routing)
    try:
        await adapter.get_response([{"role": "user", "content": "one"}], stream=False)
        await adapter.get_response([{"role": "user", "content": "two"}], stream=False)
    finally:
        CURRENT_CODEX_ROUTING.reset(token)
    token = CURRENT_CODEX_ROUTING.set(CodexRouting("session-a"))
    try:
        await adapter.get_response([{"role": "user", "content": "three"}], stream=False)
    finally:
        CURRENT_CODEX_ROUTING.reset(token)
    headers = [r["headers"] for r in transport.requests]
    assert all(h["session-id"] == "session-a" for h in headers)
    assert "x-codex-turn-state" not in headers[0]
    assert headers[1]["x-codex-turn-state"] == "opaque"
    assert "x-codex-turn-state" not in headers[2]
    assert CURRENT_CODEX_ROUTING.get() is None


def test_nested_cache_writes_and_legacy_fallback(monkeypatch):
    install_oauth_codex_test_auth(monkeypatch)
    adapter = codex_adapter()
    assert (
        adapter._normalize_usage({"input_tokens_details": {"cache_write_tokens": 7}})[
            "cache_write_tokens"
        ]
        == 7
    )
    assert (
        adapter._normalize_usage({"input_cache_write_tokens": 9})["cache_write_tokens"]
        == 9
    )
    assert (
        adapter._normalize_usage(
            {
                "input_tokens_details": {"cache_write_tokens": 0},
                "input_cache_write_tokens": 9,
            }
        )["cache_write_tokens"]
        == 0
    )


@pytest.mark.asyncio
async def test_concurrent_turn_contexts_are_isolated():
    import asyncio

    async def run(session):
        routing = CodexRouting(session)
        token = CURRENT_CODEX_ROUTING.set(routing)
        try:
            routing.headers(session)
            routing.capture("state-" + session)
            await asyncio.sleep(0)
            assert CURRENT_CODEX_ROUTING.get() is routing
            return routing.headers(session)
        finally:
            CURRENT_CODEX_ROUTING.reset(token)

    a, b = await asyncio.gather(run("a"), run("b"))
    assert a["x-codex-turn-state"] == "state-a"
    assert b["x-codex-turn-state"] == "state-b"
    assert CURRENT_CODEX_ROUTING.get() is None


@pytest.mark.asyncio
async def test_adapter_reports_served_not_requested_tier(monkeypatch):
    from .codex_oauth_fixtures import codex_sse

    install_oauth_codex_test_auth(monkeypatch)
    transport = FakeCodexTransport(
        [
            FakeResponse(
                200,
                lines=[
                    codex_sse(
                        {
                            "type": "response.completed",
                            "response": {
                                "service_tier": "default",
                                "usage": {
                                    "input_tokens": 100,
                                    "input_tokens_details": {"cache_write_tokens": 60},
                                },
                            },
                        }
                    )
                ],
            )
        ]
    )
    monkeypatch.setattr(
        "penguin.llm.adapters.openai.httpx.AsyncClient", transport.async_client_class()
    )
    adapter = codex_adapter()
    adapter.model_config.service_tier = "ultrafast"
    await adapter.get_response([{"role": "user", "content": "test"}], stream=False)
    lifecycle = adapter.get_last_request_lifecycle()
    assert lifecycle.provider_data["service_tier"] == "ultrafast"
    assert lifecycle.provider_data["served_service_tier"] == "default"
    assert adapter.get_last_usage()["cache_write_tokens"] == 60
