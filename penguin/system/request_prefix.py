"""Content-free diagnostics for request-prefix stability."""

from dataclasses import dataclass, field
from typing import Any

from penguin.llm.contracts import stable_payload_hash

__all__ = ["RequestPrefix"]


@dataclass
class RequestPrefix:
    """Compare ordered message boundaries and tool definitions within a turn."""

    messages: list[str] = field(default_factory=list)
    tools: str | None = None

    def compare(self, messages: list[dict[str, Any]], tools: Any) -> dict[str, Any]:
        """Return counts and divergence location without retaining prompt content."""
        hashes = [stable_payload_hash(message) for message in messages]
        tools_hash = stable_payload_hash(tools)
        common = 0
        for old, new in zip(self.messages, hashes):
            if old != new:
                break
            common += 1
        result = {
            "previous_items": len(self.messages),
            "current_items": len(hashes),
            "common_items": common,
            "first_changed_item": common if common < len(self.messages) else None,
            "tools_changed": self.tools is not None and self.tools != tools_hash,
        }
        self.messages, self.tools = hashes, tools_hash
        return result
