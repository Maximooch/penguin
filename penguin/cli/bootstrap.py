"""Dependency composition for the Python CLI."""

from __future__ import annotations

import logging
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable

from penguin.cli.environment import set_cli_workspace_path
from penguin.cli.interface import PenguinInterface
from penguin.cli.model_runtime import build_cli_model_config
from penguin.config import Config, WORKSPACE_PATH, _ensure_env_loaded
from penguin.core import PenguinCore
from penguin.llm.api_client import APIClient
from penguin.llm.model_config import ModelConfig
from penguin.system_prompt import SYSTEM_PROMPT
from penguin.tools import ToolManager
from penguin.utils.log_error import log_error

__all__ = ["BootstrapDependencies", "BootstrapResult", "bootstrap_cli"]

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BootstrapResult:
    """Fully constructed CLI dependencies, safe to publish atomically."""

    core: PenguinCore
    interface: PenguinInterface
    model_config: ModelConfig
    api_client: APIClient
    tool_manager: ToolManager
    loaded_config: Config
    workspace: Path


@dataclass(frozen=True)
class BootstrapDependencies:
    """Injectable factories for deterministic startup tests."""

    config_loader: Callable[[], Config] = Config.load_config
    api_client_factory: Callable[..., APIClient] = APIClient
    tool_manager_factory: Callable[..., ToolManager] = ToolManager
    core_factory: Callable[..., PenguinCore] = PenguinCore
    interface_factory: Callable[[PenguinCore], PenguinInterface] = PenguinInterface
    env_loader: Callable[[], None] = _ensure_env_loaded


class _ConfigWrapper:
    def __init__(self, data: dict[str, Any]) -> None:
        self._data = data
        self._data.setdefault("diagnostics", {"enabled": False})

    def __getattr__(self, name: str) -> Any:
        if name not in self._data:
            raise AttributeError(name)
        value = self._data[name]
        return _ConfigWrapper(value) if isinstance(value, dict) else value

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, default)

    def __contains__(self, key: str) -> bool:
        return key in self._data


def _compatible_config(config: Any) -> Any:
    return _ConfigWrapper(config) if isinstance(config, dict) else config


def bootstrap_cli(
    *,
    model_override: str | None = None,
    workspace_override: Path | None = None,
    no_streaming_override: bool = False,
    fast_startup_override: bool = False,
    dependencies: BootstrapDependencies | None = None,
) -> BootstrapResult:
    """Construct CLI dependencies without mutating compatibility globals."""

    deps = dependencies or BootstrapDependencies()
    started_at = time.monotonic()
    workspace_source = workspace_override or os.environ.get("PENGUIN_WORKSPACE")
    if workspace_source:
        set_cli_workspace_path(workspace_source)

    loaded_config = deps.config_loader()
    workspace = (
        Path(
            workspace_override
            or os.environ.get("PENGUIN_WORKSPACE")
            or getattr(loaded_config, "workspace_path", WORKSPACE_PATH)
        )
        .expanduser()
        .resolve()
    )
    source_model = loaded_config.model_config
    model_config = build_cli_model_config(
        loaded_config,
        model_override=model_override,
        streaming_enabled=(
            False if no_streaming_override else source_model.streaming_enabled
        ),
    )

    deps.env_loader()
    api_client = deps.api_client_factory(model_config=model_config)
    api_client.set_system_prompt(SYSTEM_PROMPT)
    config_dict = (
        loaded_config.to_dict()
        if hasattr(loaded_config, "to_dict")
        else getattr(loaded_config, "__dict__", loaded_config)
    )
    tool_manager = deps.tool_manager_factory(
        config_dict,
        log_error,
        fast_startup=(
            fast_startup_override or bool(getattr(loaded_config, "fast_startup", False))
        ),
    )
    core = deps.core_factory(
        config=_compatible_config(loaded_config),
        api_client=api_client,
        tool_manager=tool_manager,
        model_config=model_config,
    )
    interface = deps.interface_factory(core)
    logger.info("CLI dependencies constructed in %.2fs", time.monotonic() - started_at)
    return BootstrapResult(
        core=core,
        interface=interface,
        model_config=model_config,
        api_client=api_client,
        tool_manager=tool_manager,
        loaded_config=loaded_config,
        workspace=workspace,
    )
