# Phase 2: Extract Streaming Logic

## Objective
Analyze streaming logic to determine what can be extracted and what should remain in PenguinCLI.

## Current State
- cli.py: 5,629 lines (after Phase 1)
- PenguinCLI has streaming-related methods:
  - handle_event: 332 lines (handles 6 event types)
  - _finalize_streaming: 23 lines (stops StreamingDisplay)
- StreamingDisplay already exists with Rich.Live implementation

## Analysis

### handle_event Method (332 lines)
Handles 6 event types:
1. stream_chunk: Streaming text chunks from Core
2. token_update: Token usage updates
3. tool: Tool execution events
4. message: Message events
5. status: Status updates
6. error: Error events

**Observation:**
- handle_event is already using StreamingDisplay for streaming
- It's an event dispatcher that connects Core to UI
- This is the RIGHT place for this logic (event handling, not display)
- Moving it to StreamingDisplay would be wrong (display component shouldn't handle events)

### What CAN be extracted:
1. **Event-specific handlers**: Break handle_event into smaller methods
   - _handle_stream_chunk_event
   - _handle_token_update_event
   - _handle_tool_event
   - _handle_message_event
   - _handle_status_event
   - _handle_error_event

2. **Streaming state management**: Extract to a StreamingState class
   - Active stream ID tracking
   - Buffer management
   - Deduplication tracking

### What SHOULD remain in PenguinCLI:
- handle_event: Event dispatcher (orchestrates other methods)
- _finalize_streaming: Cleanup method (needs CLI context)
- State management: CLI needs to track streaming state

## Strategy
Since streaming logic is already well-structured (using StreamingDisplay), Phase 2 will focus on:
1. Extract event-specific handlers from handle_event
2. Create StreamingState class for state management
3. Improve code organization without breaking functionality

## Expected Outcome
- Better code organization (smaller methods)
- Clearer separation of concerns
- No significant line reduction (logic is already in right place)
- Easier to maintain and test

## Execution Steps
1. Analyze handle_event to identify extractable logic
2. Create event-specific handler methods
3. Create StreamingState class
4. Update handle_event to use new methods
5. Run tests to verify no regressions
