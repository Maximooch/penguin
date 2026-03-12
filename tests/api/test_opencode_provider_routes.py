"""Tests for OpenCode-compatible config/provider/auth routes."""

from __future__ import annotations

import os
import time
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any, cast

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from penguin.web import routes as routes_module
from penguin.web.routes import (
    MessageRequest,
    ProviderOAuthAuthorizeRequest,
    ProviderOAuthCallbackRequest,
    api_auth_remove,
    api_auth_set,
    api_config_get,
    api_config_providers,
    api_config_update,
    api_instance_dispose,
    api_provider_auth,
    api_provider_list,
    api_provider_oauth_authorize,
    api_provider_oauth_callback,
    handle_chat_message,
    opencode_auth_remove,
    opencode_auth_set,
    opencode_config_get,
    opencode_config_providers,
    opencode_config_update,
    opencode_instance_dispose,
    opencode_provider_auth,
    opencode_provider_list,
    opencode_provider_oauth_authorize,
    opencode_provider_oauth_callback,
)
from penguin.web.services import (
    opencode_provider as provider_service,
    provider_catalog,
)
from penguin.web.services.opencode_provider import get_provider_auth_records

if TYPE_CHECKING:
    from pathlib import Path


class _Core:
    def __init__(self, workspace: Path) -> None:
        self.runtime_config = SimpleNamespace(
            workspace_root=str(workspace),
            project_root=str(workspace),
            active_root=str(workspace),
        )
        self.config = SimpleNamespace(
            model_configs={
                "openai/gpt-5": {
                    "provider": "openai",
                    "model": "gpt-5",
                    "max_output_tokens": 8192,
                    "context_window": 128000,
                },
                "openai/gpt-5-codex": {
                    "provider": "openrouter",
                    "model": "openai/gpt-5-codex",
                    "max_output_tokens": 8192,
                    "context_window": 128000,
                },
            }
        )
        self.model_config = SimpleNamespace(provider="openrouter", api_key=None)
        self.conversation_manager = SimpleNamespace(current_agent_id="default")
        self._current_model = {
            "provider": "openrouter",
            "model": "openai/gpt-5-codex",
            "client_preference": "openrouter",
            "max_output_tokens": 8192,
            "context_window": 128000,
        }
        self._load_model_success = True
        self.loaded_model: str | None = None

    def get_current_model(self) -> dict[str, Any]:
        return dict(self._current_model)

    async def load_model(self, model_id: str) -> bool:
        self.loaded_model = model_id
        if not self._load_model_success:
            return False

        provider = model_id.split("/", 1)[0] if "/" in model_id else "openrouter"
        model = model_id.split("/", 1)[1] if "/" in model_id else model_id
        self._current_model["provider"] = provider
        self._current_model["model"] = model
        return True

    def set_active_agent(self, agent_id: str) -> None:
        self.conversation_manager.current_agent_id = agent_id


@pytest.mark.asyncio
async def test_config_get_and_update(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    before = await opencode_config_get(core=typed_core)
    assert before["model"] == "openrouter/openai/gpt-5-codex"
    assert before["default_agent"] == "default"

    updated = await opencode_config_update(
        config={"model": "openai/gpt-5", "default_agent": "builder"},
        core=typed_core,
    )
    assert core.loaded_model == "openai/gpt-5"
    assert updated["model"] == "openai/gpt-5"
    assert updated["default_agent"] == "builder"


@pytest.mark.asyncio
async def test_config_update_returns_400_when_model_switch_fails(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    core._load_model_success = False
    typed_core = cast(Any, core)

    with pytest.raises(HTTPException) as exc:
        await opencode_config_update(config={"model": "openai/gpt-5"}, core=typed_core)
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_chat_message_model_load_failure_surfaces_reason(
    tmp_path: Path,
) -> None:
    class _ChatCore(_Core):
        async def load_model(self, model_id: str) -> bool:
            self.loaded_model = model_id
            self._last_model_load_error = "Native anthropic model lookup failed"
            return False

    core = _ChatCore(tmp_path)
    typed_core = cast(Any, core)

    request = MessageRequest(
        text="hello",
        model="anthropic/claude-3-7-sonnet-latest",
        directory=str(tmp_path),
    )

    with pytest.raises(HTTPException) as exc:
        await handle_chat_message(request=request, core=typed_core)

    assert exc.value.status_code == 400
    assert "Failed to load model 'anthropic/claude-3-7-sonnet-latest'" in str(
        exc.value.detail
    )
    assert "Native anthropic model lookup failed" in str(exc.value.detail)


@pytest.mark.asyncio
async def test_config_providers_and_auth_methods(tmp_path: Path) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    providers = await opencode_config_providers(core=typed_core)
    ids = {item["id"] for item in providers["providers"]}
    assert "openrouter" in ids
    assert "openai" in ids

    methods = await opencode_provider_auth(core=typed_core)
    openai_types = [item["type"] for item in methods["openai"]]
    assert openai_types == ["oauth", "oauth", "api"]
    openai_labels = [item["label"] for item in methods["openai"]]
    assert openai_labels == [
        "ChatGPT Pro/Plus (browser)",
        "ChatGPT Pro/Plus (headless)",
        "Manually enter API key",
    ]


@pytest.mark.asyncio
async def test_config_payload_canonicalizes_unqualified_current_model(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    core._current_model["provider"] = "openai"
    core._current_model["model"] = "gpt-5"
    typed_core = cast(Any, core)

    config = await opencode_config_get(core=typed_core)
    assert config["model"] == "openai/gpt-5"

    providers = await opencode_config_providers(core=typed_core)
    assert providers["default"]["openai"] == "gpt-5"


@pytest.mark.asyncio
async def test_config_providers_use_provider_local_model_ids(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    providers = await opencode_config_providers(core=typed_core)
    openai = next(item for item in providers["providers"] if item["id"] == "openai")
    openrouter = next(
        item for item in providers["providers"] if item["id"] == "openrouter"
    )

    assert "gpt-5" in openai["models"]
    assert "openai/gpt-5" not in openai["models"]
    assert "openai/gpt-5-codex" in openrouter["models"]
    assert providers["default"]["openrouter"] == "openai/gpt-5-codex"


@pytest.mark.asyncio
async def test_config_get_includes_runtime_and_reasoning_metadata(
    tmp_path: Path,
) -> None:
    class _Runtime:
        execution_mode = "project"
        active_root = str(tmp_path)
        project_root = str(tmp_path)
        workspace_root = str(tmp_path)

        def to_dict(self) -> dict[str, Any]:
            return {
                "project_root": str(tmp_path),
                "workspace_root": str(tmp_path),
                "execution_mode": "project",
                "active_root": str(tmp_path),
                "security_mode": "workspace",
                "security_enabled": True,
            }

    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    typed_core.runtime_config = _Runtime()
    typed_core.model_config = SimpleNamespace(
        provider="openrouter",
        api_key=None,
        reasoning_enabled=True,
        reasoning_effort="high",
        reasoning_max_tokens=2048,
        reasoning_exclude=False,
        supports_reasoning=True,
        vision_enabled=True,
    )

    config = await opencode_config_get(core=typed_core)
    assert config["reasoning"]["enabled"] is True
    assert config["reasoning"]["effort"] == "high"
    assert config["reasoning"]["max_tokens"] == 2048
    assert config["reasoning"]["supported"] is True
    assert config["penguin"]["security_mode"] == "workspace"
    assert (
        config["penguin"]["current_model"]["qualified"]
        == "openrouter/openai/gpt-5-codex"
    )


@pytest.mark.asyncio
async def test_config_payload_qualifies_gateway_model_with_provider_prefix(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    config = await opencode_config_get(core=typed_core)
    assert config["model"] == "openrouter/openai/gpt-5-codex"


@pytest.mark.asyncio
async def test_config_update_accepts_provider_qualified_model_selector(
    tmp_path: Path,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    updated = await opencode_config_update(
        config={"model": "openrouter/openai/gpt-5-codex"},
        core=typed_core,
    )
    assert core.loaded_model == "openai/gpt-5-codex"
    assert updated["model"].endswith("openai/gpt-5-codex")


@pytest.mark.asyncio
async def test_provider_list_includes_env_connected_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("OLLAMA_HOST", "http://localhost:11434")

    core = _Core(tmp_path)
    core.config.model_configs = {}
    core._current_model = {
        "provider": "openai",
        "model": "gpt-5",
        "client_preference": "native",
    }
    typed_core = cast(Any, core)

    providers = await opencode_provider_list(core=typed_core)
    all_ids = {item["id"] for item in providers["all"]}
    assert "ollama" in all_ids
    assert "ollama" in providers["connected"]


@pytest.mark.asyncio
async def test_openrouter_catalog_expands_provider_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_openrouter_catalog.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    cache = cast(Any, getattr(provider_service, "_OPENROUTER_CATALOG_CACHE"))
    cache["fetched_at"] = 0.0
    cache["models"] = {}

    class _CatalogResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "data": [
                    {
                        "id": "openai/gpt-5-mini",
                        "name": "GPT-5 Mini",
                        "context_length": 256000,
                        "created": 1720000000,
                        "pricing": {
                            "prompt": "0.00000125",
                            "completion": "0.00001",
                            "input_cache_read": "0.000000125",
                            "input_cache_write": "0.00000125",
                        },
                        "architecture": {"input_modalities": ["text", "image"]},
                        "top_provider": {"max_completion_tokens": 32768},
                    }
                ]
            }

    class _CatalogClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> _CatalogClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            del exc_type, exc, tb
            return False

        def get(self, url: str, headers: dict[str, str]) -> _CatalogResponse:
            assert "openrouter.ai/api/v1/models" in url
            assert headers["Authorization"].startswith("Bearer ")
            return _CatalogResponse()

    monkeypatch.setattr(provider_service.httpx, "Client", _CatalogClient)

    core = _Core(tmp_path)
    core.config.model_configs = {}
    core._current_model = {
        "provider": "openai",
        "model": "gpt-5",
        "client_preference": "native",
    }
    typed_core = cast(Any, core)

    saved = await opencode_auth_set(
        providerID="openrouter",
        auth={"type": "api", "key": "sk-or-catalog"},
        core=typed_core,
    )
    assert saved is True

    providers_payload = await opencode_config_providers(core=typed_core)
    openrouter = next(
        item for item in providers_payload["providers"] if item["id"] == "openrouter"
    )
    assert openrouter["source"] == "api"
    assert "openai/gpt-5-mini" in openrouter["models"]
    assert (
        openrouter["models"]["openai/gpt-5-mini"]["capabilities"]["attachment"] is True
    )
    assert openrouter["models"]["openai/gpt-5-mini"]["cost"]["input"] == 0.00000125
    assert openrouter["models"]["openai/gpt-5-mini"]["cost"]["output"] == 0.00001
    assert set(openrouter["models"]["openai/gpt-5-mini"]["variants"].keys()) == {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }

    provider_payload = await opencode_provider_list(core=typed_core)
    openrouter_provider = next(
        item for item in provider_payload["all"] if item["id"] == "openrouter"
    )
    assert "openai/gpt-5-mini" in openrouter_provider["models"]
    assert openrouter_provider["models"]["openai/gpt-5-mini"]["reasoning"] is True
    assert openrouter_provider["models"]["openai/gpt-5-mini"][
        "release_date"
    ].startswith("2024-")
    assert set(
        openrouter_provider["models"]["openai/gpt-5-mini"]["variants"].keys()
    ) == {"none", "minimal", "low", "medium", "high", "xhigh"}


@pytest.mark.asyncio
async def test_models_dev_catalog_expands_openai_and_anthropic_payloads(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = cast(Any, getattr(provider_catalog, "_MODELS_DEV_CACHE"))
    cache["fetched_at"] = 0.0
    cache["providers"] = {}

    class _ModelsDevResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self) -> dict[str, Any]:
            return {
                "openai": {
                    "id": "openai",
                    "models": {
                        "gpt-5.4": {
                            "id": "gpt-5.4",
                            "name": "GPT-5.4",
                            "attachment": True,
                            "reasoning": True,
                            "release_date": "2026-01-01T00:00:00+00:00",
                            "limit": {"context": 400000, "output": 128000},
                            "cost": {
                                "input": 1.25,
                                "output": 10.0,
                                "cache_read": 0.625,
                                "cache_write": 1.25,
                            },
                        }
                    },
                },
                "anthropic": {
                    "id": "anthropic",
                    "models": {
                        "claude-opus-4-6": {
                            "id": "claude-opus-4-6",
                            "name": "Claude Opus 4.6",
                            "attachment": True,
                            "reasoning": True,
                            "release_date": "2026-02-02T00:00:00+00:00",
                            "limit": {"context": 200000, "output": 64000},
                            "cost": {
                                "input": 3.0,
                                "output": 15.0,
                                "cache_read": 0.3,
                            },
                        }
                    },
                },
            }

    class _ModelsDevClient:
        def __init__(self, timeout: float) -> None:
            self.timeout = timeout

        def __enter__(self) -> _ModelsDevClient:
            return self

        def __exit__(self, exc_type: Any, exc: Any, tb: Any) -> bool:
            del exc_type, exc, tb
            return False

        def get(self, url: str, headers: dict[str, str]) -> _ModelsDevResponse:
            assert "models.dev/api.json" in url
            assert "User-Agent" in headers
            return _ModelsDevResponse()

    monkeypatch.setattr(provider_catalog.httpx, "Client", _ModelsDevClient)

    core = _Core(tmp_path)
    core.config.model_configs = {}
    core._current_model = {
        "provider": "openrouter",
        "model": "openai/gpt-5-codex",
        "client_preference": "openrouter",
    }
    typed_core = cast(Any, core)

    providers_payload = await opencode_config_providers(core=typed_core)
    provider_ids = {item["id"] for item in providers_payload["providers"]}
    assert "openai" in provider_ids
    assert "anthropic" in provider_ids

    openai = next(
        item for item in providers_payload["providers"] if item["id"] == "openai"
    )
    assert "gpt-5.4" in openai["models"]
    assert openai["models"]["gpt-5.4"]["capabilities"]["reasoning"] is True
    assert set(openai["models"]["gpt-5.4"]["variants"].keys()) == {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }

    anthropic = next(
        item for item in providers_payload["providers"] if item["id"] == "anthropic"
    )
    assert "claude-opus-4-6" in anthropic["models"]
    assert anthropic["models"]["claude-opus-4-6"]["cost"]["input"] == 3.0
    assert set(anthropic["models"]["claude-opus-4-6"]["variants"].keys()) == {
        "low",
        "medium",
        "high",
        "max",
    }

    provider_payload = await opencode_provider_list(core=typed_core)
    openai_provider = next(
        item for item in provider_payload["all"] if item["id"] == "openai"
    )
    assert "gpt-5.4" in openai_provider["models"]
    assert openai_provider["models"]["gpt-5.4"]["reasoning"] is True
    assert set(openai_provider["models"]["gpt-5.4"]["variants"].keys()) == {
        "none",
        "minimal",
        "low",
        "medium",
        "high",
        "xhigh",
    }

    anthropic_provider = next(
        item for item in provider_payload["all"] if item["id"] == "anthropic"
    )
    assert "claude-opus-4-6" in anthropic_provider["models"]
    assert set(anthropic_provider["models"]["claude-opus-4-6"]["variants"].keys()) == {
        "low",
        "medium",
        "high",
        "max",
    }


@pytest.mark.asyncio
async def test_provider_filters_hide_disabled_models_dev_providers(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cache = cast(Any, getattr(provider_catalog, "_MODELS_DEV_CACHE"))
    cache["fetched_at"] = time.time()
    cache["providers"] = {
        "openai": {
            "id": "openai",
            "models": {"gpt-5": {"id": "gpt-5", "name": "GPT-5", "limit": {}}},
        },
        "anthropic": {
            "id": "anthropic",
            "models": {
                "claude-4.5-sonnet": {
                    "id": "claude-4.5-sonnet",
                    "name": "Claude 4.5 Sonnet",
                    "limit": {},
                }
            },
        },
    }

    monkeypatch.setattr(
        provider_service,
        "load_config",
        lambda: {
            "enabled_providers": ["openai", "anthropic"],
            "disabled_providers": ["anthropic"],
        },
    )

    core = _Core(tmp_path)
    core.config.model_configs = {}
    typed_core = cast(Any, core)

    providers_payload = await opencode_config_providers(core=typed_core)
    provider_ids = {item["id"] for item in providers_payload["providers"]}
    assert "openai" in provider_ids
    assert "anthropic" not in provider_ids

    provider_payload = await opencode_provider_list(core=typed_core)
    list_ids = {item["id"] for item in provider_payload["all"]}
    assert "openai" in list_ids
    assert "anthropic" not in list_ids


@pytest.mark.asyncio
async def test_auth_set_and_remove_round_trip(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)

    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    try:
        saved = await opencode_auth_set(
            providerID="openrouter",
            auth={"type": "api", "key": "sk-or-test"},
            core=typed_core,
        )
        assert saved is True
        assert os.environ.get("OPENROUTER_API_KEY") == "sk-or-test"

        providers = await opencode_provider_list(core=typed_core)
        assert "openrouter" in providers["connected"]

        records = get_provider_auth_records()
        assert records["openrouter"]["key"] == "sk-or-test"

        removed = await opencode_auth_remove(providerID="openrouter")
        assert removed is True
        assert "openrouter" not in get_provider_auth_records()
    finally:
        os.environ.pop("OPENROUTER_API_KEY", None)


@pytest.mark.asyncio
async def test_auth_set_bad_payload_returns_400(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_invalid.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    with pytest.raises(HTTPException) as exc:
        await opencode_auth_set(
            providerID="openrouter",
            auth={"type": "api"},
            core=typed_core,
        )
    assert exc.value.status_code == 400


@pytest.mark.asyncio
async def test_oauth_routes_delegate_to_service(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    seen: dict[str, Any] = {}

    async def _authorize(provider_id: str, method: int) -> dict[str, str]:
        seen["authorize"] = (provider_id, method)
        return {
            "url": "https://example.com/device",
            "method": "auto",
            "instructions": "Enter code: ABCD",
        }

    async def _callback(provider_id: str, method: int, code: str | None = None) -> bool:
        seen["callback"] = (provider_id, method, code)
        return True

    monkeypatch.setattr(routes_module, "provider_oauth_authorize", _authorize)
    monkeypatch.setattr(routes_module, "provider_oauth_callback", _callback)

    authorized = await opencode_provider_oauth_authorize(
        providerID="openai",
        request=ProviderOAuthAuthorizeRequest(method=1),
    )
    assert authorized["method"] == "auto"
    assert seen["authorize"] == ("openai", 1)

    completed = await opencode_provider_oauth_callback(
        providerID="openai",
        request=ProviderOAuthCallbackRequest(method=1, code="token-code"),
    )
    assert completed is True
    assert seen["callback"] == ("openai", 1, "token-code")


@pytest.mark.asyncio
async def test_oauth_callback_applies_runtime_credentials(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    core = _Core(tmp_path)
    typed_core = cast(Any, core)
    seen: dict[str, Any] = {}

    async def _callback(provider_id: str, method: int, code: str | None = None) -> bool:
        seen["callback"] = (provider_id, method, code)
        return True

    def _records() -> dict[str, dict[str, Any]]:
        return {
            "openai": {
                "type": "oauth",
                "access": "oauth-access",
                "refresh": "oauth-refresh",
                "expires": 9_999_999_999_000,
                "accountId": "acct_test_runtime",
            }
        }

    def _apply(core_obj: Any, provider_id: str, auth_record: dict[str, Any]) -> None:
        seen["runtime"] = (core_obj, provider_id, auth_record)

    monkeypatch.setattr(routes_module, "provider_oauth_callback", _callback)
    monkeypatch.setattr(routes_module, "get_provider_auth_records", _records)
    monkeypatch.setattr(routes_module, "apply_auth_to_runtime", _apply)

    completed = await opencode_provider_oauth_callback(
        providerID="openai",
        request=ProviderOAuthCallbackRequest(method=0, code="browser-code"),
        core=typed_core,
    )
    assert completed is True
    assert seen["callback"] == ("openai", 0, "browser-code")
    runtime_core, runtime_provider, runtime_record = seen["runtime"]
    assert runtime_core is typed_core
    assert runtime_provider == "openai"
    assert runtime_record["accountId"] == "acct_test_runtime"


@pytest.mark.asyncio
async def test_api_v1_aliases_match_opencode_routes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_aliases.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

    core = _Core(tmp_path)
    typed_core = cast(Any, core)

    config = await api_config_get(core=typed_core)
    assert config["default_agent"] == "default"

    updated = await api_config_update(
        config={"model": "openai/gpt-5", "default_agent": "builder"},
        core=typed_core,
    )
    assert updated["default_agent"] == "builder"

    providers = await api_config_providers(core=typed_core)
    assert isinstance(providers["providers"], list)

    provider_list = await api_provider_list(core=typed_core)
    assert "all" in provider_list

    methods = await api_provider_auth(core=typed_core)
    assert "openai" in methods

    saved = await api_auth_set(
        providerID="openrouter",
        auth={"type": "api", "key": "sk-alias"},
        core=typed_core,
    )
    assert saved is True

    removed = await api_auth_remove(providerID="openrouter")
    assert removed is True

    disposed = await opencode_instance_dispose()
    assert disposed is True

    disposed_alias = await api_instance_dispose()
    assert disposed_alias is True

    seen: dict[str, Any] = {}

    async def _authorize(provider_id: str, method: int) -> dict[str, str]:
        seen["authorize"] = f"{provider_id}:{method}"
        return {
            "url": "https://example.com/device",
            "method": "auto",
            "instructions": "Enter code: ABCD",
        }

    async def _callback(provider_id: str, method: int, code: str | None = None) -> bool:
        seen["callback"] = f"{provider_id}:{method}:{code}"
        return True

    monkeypatch.setattr(routes_module, "provider_oauth_authorize", _authorize)
    monkeypatch.setattr(routes_module, "provider_oauth_callback", _callback)

    auth_data = await api_provider_oauth_authorize(
        providerID="openai",
        request=ProviderOAuthAuthorizeRequest(method=0),
    )
    assert auth_data["method"] == "auto"
    assert seen["authorize"] == "openai:0"

    callback_ok = await api_provider_oauth_callback(
        providerID="openai",
        request=ProviderOAuthCallbackRequest(method=0, code="alias-code"),
    )
    assert callback_ok is True
    assert seen["callback"] == "openai:0:alias-code"


def test_http_route_wiring_for_config_provider_auth(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    store_path = tmp_path / "provider_auth_http.json"
    monkeypatch.setenv("PENGUIN_PROVIDER_AUTH_STORE", str(store_path))

    async def _authorize(provider_id: str, method: int) -> dict[str, str]:
        del provider_id, method
        return {
            "url": "https://example.com/device",
            "method": "auto",
            "instructions": "Enter code: TEST",
        }

    async def _callback(provider_id: str, method: int, code: str | None = None) -> bool:
        del provider_id, method, code
        return True

    monkeypatch.setattr(routes_module, "provider_oauth_authorize", _authorize)
    monkeypatch.setattr(routes_module, "provider_oauth_callback", _callback)

    core = _Core(tmp_path)
    cast(Any, routes_module.router).core = cast(Any, core)
    app = FastAPI()
    app.include_router(routes_module.router)

    with TestClient(app) as client:
        config_response = client.get("/config")
        assert config_response.status_code == 200

        config_alias_response = client.get("/api/v1/config")
        assert config_alias_response.status_code == 200

        provider_response = client.get("/provider")
        assert provider_response.status_code == 200

        provider_alias_response = client.get("/api/v1/provider")
        assert provider_alias_response.status_code == 200

        auth_methods_response = client.get("/provider/auth")
        assert auth_methods_response.status_code == 200

        auth_set_response = client.put(
            "/auth/openrouter",
            json={"type": "api", "key": "sk-http"},
        )
        assert auth_set_response.status_code == 200
        assert auth_set_response.json() is True

        auth_remove_response = client.delete("/api/v1/auth/openrouter")
        assert auth_remove_response.status_code == 200
        assert auth_remove_response.json() is True

        dispose_response = client.post("/instance/dispose")
        assert dispose_response.status_code == 200
        assert dispose_response.json() is True

        dispose_alias_response = client.post("/api/v1/instance/dispose")
        assert dispose_alias_response.status_code == 200
        assert dispose_alias_response.json() is True

        oauth_authorize_response = client.post(
            "/provider/openai/oauth/authorize",
            json={"method": 0},
        )
        assert oauth_authorize_response.status_code == 200

        oauth_authorize_missing_method = client.post(
            "/provider/openai/oauth/authorize",
            json={},
        )
        assert oauth_authorize_missing_method.status_code == 422

        oauth_callback_response = client.post(
            "/api/v1/provider/openai/oauth/callback",
            json={"method": 0},
        )
        assert oauth_callback_response.status_code == 200
        assert oauth_callback_response.json() is True

        oauth_callback_missing_method = client.post(
            "/api/v1/provider/openai/oauth/callback",
            json={},
        )
        assert oauth_callback_missing_method.status_code == 422
