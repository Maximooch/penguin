"""Immutable startup capability policy for runtime tool access."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping

TOOL_ALLOWLIST_ENV = "PENGUIN_TOOL_ALLOWLIST_JSON"
_DENIAL_REASON = "Tool is not enabled by the startup capability policy."


@dataclass(frozen=True)
class ToolCapabilityPolicy:
    """Construction-time tool allowlist captured from the process environment."""

    allowed_names: frozenset[str] | None

    @classmethod
    def from_environment(
        cls, environment: Mapping[str, str] | None = None
    ) -> ToolCapabilityPolicy:
        """Capture the startup policy; invalid configured values fail closed."""
        source = os.environ if environment is None else environment
        if TOOL_ALLOWLIST_ENV not in source:
            return cls(allowed_names=None)

        raw_value = source.get(TOOL_ALLOWLIST_ENV, "")
        try:
            decoded = json.loads(raw_value)
        except (TypeError, json.JSONDecodeError):
            return cls(allowed_names=frozenset())

        if not isinstance(decoded, list) or not decoded:
            return cls(allowed_names=frozenset())
        if any(not isinstance(name, str) or not name.strip() for name in decoded):
            return cls(allowed_names=frozenset())
        return cls(allowed_names=frozenset(decoded))

    @property
    def restricted(self) -> bool:
        """Return whether an explicit startup boundary is active."""
        return self.allowed_names is not None

    def allows(self, requested_name: str, canonical_name: str) -> bool:
        """Allow exact canonical capabilities; aliases cannot grant themselves."""
        if self.allowed_names is None:
            return True
        return canonical_name in self.allowed_names

    def denial_payload(self, requested_name: str) -> dict[str, str]:
        """Return a stable, input-free denial payload."""
        return {
            "error": "tool_capability_denied",
            "tool": requested_name,
            "reason": _DENIAL_REASON,
        }

    def denial_json(self, requested_name: str) -> str:
        """Serialize a denial without including arguments or other secret data."""
        return json.dumps(self.denial_payload(requested_name))

    def require(self, requested_name: str, canonical_name: str) -> None:
        """Raise when direct function lookup would bypass the boundary."""
        if not self.allows(requested_name, canonical_name):
            raise PermissionError(self.denial_json(requested_name))


__all__ = ["TOOL_ALLOWLIST_ENV", "ToolCapabilityPolicy"]
