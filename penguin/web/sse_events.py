"""SSE endpoint for OpenCode TUI compatibility.

Provides Server-Sent Events endpoint that streams OpenCode-compatible
message/part events to the TUI client.
"""

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse
import asyncio
import json
from typing import Optional, Any, AsyncIterator, TYPE_CHECKING

if TYPE_CHECKING:
    from penguin.core import PenguinCore

router = APIRouter()

# Global reference to core instance (set by app.py)
_core_instance: Optional["PenguinCore"] = None


def set_core_instance(core: "PenguinCore"):
    """Set the core instance for dependency injection."""
    global _core_instance
    _core_instance = core


def get_core_instance() -> "PenguinCore":
    """Get the core instance."""
    if _core_instance is None:
        raise RuntimeError("Core instance not set - call set_core_instance() first")
    return _core_instance


@router.get("/api/v1/events/sse")
async def events_sse(
    session_id: Optional[str] = Query(None, description="Filter to specific session"),
    conversation_id: Optional[str] = Query(None, description="Alias for session_id (API compatibility)"),
    agent_id: Optional[str] = Query(None, description="Filter to specific agent"),
    directory: Optional[str] = Query(None, description="Workspace directory"),
):
    """
    SSE stream of OpenCode-compatible events.
    
    Query params:
    - session_id: Filter events to specific session
    - agent_id: Filter events to specific agent  
    - directory: Workspace directory (for context)
    """
    core = get_core_instance()
    
    # Use conversation_id if session_id not provided (API compatibility)
    effective_session_id = session_id or conversation_id
    effective_agent_id = agent_id
    
    async def event_generator() -> AsyncIterator[str]:
        queue: asyncio.Queue[dict] = asyncio.Queue(maxsize=1000)
        
        def event_handler(event_type: str, data: Any):
            """Handler for EventBus events."""
            # Only handle opencode_event type
            if event_type != "opencode_event":
                return
            
            # Data should already be in OpenCode format
            if not isinstance(data, dict):
                return
            
            # Filter by session_id if provided
            if effective_session_id:
                event_session = data.get("properties", {}).get("sessionID")
                if event_session != effective_session_id:
                    return
            
            # Filter by agent_id if provided (check multiple possible fields)
            if agent_id:
                props = data.get("properties", {})
                event_agent = props.get("agentID") or props.get("agent_id")
                # Also check nested part if present
                if not event_agent and "part" in props:
                    event_agent = props["part"].get("agentID") or props["part"].get("agent_id")
                if event_agent and event_agent != agent_id:
                    return
            
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                # Drop event if queue is full (client is slow)
                pass
        
        # Subscribe to events
        core.event_bus.subscribe("opencode_event", event_handler)
        
        try:
            # Send initial server.connected event
            connected_event = {
                "type": "server.connected",
                "properties": {
                    "sessionID": effective_session_id,
                    "agentID": effective_agent_id,
                    "directory": directory
                }
            }
            yield f"data: {json.dumps(connected_event)}\n\n"
            
            # Stream events
            while True:
                try:
                    # Wait for event with timeout for keepalive
                    event = await asyncio.wait_for(queue.get(), timeout=300.0)
                    yield f"data: {json.dumps(event)}\n\n"
                except asyncio.TimeoutError:
                    # Send keepalive comment
                    yield ": keepalive\n\n"
                    
        except asyncio.CancelledError:
            # Client disconnected
            pass
        finally:
            # Always unsubscribe
            try:
                core.event_bus.unsubscribe("opencode_event", event_handler)
            except Exception:
                pass
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
    )


@router.get("/api/v1/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "penguin-sse"}