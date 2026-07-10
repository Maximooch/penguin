"""Runtime storage ownership tests for Penguin web servers."""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
import sys
import types
from pathlib import Path

import pytest

from penguin.web import server
from penguin.web.runtime_storage import (
    RuntimeStorageLease,
    RuntimeStorageOwnershipError,
    build_isolated_test_environment,
    resolve_runtime_storage,
)


def _tree_snapshot(root: Path) -> dict[str, tuple[str, int, int, int, str | None]]:
    """Return a byte/stat snapshot suitable for mutation assertions."""

    snapshot: dict[str, tuple[str, int, int, int, str | None]] = {}
    for path in [root, *sorted(root.rglob("*"))]:
        relative = "." if path == root else path.relative_to(root).as_posix()
        stat = path.stat()
        digest = (
            hashlib.sha256(path.read_bytes()).hexdigest() if path.is_file() else None
        )
        snapshot[relative] = (
            "file" if path.is_file() else "directory",
            stat.st_size,
            stat.st_mode,
            stat.st_mtime_ns,
            digest,
        )
    return snapshot


def test_test_server_environment_is_fully_isolated(tmp_path: Path) -> None:
    """The supported 8080 environment keeps every mutable path under one root."""

    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="phase-0",
        environ={},
    )
    layout = resolve_runtime_storage(
        host=env["HOST"],
        port=int(env["PORT"]),
        environ=env,
    )

    assert layout.role == "test"
    assert layout.host == "127.0.0.1"
    assert layout.port == 8080
    assert env["PENGUIN_SERVER_ROLE"] == "test"
    assert env["PENGUIN_WORKSPACE"] == str(layout.workspace)

    for path in layout.mutable_paths:
        assert path == layout.workspace or path.is_relative_to(layout.workspace)


def test_supported_runner_does_not_touch_ambient_workspace(tmp_path: Path) -> None:
    """The runner installs isolation before any config import can create paths."""

    repository = Path(__file__).resolve().parents[2]
    production_sentinel = tmp_path / "production-sentinel"
    environment = dict(os.environ)
    environment["PENGUIN_WORKSPACE"] = str(production_sentinel)
    environment["PENGUIN_CONFIG_PATH"] = str(tmp_path / "ambient-config.yml")

    result = subprocess.run(
        [
            sys.executable,
            "scripts/run_runtime_reliability_server.py",
            "--describe",
            "--base-directory",
            str(tmp_path / "test-runtimes"),
            "--run-id",
            "subprocess-check",
        ],
        cwd=repository,
        env=environment,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    assert not production_sentinel.exists()
    diagnostics = json.loads(result.stdout)
    assert diagnostics["server_role"] == "test"
    assert diagnostics["workspace"].endswith("test-runtimes/subprocess-check")


def test_test_server_rejects_default_or_external_mutable_paths(
    tmp_path: Path,
) -> None:
    """Port 8080 must not silently fall back to production-style storage."""

    with pytest.raises(RuntimeStorageOwnershipError, match="PENGUIN_WORKSPACE"):
        resolve_runtime_storage(
            host="127.0.0.1",
            port=8080,
            environ={"PENGUIN_SERVER_ROLE": "test"},
        )

    workspace = tmp_path / "isolated"
    with pytest.raises(RuntimeStorageOwnershipError, match="ledger"):
        resolve_runtime_storage(
            host="127.0.0.1",
            port=8080,
            environ={
                "PENGUIN_SERVER_ROLE": "test",
                "PENGUIN_WORKSPACE": str(workspace),
                "PENGUIN_RUNTIME_EVENT_LEDGER_PATH": str(
                    tmp_path / "shared" / "runtime.db"
                ),
            },
        )


def test_test_role_requires_the_documented_host_and_port(tmp_path: Path) -> None:
    """A declared test backend cannot accidentally bind like production."""

    env = {
        "PENGUIN_SERVER_ROLE": "test",
        "PENGUIN_WORKSPACE": str(tmp_path / "runtime"),
    }

    with pytest.raises(RuntimeStorageOwnershipError, match="127.0.0.1:8080"):
        resolve_runtime_storage(host="0.0.0.0", port=8080, environ=env)
    with pytest.raises(RuntimeStorageOwnershipError, match="127.0.0.1:8080"):
        resolve_runtime_storage(host="127.0.0.1", port=9000, environ=env)
    with pytest.raises(RuntimeStorageOwnershipError, match="reserved for test"):
        resolve_runtime_storage(
            host="127.0.0.1",
            port=8080,
            environ={
                "PENGUIN_SERVER_ROLE": "production",
                "PENGUIN_WORKSPACE": str(tmp_path / "production-bypass"),
            },
        )


def test_test_environment_isolates_global_caches_and_credentials(
    tmp_path: Path,
) -> None:
    """A test run must not mutate home-global auth, cache, or credential files."""

    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="global-state",
        environ={},
    )
    workspace = Path(env["PENGUIN_WORKSPACE"])

    for variable in (
        "PENGUIN_CACHE_DIR",
        "PENGUIN_LOCAL_AUTH_CACHE_DIR",
        "PENGUIN_PROVIDER_CREDENTIALS_STORE",
        "PENGUIN_PROVIDER_AUTH_STORE",
        "XDG_CONFIG_HOME",
        "XDG_CACHE_HOME",
    ):
        path = Path(env[variable])
        assert path == workspace or path.is_relative_to(workspace)


def test_storage_lease_rejects_two_backends_sharing_workspace(
    tmp_path: Path,
) -> None:
    """A live owner prevents a second backend from sharing mutable state."""

    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="shared",
        environ={},
    )
    first_layout = resolve_runtime_storage(
        host="127.0.0.1",
        port=8080,
        environ=env,
    )
    second_layout = resolve_runtime_storage(
        host="127.0.0.1",
        port=8080,
        environ=env,
    )

    with RuntimeStorageLease(first_layout):
        with pytest.raises(RuntimeStorageOwnershipError, match="already owned"):
            with RuntimeStorageLease(second_layout):
                raise AssertionError("shared storage lease unexpectedly acquired")


def test_isolated_production_and_test_layouts_can_be_owned_together(
    tmp_path: Path,
) -> None:
    """Distinct 9000 and 8080 workspaces do not contend on any mutable path."""

    production = resolve_runtime_storage(
        host="127.0.0.1",
        port=9000,
        environ={
            "PENGUIN_SERVER_ROLE": "production",
            "PENGUIN_WORKSPACE": str(tmp_path / "production"),
        },
    )
    test_env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="test",
        environ={},
    )
    test = resolve_runtime_storage(
        host="127.0.0.1",
        port=8080,
        environ=test_env,
    )

    assert set(production.mutable_paths).isdisjoint(test.mutable_paths)
    with RuntimeStorageLease(production), RuntimeStorageLease(test):
        assert production.lease_path.exists()
        assert test.lease_path.exists()


def test_isolated_runtime_real_writers_leave_production_tree_unchanged(
    tmp_path: Path,
) -> None:
    """Real test-side persistence writers cannot mutate production storage."""

    repository = Path(__file__).resolve().parents[2]
    production = tmp_path / "production"
    (production / "conversations").mkdir(parents=True)
    (production / "checkpoints").mkdir()
    (production / "runtime-events.db").write_bytes(b"production-ledger-sentinel")
    (production / "conversations" / "session.json").write_text(
        '{"sentinel": "production-session"}',
        encoding="utf-8",
    )
    (production / "checkpoints" / "checkpoint.json.gz").write_bytes(
        b"production-checkpoint-sentinel"
    )
    before = _tree_snapshot(production)

    env = build_isolated_test_environment(
        base_directory=tmp_path / "test-runtimes",
        run_id="real-writers",
        environ=os.environ,
    )
    writer = r'''
import asyncio
import json
import os
from pathlib import Path

from penguin.local_auth import write_local_auth_token
from penguin.system.checkpoint_manager import (
    CheckpointConfig,
    CheckpointManager,
    CheckpointType,
)
from penguin.system.runtime_event_ledger import RuntimeEventLedger
from penguin.system.runtime_events import build_runtime_event
from penguin.system.session_manager import SessionManager
from penguin.system.state import MessageCategory, create_message
from penguin.tools.runtime import ToolResult, tool_result_with_model_output_policy
from penguin.web.services.provider_credentials import set_provider_credential


async def main() -> None:
    workspace = Path(os.environ["PENGUIN_WORKSPACE"])
    conversations = workspace / "conversations"
    manager = SessionManager(base_path=str(conversations), auto_save_interval=0)
    session = manager.create_session()
    message = create_message("user", "isolated request", MessageCategory.DIALOG)
    session.add_message(message)
    assert manager.save_session(session)

    ledger = RuntimeEventLedger(Path(os.environ["PENGUIN_RUNTIME_EVENT_LEDGER_PATH"]))
    event = build_runtime_event(
        event_type="message.updated",
        payload={
            "id": "isolated-message",
            "sessionID": session.id,
            "role": "assistant",
        },
        sequence=1,
        time_ms=1_000,
    )
    assert ledger.append(event)

    write_local_auth_token("isolated-token", host="127.0.0.1", port=8080)
    set_provider_credential(
        "isolation-test",
        {"type": "api", "key": "sk-isolated-test-only"},
    )
    artifact = tool_result_with_model_output_policy(
        ToolResult(
            call_id="isolated-tool",
            name="isolated",
            status="completed",
            output="x" * 256,
        ),
        max_chars=32,
        artifact_dir=workspace / "conversations" / "tool-results",
    )
    assert artifact.artifact_path

    checkpoint_manager = CheckpointManager(
        workspace,
        manager,
        CheckpointConfig(enabled=True, max_auto_checkpoints=10),
    )
    checkpoint_id = await checkpoint_manager.create_checkpoint(
        session,
        message,
        CheckpointType.MANUAL,
        name="isolation-proof",
    )
    assert checkpoint_id
    assert checkpoint_manager.checkpoint_queue is not None
    await checkpoint_manager.checkpoint_queue.join()
    await checkpoint_manager.stop_workers()

    generated = [
        str(path.relative_to(workspace))
        for path in workspace.rglob("*")
        if path.is_file()
    ]
    print(json.dumps({"workspace": str(workspace), "generated": sorted(generated)}))


asyncio.run(main())
'''
    result = subprocess.run(
        [sys.executable, "-c", writer],
        cwd=repository,
        env=env,
        check=False,
        capture_output=True,
        text=True,
        timeout=30,
    )

    assert result.returncode == 0, result.stderr
    output = json.loads(result.stdout.strip().splitlines()[-1])
    test_workspace = Path(env["PENGUIN_WORKSPACE"]).resolve()
    assert Path(output["workspace"]).resolve() == test_workspace
    assert output["generated"]
    assert all(
        path.resolve().is_relative_to(test_workspace)
        for path in test_workspace.rglob("*")
    )
    assert _tree_snapshot(production) == before


def test_cross_process_storage_owner_fails_fast(tmp_path: Path) -> None:
    """A second backend process cannot acquire a live owner's workspace."""

    repository = Path(__file__).resolve().parents[2]
    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="cross-process-owner",
        environ=os.environ,
    )
    holder = r'''
import os
import sys

from penguin.web.runtime_storage import RuntimeStorageLease, resolve_runtime_storage

layout = resolve_runtime_storage(host="127.0.0.1", port=8080, environ=os.environ)
with RuntimeStorageLease(layout):
    print("owned", flush=True)
    sys.stdin.readline()
'''
    process = subprocess.Popen(
        [sys.executable, "-c", holder],
        cwd=repository,
        env=env,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "owned"
        layout = resolve_runtime_storage(
            host="127.0.0.1",
            port=8080,
            environ=env,
        )
        with pytest.raises(RuntimeStorageOwnershipError, match="already owned"):
            with RuntimeStorageLease(layout):
                raise AssertionError(
                    "cross-process shared storage unexpectedly acquired"
                )
    finally:
        if process.stdin is not None:
            process.stdin.write("release\n")
            process.stdin.flush()
            process.stdin.close()
        process.wait(timeout=10)


def test_startup_diagnostics_report_paths_without_environment_values(
    tmp_path: Path,
) -> None:
    """Diagnostics expose ownership paths but not unrelated environment secrets."""

    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="diagnostics",
        environ={"OPENAI_API_KEY": "never-log-this"},
    )
    layout = resolve_runtime_storage(
        host="127.0.0.1",
        port=8080,
        environ=env,
    )

    diagnostics = layout.to_diagnostics()
    encoded = json.dumps(diagnostics, sort_keys=True)

    assert diagnostics["server_role"] == "test"
    assert diagnostics["workspace"] == str(layout.workspace)
    assert diagnostics["runtime_event_ledger"] == str(layout.ledger_path)
    assert diagnostics["checkpoints"] == str(layout.checkpoint_path)
    assert diagnostics["conversations"] == str(layout.conversation_path)
    assert "never-log-this" not in encoded


def test_web_main_refuses_unisolated_8080_before_app_creation(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """The normal web entrypoint enforces test isolation before app startup."""

    app_created = False

    def create_app() -> object:
        nonlocal app_created
        app_created = True
        return object()

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=lambda: None))
    monkeypatch.setattr(server, "create_app_factory", create_app)
    monkeypatch.setenv("HOST", "127.0.0.1")
    monkeypatch.setenv("PORT", "8080")
    monkeypatch.setenv("PENGUIN_SERVER_ROLE", "test")
    monkeypatch.setenv("PENGUIN_WEB_LOG_ENABLED", "false")
    monkeypatch.delenv("PENGUIN_WORKSPACE", raising=False)

    assert server.main([]) == 1
    assert app_created is False
    assert "requires an explicit isolated PENGUIN_WORKSPACE" in capsys.readouterr().out


def test_web_main_holds_storage_lease_and_emits_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """The web entrypoint owns storage for the full uvicorn invocation."""

    env = build_isolated_test_environment(
        base_directory=tmp_path,
        run_id="server-main",
        environ={},
    )
    layout = resolve_runtime_storage(
        host="127.0.0.1",
        port=8080,
        environ=env,
    )
    calls: list[tuple[tuple[object, ...], dict[str, object]]] = []

    def run(*args: object, **kwargs: object) -> None:
        calls.append((args, kwargs))
        with pytest.raises(RuntimeStorageOwnershipError, match="already owned"):
            with RuntimeStorageLease(layout):
                raise AssertionError("server storage was not leased")

    monkeypatch.setitem(sys.modules, "uvicorn", types.SimpleNamespace(run=run))
    monkeypatch.setattr(server, "create_app_factory", lambda: object())
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    monkeypatch.setenv("PENGUIN_WEB_LOG_ENABLED", "false")
    monkeypatch.setenv("PENGUIN_AUTH_ENABLED", "true")

    with caplog.at_level("INFO", logger="penguin.web.server"):
        assert server.main([]) == 0

    assert calls
    assert any("runtime storage" in record.message for record in caplog.records)
    with RuntimeStorageLease(layout):
        assert layout.lease_path.exists()
