"""Focused tests for web startup and shutdown ownership."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from penguin.web import app as web_app


class _AsyncCallRecorder:
    """Record calls made to an awaitable cleanup hook."""

    def __init__(self) -> None:
        self.calls = 0

    async def __call__(self) -> None:
        self.calls += 1


def _runtime_core(stop_workers: _AsyncCallRecorder) -> SimpleNamespace:
    """Return the minimum core shape used by app construction and lifespan."""

    checkpoint_manager = SimpleNamespace(stop_workers=stop_workers)
    return SimpleNamespace(
        config=SimpleNamespace(model_configs={}),
        conversation_manager=SimpleNamespace(
            checkpoint_manager=checkpoint_manager,
        ),
        tool_manager=SimpleNamespace(),
    )


def _install_lifespan_fakes(
    monkeypatch: pytest.MonkeyPatch,
    *,
    core: SimpleNamespace,
) -> tuple[_AsyncCallRecorder, _AsyncCallRecorder]:
    """Isolate app lifecycle hooks and return watcher/pool recorders."""

    stop_watcher = _AsyncCallRecorder()
    close_pools = _AsyncCallRecorder()
    monkeypatch.setattr(web_app, "get_or_create_core", lambda: core)
    monkeypatch.setattr(web_app, "_rehydrate_provider_credentials", lambda _core: None)
    monkeypatch.setattr(web_app, "start_vcs_watcher", lambda _core: None)
    monkeypatch.setattr(web_app, "stop_vcs_watcher", stop_watcher)
    monkeypatch.setattr(
        web_app.ConnectionPoolManager,
        "get_instance",
        lambda: SimpleNamespace(close_all=close_pools),
    )
    return stop_watcher, close_pools


@pytest.mark.asyncio
async def test_lifespan_always_stops_checkpoint_workers_on_runtime_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exception from the serving body cannot skip owned cleanup."""

    stop_workers = _AsyncCallRecorder()
    core = _runtime_core(stop_workers)
    stop_watcher, close_pools = _install_lifespan_fakes(monkeypatch, core=core)
    app = web_app.create_app()

    with pytest.raises(RuntimeError, match="serving failed"):
        async with app.router.lifespan_context(app):
            raise RuntimeError("serving failed")

    assert stop_workers.calls == 1
    assert stop_watcher.calls == 1
    assert close_pools.calls == 1


@pytest.mark.asyncio
async def test_lifespan_core_hook_failure_does_not_skip_serving_or_shutdown(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A startup-hook core lookup remains isolated from the app lifespan."""

    stop_workers = _AsyncCallRecorder()
    core = _runtime_core(stop_workers)
    stop_watcher, close_pools = _install_lifespan_fakes(monkeypatch, core=core)
    calls = 0

    def _get_core() -> SimpleNamespace:
        nonlocal calls
        calls += 1
        if calls == 1:
            return core
        raise RuntimeError("startup hook core lookup failed")

    monkeypatch.setattr(web_app, "get_or_create_core", _get_core)
    app = web_app.create_app()

    entered = False
    async with app.router.lifespan_context(app):
        entered = True

    assert entered is True
    assert stop_workers.calls == 0
    assert stop_watcher.calls == 1
    assert close_pools.calls == 1
