"""Resolve and guard mutable storage owned by one Penguin web server.

The web port is not a storage boundary. A production backend on port 9000 and a
test backend on port 8080 can still corrupt or stall each other if they share a
workspace or runtime-event ledger. This module makes that ownership explicit
before the application is constructed.
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import IO, Mapping

__all__ = [
    "RuntimeStorageLayout",
    "RuntimeStorageLease",
    "RuntimeStorageOwnershipError",
    "build_isolated_test_environment",
    "resolve_runtime_storage",
]

TEST_SERVER_HOST = "127.0.0.1"
TEST_SERVER_PORT = 8080
PRODUCTION_SERVER_PORT = 9000
VALID_SERVER_ROLES = {"production", "test", "custom"}


class RuntimeStorageOwnershipError(RuntimeError):
    """Raised when a server would use unsafe or already-owned mutable storage."""


@dataclass(frozen=True)
class RuntimeStorageLayout:
    """Resolved mutable storage owned by one web-server process.

    Attributes:
        role: Declared server role: production, test, or custom.
        host: Configured bind host.
        port: Configured bind port.
        pid: Process identifier used in startup diagnostics.
        workspace: Root for conversations, checkpoints, and other runtime state.
        log_directory: Directory containing managed server logs.
        ledger_path: SQLite runtime-event ledger path.
        checkpoint_path: Conversation checkpoint directory.
        conversation_path: Persisted conversation directory.
        artifact_path: Full tool-output artifact directory.
        cache_directory: Runtime cache directory.
        local_auth_directory: Local web-auth token cache directory.
        credentials_path: Provider credential store path.
        legacy_credentials_path: Legacy provider-auth store path.
        config_directory: Test-isolated XDG configuration directory.
    """

    role: str
    host: str
    port: int
    pid: int
    workspace: Path
    log_directory: Path
    ledger_path: Path
    checkpoint_path: Path
    conversation_path: Path
    artifact_path: Path
    cache_directory: Path
    local_auth_directory: Path
    credentials_path: Path
    legacy_credentials_path: Path
    config_directory: Path

    @property
    def mutable_paths(self) -> tuple[Path, ...]:
        """Return all configured mutable paths used for isolation checks."""

        return (
            self.workspace,
            self.log_directory,
            self.ledger_path,
            self.checkpoint_path,
            self.conversation_path,
            self.artifact_path,
            self.cache_directory,
            self.local_auth_directory,
            self.credentials_path,
            self.legacy_credentials_path,
            self.config_directory,
        )

    @property
    def lease_path(self) -> Path:
        """Return the primary workspace lease path."""

        return self.workspace / ".runtime" / "server.lock"

    @property
    def lease_paths(self) -> tuple[Path, ...]:
        """Return lease files protecting the workspace and ledger.

        A separately overridden ledger can be shared even when workspaces differ,
        so it receives its own lease in addition to the workspace lease.
        """

        ledger_lease = self.ledger_path.with_name(
            f"{self.ledger_path.name}.server.lock"
        )
        if _is_within(ledger_lease, self.workspace):
            return (self.lease_path, ledger_lease)
        return tuple(sorted((self.lease_path, ledger_lease), key=str))

    def to_diagnostics(self) -> dict[str, str | int]:
        """Return privacy-safe startup diagnostics for this storage layout."""

        return {
            "server_role": self.role,
            "host": self.host,
            "port": self.port,
            "pid": self.pid,
            "workspace": str(self.workspace),
            "log_directory": str(self.log_directory),
            "runtime_event_ledger": str(self.ledger_path),
            "checkpoints": str(self.checkpoint_path),
            "conversations": str(self.conversation_path),
            "tool_artifacts": str(self.artifact_path),
            "cache_directory": str(self.cache_directory),
            "local_auth_directory": str(self.local_auth_directory),
            "provider_credentials": str(self.credentials_path),
            "legacy_provider_auth": str(self.legacy_credentials_path),
            "config_directory": str(self.config_directory),
        }


class RuntimeStorageLease:
    """Advisory process lease for a server's mutable workspace and ledger."""

    def __init__(self, layout: RuntimeStorageLayout) -> None:
        """Initialize an unacquired lease for ``layout``."""

        self.layout = layout
        self._files: list[IO[str]] = []

    def acquire(self) -> RuntimeStorageLease:
        """Acquire all storage leases or raise without retaining partial locks.

        Returns:
            This lease instance.

        Raises:
            RuntimeStorageOwnershipError: If another live process owns any path.
        """

        if self._files:
            return self

        try:
            for path in self.layout.lease_paths:
                self._files.append(self._acquire_path(path))
        except Exception:
            self.release()
            raise
        return self

    def release(self) -> None:
        """Release every acquired file lock, preserving diagnostics on disk."""

        while self._files:
            handle = self._files.pop()
            try:
                _unlock_file(handle)
            finally:
                handle.close()

    def __enter__(self) -> RuntimeStorageLease:
        """Acquire this lease for a context manager."""

        return self.acquire()

    def __exit__(self, *_exc_info: object) -> None:
        """Release this lease when leaving a context manager."""

        self.release()

    def _acquire_path(self, path: Path) -> IO[str]:
        """Acquire one advisory lock file and write owner diagnostics."""

        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+", encoding="utf-8")
        try:
            _lock_file(handle)
        except BlockingIOError as exc:
            handle.seek(0)
            owner = handle.read().strip() or "unknown owner"
            handle.close()
            raise RuntimeStorageOwnershipError(
                f"Mutable Penguin runtime storage is already owned: {path}. "
                f"Current owner: {owner}"
            ) from exc

        handle.seek(0)
        handle.truncate()
        json.dump(self.layout.to_diagnostics(), handle, sort_keys=True)
        handle.write("\n")
        handle.flush()
        os.fsync(handle.fileno())
        return handle


def resolve_runtime_storage(
    *,
    host: str,
    port: int,
    environ: Mapping[str, str] | None = None,
) -> RuntimeStorageLayout:
    """Resolve and validate mutable storage for a web-server invocation.

    Port 8080 is the supported test role and intentionally fails closed unless an
    explicit isolated ``PENGUIN_WORKSPACE`` is supplied. Test-role log and ledger
    overrides must also remain inside that workspace.

    Args:
        host: Configured bind host.
        port: Configured bind port.
        environ: Environment mapping. Defaults to ``os.environ``.

    Returns:
        Validated runtime storage layout.

    Raises:
        RuntimeStorageOwnershipError: If role or test isolation is unsafe.
    """

    env = os.environ if environ is None else environ
    role = _resolve_role(port=port, value=env.get("PENGUIN_SERVER_ROLE"))
    workspace_value = (env.get("PENGUIN_WORKSPACE") or "").strip()

    if role == "test" and not workspace_value:
        raise RuntimeStorageOwnershipError(
            "The 127.0.0.1:8080 test server requires an explicit isolated "
            "PENGUIN_WORKSPACE. Use "
            "`uv run python scripts/run_runtime_reliability_server.py`."
        )

    if workspace_value:
        workspace = _absolute_path(workspace_value)
    else:
        from penguin.config import get_workspace_root

        workspace = get_workspace_root().expanduser().resolve()

    log_file = (env.get("PENGUIN_WEB_LOG_FILE") or "").strip()
    log_directory_value = (env.get("PENGUIN_WEB_LOG_DIR") or "").strip()
    if log_file:
        log_directory = _absolute_path(log_file).parent
    elif log_directory_value:
        log_directory = _absolute_path(log_directory_value)
    else:
        log_directory = workspace / "server-logs"

    ledger_value = (env.get("PENGUIN_RUNTIME_EVENT_LEDGER_PATH") or "").strip()
    ledger_path = (
        _absolute_path(ledger_value)
        if ledger_value
        else workspace / "runtime_events" / "runtime_events.db"
    )
    cache_directory = _absolute_path(
        env.get("PENGUIN_CACHE_DIR")
        or env.get("XDG_CACHE_HOME")
        or Path.home() / ".cache" / "penguin"
    )
    local_auth_directory = _absolute_path(
        env.get("PENGUIN_LOCAL_AUTH_CACHE_DIR")
        or Path.home() / ".cache" / "penguin" / "auth"
    )
    credentials_path = _absolute_path(
        env.get("PENGUIN_PROVIDER_CREDENTIALS_STORE")
        or Path.home() / ".config" / "penguin" / "providers" / "credentials.json"
    )
    legacy_credentials_path = _absolute_path(
        env.get("PENGUIN_PROVIDER_AUTH_STORE")
        or Path.home() / ".config" / "penguin" / "provider_auth.json"
    )
    config_directory = _absolute_path(
        env.get("XDG_CONFIG_HOME") or Path.home() / ".config"
    )

    layout = RuntimeStorageLayout(
        role=role,
        host=host,
        port=port,
        pid=os.getpid(),
        workspace=workspace,
        log_directory=log_directory,
        ledger_path=ledger_path,
        checkpoint_path=workspace / "checkpoints",
        conversation_path=workspace / "conversations",
        artifact_path=workspace / "conversations" / "tool-results",
        cache_directory=cache_directory,
        local_auth_directory=local_auth_directory,
        credentials_path=credentials_path,
        legacy_credentials_path=legacy_credentials_path,
        config_directory=config_directory,
    )
    _validate_layout(layout)
    return layout


def build_isolated_test_environment(
    *,
    base_directory: str | Path | None = None,
    run_id: str | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, str]:
    """Build environment variables for one isolated 8080 reliability run.

    Args:
        base_directory: Parent directory for unique run workspaces. Defaults to
            ``~/.penguin/test-runtimes``.
        run_id: Optional deterministic run identifier, primarily for tests.
        environ: Base environment to copy. Defaults to ``os.environ``.

    Returns:
        A copied environment with every mutable web-server path isolated.
    """

    result = dict(os.environ if environ is None else environ)
    base = _absolute_path(base_directory or Path.home() / ".penguin" / "test-runtimes")
    identifier = run_id or _new_run_id()
    workspace = (base / identifier).resolve()

    result.update(
        {
            "HOST": TEST_SERVER_HOST,
            "PORT": str(TEST_SERVER_PORT),
            "PENGUIN_SERVER_ROLE": "test",
            "PENGUIN_RUNTIME_INSTANCE_ID": identifier,
            "PENGUIN_WORKSPACE": str(workspace),
            "PENGUIN_WEB_LOG_DIR": str(workspace / "server-logs"),
            "PENGUIN_RUNTIME_EVENT_LEDGER_PATH": str(
                workspace / "runtime_events" / "runtime_events.db"
            ),
            "PENGUIN_CACHE_DIR": str(workspace / "cache"),
            "PENGUIN_LOCAL_AUTH_CACHE_DIR": str(workspace / "auth"),
            "PENGUIN_PROVIDER_CREDENTIALS_STORE": str(
                workspace / "credentials" / "providers.json"
            ),
            "PENGUIN_PROVIDER_AUTH_STORE": str(
                workspace / "credentials" / "provider_auth.json"
            ),
            "XDG_CONFIG_HOME": str(workspace / "xdg-config"),
            "XDG_CACHE_HOME": str(workspace / "xdg-cache"),
        }
    )
    result.pop("PENGUIN_WEB_LOG_FILE", None)
    result.pop("PENGUIN_CONFIG_PATH", None)
    result.pop("PENGUIN_SETUP_ON_IMPORT", None)
    return result


def _resolve_role(*, port: int, value: str | None) -> str:
    """Resolve an explicit or port-derived server role."""

    if value:
        role = value.strip().lower()
        if role not in VALID_SERVER_ROLES:
            raise RuntimeStorageOwnershipError(
                "PENGUIN_SERVER_ROLE must be production, test, or custom; "
                f"received {value!r}."
            )
        if port == TEST_SERVER_PORT and role != "test":
            raise RuntimeStorageOwnershipError(
                "Port 8080 is reserved for test server role and cannot be declared "
                f"as {role!r}."
            )
        return role
    if port == TEST_SERVER_PORT:
        return "test"
    if port == PRODUCTION_SERVER_PORT:
        return "production"
    return "custom"


def _validate_layout(layout: RuntimeStorageLayout) -> None:
    """Validate role-specific host, port, and path ownership."""

    if layout.role != "test":
        return
    if layout.host != TEST_SERVER_HOST or layout.port != TEST_SERVER_PORT:
        raise RuntimeStorageOwnershipError(
            "The test server role must bind exactly to 127.0.0.1:8080."
        )

    labels = {
        "log directory": layout.log_directory,
        "ledger": layout.ledger_path,
        "checkpoint directory": layout.checkpoint_path,
        "conversation directory": layout.conversation_path,
        "artifact directory": layout.artifact_path,
        "cache directory": layout.cache_directory,
        "local auth directory": layout.local_auth_directory,
        "provider credentials": layout.credentials_path,
        "legacy provider auth": layout.legacy_credentials_path,
        "config directory": layout.config_directory,
    }
    for label, path in labels.items():
        if not _is_within(path, layout.workspace):
            raise RuntimeStorageOwnershipError(
                f"Test server {label} must remain inside PENGUIN_WORKSPACE "
                f"{layout.workspace}; received {path}."
            )


def _absolute_path(value: str | Path) -> Path:
    """Expand and resolve one configured path without creating it."""

    return Path(value).expanduser().resolve()


def _is_within(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is equal to or below ``parent``."""

    return path == parent or parent in path.parents


def _new_run_id() -> str:
    """Return a collision-resistant human-readable test-run identifier."""

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"runtime-reliability-{timestamp}-{os.getpid()}-{uuid.uuid4().hex[:8]}"


def _lock_file(handle: IO[str]) -> None:
    """Acquire a non-blocking exclusive advisory lock."""

    try:
        import fcntl
    except ImportError as exc:  # pragma: no cover - Penguin currently targets POSIX
        raise RuntimeStorageOwnershipError(
            "Runtime storage ownership locks require POSIX fcntl support."
        ) from exc
    fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)


def _unlock_file(handle: IO[str]) -> None:
    """Release an advisory lock held by ``handle``."""

    try:
        import fcntl
    except ImportError:  # pragma: no cover - see _lock_file
        return
    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
