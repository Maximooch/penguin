"""The utils EventBus delivers to bound-method subscribers (SM-31)."""

from __future__ import annotations

import gc
from typing import Any

import pytest

from penguin.utils.events import EventBus


class _Subscriber:
    def __init__(self) -> None:
        self.seen: list[Any] = []

    def on_event(self, data: Any) -> None:
        self.seen.append(data)

    async def on_event_async(self, data: Any) -> None:
        self.seen.append(data)


@pytest.fixture
def bus() -> EventBus:
    event_bus = EventBus.__new__(EventBus)
    EventBus.__init__(event_bus)
    event_bus.clear_all_handlers()
    return event_bus


@pytest.mark.asyncio
async def test_bound_method_subscriber_receives_events(bus: EventBus) -> None:
    subscriber = _Subscriber()
    bus.subscribe("thing", subscriber.on_event)
    bus.subscribe("thing", subscriber.on_event_async)

    await bus.publish("thing", 1)

    assert subscriber.seen == [1, 1]
    assert bus.get_subscriber_count("thing") == 2


@pytest.mark.asyncio
async def test_bound_method_can_be_unsubscribed(bus: EventBus) -> None:
    subscriber = _Subscriber()
    bus.subscribe("thing", subscriber.on_event)

    bus.unsubscribe("thing", subscriber.on_event)
    await bus.publish("thing", 1)

    assert subscriber.seen == []


@pytest.mark.asyncio
async def test_collected_subscriber_is_dropped(bus: EventBus) -> None:
    subscriber = _Subscriber()
    bus.subscribe("thing", subscriber.on_event)

    del subscriber
    gc.collect()
    await bus.publish("thing", 1)

    assert bus.get_subscriber_count("thing") == 0
