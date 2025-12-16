from __future__ import annotations
import os
from typing import Any, Optional


# -----------------------------------------------------------------------------
# Numeric defaults (fallbacks)
# -----------------------------------------------------------------------------

DEFAULT_ENGINE_MAX_ITERATIONS = 5000

# Keep a hard cap for the autonomous explorer loop to prevent runaway tool-spam.
# This is NOT tied to engine.max_iterations_default on purpose.
DELEGATE_EXPLORE_TASK_MAX_ITERATIONS_CAP = int(
    os.getenv("PENGUIN_DELEGATE_EXPLORE_MAX_ITERATIONS_CAP", "100")
)

DEFAULT_MAX_HISTORY_TOKENS = 200_000
DEFAULT_CONTEXT_WINDOW_EMERGENCY_FALLBACK_TOKENS = 100_000

# Used when a provider adapter needs a last-resort output token cap.
DEFAULT_MAX_OUTPUT_TOKENS = 8192

PYDOLL_SLEEP_SECONDS = float(os.getenv("PENGUIN_PYDOLL_SLEEP_SECONDS", "0.05"))

# Small async sleep used to yield control / enforce UI message boundaries.
UI_ASYNC_SLEEP_SECONDS = float(os.getenv("PENGUIN_UI_ASYNC_SLEEP_SECONDS", "0.05"))

# Context window budgeting
CONTEXT_UNCATEGORIZED_BUDGET_FRACTION = float(
    os.getenv("PENGUIN_CONTEXT_UNCATEGORIZED_BUDGET_FRACTION", "0.05")
)

# Maximum number of images to retain in context window before trimming oldest
DEFAULT_MAX_CONTEXT_IMAGES = int(os.getenv("PENGUIN_MAX_CONTEXT_IMAGES", "5"))

# Session manager defaults
DEFAULT_SESSION_LIST_LIMIT = int(os.getenv("PENGUIN_SESSION_LIST_LIMIT", "100000"))

# Session manager message limits
DEFAULT_MAX_MESSAGES_PER_SESSION = int(os.getenv("PENGUIN_MAX_MESSAGES_PER_SESSION", "5000"))
DEFAULT_MAX_TOTAL_MESSAGES = int(os.getenv("PENGUIN_MAX_TOTAL_MESSAGES", "100000"))

# Memory/chunk size limits
DEFAULT_MAX_CHUNK_SIZE = int(os.getenv("PENGUIN_MAX_CHUNK_SIZE", "8000"))

# File size threshold for skipping in delegate explore
DEFAULT_LARGE_FILE_THRESHOLD_BYTES = int(os.getenv("PENGUIN_LARGE_FILE_THRESHOLD_BYTES", "100000"))

# Web/API server defaults
DEFAULT_WEB_PORT = int(os.getenv("PENGUIN_WEB_PORT", "8000"))

# Patch truncation limit for webhooks
DEFAULT_PATCH_TRUNCATION_LIMIT = int(os.getenv("PENGUIN_PATCH_TRUNCATION_LIMIT", "5000"))


def _coerce_int(value: Any, default: int) -> int:
    """Safely coerce a value to int, returning default on failure."""
    try:
        return int(value)
    except Exception:
        return default


def get_engine_max_iterations_default() -> int:
    """Return the canonical default max-iterations budget.

    Source of truth:
      - config key: engine.max_iterations_default
      - fallback: DEFAULT_ENGINE_MAX_ITERATIONS
    """
    try:
        from penguin.config import get_config_value

        configured = get_config_value("engine.max_iterations_default", None)
        if configured is not None:
            return _coerce_int(configured, DEFAULT_ENGINE_MAX_ITERATIONS)
    except Exception:
        pass

    return DEFAULT_ENGINE_MAX_ITERATIONS


def get_default_max_history_tokens() -> int:
    """Return the default max history tokens budget.

    This should generally be derived from model context window, but several call
    paths still need a stable fallback.
    """
    return _coerce_int(os.getenv("PENGUIN_MAX_HISTORY_TOKENS", DEFAULT_MAX_HISTORY_TOKENS), DEFAULT_MAX_HISTORY_TOKENS)


def get_default_context_window_emergency_fallback_tokens() -> int:
    return _coerce_int(
        os.getenv(
            "PENGUIN_CONTEXT_WINDOW_EMERGENCY_FALLBACK_TOKENS",
            DEFAULT_CONTEXT_WINDOW_EMERGENCY_FALLBACK_TOKENS,
        ),
        DEFAULT_CONTEXT_WINDOW_EMERGENCY_FALLBACK_TOKENS,
    )


def get_default_max_output_tokens() -> int:
    return _coerce_int(
        os.getenv("PENGUIN_DEFAULT_MAX_OUTPUT_TOKENS", DEFAULT_MAX_OUTPUT_TOKENS),
        DEFAULT_MAX_OUTPUT_TOKENS,
    )
