"""Lightweight telemetry collection for multi-agent coordination."""

from __future__ import annotations

import asyncio
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any, DefaultDict, Dict, Optional

from penguin.utils.events import EventBus


@dataclass
class MessageStats:
    total: int = 0
    by_type: DefaultDict[str, int] = field(default_factory=lambda: defaultdict(int))
    by_channel: DefaultDict[str, int] = field(default_factory=lambda: defaultdict(int))
    last_message_at: Optional[str] = None


@dataclass
class AgentStats(MessageStats):
    sent: int = 0
    received: int = 0


class TelemetryCollector:
    """Aggregate runtime telemetry for multi-agent workflows."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.message_stats: MessageStats = MessageStats()
        self.agent_stats: DefaultDict[str, AgentStats] = defaultdict(AgentStats)
        self.task_stats: DefaultDict[str, int] = defaultdict(int)
        self.room_activity: DefaultDict[str, int] = defaultdict(int)
        self._bus = EventBus.get_instance()
        self._bus.subscribe("bus.message", self._on_bus_message)

    async def _on_bus_message(self, data: Dict[str, Any]) -> None:
        async with self._lock:
            channel = data.get("channel") or "default"
            msg_type = data.get("message_type") or "message"
            sender = data.get("sender") or data.get("agent_id")
            recipient = data.get("recipient")

            self.message_stats.total += 1
            self.message_stats.by_type[msg_type] += 1
            self.message_stats.by_channel[channel] += 1
            if channel:
                self.room_activity[channel] += 1

            timestamp = data.get("timestamp")

            if sender:
                stats = self.agent_stats[sender]
                stats.sent += 1
                stats.total += 1
                stats.by_type[msg_type] += 1
                stats.by_channel[channel] += 1
                stats.last_message_at = timestamp

            if recipient:
                stats = self.agent_stats[recipient]
                stats.received += 1
                stats.total += 1
                stats.by_type[msg_type] += 1
                stats.by_channel[channel] += 1
                stats.last_message_at = timestamp

            self.message_stats.last_message_at = timestamp

    async def record_task(self, agent_id: str, task_name: Optional[str] = None) -> None:
        key = agent_id or "unknown"
        async with self._lock:
            self.task_stats[key] += 1
            if task_name:
                composite = f"{key}:{task_name}"
                self.task_stats[composite] += 1

    async def snapshot(self) -> Dict[str, Any]:
        async with self._lock:
            message_summary = {
                "total": self.message_stats.total,
                "by_type": dict(self.message_stats.by_type),
                "by_channel": dict(self.message_stats.by_channel),
            }
            agent_summary = {
                agent: {
                    "total": stats.total,
                    "sent": stats.sent,
                    "received": stats.received,
                    "by_type": dict(stats.by_type),
                    "by_channel": dict(stats.by_channel),
                }
                for agent, stats in self.agent_stats.items()
            }
            task_summary = dict(self.task_stats)
        return {
            "messages": message_summary,
            "agents": agent_summary,
            "tasks": task_summary,
            "rooms": dict(self.room_activity),
        }


def ensure_telemetry(core: Any) -> TelemetryCollector:
    if not hasattr(core, "telemetry") or getattr(core, "telemetry", None) is None:
        core.telemetry = TelemetryCollector()
    return core.telemetry
