"""Core shim coverage for extracted model-management helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from penguin.core import PenguinCore
from penguin.llm.model_config import ModelConfig


def test_model_facade_sync_shims_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    core.config = SimpleNamespace(model_configs={"gpt": {"provider": "openai"}})
    core.model_config = SimpleNamespace(
        model="openai/gpt-4o",
        client_preference="native",
    )
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    facade_globals = PenguinCore.set_llm_config.__globals__
    model_runtime = facade_globals["core_model_runtime"]

    def record(name: str, return_value: Any = None):
        def _runtime(*args: Any, **kwargs: Any) -> Any:
            calls.append((name, args, kwargs))
            return return_value

        return _runtime

    monkeypatch.setattr(
        model_runtime,
        "ensure_litellm_runtime_state",
        record("ensure_litellm_runtime_state"),
    )
    monkeypatch.setattr(
        model_runtime,
        "configure_llm_client",
        record("configure_llm_client", {"status": "ok"}),
    )
    monkeypatch.setattr(
        model_runtime,
        "refresh_api_client",
        record("refresh_api_client"),
    )
    monkeypatch.setattr(
        model_runtime,
        "apply_new_model_config",
        record("apply_new_model_config"),
    )
    monkeypatch.setattr(
        model_runtime,
        "canonicalize_runtime_model_id",
        record("canonicalize_runtime_model_id", "gpt-4o"),
    )
    monkeypatch.setattr(
        model_runtime,
        "resolve_model_provider",
        record("resolve_model_provider", ("openai", "native")),
    )
    monkeypatch.setattr(
        model_runtime,
        "list_available_models",
        record("list_available_models", [{"id": "gpt"}]),
    )
    monkeypatch.setattr(
        model_runtime,
        "current_model_payload",
        record("current_model_payload", {"model": "openai/gpt-4o"}),
    )

    PenguinCore._ensure_litellm_configured(core)
    assert PenguinCore.set_llm_config(core, base_url="http://local") == {"status": "ok"}
    PenguinCore.refresh_api_client(core)
    new_config = ModelConfig(model="gpt-5", provider="openai")
    PenguinCore._apply_new_model_config(core, new_config, context_window_tokens=100)
    assert (
        PenguinCore._canonicalize_runtime_model_id(
            core,
            "openai/gpt-4o",
            "openai",
            "native",
        )
        == "gpt-4o"
    )
    assert PenguinCore._resolve_model_provider(core, "openai/gpt-4o") == (
        "openai",
        "native",
    )
    assert PenguinCore.list_available_models(core) == [{"id": "gpt"}]
    assert PenguinCore.get_current_model(core) == {"model": "openai/gpt-4o"}

    assert [call[0] for call in calls] == [
        "ensure_litellm_runtime_state",
        "configure_llm_client",
        "refresh_api_client",
        "apply_new_model_config",
        "canonicalize_runtime_model_id",
        "resolve_model_provider",
        "list_available_models",
        "current_model_payload",
    ]
    assert calls[0][1] == (core,)
    assert sorted(calls[0][2]) == ["log"]
    assert calls[1][1] == (core,)
    assert calls[1][2]["base_url"] == "http://local"
    assert calls[2][1] == (core,)
    assert calls[2][2]["api_client_factory"] is facade_globals["APIClient"]
    assert calls[3][1] == (core, new_config)
    assert calls[3][2]["context_window_tokens"] == 100
    assert calls[3][2]["refresh_active_client"] == core.refresh_api_client
    assert calls[4][1] == ("openai/gpt-4o", "openai", "native")
    assert calls[5][1] == ("openai/gpt-4o", {"gpt": {"provider": "openai"}})
    assert calls[5][2]["current_client_preference"] == "native"
    assert calls[6][1] == ({"gpt": {"provider": "openai"}},)
    assert calls[6][2]["current_model_name"] == "openai/gpt-4o"
    assert calls[7][1] == (core.model_config,)


@pytest.mark.asyncio
async def test_model_facade_async_shims_delegate_to_runtime(monkeypatch) -> None:
    core = PenguinCore.__new__(PenguinCore)
    core.config = SimpleNamespace(model_configs={"gpt": {"provider": "openai"}})
    core.model_config = ModelConfig(model="gpt-4o", provider="openai")
    calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
    facade_globals = PenguinCore.load_model.__globals__
    model_runtime = facade_globals["core_model_runtime"]

    async def build_model_config_for_model(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[ModelConfig, int]:
        calls.append(("build_model_config_for_model", args, kwargs))
        return core.model_config, 1000

    async def resolve_request_runtime(
        *args: Any,
        **kwargs: Any,
    ) -> tuple[ModelConfig, object]:
        calls.append(("resolve_request_runtime", args, kwargs))
        return core.model_config, object()

    async def load_model_for_core(*args: Any, **kwargs: Any) -> bool:
        calls.append(("load_model_for_core", args, kwargs))
        return True

    monkeypatch.setattr(
        model_runtime,
        "build_model_config_for_model",
        build_model_config_for_model,
    )
    monkeypatch.setattr(
        model_runtime,
        "resolve_request_runtime",
        resolve_request_runtime,
    )
    monkeypatch.setattr(model_runtime, "load_model_for_core", load_model_for_core)

    config, context_window = await PenguinCore._build_model_config_for_model(
        core,
        "gpt-4o",
    )
    request_config, request_client = await PenguinCore.resolve_request_runtime(
        core,
        "gpt-5",
    )
    assert await PenguinCore.load_model(core, "gpt-5") is True

    assert config is core.model_config
    assert context_window == 1000
    assert request_config is core.model_config
    assert request_client is not None

    assert [call[0] for call in calls] == [
        "build_model_config_for_model",
        "resolve_request_runtime",
        "load_model_for_core",
    ]
    assert calls[0][1] == ("gpt-4o",)
    assert calls[0][2]["model_configs"] == {"gpt": {"provider": "openai"}}
    assert calls[0][2]["current_model_config"] is core.model_config
    assert calls[0][2]["fetch_specs"] is facade_globals["fetch_model_specs"]
    assert calls[0][2]["resolve_provider"] == core._resolve_model_provider
    assert calls[1][1] == (core, "gpt-5")
    assert calls[1][2]["api_client_factory"] is facade_globals["APIClient"]
    assert calls[2][1] == (core, "gpt-5")
    assert sorted(calls[2][2]) == ["log"]
