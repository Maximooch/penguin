"""Typed request and response schemas for Penguin's web API."""

from .chat import ChatContinuationRequest, ChatMessageRequest, ChatTerminalResponse
from .session_goal import (
    SessionGoalRunRequest,
    SessionGoalUpdateRequest,
    SessionGoalUserStatus,
)

__all__ = [
    "ChatContinuationRequest",
    "ChatMessageRequest",
    "ChatTerminalResponse",
    "SessionGoalRunRequest",
    "SessionGoalUpdateRequest",
    "SessionGoalUserStatus",
]
