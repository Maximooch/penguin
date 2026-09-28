"""Environment policy and real child-process regressions without credentials."""

from __future__ import annotations

import ast
import asyncio
import json
import os
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from penguin.system.tool_environment import (
    build_tool_environment,
    hosted_tools_enabled,
    tool_environment_capabilities,
    tool_environment_scope,
)
from penguin.tools.process_runtime import ProcessRuntime
from penguin.utils.notebook import NotebookExecutor


def test_hosted_environment_excludes_ambient_secrets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unknown server variables are excluded without enumerating secret names."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    for key in (
        "LINK_INFERENCE_SERVICE_TOKEN",
        "OPENROUTER_API_KEY",
        "UNKNOWN_SECRET",
        "BASH_ENV",
        "HOME",
    ):
        monkeypatch.setenv(key, "synthetic-secret")
    env = build_tool_environment({"BUILD_LABEL": "test"})
    assert "synthetic-secret" not in env.values()
    assert env["BUILD_LABEL"] == "test"
    assert env.get("PATH") == os.environ.get("PATH")


@pytest.mark.parametrize(
    "key",
    [
        "PATH",
        "path",
        "HOME",
        "BASH_ENV",
        "LINK_API_TOKEN",
        "LK_CONFIG",
        "PENGUIN_TOOL_ENVIRONMENT",
        "NODE_OPTIONS",
        "PYTHONPATH",
        "LD_PRELOAD",
        "GIT_CONFIG_COUNT",
        "https_proxy",
        "BAD=NAME",
    ],
)
def test_reserved_overrides_fail_without_values(
    key: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Tool arguments cannot replace bootstrap authority or startup hooks."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    with pytest.raises(ValueError, match="invalid or reserved") as error:
        build_tool_environment({key: "synthetic-secret"})
    assert "synthetic-secret" not in str(error.value)


def test_local_mode_preserves_inheritance(monkeypatch: pytest.MonkeyPatch) -> None:
    """Local operators retain their existing child environment behavior."""
    monkeypatch.delenv("PENGUIN_TOOL_ENVIRONMENT", raising=False)
    monkeypatch.setenv("UNKNOWN_SECRET", "synthetic-local")
    assert build_tool_environment()["UNKNOWN_SECRET"] == "synthetic-local"
    assert build_tool_environment({"PATH": "custom"})["PATH"] == "custom"


def test_unknown_mode_fails_closed(monkeypatch: pytest.MonkeyPatch) -> None:
    """A misspelled deployment policy must not select local inheritance."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosetd")
    with pytest.raises(ValueError):
        hosted_tools_enabled()


@pytest.mark.asyncio
async def test_scoped_values_survive_offload_without_cross_task_leak(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Concurrent contexts have independent snapshots and unwind on errors."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")

    async def child(label: str) -> str:
        """Read one trusted value from an actual subprocess after offload."""
        supplied = {"LINK_API_TOKEN": label}
        with tool_environment_scope(supplied):
            supplied["LINK_API_TOKEN"] = "mutated"
            await asyncio.sleep(0)

            def run() -> str:
                """Launch a process with the current task's environment."""
                return subprocess.check_output(
                    [
                        sys.executable,
                        "-c",
                        "import os; print(os.environ['LINK_API_TOKEN'])",
                    ],
                    env=build_tool_environment(),
                    text=True,
                ).strip()

            return await asyncio.to_thread(run)

    assert await asyncio.gather(child("one"), child("two")) == ["one", "two"]
    assert "LINK_API_TOKEN" not in build_tool_environment()
    with pytest.raises(RuntimeError), tool_environment_scope({"LINK_API_TOKEN": "one"}):
        raise RuntimeError("test")
    assert "LINK_API_TOKEN" not in build_tool_environment()


def test_process_runtime_and_notebook_shell_use_policy(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Actual shell paths cannot inherit a synthetic service credential."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    monkeypatch.setenv("LINK_INFERENCE_SERVICE_TOKEN", "synthetic-secret")
    command = f"{shlex.quote(sys.executable)} -c " + shlex.quote(
        "import os,json; print(json.dumps(dict(os.environ)))"
    )
    runtime = ProcessRuntime(log_dir=tmp_path)
    started = runtime.start(command, cwd=str(tmp_path), env={"BUILD_LABEL": "test"})
    process_id = started["process_id"]
    try:
        runtime._processes[process_id].process.wait(timeout=5)
        runtime._processes[process_id].reader.join(timeout=5)
        output = runtime.poll(process_id)["output"]
        assert "synthetic-secret" not in output
        assert "BUILD_LABEL" in output
    finally:
        runtime.stop(process_id)
    executor = object.__new__(NotebookExecutor)
    executor.active_directory = str(tmp_path)
    assert "synthetic-secret" not in executor.execute_shell(command)
    denied = runtime.start(
        "echo should-not-run", env={"LINK_API_TOKEN": "synthetic-secret"}
    )
    assert "reserved" in json.dumps(denied)
    assert "synthetic-secret" not in json.dumps(denied)


def test_notebook_python_is_denied_before_execution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Hosted Python cannot inspect the server's in-process environment."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    executor = object.__new__(NotebookExecutor)
    assert "disabled in hosted mode" in executor.execute_code(
        "raise AssertionError('ran')"
    )


def test_manager_denies_notebook_before_starting_thread(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The tool entry point rejects hosted Python without requiring an executor."""
    from penguin.tools.tool_manager import ToolManager

    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    manager = object.__new__(ToolManager)
    assert "disabled in hosted mode" in manager.execute_code(
        "raise AssertionError('ran')"
    )


def test_capability_does_not_claim_isolation(monkeypatch: pytest.MonkeyPatch) -> None:
    """Environment hygiene is not authorization for hosted credential delivery."""
    monkeypatch.setenv("PENGUIN_TOOL_ENVIRONMENT", "hosted")
    assert tool_environment_capabilities() == {
        "version": 1,
        "mode": "hosted",
        "execution_isolation": False,
        "remote_credential_delivery": False,
    }


def test_tool_subprocess_sites_pass_explicit_environment() -> None:
    """Prevent ambient inheritance from returning to the audited launch sites."""
    root = Path(__file__).resolve().parents[2]
    paths = list((root / "penguin/tools").rglob("*.py")) + [
        root / "penguin" / path
        for path in (
            "utils/notebook.py",
            "utils/process_manager.py",
            "utils/parser.py",
            "project/validation_manager.py",
            "system/conversation.py",
            "system/file_manager.py",
            "system/file_session.py",
        )
    ]
    for path in paths:
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(
                node.func, ast.Attribute
            ):
                continue
            if not isinstance(node.func.value, ast.Name):
                continue
            pair = (node.func.value.id, node.func.attr)
            if pair in {
                ("subprocess", "run"),
                ("subprocess", "Popen"),
                ("asyncio", "create_subprocess_exec"),
                ("asyncio", "create_subprocess_shell"),
            }:
                assert any(k.arg == "env" for k in node.keywords), (
                    f"{path}:{node.lineno}"
                )
