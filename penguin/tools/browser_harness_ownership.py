"""Ownership persistence for browser-harness daemon identities."""

from __future__ import annotations

import datetime
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional

from penguin.config import WORKSPACE_PATH


class BrowserHarnessOwnershipStore:
    """Persist Penguin-owned browser-harness daemon identities."""

    def __init__(self, path: Optional[str] = None):
        self.path = Path(path).expanduser() if path else self.default_path()

    @staticmethod
    def default_path() -> Path:
        return Path(WORKSPACE_PATH) / "context" / "browser_harness" / "ownership.json"

    def _empty_payload(self) -> Dict[str, Any]:
        return {"version": 1, "records": {}}

    def read(self) -> Dict[str, Any]:
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

    def write(self, payload: Dict[str, Any]) -> None:
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

    def get(self, bu_name: str) -> Optional[Dict[str, Any]]:
        record = self.read().get("records", {}).get(bu_name)
        return dict(record) if isinstance(record, dict) else None

    def list(self) -> Dict[str, Dict[str, Any]]:
        records = self.read().get("records", {})
        return {
            str(name): dict(record)
            for name, record in records.items()
            if isinstance(record, dict)
        }

    def is_owned(self, bu_name: str) -> bool:
        record = self.get(bu_name)
        return bool(record and record.get("started_by_penguin"))

    def record_started(self, identity: Dict[str, Any]) -> Dict[str, Any]:
        bu_name = str(identity.get("bu_name") or "")
        if not bu_name:
            raise ValueError("Cannot persist browser ownership without bu_name")

        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
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

    def remove(self, bu_name: str) -> Optional[Dict[str, Any]]:
        payload = self.read()
        records = payload.setdefault("records", {})
        if not isinstance(records, dict):
            return None
        record = records.pop(bu_name, None)
        self.write(payload)
        return dict(record) if isinstance(record, dict) else None
