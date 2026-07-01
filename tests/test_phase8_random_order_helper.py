"""Tests for Phase 8 local random-order pytest helper."""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from types import ModuleType


def _load_random_order_helper() -> ModuleType:
    script_path = (
        Path(__file__).resolve().parents[1] / "scripts" / "random_order_pytest.py"
    )
    spec = importlib.util.spec_from_file_location(
        "random_order_pytest",
        script_path,
    )
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_collect_pytest_args_strips_quiet_flags_that_hide_nodeids() -> None:
    helper = _load_random_order_helper()

    assert helper._collect_pytest_args(
        [
            "tests/core_runtime/test_action_mapping.py",
            "-q",
            "--quiet",
            "-qq",
            "-k",
            "action_mapping",
        ]
    ) == [
        "tests/core_runtime/test_action_mapping.py",
        "-k",
        "action_mapping",
    ]
