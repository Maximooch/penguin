"""Runtime job records for project-scoped execution attempts."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Dict, Optional


RUNTIME_JOB_RESULT_JSON_LIMIT = 64 * 1024
RUNTIME_JOB_RESULT_SUMMARY_LIMIT = 4 * 1024
RUNTIME_JOB_ERROR_LIMIT = 16 * 1024

TERMINAL_RUNTIME_JOB_STATUSES = {"completed", "failed", "cancelled"}


@dataclass
class RuntimeJobRecord:
    """Durable runtime job record stored with project/task state."""

    job_id: str
    kind: str
    status: str
    started_at: str
    updated_at: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    project_id: Optional[str] = None
    task_id: Optional[str] = None
    session_id: Optional[str] = None
    finished_at: Optional[str] = None
    cancel_requested: bool = False
    cancel_reason: Optional[str] = None
    result_summary: Optional[str] = None
    result_json: Optional[str] = None
    error: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def terminal(self) -> bool:
        """Return whether the record is terminal."""
        return self.status in TERMINAL_RUNTIME_JOB_STATUSES

    def to_dict(self) -> Dict[str, Any]:
        """Return a JSON-serializable dictionary."""
        result = _decode_json(self.result_json)
        return {
            "job_id": self.job_id,
            "kind": self.kind,
            "status": self.status,
            "project_id": self.project_id,
            "task_id": self.task_id,
            "session_id": self.session_id,
            "started_at": self.started_at,
            "updated_at": self.updated_at,
            "finished_at": self.finished_at,
            "cancel_requested": self.cancel_requested,
            "cancel_reason": self.cancel_reason,
            "result_summary": self.result_summary,
            "result": result,
            "error": self.error,
            "metadata": dict(self.metadata or {}),
            "durable": True,
        }


def build_runtime_job_record(
    *,
    job_id: str,
    kind: str,
    status: str,
    project_id: Optional[str] = None,
    task_id: Optional[str] = None,
    session_id: Optional[str] = None,
    started_at: Optional[str] = None,
    updated_at: Optional[str] = None,
    finished_at: Optional[str] = None,
    cancel_requested: bool = False,
    cancel_reason: Optional[str] = None,
    result: Optional[Any] = None,
    result_summary: Optional[str] = None,
    error: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> RuntimeJobRecord:
    """Build a durable runtime job record with capped result/error fields."""
    now = datetime.utcnow().isoformat()
    encoded_result = encode_result_json(result)
    return RuntimeJobRecord(
        job_id=job_id,
        kind=kind,
        status=status,
        project_id=project_id,
        task_id=task_id,
        session_id=session_id,
        started_at=started_at or now,
        updated_at=updated_at or now,
        finished_at=finished_at,
        cancel_requested=cancel_requested,
        cancel_reason=_truncate(cancel_reason, RUNTIME_JOB_ERROR_LIMIT),
        result_summary=_truncate(
            result_summary if result_summary is not None else summarize_result(result),
            RUNTIME_JOB_RESULT_SUMMARY_LIMIT,
        ),
        result_json=encoded_result,
        error=_truncate(error, RUNTIME_JOB_ERROR_LIMIT),
        metadata=dict(metadata or {}),
    )


def summarize_result(result: Optional[Any]) -> Optional[str]:
    """Return a compact summary for a runtime result payload."""
    if result is None:
        return None
    if isinstance(result, dict):
        for key in ("message", "summary", "status", "completion_type"):
            value = result.get(key)
            if value:
                return _truncate(str(value), RUNTIME_JOB_RESULT_SUMMARY_LIMIT)
        if "result" in result:
            return _truncate(str(result["result"]), RUNTIME_JOB_RESULT_SUMMARY_LIMIT)
    return _truncate(str(result), RUNTIME_JOB_RESULT_SUMMARY_LIMIT)


def encode_result_json(result: Optional[Any]) -> Optional[str]:
    """Encode a JSON result payload with a conservative size cap."""
    if result is None:
        return None
    try:
        encoded = json.dumps(result, default=str)
    except (TypeError, ValueError):
        encoded = json.dumps({"repr": str(result)})
    if len(encoded) > RUNTIME_JOB_RESULT_JSON_LIMIT:
        return json.dumps(
            {
                "truncated": True,
                "limit": RUNTIME_JOB_RESULT_JSON_LIMIT,
                "preview": encoded[:RUNTIME_JOB_RESULT_JSON_LIMIT],
            }
        )
    return encoded


def _decode_json(value: Optional[str]) -> Optional[Any]:
    if not value:
        return None
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return {"raw": value}


def _truncate(value: Optional[str], limit: int) -> Optional[str]:
    if value is None:
        return None
    if len(value) <= limit:
        return value
    return value[:limit] + "…"


__all__ = [
    "RuntimeJobRecord",
    "TERMINAL_RUNTIME_JOB_STATUSES",
    "build_runtime_job_record",
    "encode_result_json",
    "summarize_result",
]
