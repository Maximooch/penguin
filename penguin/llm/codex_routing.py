"""Turn-scoped Codex routing state, never persisted with conversations."""

from contextvars import ContextVar
from dataclasses import dataclass

__all__ = ["CURRENT_CODEX_ROUTING", "CodexRouting"]


@dataclass
class CodexRouting:
    """Affinity and opaque routing token owned by one engine turn."""

    session_id: str
    owner: str | None = None
    turn_state: str | None = None

    def headers(self, owner: str) -> dict[str, str]:
        """Clear opaque state when credentials change; return request headers."""
        if self.owner != owner:
            self.owner = owner
            self.turn_state = None
        headers = {"session-id": self.session_id}
        if self.turn_state:
            headers["x-codex-turn-state"] = self.turn_state
        return headers

    def capture(self, value: str | None) -> None:
        """Remember the first valid routing token, without logging it."""
        if not self.turn_state and value and len(value) <= 8192:
            if all(32 <= ord(char) < 127 for char in value):
                self.turn_state = value


CURRENT_CODEX_ROUTING: ContextVar[CodexRouting | None] = ContextVar(
    "penguin_codex_routing", default=None
)
