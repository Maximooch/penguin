"""Contract tests for extracted CLI startup composition."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from penguin.cli.bootstrap import BootstrapDependencies, bootstrap_cli
from penguin.llm.model_config import ModelConfig


def _loaded_config(workspace: Path) -> SimpleNamespace:
    model_config = ModelConfig(
        model="gpt-4o",
        provider="openai",
        client_preference="native",
        streaming_enabled=True,
    )
    return SimpleNamespace(
        model_config=model_config,
        model_configs={},
        api=SimpleNamespace(base_url=None),
        workspace_path=workspace,
        fast_startup=False,
        to_dict=lambda: {"model": {"default": "gpt-4o"}},
    )


def test_bootstrap_constructs_complete_result_before_publication(
    tmp_path: Path,
) -> None:
    loaded_config = _loaded_config(tmp_path)
    api_client = SimpleNamespace(set_system_prompt=Mock())
    tool_manager = object()
    core = object()
    interface = object()
    dependencies = BootstrapDependencies(
        config_loader=lambda: loaded_config,
        api_client_factory=Mock(return_value=api_client),
        tool_manager_factory=Mock(return_value=tool_manager),
        core_factory=Mock(return_value=core),
        interface_factory=Mock(return_value=interface),
        env_loader=Mock(),
    )

    result = bootstrap_cli(
        workspace_override=tmp_path,
        no_streaming_override=True,
        fast_startup_override=True,
        dependencies=dependencies,
    )

    assert result.core is core
    assert result.interface is interface
    assert result.workspace == tmp_path.resolve()
    assert result.model_config.streaming_enabled is False
    dependencies.env_loader.assert_called_once_with()
    dependencies.tool_manager_factory.assert_called_once()
    assert dependencies.tool_manager_factory.call_args.kwargs["fast_startup"] is True
    api_client.set_system_prompt.assert_called_once()


def test_bootstrap_propagates_factory_failure_without_partial_result(
    tmp_path: Path,
) -> None:
    loaded_config = _loaded_config(tmp_path)
    dependencies = BootstrapDependencies(
        config_loader=lambda: loaded_config,
        api_client_factory=Mock(side_effect=RuntimeError("provider unavailable")),
        tool_manager_factory=Mock(),
        core_factory=Mock(),
        interface_factory=Mock(),
        env_loader=Mock(),
    )

    with pytest.raises(RuntimeError, match="provider unavailable"):
        bootstrap_cli(dependencies=dependencies)

    dependencies.tool_manager_factory.assert_not_called()
    dependencies.core_factory.assert_not_called()
    dependencies.interface_factory.assert_not_called()


def test_bootstrap_model_override_reaches_target_factory(tmp_path: Path) -> None:
    loaded_config = _loaded_config(tmp_path)
    api_client_factory = Mock(return_value=SimpleNamespace(set_system_prompt=Mock()))
    dependencies = BootstrapDependencies(
        config_loader=lambda: loaded_config,
        api_client_factory=api_client_factory,
        tool_manager_factory=Mock(return_value=object()),
        core_factory=Mock(return_value=object()),
        interface_factory=Mock(return_value=object()),
        env_loader=Mock(),
    )

    result = bootstrap_cli(model_override="gpt-5.6-sol", dependencies=dependencies)

    assert result.model_config.model == "gpt-5.6-sol"
    assert result.model_config.supports_reasoning is True
    assert api_client_factory.call_args.kwargs["model_config"] is result.model_config
