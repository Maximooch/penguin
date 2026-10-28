"""ACP workspace ownership and replay stored with native Penguin sessions."""

from __future__ import annotations

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
        session = self.store.load_session(sid)
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
        """Keep exactly the visible protocol history, including tool ordering."""
        if not self.available:
            return
        session = self.get(sid)
        history = session.metadata.setdefault("acp_history", [])
        history.append(update.model_dump(by_alias=True, exclude_none=True))
        self.save(session)

    def history(self, session: Any) -> list[Any]:
        """Validate stored updates before replay; fail rather than omit records."""
        try:
            updates = [
                SessionNotification(session_id=session.id, update=item).update
                for item in session.metadata.get("acp_history", [])
            ]
        except (TypeError, ValueError):
            raise RequestError.internal_error(
                {"reason": "Invalid ACP replay history"}
            ) from None
        pending: set[str] = set()
        for update in updates:
            if update.session_update not in {"tool_call", "tool_call_update"}:
                continue
            if update.status in {"completed", "failed"}:
                pending.discard(update.tool_call_id)
            else:
                pending.add(update.tool_call_id)
        for call_id in sorted(pending):
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
            session.metadata["acp_history"].append(
                failed.model_dump(by_alias=True, exclude_none=True)
            )
        if pending:
            self.save(session)
        return updates
