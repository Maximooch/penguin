"""Telegram session control and picker regressions."""

from __future__ import annotations

import asyncio
import threading
from copy import deepcopy
from types import SimpleNamespace
from typing import Any

import pytest

from penguin.channels.schema import ChannelAddress, InboundEnvelope
from penguin.channels.store import ChannelStore
from penguin.core_runtime import process_lifecycle
from penguin.integrations.telegram import _controls
from penguin.integrations.telegram._controls import (
    handle_control_command,
    resolve_control_callback,
)
from penguin.integrations.telegram._session_runtime import (
    SessionRuntimePreferences,
    load_session_runtime_preferences,
    update_session_runtime_preferences,
)
from penguin.integrations.telegram._sessions import RECENT_SESSIONS_KEY
from penguin.integrations.telegram.binding_policy import TelegramBindingPolicy
from penguin.integrations.telegram.config import TelegramConfig
from penguin.integrations.telegram.manager import TelegramManager


class SessionManager:
    def __init__(self, *session_ids: str) -> None:
        self.sessions = {
            session_id: (
                SimpleNamespace(
                    id=session_id,
                    metadata={},
                    messages=[],
                    last_active="2026-08-11T12:00:00",
                ),
                False,
            )
            for session_id in session_ids
        }
        self.session_index: dict[str, Any] = {}

    def mark_session_modified(self, session_id: str) -> None:
        del session_id

    def save_session(self, session: Any) -> bool:
        del session
        return True


class ControlCore:
    def __init__(self, *session_ids: str) -> None:
        self.session_manager = SessionManager(*session_ids)
        self.conversation_manager = SimpleNamespace(
            session_manager=self.session_manager,
            agent_session_managers={},
        )
        self.model_config = SimpleNamespace(
            provider="openai",
            model="gpt-5.6-sol",
            reasoning_enabled=False,
            reasoning_effort=None,
            reasoning_max_tokens=None,
            reasoning_exclude=False,
            service_tier=None,
        )
        self.api_client = SimpleNamespace(name="global")
        self.resolved: list[str | None] = []
        self.calls: list[dict[str, Any]] = []
        self.fail_resolution: str | None = None

    def get_current_model(self) -> dict[str, str]:
        return {"provider": "openai", "model": "gpt-5.6-sol"}

    async def resolve_request_runtime(self, model_id: str | None = None) -> Any:
        self.resolved.append(model_id)
        if self.fail_resolution:
            raise ValueError(self.fail_resolution)
        model_config = deepcopy(self.model_config)
        if model_id:
            provider, _, model = model_id.partition("/")
            model_config.provider = provider
            model_config.model = model
        model_config.supported_reasoning_levels = [
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ]
        return model_config, SimpleNamespace(model_config=model_config)

    async def process(self, **kwargs: Any) -> dict[str, Any]:
        self.calls.append(kwargs)
        return {"status": "ok", "assistant_response": "done"}


class ProjectionManager(SimpleNamespace):
    def __init__(self, core: ControlCore, store: ChannelStore) -> None:
        super().__init__(
            core=core,
            store=store,
            config=SimpleNamespace(
                streaming_mode="edit",
                permission_mode="workspace",
                permissions_summary="Mode cap: workspace",
            ),
        )
        self.projections: list[dict[str, Any]] = []

    async def _create_projection(
        self,
        address: ChannelAddress,
        key: str,
        text: str,
        buttons: list[list[dict[str, str]]],
        **kwargs: Any,
    ) -> None:
        self.projections.append(
            {
                "address": address,
                "key": key,
                "text": text,
                "buttons": buttons,
                **kwargs,
            }
        )


def catalog() -> dict[str, Any]:
    return {
        "connected": ["anthropic", "openai"],
        "all": [
            {
                "id": "openai",
                "connected": True,
                "models": {
                    "gpt-5.6-sol": {
                        "name": "GPT 5.6 Sol",
                        "status": "active",
                        "variants": {
                            "low": {},
                            "medium": {},
                            "high": {},
                        },
                    }
                },
            },
            {
                "id": "anthropic",
                "connected": True,
                "models": {
                    "claude-sonnet-4-6": {
                        "name": "Claude Sonnet 4.6",
                        "status": "active",
                        "variants": {"low": {}, "high": {}},
                    }
                },
            },
            {
                "id": "unconnected",
                "connected": False,
                "models": {"hidden": {"name": "Secret"}},
            },
        ],
    }


def model_catalog(count: int) -> dict[str, Any]:
    return {
        "connected": ["openai"],
        "all": [
            {
                "id": "openai",
                "connected": True,
                "models": {
                    f"model-{index:02d}": {
                        "name": f"Model {index:02d}",
                        "status": "active",
                        "variants": {"low": {}, "medium": {}},
                    }
                    for index in range(count)
                },
            }
        ],
    }


def envelope() -> InboundEnvelope:
    return InboundEnvelope(
        event_id="telegram:bot:1",
        source_sequence=1,
        address=ChannelAddress("telegram", "bot", "42"),
        sender_id="42",
    )


def binding(store: ChannelStore, *, settings: dict[str, Any] | None = None) -> Any:
    return store.upsert_binding(
        envelope().address.lane_key,
        "session-one",
        directory="/tmp/project",
        agent_mode="build",
        settings=settings or {},
        expected_version=0,
    )


@pytest.mark.asyncio
async def test_direct_model_accepts_unique_unqualified_exact_and_validates_first(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())

    response = await handle_control_command(
        manager, "model", "gpt-5.6-sol", envelope(), current
    )

    assert response == (
        "Session model set to openai/gpt-5.6-sol. Reasoning and fast mode reset."
    )
    assert core.resolved == ["openai/gpt-5.6-sol"]
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences(provider_id="openai", model_id="gpt-5.6-sol")
    )
    assert core.model_config.model == "gpt-5.6-sol"
    assert core.api_client.name == "global"


@pytest.mark.asyncio
async def test_connected_catalog_model_is_not_persisted_when_resolver_fails(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    core.fail_resolution = "provider is unavailable"
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())

    response = await handle_control_command(
        manager, "model", "openai/gpt-5.6-sol", envelope(), current
    )

    assert response == "provider is unavailable"
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )


@pytest.mark.asyncio
async def test_shared_model_runtime_is_rejected_before_persist(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")

    async def shared_runtime(_model_id: str | None = None) -> Any:
        return core.model_config, core.api_client

    core.resolve_request_runtime = shared_runtime
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())

    response = await handle_control_command(
        manager, "model", "openai/gpt-5.6-sol", envelope(), current
    )

    assert response == "Penguin returned a shared runtime for that model."
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )


@pytest.mark.asyncio
async def test_gate_locked_direct_setting_rejects_without_persisting(tmp_path) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )
    gate = process_lifecycle.get_session_request_gate(core, "session-one")
    await gate.acquire()
    try:
        response = await handle_control_command(
            manager, "fast", "on", envelope(), current
        )
    finally:
        gate.release()

    assert "busy" in str(response).lower()
    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences is not None
    assert preferences.service_tier is None


@pytest.mark.asyncio
async def test_cancelled_setting_waits_for_thread_write_before_releasing_gate(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    started = threading.Event()
    release = threading.Event()
    persisted = threading.Event()
    real_update = _controls.update_session_runtime_preferences

    def delayed_update(*args: Any, **kwargs: Any) -> Any:
        started.set()
        assert release.wait(timeout=2)
        result = real_update(*args, **kwargs)
        persisted.set()
        return result

    monkeypatch.setattr(_controls, "update_session_runtime_preferences", delayed_update)
    task = asyncio.create_task(
        handle_control_command(manager, "fast", "on", envelope(), current)
    )
    assert await asyncio.to_thread(started.wait, 1)
    gate = process_lifecycle.get_session_request_gate(core, "session-one")

    task.cancel()
    await asyncio.sleep(0)
    assert not task.done()
    assert gate.locked()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert persisted.is_set()
    assert not gate.locked()
    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences is not None
    assert preferences.service_tier == "priority"


@pytest.mark.asyncio
async def test_model_picker_persists_only_bounded_connected_ids(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())

    assert (
        await handle_control_command(manager, "model", "", envelope(), current) is None
    )

    projection = manager.projections[-1]
    payload = projection["callback_payload"]
    assert payload["kind"] == "control"
    assert payload["session_id"] == "session-one"
    assert payload["binding_version"] == current.version
    assert payload["session_revision"] == _controls._preferences_revision(
        SessionRuntimePreferences()
    )
    assert payload["choices"] == [
        "reset",
        "openai/gpt-5.6-sol",
        "anthropic/claude-sonnet-4-6",
    ]
    assert "hidden" not in repr(projection)
    assert "api_client" not in repr(payload)
    assert all(len(value) <= 512 for value in payload["choices"])


@pytest.mark.asyncio
async def test_model_picker_pages_reach_every_connected_model(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(
        _controls, "_build_provider_payload", lambda _core: model_catalog(61)
    )

    assert (
        await handle_control_command(manager, "model", "", envelope(), current) is None
    )

    seen: set[str] = set()
    for page in range(3):
        projection = manager.projections[-1]
        payload = projection["callback_payload"]
        choices = payload["choices"]
        page_models = {value for value in choices if value.startswith("openai/model-")}
        seen.update(page_models)
        assert len(page_models) <= 25
        assert len(choices) <= 28
        assert all(
            len(button[0]["data"].encode("utf-8")) < 64
            for button in projection["buttons"]
        )
        assert f"page {page + 1}/3" in projection["text"]
        if page < 2:
            result = await resolve_control_callback(
                manager,
                envelope(),
                payload,
                f"c{choices.index(f'page:{page + 1}')}",
            )
            assert result.resolved is True
            assert result.label == f"Opened model page {page + 2}"

    payload = manager.projections[-1]["callback_payload"]
    result = await resolve_control_callback(
        manager,
        envelope(),
        payload,
        f"c{payload['choices'].index('openai/model-60')}",
    )

    assert result.resolved is True
    assert seen == {f"openai/model-{index:02d}" for index in range(61)}
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences(provider_id="openai", model_id="model-60")
    )


@pytest.mark.asyncio
async def test_model_page_navigation_revalidates_catalog(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    current_catalog = model_catalog(40)
    monkeypatch.setattr(
        _controls, "_build_provider_payload", lambda _core: current_catalog
    )
    await handle_control_command(manager, "model", "", envelope(), current)
    payload = manager.projections[-1]["callback_payload"]
    action = f"c{payload['choices'].index('page:1')}"
    projection_count = len(manager.projections)

    current_catalog["all"][0]["models"] = model_catalog(5)["all"][0]["models"]
    result = await resolve_control_callback(manager, envelope(), payload, action)

    assert result.resolved is False
    assert result.label == "Unavailable"
    assert "catalog changed" in result.answer.lower()
    assert len(manager.projections) == projection_count
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )


@pytest.mark.asyncio
async def test_control_callback_rejects_stale_binding_before_mutation(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())
    changed = store.upsert_binding(
        current.address_key,
        current.session_id,
        directory=current.directory,
        agent_mode="plan",
        settings=current.settings,
        expected_version=current.version,
    )

    result = await resolve_control_callback(
        manager,
        envelope(),
        {
            "kind": "control",
            "control": "model",
            "session_id": current.session_id,
            "binding_version": current.version,
            "choices": ["openai/gpt-5.6-sol"],
        },
        "c0",
    )

    assert result.resolved is False
    assert result.label == "Stale"
    assert store.get_binding(current.address_key) == changed
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control", "selection"),
    (
        ("model", "openai/gpt-5.6-sol"),
        ("reasoning", "medium"),
        ("fast", "on"),
    ),
)
async def test_session_callback_rechecks_binding_inside_gate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
    selection: str,
) -> None:
    core = ControlCore("session-one", "session-two")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())
    await handle_control_command(manager, control, "", envelope(), current)
    payload = manager.projections[-1]["callback_payload"]
    real_gate = process_lifecycle.get_session_request_gate(core, "session-one")
    acquire_started = asyncio.Event()
    resume = asyncio.Event()

    class BlockingGate:
        def locked(self) -> bool:
            return real_gate.locked()

        async def acquire(self) -> bool:
            acquire_started.set()
            await resume.wait()
            return await real_gate.acquire()

        def release(self) -> None:
            real_gate.release()

    monkeypatch.setattr(
        _controls.process_lifecycle,
        "get_session_request_gate",
        lambda _core, _session_id: BlockingGate(),
    )
    callback = asyncio.create_task(
        resolve_control_callback(
            manager,
            envelope(),
            payload,
            f"c{payload['choices'].index(selection)}",
        )
    )
    await asyncio.wait_for(acquire_started.wait(), timeout=1)
    changed = store.upsert_binding(
        current.address_key,
        "session-two",
        directory=current.directory,
        agent_mode=current.agent_mode,
        settings=current.settings,
        expected_version=current.version,
    )
    resume.set()

    result = await callback

    assert result.resolved is False
    assert result.label == "Stale"
    assert store.get_binding(current.address_key) == changed
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )
    assert load_session_runtime_preferences(core, "session-two") == (
        SessionRuntimePreferences()
    )
    assert core.resolved == []
    assert not real_gate.locked()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "value"),
    (
        ("model", "openai/gpt-5.6-sol"),
        ("reasoning", "medium"),
        ("fast", "on"),
    ),
)
async def test_direct_session_setting_rechecks_binding_inside_gate(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    value: str,
) -> None:
    core = ControlCore("session-one", "session-two")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())
    real_gate = process_lifecycle.get_session_request_gate(core, "session-one")
    acquire_started = asyncio.Event()
    resume = asyncio.Event()

    class BlockingGate:
        def locked(self) -> bool:
            return real_gate.locked()

        async def acquire(self) -> bool:
            acquire_started.set()
            await resume.wait()
            return await real_gate.acquire()

        def release(self) -> None:
            real_gate.release()

    monkeypatch.setattr(
        _controls.process_lifecycle,
        "get_session_request_gate",
        lambda _core, _session_id: BlockingGate(),
    )
    setting = asyncio.create_task(
        handle_control_command(manager, command, value, envelope(), current)
    )
    await asyncio.wait_for(acquire_started.wait(), timeout=1)
    changed = store.upsert_binding(
        current.address_key,
        "session-two",
        directory=current.directory,
        agent_mode=current.agent_mode,
        settings=current.settings,
        expected_version=current.version,
    )
    resume.set()

    response = await setting

    assert response == "Settings changed. Reopen the control and try again."
    assert store.get_binding(current.address_key) == changed
    assert load_session_runtime_preferences(core, "session-one") == (
        SessionRuntimePreferences()
    )
    assert load_session_runtime_preferences(core, "session-two") == (
        SessionRuntimePreferences()
    )
    assert core.resolved == []
    assert not real_gate.locked()


@pytest.mark.asyncio
async def test_control_callback_rejects_gate_locked_session(tmp_path) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )
    gate = process_lifecycle.get_session_request_gate(core, "session-one")
    await gate.acquire()
    try:
        result = await resolve_control_callback(
            manager,
            envelope(),
            {
                "kind": "control",
                "control": "fast",
                "session_id": current.session_id,
                "binding_version": current.version,
                "session_revision": _controls._preferences_revision(
                    SessionRuntimePreferences(
                        provider_id="openai", model_id="gpt-5.6-sol"
                    )
                ),
                "choices": ["on"],
            },
            "c0",
        )
    finally:
        gate.release()

    assert result.resolved is False
    assert result.label == "Busy"
    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences is not None
    assert preferences.service_tier is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("control", "selection", "direct_command", "direct_value", "large_models"),
    (
        ("model", "page:1", "fast", "on", True),
        ("reasoning", "medium", "fast", "on", False),
        ("fast", "off", "reasoning", "medium", False),
    ),
)
async def test_session_control_picker_rejects_change_after_open(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    control: str,
    selection: str,
    direct_command: str,
    direct_value: str,
    large_models: bool,
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(
        _controls,
        "_build_provider_payload",
        lambda _core: model_catalog(30) if large_models else catalog(),
    )
    await handle_control_command(manager, control, "", envelope(), current)
    payload = manager.projections[-1]["callback_payload"]
    projection_count = len(manager.projections)

    response = await handle_control_command(
        manager, direct_command, direct_value, envelope(), current
    )
    assert response is not None and "set to" in response
    expected = load_session_runtime_preferences(core, "session-one")
    result = await resolve_control_callback(
        manager,
        envelope(),
        payload,
        f"c{payload['choices'].index(selection)}",
    )

    assert result.resolved is False
    assert result.label == "Stale"
    assert "session settings changed" in result.answer.lower()
    assert load_session_runtime_preferences(core, "session-one") == expected
    assert len(manager.projections) == projection_count


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("command", "value", "expected_response"),
    (
        ("reasoning", "medium", "Session reasoning set to medium."),
        ("fast", "on", "Session fast mode set to on."),
    ),
)
async def test_session_setting_holds_gate_across_validation_and_persist(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    command: str,
    value: str,
    expected_response: str,
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )
    validation_started = asyncio.Event()
    finish_validation = asyncio.Event()
    real_preferences = _controls._preferences
    first_call = True

    async def delayed_preferences(manager_arg: Any, session_id: str) -> Any:
        nonlocal first_call
        if first_call:
            first_call = False
            validation_started.set()
            await finish_validation.wait()
        return await real_preferences(manager_arg, session_id)

    monkeypatch.setattr(_controls, "_preferences", delayed_preferences)
    setting = asyncio.create_task(
        handle_control_command(manager, command, value, envelope(), current)
    )
    await asyncio.wait_for(validation_started.wait(), timeout=1)
    gate = process_lifecycle.get_session_request_gate(core, "session-one")
    assert gate.locked()

    raced_model = await handle_control_command(
        manager,
        "model",
        "anthropic/claude-sonnet-4-6",
        envelope(),
        current,
    )
    assert "busy" in str(raced_model).lower()
    finish_validation.set()
    assert await setting == expected_response

    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences is not None
    assert preferences.provider_id == "openai"
    assert preferences.model_id == "gpt-5.6-sol"
    assert core.resolved == []


@pytest.mark.asyncio
async def test_reasoning_fast_and_streaming_are_curated_and_scoped(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    monkeypatch.setattr(_controls, "_build_provider_payload", lambda _core: catalog())
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )

    assert (
        await handle_control_command(
            manager, "reasoning", "medium", envelope(), current
        )
        == "Session reasoning set to medium."
    )
    assert (
        await handle_control_command(manager, "fast", "on", envelope(), current)
        == "Session fast mode set to on."
    )
    assert (
        await handle_control_command(manager, "fast", "off", envelope(), current)
        == "Session fast mode set to off."
    )
    assert (
        await handle_control_command(manager, "fast", "reset", envelope(), current)
        == "Session fast mode set to inherited."
    )
    assert (
        await handle_control_command(
            manager, "settings", "streaming progress", envelope(), current
        )
        == "Telegram streaming set to progress."
    )

    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences == SessionRuntimePreferences(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
    )
    updated = store.get_binding(current.address_key)
    assert updated is not None
    assert updated.settings["streaming_mode"] == "progress"
    assert updated.settings[RECENT_SESSIONS_KEY] == ["session-one"]


@pytest.mark.asyncio
async def test_fast_reset_remains_available_after_effective_provider_changes(
    tmp_path,
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(store)
    update_session_runtime_preferences(
        core,
        "session-one",
        service_tier="priority",
    )
    core.model_config.provider = "anthropic"
    core.model_config.model = "claude-sonnet-4-6"
    core.get_current_model = lambda: {
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
    }

    response = await handle_control_command(
        manager, "fast", "reset", envelope(), current
    )

    assert response == "Session fast mode set to inherited."
    preferences = load_session_runtime_preferences(core, "session-one")
    assert preferences is not None
    assert preferences.service_tier is None


@pytest.mark.asyncio
async def test_legacy_settings_picker_seeds_current_session_once(tmp_path) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    legacy = binding(store, settings={"prompt": "keep"})

    assert (
        await handle_control_command(manager, "settings", "", envelope(), legacy)
        is None
    )

    seeded = store.get_binding(legacy.address_key)
    assert seeded is not None
    assert seeded.settings == {
        "prompt": "keep",
        RECENT_SESSIONS_KEY: ["session-one"],
    }
    assert manager.projections[-1]["callback_payload"]["binding_version"] == (
        seeded.version
    )


@pytest.mark.asyncio
async def test_sessions_direct_rebind_is_limited_to_lane_history(tmp_path) -> None:
    core = ControlCore("session-one", "session-two")
    store = ChannelStore(tmp_path / "channel.db")
    manager = ProjectionManager(core, store)
    current = binding(
        store,
        settings={RECENT_SESSIONS_KEY: ["session-one", "session-two"]},
    )

    response = await handle_control_command(
        manager, "sessions", "session-two", envelope(), current
    )

    assert response == ("Telegram is now bound to Penguin session session-two.")
    rebound = store.get_binding(current.address_key)
    assert rebound is not None
    assert rebound.session_id == "session-two"
    assert rebound.settings[RECENT_SESSIONS_KEY] == [
        "session-two",
        "session-one",
    ]


@pytest.mark.asyncio
async def test_configured_new_binding_preserves_older_recent_history(tmp_path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    core = ControlCore("older", "current")
    core.create_conversation = lambda: "new-session"
    store = ChannelStore(tmp_path / "channel.db")
    address = ChannelAddress("telegram", "bot", "-100")
    current = store.upsert_binding(
        address.lane_key,
        "current",
        directory=str(project),
        agent_mode="build",
        settings={
            "prompt": "old prompt",
            RECENT_SESSIONS_KEY: ["current", "older"],
        },
        expected_version=0,
    )
    policy = TelegramBindingPolicy.from_mapping(
        {
            "-100": {
                "prompt": "configured prompt",
                "directory": str(project),
                "history_limit": 7,
            }
        }
    )
    manager = TelegramManager(
        core,
        TelegramConfig(binding_policy=policy),
        store=store,
        bot=TurnBot(),
    )

    updated = await manager._new_binding(address, current)

    assert updated.session_id == "new-session"
    assert updated.settings["prompt"] == "configured prompt"
    assert updated.settings["history_limit"] == 7
    assert updated.settings[RECENT_SESSIONS_KEY] == [
        "new-session",
        "current",
        "older",
    ]


class TurnBot:
    async def send_chat_action(self, **kwargs: Any) -> None:
        del kwargs


@pytest.mark.asyncio
async def test_turn_uses_fresh_session_runtime_and_binding_streaming_mode(
    tmp_path,
) -> None:
    core = ControlCore("session-one")
    store = ChannelStore(tmp_path / "channel.db")
    current = binding(store, settings={"streaming_mode": "off"})
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
        service_tier="priority",
    )
    manager = TelegramManager(
        core,
        TelegramConfig(streaming_mode="edit"),
        store=store,
        bot=TurnBot(),
    )

    result, preview_id = await manager._execute_turn(
        envelope(),
        current,
        image_paths=[],
        document_inputs=[],
        group_history=[],
        directory=str(tmp_path),
    )

    assert result["status"] == "ok"
    assert preview_id is None
    assert len(core.calls) == 1
    call = core.calls[0]
    assert call["streaming"] is False
    assert call["stream_callback"] is None
    assert call["model_config_override"] is not core.model_config
    assert call["model_config_override"].reasoning_effort == "medium"
    assert call["model_config_override"].service_tier == "priority"
    assert call["api_client_override"] is not core.api_client


@pytest.mark.asyncio
async def test_turn_runtime_resolution_failure_is_visible_and_leaks_no_targets(
    tmp_path,
) -> None:
    core = ControlCore("session-one")
    core.fail_resolution = "bad session model"
    store = ChannelStore(tmp_path / "channel.db")
    current = binding(store, settings={"streaming_mode": "off"})
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )
    manager = TelegramManager(
        core,
        TelegramConfig(streaming_mode="off"),
        store=store,
        bot=TurnBot(),
    )

    result, preview_id = await manager._execute_turn(
        envelope(),
        current,
        image_paths=[],
        document_inputs=[],
        group_history=[],
        directory=str(tmp_path),
    )

    assert result == {
        "status": "error",
        "error": {"message": "Session model settings are invalid: bad session model"},
    }
    assert preview_id is None
    assert manager._request_targets == {}
    assert manager._session_targets == {}
    assert core.calls == []
