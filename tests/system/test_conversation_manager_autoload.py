#!/usr/bin/env python3
"""Standalone smoke test for ConversationManager project-doc autoloading.

Run with `python tests/system/test_conversation_manager_autoload.py`.
Checks two cases:
  1. Autoload pulls in PENGUIN.md when enabled.
  2. Autoload stays off when config flag is false.

Exits with non-zero status if any check fails.
"""

from __future__ import annotations

import copy
import os
import sys
import tempfile
import traceback
from contextlib import contextmanager
from pathlib import Path
from typing import Callable, Iterator


@contextmanager
def _temporary_workspace() -> Iterator[Path]:
    """Provide a temporary workspace and patch global config paths."""

    import importlib
    import sys

    original_env = os.environ.get("PENGUIN_WORKSPACE")
    with tempfile.TemporaryDirectory(prefix="penguin_autoload_") as tmp_dir:
        workspace = Path(tmp_dir)
        os.environ["PENGUIN_WORKSPACE"] = str(workspace)

        # Ensure penguin.config is loaded/reloaded after env override
        cfg_module = sys.modules.get("penguin.config")
        if cfg_module is not None and hasattr(cfg_module, "WORKSPACE_PATH"):
            cfg_module = importlib.reload(cfg_module)
        else:
            cfg_module = importlib.import_module("penguin.config")

        # Capture config globals that depend on workspace path
        original_workspace = cfg_module.WORKSPACE_PATH
        original_conversations = cfg_module.CONVERSATIONS_PATH
        paths_present = "paths" in cfg_module.config
        original_paths = copy.deepcopy(cfg_module.config.get("paths", {}))

        # Patch config globals and derived paths
        cfg_module.WORKSPACE_PATH = workspace
        cfg_module.CONVERSATIONS_PATH = workspace / "conversations"
        cfg_module.CONVERSATIONS_PATH.mkdir(parents=True, exist_ok=True)

        cfg_module.config.setdefault("paths", {})
        cfg_module.config["paths"].update(
            {
                "workspace": str(workspace),
                "conversations": str(cfg_module.CONVERSATIONS_PATH),
                "memory_db": str(workspace / "memory_db"),
                "logs": str(workspace / "logs"),
            }
        )

        for folder in ("memory_db", "logs", "context"):
            (workspace / folder).mkdir(parents=True, exist_ok=True)

        # SimpleContextLoader captures WORKSPACE_PATH at import time.
        loader_module = sys.modules.get("penguin.system.context_loader")
        if loader_module is not None and hasattr(loader_module, "WORKSPACE_PATH"):
            loader_module = importlib.reload(loader_module)
        else:
            loader_module = importlib.import_module("penguin.system.context_loader")

        original_loader_workspace = loader_module.WORKSPACE_PATH
        loader_module.WORKSPACE_PATH = workspace

        # Ensure ConversationManager module sees refreshed config each time
        manager_module = sys.modules.get("penguin.system.conversation_manager")
        if manager_module is not None:
            importlib.reload(manager_module)

        
        try:
            yield workspace
        finally:
            # Restore context loader and config globals
            loader_module.WORKSPACE_PATH = original_loader_workspace
            cfg_module.WORKSPACE_PATH = original_workspace
            cfg_module.CONVERSATIONS_PATH = original_conversations
            if paths_present:
                cfg_module.config["paths"] = original_paths
            else:
                cfg_module.config.pop("paths", None)

            if original_env is None:
                os.environ.pop("PENGUIN_WORKSPACE", None)
            else:
                os.environ["PENGUIN_WORKSPACE"] = original_env


def _find_project_docs_message(conversation_manager) -> bool:
    from penguin.system.state import MessageCategory

    for message in conversation_manager.conversation.session.messages:
        if message.category != MessageCategory.CONTEXT:
            continue
        if not isinstance(message.content, str):
            continue
        metadata = message.metadata or {}
        if metadata.get("source") == "project_docs":
            return True
        if "Project Instructions (PENGUIN.md)" in message.content:
            return True
        if "Agent Specifications (AGENTS.md)" in message.content:
            return True
    return False

def _get_config_module():
    import importlib
    import sys

    module = sys.modules.get("penguin.config")
    if module is None or not hasattr(module, "config"):
        module = importlib.import_module("penguin.config")
    return module


def _set_autoload_flag(value: bool) -> Callable[[], None]:
    """Apply the autoload flag and return a restore callback."""

    cfg_module = _get_config_module()

    context_cfg = cfg_module.config.setdefault("context", {})
    had_key = "autoload_project_docs" in context_cfg
    previous = context_cfg.get("autoload_project_docs")
    context_cfg["autoload_project_docs"] = value

    def _restore() -> None:
        if had_key:
            context_cfg["autoload_project_docs"] = previous
        else:
            context_cfg.pop("autoload_project_docs", None)

    return _restore


def _make_conversation_manager(workspace: Path):
    from penguin.system.conversation_manager import ConversationManager

    return ConversationManager(
        model_config=None,
        api_client=None,
        workspace_path=workspace,
        system_prompt="",
        auto_save_interval=0,
    )


def _test_autoload_enabled() -> Tuple[bool, str]:
    with _temporary_workspace() as workspace:
        restore_autoload = _set_autoload_flag(True)
        try:
            (workspace / "PENGUIN.md").write_text("Penguin rules!", encoding="utf-8")
            cm = _make_conversation_manager(workspace)
            if _find_project_docs_message(cm):
                return True, "project docs context message detected"
            return False, "expected project docs context message not found"
        finally:
            restore_autoload()


def _test_autoload_disabled() -> Tuple[bool, str]:
    with _temporary_workspace() as workspace:
        restore_autoload = _set_autoload_flag(False)
        try:
            (workspace / "PENGUIN.md").write_text("Penguin rules!", encoding="utf-8")
            cm = _make_conversation_manager(workspace)
            if not _find_project_docs_message(cm):
                return True, "autoload disabled successfully"
            return False, "project docs context message appeared despite flag being disabled"
        finally:
            restore_autoload()


def main() -> int:
    checks = [
        ("autoload enabled loads PENGUIN.md", _test_autoload_enabled),
        ("autoload flag disables loading", _test_autoload_disabled),
    ]

    failures = 0
    for name, func in checks:
        try:
            passed, detail = func()
        except Exception as exc:  # noqa: BLE001 - surface unexpected failures
            failures += 1
            print(f"❌ {name}: unexpected error: {exc}")
            traceback.print_exc()
            continue

        if passed:
            print(f"✅ {name}: {detail}")
        else:
            failures += 1
            print(f"❌ {name}: {detail}")

    if failures:
        print(f"\n{failures} check(s) failed.")
        return 1

    print("\nAll autoload checks passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
