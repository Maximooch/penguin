"""Tests for OpenCode bridge payload helpers."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from hypothesis import given, strategies as st

from penguin.core_runtime import opencode_bridge


def test_resolve_model_state_prefers_explicit_values() -> None:
    state = opencode_bridge.resolve_model_state(
        session_metadata={
            opencode_bridge.SESSION_PROVIDER_ID_KEY: "openrouter",
            opencode_bridge.SESSION_MODEL_ID_KEY: "anthropic/claude",
            opencode_bridge.SESSION_VARIANT_KEY: "low",
        },
        model_config=SimpleNamespace(model="gpt-5.4", provider="openai"),
        model_id="z-ai/glm-5.1",
        provider_id="openrouter",
        variant="high",
    )

    assert state == {
        "providerID": "openrouter",
        "modelID": "z-ai/glm-5.1",
        "variant": "high",
    }


def test_resolve_model_state_falls_back_to_session_metadata_then_config() -> None:
    session_state = opencode_bridge.resolve_model_state(
        session_metadata={
            opencode_bridge.SESSION_PROVIDER_ID_KEY: "openrouter",
            opencode_bridge.SESSION_MODEL_ID_KEY: "z-ai/glm-5.1",
        },
        model_config=SimpleNamespace(model="gpt-5.4", provider="openai"),
    )
    config_state = opencode_bridge.resolve_model_state(
        session_metadata={},
        model_config=SimpleNamespace(model="gpt-5.4", provider="openai"),
    )

    assert session_state["providerID"] == "openrouter"
    assert session_state["modelID"] == "z-ai/glm-5.1"
    assert config_state["providerID"] == "openai"
    assert config_state["modelID"] == "gpt-5.4"


def test_resolve_session_id_prefers_execution_context_over_current_session() -> None:
    context = SimpleNamespace(session_id="session_ctx", conversation_id="conv_ctx")
    manager = SimpleNamespace(
        get_current_session=lambda: SimpleNamespace(id="session_current")
    )

    assert (
        opencode_bridge.resolve_session_id(
            execution_context=context,
            conversation_manager=manager,
        )
        == "session_ctx"
    )


def test_resolve_adapter_directory_prefers_session_mapping() -> None:
    directory = opencode_bridge.resolve_adapter_directory(
        "session_1",
        session_directories={"session_1": " /session/project "},
        execution_context=SimpleNamespace(directory="/context/project"),
        runtime_config=SimpleNamespace(
            active_root="/runtime/active",
            project_root="/runtime/project",
        ),
        env_getter=lambda _key: "/env/project",
        cwd_getter=lambda: "/cwd/project",
    )

    assert directory == "/session/project"


def test_resolve_adapter_directory_falls_back_by_context_runtime_env_cwd() -> None:
    context_directory = opencode_bridge.resolve_adapter_directory(
        "session_1",
        session_directories={},
        execution_context=SimpleNamespace(directory="/context/project"),
        runtime_config=SimpleNamespace(active_root="/runtime/active"),
        env_getter=lambda _key: "/env/project",
        cwd_getter=lambda: "/cwd/project",
    )
    runtime_directory = opencode_bridge.resolve_adapter_directory(
        "session_1",
        session_directories={},
        execution_context=SimpleNamespace(directory=" "),
        runtime_config=SimpleNamespace(
            active_root=" ",
            project_root="/runtime/project",
        ),
        env_getter=lambda _key: "/env/project",
        cwd_getter=lambda: "/cwd/project",
    )
    env_directory = opencode_bridge.resolve_adapter_directory(
        "session_1",
        session_directories={},
        execution_context=SimpleNamespace(directory=""),
        runtime_config=SimpleNamespace(active_root=None, project_root=None),
        env_getter=lambda _key: " /env/project ",
        cwd_getter=lambda: "/cwd/project",
    )
    cwd_directory = opencode_bridge.resolve_adapter_directory(
        "session_1",
        session_directories={},
        execution_context=SimpleNamespace(directory=""),
        runtime_config=SimpleNamespace(active_root=None, project_root=None),
        env_getter=lambda _key: "",
        cwd_getter=lambda: "/cwd/project",
    )

    assert context_directory == "/context/project"
    assert runtime_directory == "/runtime/project"
    assert env_directory == "/env/project"
    assert cwd_directory == "/cwd/project"


def test_prepare_scoped_event_properties_prefers_context_directory() -> None:
    properties, session_id = opencode_bridge.prepare_scoped_event_properties(
        {"session_id": "session_1", "payload": True},
        execution_context=SimpleNamespace(
            session_id="session_ctx",
            conversation_id="conversation_ctx",
            directory="/context/project",
        ),
        session_directories={"session_1": "/session/project"},
    )

    assert session_id == "session_1"
    assert properties is not None
    assert properties["sessionID"] == "session_1"
    assert properties["conversation_id"] == "session_1"
    assert properties["directory"] == "/context/project"
    assert properties["payload"] is True


def test_prepare_scoped_event_properties_uses_context_session_then_directory_map() -> (
    None
):
    properties, session_id = opencode_bridge.prepare_scoped_event_properties(
        {"payload": True},
        execution_context=SimpleNamespace(
            session_id="session_ctx",
            conversation_id="conversation_ctx",
            directory="",
        ),
        session_directories={"session_ctx": " /session/project "},
    )

    assert session_id == "session_ctx"
    assert properties is not None
    assert properties["sessionID"] == "session_ctx"
    assert properties["conversation_id"] == "session_ctx"
    assert properties["directory"] == "/session/project"


def test_prepare_scoped_event_properties_can_require_session() -> None:
    properties, session_id = opencode_bridge.prepare_scoped_event_properties(
        {"payload": True},
        execution_context=None,
        session_directories={},
        require_session=True,
    )

    assert properties is None
    assert session_id is None


def test_build_assistant_message_info_uses_fallback_tokens_and_variant() -> None:
    info = opencode_bridge.build_assistant_message_info(
        message_id="msg_1",
        session_id="session_1",
        directory="/tmp/project",
        model_state={
            "modelID": "z-ai/glm-5.1",
            "providerID": "openrouter",
            "variant": "high",
        },
        created_ms=123,
    )

    assert info["id"] == "msg_1"
    assert info["sessionID"] == "session_1"
    assert info["modelID"] == "z-ai/glm-5.1"
    assert info["providerID"] == "openrouter"
    assert info["variant"] == "high"
    assert info["path"] == {"cwd": "/tmp/project", "root": "/tmp/project"}
    assert info["tokens"] == {
        "input": 0,
        "output": 0,
        "reasoning": 0,
        "cache": {"read": 0, "write": 0},
    }


def test_latest_model_usage_returns_empty_for_bad_handler() -> None:
    client = SimpleNamespace(
        client_handler=SimpleNamespace(
            get_last_usage=lambda: (_ for _ in ()).throw(RuntimeError("boom"))
        )
    )

    assert opencode_bridge.latest_model_usage(client) == {}


@given(
    usage=st.dictionaries(
        keys=st.sampled_from(
            [
                "input_tokens",
                "output_tokens",
                "reasoning_tokens",
                "cache_read_tokens",
                "cache_write_tokens",
                "cost",
            ]
        ),
        values=st.one_of(
            st.integers(min_value=-100, max_value=1000),
            st.floats(
                allow_nan=False, allow_infinity=False, min_value=-100, max_value=1000
            ),
            st.text(max_size=8),
            st.none(),
        ),
        max_size=6,
    )
)
def test_usage_tokens_and_cost_never_returns_negative_cost(
    usage: dict[str, Any],
) -> None:
    tokens, cost = opencode_bridge.usage_tokens_and_cost(usage)

    assert set(tokens) == {"input", "output", "reasoning", "cache"}
    assert set(tokens["cache"]) == {"read", "write"}
    assert tokens["input"] >= 0
    assert tokens["output"] >= 0
    assert tokens["reasoning"] >= 0
    assert tokens["cache"]["read"] >= 0
    assert tokens["cache"]["write"] >= 0
    assert cost >= 0
