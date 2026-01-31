"""Tests for SSE endpoint and OpenCode event adapter.

These tests verify the SSE endpoint structure and event flow.
Full integration tests require a running server instance.
"""

import pytest
from unittest.mock import MagicMock, AsyncMock, patch
import asyncio
import json


def test_part_events_imports():
    """Verify part_events module can be imported."""
    from penguin.engine.part_events import (
        PartType, Part, Message, EventEnvelope, PartEventAdapter
    )
    assert PartType.TEXT.value == "text"
    assert PartType.REASONING.value == "reasoning"
    assert PartType.TOOL.value == "tool"


def test_part_creation():
    """Test Part dataclass creation."""
    from penguin.engine.part_events import Part, PartType
    
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


def test_event_envelope_serialization():
    """Test EventEnvelope to SSE format."""
    from penguin.engine.part_events import EventEnvelope
    
    envelope = EventEnvelope(
        type="message.updated",
        properties={"id": "msg_123", "role": "assistant"}
    )
    
    sse = envelope.to_sse()
    assert sse.startswith("data: ")
    assert "message.updated" in sse
    assert "msg_123" in sse
    
    # Verify it's valid JSON after the prefix
    json_part = sse.replace("data: ", "").strip()
    data = json.loads(json_part)
    assert data["type"] == "message.updated"
    assert data["properties"]["id"] == "msg_123"


@pytest.mark.asyncio
async def test_part_event_adapter_stream_lifecycle():
    """Test full stream lifecycle with PartEventAdapter."""
    from penguin.engine.part_events import PartEventAdapter
    
    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()
    
    adapter = PartEventAdapter(mock_bus)
    adapter.set_session("test_session")
    
    # Start stream
    msg_id, part_id = await adapter.on_stream_start(
        agent_id="test_agent",
        model_id="gpt-4",
        provider_id="openai"
    )
    
    assert msg_id.startswith("msg_")
    assert part_id.startswith("part_")
    assert adapter._current_message_id == msg_id
    
    # Verify message.updated was emitted
    assert mock_bus.emit.called
    call = mock_bus.emit.call_args
    assert call[0][0] == "opencode_event"
    assert call[0][1]["type"] == "message.updated"
    
    # Emit chunks
    mock_bus.emit.reset_mock()
    await adapter.on_stream_chunk(msg_id, part_id, "Hello ", "assistant")
    await adapter.on_stream_chunk(msg_id, part_id, "world!", "assistant")
    
    assert mock_bus.emit.call_count == 2
    calls = [c[0][1] for c in mock_bus.emit.call_args_list]
    assert calls[0]["type"] == "message.part.updated"
    assert calls[0]["properties"]["delta"] == "Hello "
    assert calls[1]["properties"]["delta"] == "world!"
    
    # End stream
    mock_bus.emit.reset_mock()
    await adapter.on_stream_end(msg_id, part_id)
    
    assert mock_bus.emit.called
    call = mock_bus.emit.call_args
    assert call[0][1]["type"] == "message.updated"
    assert call[0][1]["properties"]["time"]["completed"] is not None


@pytest.mark.asyncio
async def test_part_event_adapter_tool_execution():
    """Test tool execution events."""
    from penguin.engine.part_events import PartEventAdapter, PartType
    
    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()
    
    adapter = PartEventAdapter(mock_bus)
    adapter.set_session("test_session")
    
    # Start a message first
    msg_id, _ = await adapter.on_stream_start()
    
    # Start tool execution
    tool_part_id = await adapter.on_tool_start(
        tool_name="search",
        tool_input={"query": "test"},
        tool_[tool-call-reference]="call_123"
    )
    
    assert tool_part_id.startswith("part_")
    
    call = mock_bus.emit.call_args
    assert call[0][1]["type"] == "message.part.updated"
    part = call[0][1]["properties"]["part"]
    assert part["type"] == "tool"
    assert part["tool"] == "search"
    assert part["state"] == "running"
    assert part["callID"] == "call_123"
    
    # Complete tool execution
    mock_bus.emit.reset_mock()
    await adapter.on_tool_end(
        tool_part_id,
        output={"results": ["item1", "item2"]},
        error=None
    )
    
    call = mock_bus.emit.call_args
    part = call[0][1]["properties"]["part"]
    assert part["state"] == "completed"
    assert part["output"] == {"results": ["item1", "item2"]}


@pytest.mark.asyncio
async def test_part_event_adapter_user_message():
    """Test user message creation."""
    from penguin.engine.part_events import PartEventAdapter
    
    mock_bus = MagicMock()
    mock_bus.emit = AsyncMock()
    
    adapter = PartEventAdapter(mock_bus)
    adapter.set_session("test_session")
    
    msg_id = await adapter.on_user_message("Hello assistant!")
    
    assert msg_id.startswith("msg_")
    assert mock_bus.emit.call_count == 2  # message.updated + message.part.updated
    
    calls = [c[0][1] for c in mock_bus.emit.call_args_list]
    assert calls[0]["type"] == "message.updated"
    assert calls[0]["properties"]["role"] == "user"
    assert calls[1]["type"] == "message.part.updated"


def test_sse_endpoint_imports():
    """Verify SSE module can be imported."""
    from penguin.web.sse_events import (
        router, events_sse, set_core_instance, get_core_instance
    )
    assert router is not None
    assert events_sse is not None


def test_sse_router_has_routes():
    """Verify router has the expected routes."""
    from penguin.web.sse_events import router
    
    routes = [route for route in router.routes]
    route_paths = [getattr(r, "path", None) for r in routes]
    
    assert "/api/v1/events/sse" in route_paths
    assert "/api/v1/health" in route_paths


@pytest.mark.asyncio
async def test_sse_event_generator():
    """Test SSE event generator logic."""
    from penguin.web.sse_events import events_sse
    
    # Mock core and event bus
    mock_core = MagicMock()
    mock_bus = MagicMock()
    mock_bus.subscribe = MagicMock()
    mock_bus.unsubscribe = MagicMock()
    
    mock_core.event_bus = mock_bus
    
    # Patch get_core_instance
    with patch("penguin.web.sse_events.get_core_instance", return_value=mock_core):
        # Import FastAPI test client
        from fastapi.testclient import TestClient
        from fastapi import FastAPI
        
        app = FastAPI()
        from penguin.web import sse_events
        app.include_router(sse_events.router)
        
        # Note: Full streaming test requires running server
        # This just verifies the endpoint structure
        client = TestClient(app)
        response = client.get("/api/v1/events/sse", timeout=0.5)
        
        # Should connect (but will timeout waiting for events)
        assert response.status_code == 200
        assert response.headers["content-type"] == "text/event-stream; charset=utf-8"


def test_core_integration():
    """Verify core has PartEventAdapter integrated."""
    # This tests the import structure only
    # Full integration requires full core initialization
    try:
        from penguin.core import PenguinCore
        import inspect
        
        # Check that PartEventAdapter is referenced in source
        source = inspect.getsource(PenguinCore)
        assert "PartEventAdapter" in source
        assert "_part_event_adapter" in source
        assert "_current_stream_ids" in source
        
    except ImportError as e:
        pytest.skip(f"Cannot import PenguinCore: {e}")


# Integration tests (require running server)
@pytest.mark.integration
def test_sse_endpoint_live():
    """Test SSE endpoint with running server.
    
    Requires:
    - Server running on localhost:8000
    - Core instance initialized
    
    Run with: pytest tests/test_sse_endpoint.py -m integration
    """
    import requests
    
    try:
        response = requests.get(
            "http://localhost:8000/api/v1/events/sse",
            stream=True,
            timeout=5
        )
        assert response.status_code == 200
        assert response.headers.get("content-type") == "text/event-stream"
        
        # Read first event
        for line in response.iter_lines():
            if line:
                line_str = line.decode("utf-8")
                assert line_str.startswith("data: ")
                data = json.loads(line_str.replace("data: ", ""))
                assert "type" in data
                assert "properties" in data
                break
                
    except requests.exceptions.ConnectionError:
        pytest.skip("Server not running on localhost:8000")
    except requests.exceptions.Timeout:
        pytest.skip("Server timeout - may need longer timeout or check server health")