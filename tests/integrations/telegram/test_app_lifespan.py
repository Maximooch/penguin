from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from fastapi.testclient import TestClient

from penguin.integrations.telegram import manager as manager_module
from penguin.web import app as web_app


@pytest.mark.parametrize("fail_start", [False, True])
def test_web_lifespan_starts_and_stops_telegram_manager(
    monkeypatch: Any, fail_start: bool
) -> None:
    events: list[str] = []

    class FakeManager:
        def __init__(self, core: Any, config: Any) -> None:
            self.core = core
            self.config = config

        async def start(self) -> None:
            events.append("start")
            if fail_start:
                raise RuntimeError("Telegram unavailable")

        async def stop(self) -> None:
            events.append("stop")

        def status(self) -> dict[str, str]:
            return {"error": "Telegram unavailable"}

    class FakePool:
        async def close_all(self) -> None:
            events.append("close_pool")

    core = SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        tool_manager=None,
    )

    async def stop_vcs_watcher() -> None:
        events.append("stop_vcs")

    monkeypatch.setattr(manager_module, "TelegramManager", FakeManager)
    monkeypatch.setattr(web_app, "get_or_create_core", lambda: core)
    monkeypatch.setattr(web_app, "_rehydrate_provider_credentials", lambda _core: None)
    monkeypatch.setattr(web_app, "start_vcs_watcher", lambda _core: None)
    monkeypatch.setattr(web_app, "stop_vcs_watcher", stop_vcs_watcher)
    monkeypatch.setattr(
        web_app.ConnectionPoolManager,
        "get_instance",
        classmethod(lambda cls: FakePool()),
    )

    app = web_app.create_app()
    with TestClient(app) as client:
        assert client.get("/api/v1/health").status_code == 200
        assert events == ["start"]

    assert events == ["start", "stop", "stop_vcs", "close_pool"]
