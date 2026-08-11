"""Telegram network error and retry policy helpers."""

from __future__ import annotations

import random
from dataclasses import dataclass
from datetime import timedelta
from typing import Any, Callable

__all__ = ["TelegramFailure", "classify_failure", "retry_delay"]


@dataclass(frozen=True)
class TelegramFailure:
    """Sanitized delivery failure classification."""

    error_class: str
    message: str
    retryable: bool
    retry_after: float | None = None
    polling_conflict: bool = False


def classify_failure(exc: BaseException) -> TelegramFailure:
    """Classify PTB errors without importing the optional dependency."""

    name = type(exc).__name__
    message = str(exc)[:1000]
    lowered = name.casefold()
    retry_after = _seconds(getattr(exc, "retry_after", None))
    if retry_after is not None or lowered == "retryafter":
        return TelegramFailure(name, message, True, retry_after=retry_after)
    if lowered in {
        "timedout",
        "timeouterror",
        "networkerror",
        "connecterror",
        "readerror",
    }:
        return TelegramFailure(name, message, True)
    if lowered == "conflict":
        return TelegramFailure(name, message, False, polling_conflict=True)
    if lowered in {"forbidden", "invalidtoken", "badrequest"}:
        return TelegramFailure(name, message, False)
    return TelegramFailure(name, message, False)


def retry_delay(
    attempt: int,
    *,
    base_seconds: float,
    max_seconds: float,
    retry_after: float | None = None,
    random_value: Callable[[], float] = random.random,
) -> float:
    """Return bounded exponential backoff with equal jitter."""

    if attempt < 1:
        raise ValueError("attempt must be positive")
    if base_seconds <= 0 or max_seconds < base_seconds:
        raise ValueError("invalid retry bounds")
    if retry_after is not None:
        return min(max_seconds, max(0.0, retry_after))
    ceiling = min(max_seconds, base_seconds * (2 ** (attempt - 1)))
    jitter = min(1.0, max(0.0, float(random_value())))
    return ceiling / 2 + (ceiling / 2 * jitter)


def _seconds(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, timedelta):
        return max(0.0, value.total_seconds())
    try:
        return max(0.0, float(value))
    except (TypeError, ValueError):
        return None
