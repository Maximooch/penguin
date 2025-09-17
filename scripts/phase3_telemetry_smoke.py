"""Phase 3 telemetry smoke test.

Exercises the telemetry collector with synthetic bus messages and task records to
ensure channel/agent summaries look sensible.

Run with:
    uv run python scripts/phase3_telemetry_smoke.py
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime

from penguin.telemetry.collector import TelemetryCollector


def make_message(**kwargs):
    payload = {
        "sender": kwargs.get("sender"),
        "recipient": kwargs.get("recipient"),
        "channel": kwargs.get("channel", "dev-room"),
        "message_type": kwargs.get("message_type", "message"),
        "metadata": kwargs.get("metadata", {}),
        "timestamp": datetime.utcnow().isoformat(),
    }
    return payload


async def main() -> None:
    telemetry = TelemetryCollector()

    # Simulate room conversation between planner and implementer
    await telemetry._on_bus_message(make_message(sender="planner", recipient="implementer"))
    await telemetry._on_bus_message(make_message(sender="implementer", recipient="planner"))
    await telemetry._on_bus_message(make_message(sender="qa", recipient="planner", channel="qa-room"))

    # Record a few tasks per agent
    await telemetry.record_task("planner", task_name="bugfix")
    await telemetry.record_task("planner", task_name="bugfix")
    await telemetry.record_task("qa", task_name="regression")

    summary = await telemetry.snapshot()
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    asyncio.run(main())
