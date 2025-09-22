from __future__ import annotations

import textwrap
from types import SimpleNamespace
from typing import Any, Dict, Optional
from unittest.mock import MagicMock

import pytest

from penguin.config import AgentModelSettings, AgentPersonaConfig, Config
from penguin.llm.model_config import ModelConfig

import os
from pathlib import Path

_TEST_WORKSPACE = Path(__file__).resolve().parents[1] / "tmp_workspace" / "persona_tests"
_TEST_WORKSPACE.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("PENGUIN_WORKSPACE", str(_TEST_WORKSPACE))


class StubContextWindow:
    def __init__(self, model_config: ModelConfig) -> None:
        self.model_config = model_config
        self.max_tokens: Optional[int] = model_config.max_tokens

    def is_over_budget(self) -> bool:
        return False


class StubConversation:
    def __init__(self) -> None:
        self.system_prompt: Optional[str] = None
        self.session = SimpleNamespace(id="session-id", metadata={})

    def set_system_prompt(self, prompt: str) -> None:
        self.system_prompt = prompt


class StubConversationManager:
    def __init__(self, base_model_config: ModelConfig) -> None:
        self.agent_sessions: Dict[str, StubConversation] = {"default": StubConversation()}
        self.agent_session_managers: Dict[str, Any] = {"default": object()}
        self.agent_checkpoint_managers: Dict[str, Any] = {"default": object()}
        self.agent_context_windows: Dict[str, StubContextWindow] = {
            "default": StubContextWindow(base_model_config)
        }
        self.current_agent_id = "default"
        self.context_window = self.agent_context_windows["default"]
        self.sub_agent_parent: Dict[str, str] = {}
        self.parent_sub_agents: Dict[str, list[str]] = {}

    def get_agent_conversation(self, agent_id: str, create_if_missing: bool = True) -> StubConversation:
        if create_if_missing and agent_id not in self.agent_sessions:
            self.agent_sessions[agent_id] = StubConversation()
            self.agent_session_managers[agent_id] = object()
            self.agent_checkpoint_managers[agent_id] = object()
            self.agent_context_windows[agent_id] = StubContextWindow(
                self.context_window.model_config
            )
        return self.agent_sessions[agent_id]

    def create_sub_agent(
        self,
        agent_id: str,
        *,
        parent_agent_id: str,
        share_session: bool,
        share_context_window: bool,
        shared_cw_max_tokens: Optional[int],
    ) -> None:
        # For this stub we simply ensure the conversation exists.
        self.get_agent_conversation(agent_id)
        self.sub_agent_parent[agent_id] = parent_agent_id
        children = self.parent_sub_agents.setdefault(parent_agent_id, [])
        if agent_id not in children:
            children.append(agent_id)

    def set_current_agent(self, agent_id: str) -> None:
        self.current_agent_id = agent_id

    def remove_agent(self, agent_id: str) -> bool:
        self.agent_sessions.pop(agent_id, None)
        self.agent_session_managers.pop(agent_id, None)
        self.agent_checkpoint_managers.pop(agent_id, None)
        self.agent_context_windows.pop(agent_id, None)
        if agent_id in self.sub_agent_parent:
            parent = self.sub_agent_parent.pop(agent_id)
            children = self.parent_sub_agents.get(parent)
            if children and agent_id in children:
                children.remove(agent_id)
        return True

    def list_agents(self) -> list[str]:
        return sorted(self.agent_sessions.keys())

    def list_sub_agents(self, parent_agent_id: Optional[str] = None) -> Dict[str, list[str]]:
        if parent_agent_id:
            return {parent_agent_id: list(self.parent_sub_agents.get(parent_agent_id, []))}
        return {parent: list(children) for parent, children in self.parent_sub_agents.items()}

    def save(self) -> bool:
        return True


@pytest.fixture(autouse=True)
def _disable_message_bus(monkeypatch: pytest.MonkeyPatch) -> None:
    import penguin.core as core_module

    monkeypatch.setattr(core_module, "MessageBus", None)
    monkeypatch.setattr(core_module, "ProtocolMessage", None)


def test_load_config_parses_agent_personas(tmp_path) -> None:
    config_body = textwrap.dedent(
        """
        model:
          default: openai/gpt-5-high
          provider: openai
        model_configs:
          kimi-lite:
            model: openrouter/kimi-k2
            provider: openrouter
            client_preference: openrouter
            temperature: 0.15
        agents:
          research:
            description: Research assistant
            system_prompt: Focus on sourcing relevant documentation.
            model:
              id: kimi-lite
              temperature: 0.1
            default_tools:
              - read_file
              - grep_search
    """
    )
    cfg_path = tmp_path / "config.yml"
    cfg_path.write_text(config_body, encoding="utf-8")

    cfg = Config.load_config(config_path=cfg_path)

    persona = cfg.agent_personas["research"]
    assert persona.system_prompt == "Focus on sourcing relevant documentation."
    assert persona.default_tools == ["read_file", "grep_search"]
    assert persona.model is not None
    assert persona.model.id == "kimi-lite"
    assert persona.model.temperature == 0.1


def test_register_agent_applies_persona_model(monkeypatch: pytest.MonkeyPatch) -> None:
    from penguin.core import PenguinCore

    base_model = ModelConfig(
        model="openai/gpt-5-high",
        provider="openai",
        client_preference="native",
        max_tokens=80000,
    )

    persona_model = AgentModelSettings(id="kimi-lite")
    persona_config = AgentPersonaConfig(
        name="research",
        system_prompt="Research diligently",
        model=persona_model,
        default_tools=["read_file"],
        activate_by_default=True,
    )

    config_ns = SimpleNamespace(
        agent_personas={"research": persona_config},
        model_configs={
            "kimi-lite": {
                "model": "openrouter/kimi-k2",
                "provider": "openrouter",
                "client_preference": "openrouter",
                "temperature": 0.2,
            }
        },
        model_config=base_model,
        diagnostics=SimpleNamespace(enabled=False),
    )

    core = PenguinCore.__new__(PenguinCore)
    core.config = config_ns
    core.model_config = base_model
    core.system_prompt = "Default"
    core.tool_manager = MagicMock()
    core.project_manager = MagicMock()
    async def _noop_event(*_: Any, **__: Any) -> None:
        return None

    core.emit_ui_event = _noop_event
    core.conversation_manager = StubConversationManager(base_model)
    core._agent_bus_handlers = {}
    core._agent_api_clients = {}
    core._agent_model_overrides = {}
    core._agent_tool_defaults = {}
    engine = MagicMock()
    engine.set_default_agent = MagicMock()
    core.engine = engine

    core.register_agent("research", persona="research")

    api_client = engine.register_agent.call_args.kwargs["api_client"]
    assert api_client is core._agent_api_clients["research"]
    assert api_client.model_config.model == "openrouter/kimi-k2"
    assert api_client.model_config.provider == "openrouter"

    convo = core.conversation_manager.agent_sessions["research"]
    assert convo.system_prompt == "Research diligently"
    assert convo.session.metadata["persona"] == "research"

    agent_cw = core.conversation_manager.agent_context_windows["research"]
    assert agent_cw.model_config.model == "openrouter/kimi-k2"

    assert core._agent_tool_defaults["research"] == ("read_file",)

    engine.set_default_agent.assert_called_with("research")

    roster = core.get_agent_roster()
    research_entry = next((entry for entry in roster if entry["id"] == "research"), None)
    assert research_entry is not None
    assert research_entry["persona"] == "research"
    assert research_entry["model"]["model"] == "openrouter/kimi-k2"
    profile = core.get_agent_profile("research")
    assert profile is not None
    assert profile["default_tools"] == ["read_file"]

    personas = core.get_persona_catalog()
    assert any(p["name"] == "research" for p in personas)
