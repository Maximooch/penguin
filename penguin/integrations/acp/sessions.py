"""ACP workspace ownership and replay stored with native Penguin sessions."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from acp import RequestError
from acp.helpers import text_block
from acp.schema import ContentToolCallContent, SessionNotification, ToolCallProgress

__all__ = ["SessionRegistry"]


class SessionRegistry:
    """Use the core's transaction-safe session store without a second database."""

    def __init__(self, core: Any, allowed_roots: tuple[Path, ...]) -> None:
        manager = getattr(core, "conversation_manager", None)
        self.store = getattr(manager, "session_manager", None)
        self.allowed_roots = allowed_roots

    @property
    def available(self) -> bool:
        return self.store is not None

    def get(self, sid: str) -> Any:
        """Load only indexed, syntactically safe IDs; never interpolate paths."""
        if not self.available or not re.fullmatch(r"[A-Za-z0-9_-]+", sid):
            raise RequestError.invalid_params({"reason": "Unknown ACP session"})
        if sid not in self.store.session_index:
            raise RequestError.invalid_params({"reason": "Unknown ACP session"})
        previous = self.store.current_session
        try:
            session = self.store.load_session(sid)
        finally:
            self.store.current_session = previous
        if session is None or session.id != sid:
            raise RequestError.internal_error(
                {"reason": "Session could not be restored"}
            )
        return session

    def create(self, sid: str, cwd: Path) -> None:
        if not self.available:
            return
        session = self.get(sid)
        session.metadata["acp_workspace"] = str(cwd)
        session.metadata["acp_history"] = []
        self.save(session)

    def save(self, session: Any) -> None:
        if not self.store.save_session(session):
            raise RequestError.internal_error(
                {"reason": "Could not persist ACP session"}
            )

    def cwd(self, session: Any) -> Path | None:
        """Validate immutable ownership against currently authorized roots."""
        raw = session.metadata.get("acp_workspace")
        if not isinstance(raw, str):
            return None
        path = Path(raw)
        if not path.is_absolute():
            return None
        resolved = path.resolve()
        if str(resolved) != raw or not resolved.is_dir():
            return None
        if not any(resolved.is_relative_to(root) for root in self.allowed_roots):
            return None
        return resolved

    def record(self, sid: str, update: Any) -> None:
        """Append one update without rewriting the growing transcript."""
        self.append(sid, update.model_dump(by_alias=True, exclude_none=True))

    def append(self, sid: str, payload: dict[str, Any]) -> None:
        """Append a validated update or a child-targeted replay envelope."""
        if not self.available:
            return
        session = self.get(sid)
        path = self._journal_path(session)
        path.parent.mkdir(parents=True, exist_ok=True)
        if not path.exists():
            with path.open("x", encoding="utf-8") as output:
                for record in session.metadata.get("acp_history", []):
                    output.write(json.dumps(record) + "\n")
        with path.open("a", encoding="utf-8") as output:
            output.write(json.dumps(payload) + "\n")

    def checkpoint(self, sid: str) -> None:
        """Persist native model state once at the turn boundary."""
        if self.available:
            session = self.get(sid)
            if self._journal_path(session).exists():
                session.metadata.pop("acp_history", None)
            self.save(session)

    def _journal_path(self, session: Any) -> Path:
        base = self.store.base_path.resolve()
        path = base / "acp-history" / (session.id + ".jsonl")
        if self.cwd(session) is None or not path.resolve().is_relative_to(base):
            raise RequestError.invalid_params({"reason": "Invalid replay storage"})
        return path

    def _records(self, session: Any) -> list[dict[str, Any]]:
        path = self._journal_path(session)
        if not path.exists():
            return session.metadata.get("acp_history", [])
        records = []
        offset = 0
        with path.open("rb") as source:
            lines = source.readlines()
        for index, line in enumerate(lines):
            try:
                records.append(json.loads(line))
            except (ValueError, UnicodeError):
                if index != len(lines) - 1 or line.endswith(b"\n"):
                    raise RequestError.internal_error(
                        {"reason": "Invalid replay journal"}
                    ) from None
                # A crash may leave an incomplete final append. Keep all complete
                # records and remove the uncommitted tail before future appends.
                with path.open("r+b") as output:
                    output.truncate(offset)
            offset += len(line)
        return records

    def history(self, session: Any) -> list[Any]:
        """Validate stored updates before replay; fail rather than omit records."""
        try:
            updates = [
                item
                if "acp_target" in item
                else SessionNotification(session_id=session.id, update=item).update
                for item in self._records(session)
            ]
        except (TypeError, ValueError):
            raise RequestError.internal_error(
                {"reason": "Invalid ACP replay history"}
            ) from None
        pending: set[str] = set()
        background: set[str] = set()
        for update in updates:
            if isinstance(update, dict):
                continue
            if update.session_update not in {"tool_call", "tool_call_update"}:
                continue
            if (getattr(update, "field_meta", None) or {}).get("penguin_process"):
                background.add(update.tool_call_id)
            if update.status in {"completed", "failed"}:
                pending.discard(update.tool_call_id)
            else:
                pending.add(update.tool_call_id)
        for call_id in sorted(pending - background):
            failed = ToolCallProgress(
                session_update="tool_call_update",
                tool_call_id=call_id,
                status="failed",
                content=[
                    ContentToolCallContent(
                        type="content",
                        content=text_block(
                            "Connection ended before this tool reported completion."
                        ),
                    )
                ],
            )
            updates.append(failed)
            self.record(session.id, failed)
        return updates
