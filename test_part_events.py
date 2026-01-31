"""Test the SSE and PartEvents integration."""
import asyncio
import pytest
from unittest.mock import MagicMock, AsyncMock

# Test imports
from penguin.engine.part_events import PartType, Part, Message, EventEnvelope, PartEventAdapter


def test_part_creation():
    """Test basic Part creation."""
    part = Part(
        id="part_123",
        message_id="msg_456",
        session_id="session_789",
        type=PartType.TEXT,
        content={"text": "Hello"},
        delta="Hello"
    )
    assert part.id == "part_123"
    assert part.type == PartType.TEXT
    assert part.content["text"] == "Hello"


def test_event_envelope():
    """Test EventEnvelope serialization."""
    envelope = EventEnvelope(
        type="message.updated",
        properties={"id": "msg_123", "role": "assistant"}
    )
    sse = envelope.to_sse()
    assert sse.startswith("data: ")
    assert "message.updated" in sse
    assert "msg_123" in sse


@pytest.mark.asyncio
async def test_part_event_adapter():
    """Test PartEventAdapter emits events correctly."""
    # Mock event bus
    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()

    adapter = PartEventAdapter(mock_bus)
    adapter.set_session("test_session")

    # Test stream start
    msg_id, part_id = await adapter.on_stream_start(agent_id="test_agent")
    assert msg_id.startswith("msg_")
    assert part_id.startswith("part_")

    # Verify message.updated was emitted
    assert mock_bus.emit.called
    call_args = mock_bus.emit.call_args
    assert call_args[0][0] == "opencode_event"
    assert call_args[0][1]["type"] == "message.updated"

    # Test stream chunk
    mock_bus.emit.reset_mock()
    await adapter.on_stream_chunk(msg_id, part_id, " chunk", "assistant")
    assert mock_bus.emit.called
    call_args = mock_bus.emit.call_args
    assert call_args[0][1]["type"] == "message.part.updated"
    assert call_args[0][1]["properties"]["delta"] == " chunk"


@pytest.mark.asyncio
async def test_sse_endpoint_imports():
    """Test that SSE endpoint can be imported."""
    try:
        from penguin.web.sse_events import router, events_sse, set_core_instance
        print("SSE imports successful")
        assert router is not None
        assert events_sse is not None
    except Exception as e:
        pytest.fail(f"Failed to import SSE module: {e}")


if __name__ == "__main__":
    # Run basic tests
    test_part_creation()
    print("✓ Part creation test passed")

    test_event_envelope()
    print("✓ Event envelope test passed")

    asyncio.run(test_part_event_adapter())
    print("✓ Part event adapter test passed")

    asyncio.run(test_sse_endpoint_imports())
    print("✓ SSE endpoint imports test passed")

    print("\nAll tests passed!")
