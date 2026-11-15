"""A model switch applies completely or not at all.

Covers SM-37: the new model config was assigned before the new API client was
built, so a switch whose client could not be built reported failure while
the core already named the new model and still sent requests to the old one.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from penguin.core import PenguinCore
from penguin.core_runtime.model_runtime import load_model_for_core
from penguin.llm.model_config import ModelConfig


def _config(model: str) -> ModelConfig:
    return ModelConfig(
        model=model,
        provider="openai",
        client_preference="native",
        max_output_tokens=8000,
        max_context_window_tokens=128000,
        streaming_enabled=True,
    )


class _Client:
    def __init__(self, model_config: ModelConfig) -> None:
        if model_config.model == "unbuildable":
            raise ValueError("no credential for this provider")
        self.model_config = model_config

    def set_system_prompt(self, _prompt: str) -> None:
        return None


def _core(old: ModelConfig) -> Any:
    core = PenguinCore.__new__(PenguinCore)
    core.model_config = old
    core.system_prompt = "system prompt"
    core.api_client = _Client(old)
    context_window = SimpleNamespace(
        max_context_window_tokens=200000,
        model_config=old,
        api_client=core.api_client,
        _initialize_token_budgets=MagicMock(),
    )
    core.conversation_manager = SimpleNamespace(
        context_window=context_window, model_config=old, api_client=core.api_client
    )
    core.engine = SimpleNamespace(model_config=old, api_client=core.api_client)
    core.refresh_api_client = PenguinCore.refresh_api_client.__get__(core)
    core._apply_new_model_config = PenguinCore._apply_new_model_config.__get__(core)
    return core


@pytest.mark.asyncio
async def test_a_switch_whose_client_cannot_be_built_changes_nothing() -> None:
    old = _config("gpt-4")
    core = _core(old)
    old_client = core.api_client
    core._build_model_config_for_model = AsyncMock(
        return_value=(_config("unbuildable"), 64000)
    )

    with patch.dict(PenguinCore.refresh_api_client.__globals__, {"APIClient": _Client}):
        switched = await load_model_for_core(core, "unbuildable")

    assert switched is False
    assert core.model_config is old
    assert core.api_client is old_client
    assert core.engine.model_config is old
    assert core.conversation_manager.model_config is old
    assert core.conversation_manager.context_window.max_context_window_tokens == 200000


@pytest.mark.asyncio
async def test_a_successful_switch_moves_every_component() -> None:
    core = _core(_config("gpt-4"))
    new = _config("gpt-5")
    core._build_model_config_for_model = AsyncMock(return_value=(new, 108800))

    with patch.dict(PenguinCore.refresh_api_client.__globals__, {"APIClient": _Client}):
        switched = await load_model_for_core(core, "gpt-5")

    assert switched is True
    assert core.model_config is new
    assert core.api_client.model_config is new
    for component in (
        core.engine,
        core.conversation_manager,
        core.conversation_manager.context_window,
    ):
        assert component.model_config is new
        assert component.api_client is core.api_client
    assert core.conversation_manager.context_window.max_context_window_tokens == 108800
