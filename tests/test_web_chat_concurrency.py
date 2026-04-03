import asyncio
import time

import pytest

from penguin.web import routes


class FakeCore:
    def __init__(self):
        self.model_config = None
        self.calls = []

    async def process(
        self,
        input_data,
        context=None,
        conversation_id=None,
        agent_id=None,
        max_iterations=100,
        context_files=None,
        streaming=None,
        stream_callback=None,
    ):
        start = time.perf_counter()
        self.calls.append(("start", conversation_id, start))
        await asyncio.sleep(0.15)
        end = time.perf_counter()
        self.calls.append(("end", conversation_id, end))
        return {
            "assistant_response": f"ok:{conversation_id}",
            "action_results": [],
        }


def _make_request(text: str, session_id: str) -> routes.MessageRequest:
    return routes.MessageRequest(
        text=text,
        session_id=session_id,
        conversation_id=session_id,
    )


@pytest.mark.asyncio
async def test_handle_chat_message_allows_concurrent_different_sessions(monkeypatch):
    core = FakeCore()
    monkeypatch.setattr(
        routes,
        "_queue_session_title_refresh",
        lambda *args, **kwargs: None,
    )

    started = time.perf_counter()
    first, second = await asyncio.gather(
        routes.handle_chat_message(_make_request("alpha", "session-a"), core),
        routes.handle_chat_message(_make_request("beta", "session-b"), core),
    )
    elapsed = time.perf_counter() - started

    assert first["response"] == "ok:session-a"
    assert second["response"] == "ok:session-b"
    assert elapsed < 0.25

    start_a = next(
        ts for event, sid, ts in core.calls if event == "start" and sid == "session-a"
    )
    start_b = next(
        ts for event, sid, ts in core.calls if event == "start" and sid == "session-b"
    )
    end_a = next(
        ts for event, sid, ts in core.calls if event == "end" and sid == "session-a"
    )
    end_b = next(
        ts for event, sid, ts in core.calls if event == "end" and sid == "session-b"
    )

    assert start_a < end_b
    assert start_b < end_a


@pytest.mark.asyncio
async def test_handle_chat_message_serializes_same_session(monkeypatch):
    core = FakeCore()
    monkeypatch.setattr(
        routes,
        "_queue_session_title_refresh",
        lambda *args, **kwargs: None,
    )

    started = time.perf_counter()
    await asyncio.gather(
        routes.handle_chat_message(_make_request("alpha", "shared-session"), core),
        routes.handle_chat_message(_make_request("beta", "shared-session"), core),
    )
    elapsed = time.perf_counter() - started

    starts = [
        ts
        for event, sid, ts in core.calls
        if event == "start" and sid == "shared-session"
    ]
    ends = [
        ts
        for event, sid, ts in core.calls
        if event == "end" and sid == "shared-session"
    ]

    assert len(starts) == 2
    assert len(ends) == 2
    assert elapsed >= 0.28
    assert starts[1] >= ends[0]
