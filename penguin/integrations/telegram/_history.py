"""Bounded in-memory context for Telegram group lanes."""

from __future__ import annotations

from collections import OrderedDict, deque


class GroupHistory:
    """A small LRU of independently bounded group/topic histories."""

    def __init__(self, *, max_lanes: int = 256, max_messages: int = 200) -> None:
        self.max_lanes = max_lanes
        self.max_messages = max_messages
        self._lanes: OrderedDict[str, deque[str]] = OrderedDict()

    def append(self, lane_key: str, text: str) -> None:
        lane = self._lanes.pop(lane_key, None)
        if lane is None:
            lane = deque(maxlen=self.max_messages)
        lane.append(text)
        self._lanes[lane_key] = lane
        while len(self._lanes) > self.max_lanes:
            self._lanes.popitem(last=False)

    def recent(self, lane_key: str, limit: int) -> list[str]:
        lane = self._lanes.pop(lane_key, None)
        if lane is None:
            return []
        self._lanes[lane_key] = lane
        if limit <= 0:
            return []
        return list(lane)[-limit:]

    def __len__(self) -> int:
        return len(self._lanes)


__all__ = ["GroupHistory"]
