"""Strict request schemas for session-goal HTTP endpoints."""

from __future__ import annotations

# Keep typing aliases because Pydantic 1.x evaluates model fields on Python 3.9.
# ruff: noqa
from enum import Enum
from typing import Any, Dict, Optional

from pydantic import BaseModel, StrictBool, conint, constr

from penguin.core_runtime.session_goals import (
    MAX_GOAL_OBJECTIVE_CHARS,
)

__all__ = [
    "SessionGoalRunRequest",
    "SessionGoalUpdateRequest",
    "SessionGoalUserStatus",
]

StrictGoalTokenBudget = conint(
    strict=True,
    gt=0,
)
StrictGoalMaxIterations = conint(
    strict=True,
    gt=0,
)
StrictGoalTimeoutSeconds = conint(
    strict=True,
    gt=0,
)
StrictGoalObjective = constr(
    strict=True,
    strip_whitespace=True,
    min_length=1,
    max_length=MAX_GOAL_OBJECTIVE_CHARS,
)
StrictGoalDisplayCommand = constr(
    strict=True,
    min_length=1,
    max_length=MAX_GOAL_OBJECTIVE_CHARS + 64,
)
StrictGoalClientMessageID = constr(
    strict=True,
    strip_whitespace=True,
    min_length=1,
    max_length=256,
)
StrictGoalDirectory = constr(
    strict=True,
    min_length=1,
    max_length=4_096,
)


class SessionGoalUserStatus(str, Enum):
    """User-controlled, non-terminal goal status transitions."""

    ACTIVE = "active"
    PAUSED = "paused"


class _StrictRequest(BaseModel):
    class Config:
        extra = "forbid"


class SessionGoalUpdateRequest(_StrictRequest):
    """Create/replace a goal or perform a user-controlled state transition."""

    objective: Optional[StrictGoalObjective] = None
    status: Optional[SessionGoalUserStatus] = None
    replace: StrictBool = False
    token_budget: Optional[StrictGoalTokenBudget] = None
    metadata: Optional[Dict[str, Any]] = None
    display_command: Optional[StrictGoalDisplayCommand] = None
    client_message_id: Optional[StrictGoalClientMessageID] = None
    client_part_id: Optional[StrictGoalClientMessageID] = None


class SessionGoalRunRequest(_StrictRequest):
    """Optional user-configured limits and scope for goal execution."""

    max_iterations: Optional[StrictGoalMaxIterations] = None
    timeout_seconds: Optional[StrictGoalTimeoutSeconds] = None
    directory: Optional[StrictGoalDirectory] = None
