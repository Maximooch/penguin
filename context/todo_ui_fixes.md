# UI/UX Fixes TODO

Date: 2025-11-02
Goal: Fix streaming conversation display issues

## Issues to Fix

### 1. Tool Results Not Appearing Chronologically (CRITICAL)
**Problem:** Tool results appear bundled instead of inline with conversation flow
**Impact:** Users can't follow task progress, breaks understanding

**Tasks:**
- [ ] Find frontend WebSocket message handler
- [ ] Ensure tool result messages (`message_type: "action"`) are inserted chronologically
- [ ] Add distinct styling for tool results (system message style)
- [ ] Test with multi-iteration task

### 2. UI Performance - Stuttering/Freezing (CRITICAL)
**Problem:** UI freezes during rapid updates (27+ messages), can't scroll
**Impact:** Long-running tasks are unusable

**Tasks:**
- [ ] Implement debounced rendering (batch updates every 50-100ms)
- [ ] Add virtual scrolling for long message lists
- [ ] Memoize message components to prevent unnecessary re-renders
- [ ] Optimize auto-scroll behavior
- [ ] Test with high-iteration tasks

### 3. WebSocket Error Handling (MEDIUM)
**Problem:** Normal disconnects logged as ERROR
**Impact:** Log noise, confusion

**Tasks:**
- [ ] Catch `WebSocketDisconnect` and `ConnectionClosedOK` in web/routes.py
- [ ] Change normal disconnect logging to INFO/DEBUG level
- [ ] Add connection state checking before send operations
- [ ] Clean up tasks on disconnect

## Implementation Plan

### Phase 1: Backend WebSocket Error Handling (Quick Win)
**Files:** `penguin/web/routes.py`
**Estimated Time:** 15 minutes

Fix the noisy error logging:
- Wrap WebSocket send operations in try/except
- Catch specific disconnect exceptions
- Log at appropriate level (INFO for normal, ERROR for unexpected)

### Phase 2: Frontend Investigation
**Files:** Unknown - need to find frontend code
**Estimated Time:** 30 minutes

Locate:
- WebSocket event handler
- Message rendering component
- Conversation display logic

### Phase 3: Chronological Tool Results
**Files:** Frontend message handler and renderer
**Estimated Time:** 1-2 hours

Implementation:
- Ensure messages maintain sequence order
- Insert tool results inline with conversation
- Add visual distinction for tool results
- Test with file picker task (27 iterations)

### Phase 4: Performance Optimization
**Files:** Frontend message list component
**Estimated Time:** 2-3 hours

Implementation:
- Debounced render updates
- Virtual scrolling (react-window or similar)
- Component memoization
- Lazy loading for large messages
- Auto-scroll optimization

## Testing

### Test Case 1: File Picker Task
- 27 iterations
- Mix of searches, reads, writes
- Large file creation at end
- Should see all tool results inline
- Should not freeze or stutter

### Test Case 2: Rapid Updates
- Simulate 50+ quick messages
- UI should remain responsive
- Auto-scroll should work smoothly
- Should handle 100 iterations without issue

### Test Case 3: Normal Disconnect
- Start task
- Close browser tab
- Check logs - should be INFO/DEBUG, not ERROR

## Success Criteria

- [ ] Tool results appear inline chronologically
- [ ] UI remains responsive during 100+ iteration tasks
- [ ] Can scroll smoothly during streaming
- [ ] Auto-scroll works correctly
- [ ] Normal disconnects don't log ERROR
- [ ] All existing tests still pass
