from __future__ import annotations

from copy import deepcopy
from types import SimpleNamespace
from typing import TYPE_CHECKING, Any

import pytest

from penguin.core_runtime.opencode_bridge import (
    SESSION_MODEL_ID_KEY,
    SESSION_PROVIDER_ID_KEY,
    SESSION_VARIANT_KEY,
)
from penguin.integrations.telegram._session_runtime import (
    SESSION_SERVICE_TIER_KEY,
    SessionRuntimePreferences,
    load_session_runtime_preferences,
    resolve_session_request_runtime,
    update_session_runtime_preferences,
)
from penguin.system.session_manager import SessionManager
from penguin.system.state import Session

if TYPE_CHECKING:
    from pathlib import Path


class _SessionManager:
    def __init__(self, *session_ids: str) -> None:
        self.sessions = {
            session_id: (SimpleNamespace(id=session_id, metadata={}), False)
            for session_id in session_ids
        }
        self.marked: list[str] = []
        self.saved: list[str] = []
        self.session_index: dict[str, Any] = {}

    def mark_session_modified(self, session_id: str) -> None:
        self.marked.append(session_id)

    def save_session(self, session: Any) -> bool:
        self.saved.append(session.id)
        return True


def _core(*session_ids: str) -> tuple[Any, _SessionManager]:
    manager = _SessionManager(*session_ids)
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )
    return core, manager


def test_session_runtime_preferences_persist_on_the_target_session() -> None:
    core, manager = _core("session-one")

    updated = update_session_runtime_preferences(
        core,
        "session-one",
        provider_id=" OpenAI ",
        model_id="openai/gpt-5.6-sol",
        reasoning_variant=" Medium ",
        service_tier=" PRIORITY ",
    )

    assert updated == SessionRuntimePreferences(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
        service_tier="priority",
    )
    assert load_session_runtime_preferences(core, "session-one") == updated
    assert manager.marked == ["session-one"]
    assert manager.saved == ["session-one"]


def test_session_runtime_preferences_are_isolated_between_sessions() -> None:
    core, _manager = _core("session-one", "session-two")

    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
    )
    update_session_runtime_preferences(
        core,
        "session-two",
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
    )

    assert load_session_runtime_preferences(
        core, "session-one"
    ) == SessionRuntimePreferences(provider_id="openai", model_id="gpt-5.6-sol")
    assert load_session_runtime_preferences(
        core, "session-two"
    ) == SessionRuntimePreferences(
        provider_id="anthropic",
        model_id="claude-sonnet-4-6",
    )


def test_runtime_update_distinguishes_unchanged_from_clear() -> None:
    core, manager = _core("session-one")
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="high",
        service_tier="priority",
    )

    reasoning_cleared = update_session_runtime_preferences(
        core,
        "session-one",
        reasoning_variant=None,
    )

    assert reasoning_cleared == SessionRuntimePreferences(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        service_tier="priority",
    )
    reset = update_session_runtime_preferences(
        core,
        "session-one",
        provider_id=None,
        model_id=None,
        service_tier=None,
    )
    assert reset == SessionRuntimePreferences()
    assert load_session_runtime_preferences(core, "session-one") == reset
    assert manager.saved == ["session-one", "session-one", "session-one"]


def test_model_provider_pair_invariant_rejects_partial_updates() -> None:
    core, manager = _core("session-one")

    try:
        update_session_runtime_preferences(
            core,
            "session-one",
            model_id="gpt-5.6-sol",
        )
    except ValueError as exc:
        assert "provider_id and model_id" in str(exc)
    else:
        raise AssertionError("A model without its provider must be rejected")

    assert (
        load_session_runtime_preferences(core, "session-one")
        == SessionRuntimePreferences()
    )
    assert manager.marked == []
    assert manager.saved == []


def test_missing_session_fails_closed_without_persisting() -> None:
    core, manager = _core("known-session")

    assert load_session_runtime_preferences(core, "missing-session") is None
    assert (
        update_session_runtime_preferences(
            core,
            "missing-session",
            reasoning_variant="high",
        )
        is None
    )
    assert manager.marked == []
    assert manager.saved == []


@pytest.mark.parametrize("failure", ["false", "exception"])
def test_runtime_update_rolls_back_exact_session_state_on_save_failure(
    failure: str,
) -> None:
    core, manager = _core("session-one")
    session = manager.sessions["session-one"][0]
    original_metadata = {"nested": {"keep": [1, 2, 3]}}
    session.metadata = original_metadata
    session.last_active = "2026-08-11T12:00:00"

    def fail_save(candidate: Any) -> bool:
        candidate.metadata["nested"]["keep"].append(4)
        candidate.metadata["save-side-effect"] = True
        candidate.last_active = "changed-by-save"
        if failure == "exception":
            raise OSError("disk failed")
        return False

    manager.save_session = fail_save

    expected = OSError if failure == "exception" else RuntimeError
    with pytest.raises(expected):
        update_session_runtime_preferences(
            core,
            "session-one",
            reasoning_variant="medium",
        )

    assert session.metadata is original_metadata
    assert session.metadata == {"nested": {"keep": [1, 2, 3]}}
    assert session.last_active == "2026-08-11T12:00:00"
    assert manager.sessions["session-one"] == (session, False)


@pytest.mark.parametrize("failure", ["false", "exception"])
@pytest.mark.parametrize("had_entry", [False, True])
def test_runtime_update_rolls_back_only_target_session_index_entry(
    failure: str,
    had_entry: bool,
) -> None:
    core, manager = _core("session-one")
    original_entry = {"nested": {"keep": [1, 2, 3]}}
    if had_entry:
        manager.session_index["session-one"] = original_entry
    unrelated = {"title": "leave alone"}
    manager.session_index["unrelated"] = unrelated

    def fail_save(candidate: Any) -> bool:
        manager.session_index["session-one"] = {
            "ghost": candidate.metadata.get(SESSION_VARIANT_KEY)
        }
        manager.session_index["unrelated"]["title"] = "mutated externally"
        if failure == "exception":
            raise OSError("disk failed")
        return False

    manager.save_session = fail_save

    expected = OSError if failure == "exception" else RuntimeError
    with pytest.raises(expected):
        update_session_runtime_preferences(
            core,
            "session-one",
            reasoning_variant="medium",
        )

    if had_entry:
        assert manager.session_index["session-one"] == {"nested": {"keep": [1, 2, 3]}}
        assert manager.session_index["session-one"] is not original_entry
    else:
        assert "session-one" not in manager.session_index
    assert manager.session_index["unrelated"] == {"title": "mutated externally"}


def test_runtime_update_rejects_cached_session_with_mismatched_exact_id() -> None:
    core, manager = _core("requested")
    manager.sessions["requested"] = (
        SimpleNamespace(id="different", metadata={}, last_active="unchanged"),
        False,
    )

    assert load_session_runtime_preferences(core, "requested") is None
    assert (
        update_session_runtime_preferences(
            core,
            "requested",
            reasoning_variant="medium",
        )
        is None
    )
    assert manager.marked == []
    assert manager.saved == []


def test_uncached_runtime_preferences_use_file_without_activating_manager(
    tmp_path: Path,
) -> None:
    session = Session(
        id="persisted-session",
        metadata={"directory": "/tmp/project", "agent_id": "default"},
    )
    session_path = tmp_path / "persisted-session.json"
    session_path.write_text(session.to_json(), encoding="utf-8")
    active = SimpleNamespace(id="active-session")

    class DiskManager:
        def __init__(self) -> None:
            self.base_path = tmp_path
            self.format = "json"
            self.sessions: dict[str, Any] = {}
            self.session_index = {session.id: {}}
            self.current_session = active
            self.saved: list[str] = []

        def load_session(self, session_id: str) -> Any:
            raise AssertionError(f"activating loader called for {session_id}")

        def mark_session_modified(self, session_id: str) -> None:
            assert session_id == session.id

        def save_session(self, candidate: Session) -> bool:
            self.saved.append(candidate.id)
            session_path.write_text(candidate.to_json(), encoding="utf-8")
            return True

    manager = DiskManager()
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )

    updated = update_session_runtime_preferences(
        core,
        session.id,
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
    )

    assert updated == SessionRuntimePreferences(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
    )
    assert load_session_runtime_preferences(core, session.id) == updated
    assert manager.current_session is active
    assert manager.sessions == {}
    assert manager.saved == [session.id]


@pytest.mark.parametrize("had_primary", [False, True])
def test_real_session_manager_disk_state_rolls_back_after_index_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    had_primary: bool,
) -> None:
    manager = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    session = manager.create_session()
    session.metadata["owner"] = "original"
    if had_primary:
        assert manager.save_session(session) is True
        original_primary = (tmp_path / f"{session.id}.json").read_bytes()
        original_backup = tmp_path / f"{session.id}.json.bak"
        original_backup_state = (
            original_backup.read_bytes() if original_backup.exists() else None
        )
    else:
        primary = tmp_path / f"{session.id}.json"
        assert not primary.exists()
        original_primary = None
        original_backup_state = None
    original_index_entry = deepcopy(manager.session_index[session.id])
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )

    def fail_index(_index: Any) -> None:
        raise OSError("index persistence failed")

    monkeypatch.setattr(manager, "_save_index", fail_index)

    with pytest.raises(RuntimeError, match="Unable to persist"):
        update_session_runtime_preferences(
            core,
            session.id,
            provider_id="openai",
            model_id="gpt-5.6-sol",
            reasoning_variant="medium",
        )

    primary = tmp_path / f"{session.id}.json"
    backup = tmp_path / f"{session.id}.json.bak"
    assert manager.session_index[session.id] == original_index_entry
    if had_primary:
        assert primary.read_bytes() == original_primary
        restored = Session.from_json(primary.read_text(encoding="utf-8"))
        assert restored.metadata["owner"] == "original"
        assert SESSION_PROVIDER_ID_KEY not in restored.metadata
        assert SESSION_MODEL_ID_KEY not in restored.metadata
        assert SESSION_VARIANT_KEY not in restored.metadata
        if original_backup_state is None:
            assert not backup.exists()
        else:
            assert backup.read_bytes() == original_backup_state
    else:
        assert not primary.exists()
        assert not backup.exists()


def test_runtime_update_prefers_uncached_live_current_session_over_disk(
    tmp_path: Path,
) -> None:
    manager = SessionManager(base_path=str(tmp_path), auto_save_interval=0)
    live = manager.create_session()
    live.metadata["owner"] = "live"
    assert manager.save_session(live) is True
    manager.sessions.pop(live.id)
    assert manager.current_session is live
    core = SimpleNamespace(
        conversation_manager=SimpleNamespace(
            session_manager=manager,
            agent_session_managers={},
        )
    )

    updated = update_session_runtime_preferences(
        core,
        live.id,
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
    )

    assert updated == SessionRuntimePreferences(
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
    )
    assert live.metadata[SESSION_PROVIDER_ID_KEY] == "openai"
    assert live.metadata[SESSION_MODEL_ID_KEY] == "gpt-5.6-sol"
    assert live.metadata[SESSION_VARIANT_KEY] == "medium"
    assert manager.current_session is live

    assert manager.save_session(live) is True
    reloaded = Session.from_json(
        (tmp_path / f"{live.id}.json").read_text(encoding="utf-8")
    )
    assert reloaded.metadata[SESSION_PROVIDER_ID_KEY] == "openai"
    assert reloaded.metadata[SESSION_MODEL_ID_KEY] == "gpt-5.6-sol"
    assert reloaded.metadata[SESSION_VARIANT_KEY] == "medium"


@pytest.mark.asyncio
async def test_request_runtime_is_fresh_and_does_not_mutate_global_runtime() -> None:
    core, manager = _core("session-one")
    global_config = SimpleNamespace(
        provider="anthropic",
        model="claude-sonnet-4-6",
        reasoning_enabled=False,
        reasoning_effort=None,
        reasoning_max_tokens=2048,
        reasoning_exclude=False,
        service_tier=None,
    )
    global_client = SimpleNamespace(name="global-client")
    core.model_config = global_config
    core.api_client = global_client
    requested_models: list[str | None] = []

    async def resolve_request_runtime(model_id: str | None = None):
        requested_models.append(model_id)
        request_config = deepcopy(global_config)
        request_config.provider = "openai"
        request_config.model = "gpt-5.6-sol"
        request_config.supported_reasoning_levels = [
            "low",
            "medium",
            "high",
            "xhigh",
            "max",
        ]
        request_config.api_key = "request-only-secret"
        return request_config, SimpleNamespace(model_config=request_config)

    core.resolve_request_runtime = resolve_request_runtime
    update_session_runtime_preferences(
        core,
        "session-one",
        provider_id="openai",
        model_id="gpt-5.6-sol",
        reasoning_variant="medium",
        service_tier="priority",
    )

    first = await resolve_session_request_runtime(core, "session-one")
    second = await resolve_session_request_runtime(core, "session-one")

    assert first is not None
    assert second is not None
    first_config, first_client = first
    second_config, second_client = second
    assert requested_models == ["openai/gpt-5.6-sol", "openai/gpt-5.6-sol"]
    assert first_config is not second_config
    assert first_client is not second_client
    assert first_config.reasoning_enabled is True
    assert first_config.reasoning_effort == "medium"
    assert first_config.reasoning_max_tokens is None
    assert first_config.service_tier == "priority"
    assert global_config.reasoning_enabled is False
    assert global_config.reasoning_effort is None
    assert global_config.reasoning_max_tokens == 2048
    assert global_config.service_tier is None
    assert core.api_client is global_client

    session = manager.sessions["session-one"][0]
    assert session.metadata == {
        SESSION_PROVIDER_ID_KEY: "openai",
        SESSION_MODEL_ID_KEY: "gpt-5.6-sol",
        SESSION_VARIANT_KEY: "medium",
        SESSION_SERVICE_TIER_KEY: "priority",
    }


@pytest.mark.asyncio
async def test_fast_mode_rejects_a_non_openai_effective_runtime() -> None:
    core, _manager = _core("session-one")
    core.model_config = SimpleNamespace(provider="anthropic")
    core.api_client = SimpleNamespace(name="global-client")

    async def resolve_request_runtime(_model_id: str | None = None):
        return (
            SimpleNamespace(provider="anthropic", service_tier=None),
            SimpleNamespace(name="request-client"),
        )

    core.resolve_request_runtime = resolve_request_runtime
    update_session_runtime_preferences(
        core,
        "session-one",
        service_tier="priority",
    )

    with pytest.raises(ValueError, match="only for OpenAI"):
        await resolve_session_request_runtime(core, "session-one")
