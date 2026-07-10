"""Typed request and response schemas for Penguin's web API."""

from .chat import ChatContinuationRequest, ChatMessageRequest, ChatTerminalResponse

__all__ = [
    "ChatContinuationRequest",
    "ChatMessageRequest",
    "ChatTerminalResponse",
]
