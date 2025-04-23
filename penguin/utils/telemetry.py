"""penguin.utils.telemetry

Light‑weight *placeholder* instrumentation layer.

Purpose
-------
Provide a single import point inside Penguin so we can start wiring up
latency / token counters immediately, while keeping the external
surface tiny.  A later phase can replace the guts with OpenTelemetry or
another backend without touching call‑sites.

Design
~~~~~~
* **Singleton** Telemetry object stores in‑process aggregates.
* Thread‑safe via a simple `threading.Lock` (adequate for CPython GIL; we
  avoid external deps).
* Two public helper APIs:

    Telemetry.get().record_tokens(prompt, completion)
    with telemetry.span("llm"):
        await api_client.get_response(...)

* `snapshot()` returns a dict suitable for printing / JSON export.
* Controlled via env‑var PENGUN_TELEMETRY=off if users want zero
  overhead.
"""

from __future__ import annotations

import os
import threading
import time
from contextlib import contextmanager
from typing import Dict, List
import logging

logger = logging.getLogger(__name__)

_TELEMETRY_ENABLED = os.getenv("PENGUIN_TELEMETRY", "on").lower() not in {"0", "false", "off"}


class _SafeList(List[float]):
    """Thread‑safe list append; trivial wrapper around list."""

    _lock = threading.Lock()

    def append(self, value: float) -> None:  # type: ignore[override]
        with self._lock:
            super().append(value)


class Telemetry:
    """Singleton container for simple counters / timers."""

    _instance: "Telemetry" | None = None
    _lock = threading.Lock()

    def __init__(self) -> None:  # noqa: D401
        if Telemetry._instance is not None:
            raise RuntimeError("Telemetry is a singleton; use Telemetry.get()")

        self.metrics: Dict[str, float | list] = {
            "tokens_prompt": 0.0,
            "tokens_completion": 0.0,
            "llm_latency_sec": _SafeList(),  # type: ignore
            "tool_latency_sec": _SafeList(),  # type: ignore
            "errors": 0.0,
        }

    # ------------------------------------------------------------------
    # Singleton accessor
    # ------------------------------------------------------------------

    @classmethod
    def get(cls) -> "Telemetry":
        if not _TELEMETRY_ENABLED:
            # Return a dummy object with no‑op methods
            return _NullTelemetry.get()
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance  # type: ignore[return-value]

    # ------------------------------------------------------------------
    # Recording helpers
    # ------------------------------------------------------------------

    def record_tokens(self, prompt: int, completion: int) -> None:
        self.metrics["tokens_prompt"] += float(prompt)
        self.metrics["tokens_completion"] += float(completion)

    def record_latency(self, kind: str, duration: float) -> None:
        if kind == "llm":
            self.metrics["llm_latency_sec"].append(duration)  # type: ignore[arg-type]
        elif kind == "tool":
            self.metrics["tool_latency_sec"].append(duration)  # type: ignore[arg-type]
        else:
            logger.debug("Unknown latency kind %s", kind)

    def record_error(self) -> None:
        self.metrics["errors"] += 1.0

    # ------------------------------------------------------------------
    # Reporting helpers
    # ------------------------------------------------------------------

    def snapshot(self) -> Dict[str, float]:
        """Return a shallow copy with computed averages."""
        prompt = self.metrics["tokens_prompt"]  # type: ignore[assignment]
        completion = self.metrics["tokens_completion"]  # type: ignore[assignment]
        llm_lat = self.metrics["llm_latency_sec"]  # type: ignore[assignment]
        tool_lat = self.metrics["tool_latency_sec"]  # type: ignore[assignment]
        errors = self.metrics["errors"]  # type: ignore[assignment]

        def _avg(lst: List[float]) -> float:
            return sum(lst) / len(lst) if lst else 0.0

        return {
            "tokens_prompt": prompt,
            "tokens_completion": completion,
            "tokens_total": prompt + completion,
            "llm_latency_avg": _avg(llm_lat),
            "tool_latency_avg": _avg(tool_lat),
            "errors": errors,
        }


class _NullTelemetry(Telemetry):
    """No‑op variant when telemetry disabled."""

    _null_instance: "_NullTelemetry" | None = None

    def __init__(self):
        # Do **not** call super().__init__() because that sets real metrics.
        pass

    @classmethod
    def get(cls) -> "_NullTelemetry":  # type: ignore[override]
        with Telemetry._lock:
            if cls._null_instance is None:
                cls._null_instance = cls()
            return cls._null_instance

    # All recording methods become no‑ops
    def record_tokens(self, prompt: int, completion: int) -> None:  # noqa: D401
        return

    def record_latency(self, kind: str, duration: float) -> None:  # noqa: D401
        return

    def record_error(self) -> None:  # noqa: D401
        return

    def snapshot(self) -> Dict[str, float]:  # type: ignore[override]
        return {}


# ----------------------------------------------------------------------
# Convenience context‑manager for measuring latency
# ----------------------------------------------------------------------

@contextmanager
def span(kind: str):
    """Context‑manager that records elapsed time on exit.

    Usage::

        with span("llm"):
            assistant_response = await api_client.get_response(...)
    """
    start = time.perf_counter()
    try:
        yield
    except Exception:
        Telemetry.get().record_error()
        raise
    finally:
        Telemetry.get().record_latency(kind, time.perf_counter() - start) 