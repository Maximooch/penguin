# Penguin TUI Implementation Plan: OpenCode Fork Strategy

## Philosophy

**Fork aggressively, adapt minimally.** OpenCode's TUI represents thousands of hours of UX refinement. Rebuilding it in Python with Rich or Textual would be a 6-month quagmire. Instead, we fork their TypeScript/SolidJS implementation and build a compatibility layer on the backend.

The backend refactor to message/part events and SSE is happening anyway—current WebSocket implementation is brittle. This refactor makes Penguin more suitable for web apps, third-party clients, and future integrations.

## Directory Structure

```
penguin/
├── penguin/api/                    # FastAPI routes (existing)
│   ├── server.py                   # Main FastAPI app
│   └── sse_events.py               # NEW: SSE endpoint
├── penguin-tui/                    # NEW: Forked from OpenCode
│   ├── src/
│   │   ├── cli/cmd/tui/            # Copied from opencode/packages/opencode/src/cli/cmd/tui
│   │   │   ├── app.tsx             # Entry point (minimal changes)
│   │   │   ├── context/
│   │   │   │   ├── sdk.tsx         # REPLACED: Penguin SSE client
│   │   │   │   ├── sync.tsx        # Store management (unchanged)
│   │   │   │   └── theme.tsx       # Theme system (unchanged)
│   │   │   ├── component/          # All UI components (unchanged)
│   │   │   ├── ui/                 # Dialogs, toasts, etc. (unchanged)
│   │   │   └── routes/             # Home, Session views (unchanged)
│   │   └── sdk/                    # NEW: Thin Penguin SDK adapter
│   │       ├── client.ts           # SSE connection manager
│   │       └── types.ts            # Penguin-specific type extensions
│   ├── package.json                # Dependencies: @opentui/solid, etc.
│   └── LICENSE.opencode            # MIT attribution file
└── penguin/engine/
    └── events.py                   # REFACTORED: Message/part event emission
```

## Phase 1: Backend Refactor (Week 1-2)

### 1.1 Message/Part Event Model

Current Penguin emits raw tokens. Refactor to emit structured events:

```python
# penguin/engine/events.py - New module
from dataclasses import dataclass, field
from typing import Literal, Optional, Dict, Any
from enum import Enum

class PartType(Enum):
    TEXT = "text"
    REASONING = "reasoning"
    TOOL = "tool"
    STEP_START = "step-start"
    STEP_FINISH = "step-finish"
    PATCH = "patch"

@dataclass
class Part:
    id: str
    message_id: str
    session_id: str
    type: PartType
    content: Dict[str, Any] = field(default_factory=dict)
    delta: Optional[str] = None  # For streaming

@dataclass  
class Message:
    id: str
    session_id: str
    role: Literal["user", "assistant", "system"]
    time_created: float
    time_completed: Optional[float] = None
    model_id: Optional[str] = None
    provider_id: Optional[str] = None
    mode: str = "chat"
    cost: float = 0.0
    tokens: Dict[str, int] = field(default_factory=lambda: {
        "input": 0, "output": 0, "reasoning": 0, "cache": {"read": 0, "write": 0}
    })

class EventEnvelope:
    """OpenCode-compatible event wrapper"""
    def __init__(self, event_type: str, properties: Dict[str, Any]):
        self.type = event_type
        self.properties = properties
    
    def to_sse(self) -> str:
        return f"data: {json.dumps({'type': self.type, 'properties': self.properties})}\n\n"
```

### 1.2 Engine Integration

Refactor `engine.py` to use Part-based streaming:

```python
# In Engine.run_response() or streaming methods
async def stream_with_parts(self, session_id: str, callback=None):
    message = Message(
        id=f"msg_{uuid.uuid4().hex[:12]}",
        session_id=session_id,
        role="assistant",
        time_created=time.time()
    )
    
    # Emit message.created
    await self.event_bus.publish("message.updated", message)
    
    # Create text part for streaming
    text_part = Part(
        id=f"part_{uuid.uuid4().hex[:12]}",
        message_id=message.id,
        session_id=session_id,
        type=PartType.TEXT,
        content={"text": ""}
    )
    
    # Stream tokens as part updates
    async for chunk in llm_stream:
        text_part.delta = chunk
        text_part.content["text"] += chunk
        await self.event_bus.publish("message.part.updated", text_part)
    
    # Finalize
    text_part.delta = None  # No more deltas
    await self.event_bus.publish("message.part.updated", text_part)
    message.time_completed = time.time()
    await self.event_bus.publish("message.updated", message)
```

### 1.3 SSE Endpoint

```python
# penguin/api/sse_events.py
from fastapi import APIRouter
from fastapi.responses import StreamingResponse
import asyncio
import json

router = APIRouter()

@router.get("/api/v1/events/sse")
async def events_sse(
    session_id: Optional[str] = None,
    agent_id: Optional[str] = None,
    core: PenguinCore = Depends(get_core)
):
    """SSE stream of OpenCode-compatible events"""
    
    async def event_generator():
        queue = asyncio.Queue()
        
        def handler(event_type: str, data: Any):
            # Filter by session_id if provided
            if session_id and hasattr(data, 'session_id'):
                if data.session_id != session_id:
                    return
            
            # Convert to OpenCode envelope
            envelope = convert_to_opencode_format(event_type, data)
            queue.put_nowait(envelope.to_sse())
        
        # Subscribe to relevant events
        subscriptions = []
        for event_type in ["message.updated", "message.part.updated", "message.removed"]:
            sub = core.event_bus.subscribe(event_type, handler)
            subscriptions.append((event_type, sub))
        
        try:
            # Send server.connected immediately
            yield f"data: {json.dumps({'type': 'server.connected', 'properties': {}})}\n\n"
            
            while True:
                data = await queue.get()
                yield data
        finally:
            # Cleanup subscriptions
            for event_type, sub in subscriptions:
                core.event_bus.unsubscribe(event_type, sub)
    
    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
        }
    )
```

### 1.4 Event Conversion Layer

```python
def convert_to_opencode_format(event_type: str, data: Any) -> EventEnvelope:
    """Convert Penguin internal events to OpenCode envelope format"""
    
    if event_type == "message.updated":
        return EventEnvelope(
            type="message.updated",
            properties={
                "id": data.id,
                "sessionID": data.session_id,
                "role": data.role,
                "time": {
                    "created": int(data.time_created * 1000),
                    "completed": int(data.time_completed * 1000) if data.time_completed else None
                },
                "modelID": data.model_id,
                "providerID": data.provider_id,
                "mode": data.mode,
                "cost": data.cost,
                "tokens": data.tokens
            }
        )
    
    elif event_type == "message.part.updated":
        part_data = {
            "id": data.id,
            "messageID": data.message_id,
            "sessionID": data.session_id,
            "type": data.type.value,
        }
        
        # Add part-specific fields
        if data.type == PartType.TEXT:
            part_data["text"] = data.content.get("text", "")
            if data.delta:
                return EventEnvelope(
                    type="message.part.updated",
                    properties={"part": part_data, "delta": data.delta}
                )
        
        elif data.type == PartType.TOOL:
            part_data.update({
                "tool": data.content.get("tool_name"),
                "input": data.content.get("input", {}),
                "state": data.content.get("state", "pending"),  # pending|running|completed|error
                "output": data.content.get("output")
            })
        
        return EventEnvelope(type="message.part.updated", properties={"part": part_data})
    
    # ... other event types
```

## Phase 2: TUI Fork (Week 2-3)

### 2.1 Copy OpenCode TUI

```bash
# Create penguin-tui directory
mkdir -p penguin-tui/src/cli/cmd/tui

# Copy OpenCode TUI source
cp -r reference/opencode/packages/opencode/src/cli/cmd/tui/* penguin-tui/src/cli/cmd/tui/

# Copy necessary dependencies from OpenCode
cp reference/opencode/packages/opencode/package.json penguin-tui/
# Adjust dependencies - remove opencode-specific packages
```

### 2.2 Replace SDK Client

**File to replace:** `penguin-tui/src/cli/cmd/tui/context/sdk.tsx`

```typescript
// NEW: Penguin SSE SDK Context
import { createSimpleContext } from "./helper"
import { createGlobalEmitter } from "@solid-primitives/event-bus"
import { batch, onCleanup, onMount } from "solid-js"

export type PenguinEvent = {
  type: string
  properties: any
}

export const { use: useSDK, provider: SDKProvider } = createSimpleContext({
  name: "SDK",
  init: (props: { url: string; directory?: string }) => {
    const abort = new AbortController()
    const emitter = createGlobalEmitter<Record<string, any>>()
    
    let queue: PenguinEvent[] = []
    let timer: number | undefined
    let last = 0
    
    const flush = () => {
      if (queue.length === 0) return
      const events = queue
      queue = []
      timer = undefined
      last = Date.now()
      
      batch(() => {
        for (const event of events) {
          emitter.emit(event.type, event)
        }
      })
    }
    
    const handleEvent = (event: PenguinEvent) => {
      queue.push(event)
      const elapsed = Date.now() - last
      
      if (timer) return
      if (elapsed < 16) {
        timer = setTimeout(flush, 16)
        return
      }
      flush()
    }
    
    onMount(async () => {
      const eventSource = new EventSource(
        `${props.url}/api/v1/events/sse${props.directory ? `?directory=${encodeURIComponent(props.directory)}` : ''}`
      )
      
      eventSource.onmessage = (e) => {
        try {
          const event = JSON.parse(e.data)
          handleEvent(event)
        } catch (err) {
          console.error("Failed to parse SSE event:", err)
        }
      }
      
      eventSource.onerror = (err) => {
        console.error("SSE error:", err)
      }
      
      onCleanup(() => {
        eventSource.close()
        if (timer) clearTimeout(timer)
      })
    })
    
    return { 
      client: null,  // No REST client needed for basic TUI
      event: emitter, 
      url: props.url 
    }
  },
})
```

### 2.3 Minimal App.tsx Changes

```typescript
// penguin-tui/src/cli/cmd/tui/app.tsx
// Changes: Replace SDKProvider initialization

// BEFORE (OpenCode):
// <SDKProvider url={...} directory={...}>

// AFTER (Penguin):
<SDKProvider url={config.apiUrl} directory={config.workspaceRoot} />
```

### 2.4 Package.json Dependencies

```json
{
  "name": "penguin-tui",
  "version": "0.1.0",
  "dependencies": {
    "@opentui/core": "^0.x",
    "@opentui/solid": "^x.x",
    "solid-js": "^1.x",
    // Remove: "@opencode-ai/sdk"
    // Add any Penguin-specific deps
  },
  "scripts": {
    "dev": "tsx watch src/index.tsx",
    "build": "tsup src/index.tsx --format cjs",
    "start": "node dist/index.js"
  }
}
```

## Phase 3: Tool Rendering (Week 3-4)

### 3.1 Tool Part Mapping

OpenCode's TUI expects specific part types for tool execution. Map Penguin tools:

| Penguin Tool | OpenCode Part Type | Notes |
|-------------|-------------------|-------|
| `apply_diff` | `PatchPart` | Show diff visualization |
| `enhanced_write` | `FilePart` | Show file creation |
| `execute` | `ToolPart` | Generic command execution |
| `search` | `ToolPart` | Search results |
| Browser tools | `ToolPart` | With URL preview |

### 3.2 Tool State Machine

```python
# In tool execution, emit state transitions
class ToolPartTracker:
    async def start_tool(self, tool_name: str, input_data: dict):
        part = Part(
            id=f"tool_{uuid.uuid4().hex[:12]}",
            type=PartType.TOOL,
            content={
                "tool_name": tool_name,
                "input": input_data,
                "state": "pending"
            }
        )
        await self.emit("message.part.updated", part)
        return part.id
    
    async def update_tool(self, part_id: str, state: str, output: Any = None):
        # Emit update with new state
        pass
```

## Phase 4: Licensing & Attribution (Week 1, ongoing)

### 4.1 MIT License Compliance

Create `penguin-tui/LICENSE.opencode`:

```
OpenCode TUI Attribution
========================

The penguin-tui package contains code derived from OpenCode, 
which is licensed under the MIT License:

Copyright (c) 2024 OpenCode Inc.

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

[Full MIT license text...]

The following files were derived from OpenCode:
- src/cli/cmd/tui/app.tsx
- src/cli/cmd/tui/context/*.tsx
- src/cli/cmd/tui/component/*.tsx
- src/cli/cmd/tui/ui/*.tsx
- src/cli/cmd/tui/routes/*.tsx

Modifications made:
- Replaced SDK client with Penguin SSE adapter
- Updated API endpoint definitions
- Changed branding from OpenCode to Penguin
```

### 4.2 File Headers

Add to every forked file:

```typescript
// Derived from OpenCode (https://github.com/opencode-ai/opencode)
// Copyright (c) 2024 OpenCode Inc. - MIT License
// Modifications Copyright (c) 2025 Penguin Authors
```

## Phase 5: Integration & Testing (Week 4)

### 5.1 Build Integration

Add to root `package.json` or `Makefile`:

```makefile
tui-build:
	cd penguin-tui && npm install && npm run build

tui-dev:
	cd penguin-tui && npm run dev

run-with-tui:
	python -m penguin.api.server &  # Start backend
	cd penguin-tui && npm start     # Start TUI
```

### 5.2 Test Strategy

```python
# tests/api/test_sse_events.py
async def test_sse_message_streaming(client):
    """Test that SSE emits OpenCode-compatible message events"""
    async with client.get("/api/v1/events/sse") as response:
        # Should receive server.connected first
        line = await response.content.readline()
        assert b"server.connected" in line
        
        # Trigger a message
        await client.post("/api/v1/chat/message", json={"text": "Hello"})
        
        # Should receive message.updated
        line = await response.content.readline()
        assert b"message.updated" in line
        
        # Should receive message.part.updated with delta
        line = await response.content.readline()
        assert b"message.part.updated" in line
        assert b"delta" in line
```

## Migration Path

### Current State
- WebSocket at `/api/v1/chat/stream`
- Raw token streaming
- EventBus with custom event types

### Target State
- SSE at `/api/v1/events/sse` (new default)
- Message/part structured events
- OpenCode-compatible envelopes
- WebSocket endpoints remain for backward compatibility

### Deprecation Timeline
1. **Week 1-4**: SSE and TUI development in parallel
2. **Week 5**: Internal testing with SSE
3. **Week 6**: Mark WebSocket as deprecated in docs
4. **Month 3**: Consider WebSocket removal (based on adoption)

## Success Criteria

- [ ] SSE endpoint streams events without dropping messages
- [ ] TUI connects and displays streaming text correctly
- [ ] Tool executions render with proper state transitions
- [ ] All forked files have proper attribution headers
- [ ] MIT license file included in penguin-tui package
- [ ] WebSocket endpoints still functional (backward compatibility)
- [ ] No Python TUI code in the critical path (Ink/Textual deprecated)

## Risks & Mitigations

| Risk | Impact | Mitigation |
|-----|--------|-----------|
| SSE backpressure on large outputs | High | Implement server-side buffering, coalesce rapid deltas |
| Event ordering issues | Medium | Enforce per-session ordering, use monotonic IDs |
| Tool rendering mismatches | Medium | Extensive mapping tests, fallback to generic ToolPart |
| Build complexity (Node+Python) | Low | Docker dev container, clear README setup steps |
| License compliance | Low | Automated header checks in CI |

## Notes

- **Why not Python TUI libraries?** Rich and Textual are excellent for simple dashboards, but complex interactive TUIs (nested dialogs, real-time streaming, keyboard shortcuts) hit their limits quickly. SolidJS + OpenTUI gives us React-like component architecture with terminal rendering.

- **Backend refactor benefits:** Message/part model makes Penguin suitable for:
  - Web apps ( clearer data model)
  - Mobile clients (structured events)
  - Third-party integrations (documented schema)
  - Observability (better event tracing)

- **Fork vs. dependency:** OpenCode doesn't publish their TUI as a separate package. Forking is the only practical option. We maintain a clean boundary: our changes are limited to the SDK adapter layer.

---

**Estimated Timeline:** 4-6 weeks
**Critical Path:** Backend message/part refactor → SSE endpoint → TUI SDK adapter
**Success Metric:** Feature parity with OpenCode TUI for text streaming, tool display, and session management