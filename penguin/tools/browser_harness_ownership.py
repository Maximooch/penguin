"""Ownership persistence for browser-harness daemon identities."""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

try:  # POSIX in production/dev; fallback keeps tests portable.
    import fcntl
except ImportError:  # pragma: no cover - non-POSIX fallback
    fcntl = None  # type: ignore[assignment]

from penguin.config import WORKSPACE_PATH

__all__ = ["BrowserHarnessOwnershipStore"]


class BrowserHarnessOwnershipStore:
    """Persist Penguin-owned browser-harness daemon identities.

    Args:
        path: Optional JSON file path. Defaults to
            ``context/browser_harness/ownership.json`` under the workspace.
    """

    def __init__(self, path: str | None = None) -> None:
        self.path = Path(path).expanduser() if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        """Return the default ownership JSON path."""
        return Path(WORKSPACE_PATH) / "context" / "browser_harness" / "ownership.json"

    def _empty_payload(self) -> dict[str, Any]:
        return {"version": 1, "records": {}}

    @contextmanager
    def _locked(self) -> Iterator[None]:
        """Hold an exclusive advisory lock for read-modify-write updates."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        lock_path = self.path.with_suffix(f"{self.path.suffix}.lock")
        with lock_path.open("a+") as lock_file:
            if fcntl is not None:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
            try:
                yield
            finally:
                if fcntl is not None:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def read(self) -> dict[str, Any]:
        """Read and normalize the ownership payload."""
        if not self.path.exists():
            return self._empty_payload()
        try:
            payload = json.loads(self.path.read_text())
        except (json.JSONDecodeError, OSError):
            return self._empty_payload()
        if not isinstance(payload, dict):
            return self._empty_payload()
        records = payload.get("records")
        if not isinstance(records, dict):
            payload["records"] = {}
        payload.setdefault("version", 1)
        return payload

    def write(self, payload: dict[str, Any]) -> None:
        """Atomically write the ownership payload."""
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{self.path.name}.",
            suffix=".tmp",
            dir=str(self.path.parent),
        )
        try:
            with os.fdopen(fd, "w") as tmp:
                json.dump(payload, tmp, indent=2, sort_keys=True)
                tmp.write("\n")
            Path(tmp_name).replace(self.path)
        finally:
            tmp_path = Path(tmp_name)
            if tmp_path.exists():
                tmp_path.unlink()

    def get(self, bu_name: str) -> dict[str, Any] | None:
        """Return a copy of one ownership record, if present."""
        record = self.read().get("records", {}).get(bu_name)
        return dict(record) if isinstance(record, dict) else None

    def list_records(self) -> dict[str, dict[str, Any]]:
        """Return all ownership records keyed by ``BU_NAME``."""
        records = self.read().get("records", {})
        return {
            str(name): dict(record)
            for name, record in records.items()
            if isinstance(record, dict)
        }

    def is_owned(self, bu_name: str) -> bool:
        """Return whether ``bu_name`` has a Penguin-owned record."""
        record = self.get(bu_name)
        return bool(record and record.get("started_by_penguin"))

    def record_started(self, identity: dict[str, Any]) -> dict[str, Any]:
        """Create or update a Penguin ownership record.

        Args:
            identity: Browser-harness identity payload containing ``bu_name``.

        Returns:
            The persisted record copy.

        Raises:
            ValueError: If ``identity`` does not include a ``bu_name``.
        """
        bu_name = str(identity.get("bu_name") or "")
        if not bu_name:
            raise ValueError("Cannot persist browser ownership without bu_name")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        with self._locked():
            payload = self.read()
            records = payload.setdefault("records", {})
            existing = (
                records.get(bu_name, {})
                if isinstance(records.get(bu_name), dict)
                else {}
            )
            record = {
                **existing,
                "bu_name": bu_name,
                "backend": identity.get("backend", "browser-harness"),
                "session_id": identity.get("session_id"),
                "agent_id": identity.get("agent_id"),
                "skills_dir": identity.get("skills_dir"),
                "started_by_penguin": bool(identity.get("started_by_penguin")),
                "domain_skills_enabled": bool(identity.get("domain_skills_enabled")),
                "ownership_path": str(self.path),
                "updated_at": now,
            }
            record.setdefault("created_at", now)
            records[bu_name] = record
            self.write(payload)
            return dict(record)

    def remove(self, bu_name: str) -> dict[str, Any] | None:
        """Remove and return a Penguin ownership record, if present."""
        with self._locked():
            payload = self.read()
            records = payload.setdefault("records", {})
            record = records.pop(bu_name, None)
            if record is None:
                return None
            self.write(payload)
            return dict(record) if isinstance(record, dict) else None
