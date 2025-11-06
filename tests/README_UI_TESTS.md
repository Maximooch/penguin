# Penguin UI Tests

Test scripts for verifying UI timeline ordering and event handling.

## Tests Overview

### 1. Timeline Ordering Tests (`test_ui_timeline.py`)

Unit tests for timeline chronological ordering logic. Tests the same logic used in `EventTimeline.tsx`.

**What it tests:**
- Messages and tool events sort chronologically
- Tool events appear AFTER the message that invoked them
- Stream start timestamp capture (T0 vs first token timestamp)

**Run:**
```bash
python tests/test_ui_timeline.py
```

**Expected output:**
```
✅ TEST 1 PASSED: Tools appear after triggering message
✅ TEST 2 PASSED: All tool events in correct order
Passed: 2/2
✅ All tests passed!
```

### 2. Integration Tests (`test_ui_integration.py`)

Full integration tests connecting to real backend server via WebSocket.

**What it tests:**
- End-to-end event flow: Backend → WebSocket → UI
- No duplicate tool events
- Chronological ordering in real scenarios
- Event types recognized (no "Unknown event type" warnings)

**Requirements:**
- Backend server running: `uv run penguin-web`

**Run:**
```bash
# Terminal 1: Start backend
uv run penguin-web

# Terminal 2: Run tests
python tests/test_ui_integration.py
```

**Expected output:**
```
TEST 1: Simple Request (No Tools)
✓ Connected to backend
✓ Sent message: Hello, can you introduce yourself?
✓ Received 12 events in 2.34s
✓ No duplicates found (0 unique tool events)
✓ Correct order: User → Assistant → 0 tools
✅ TEST 1 PASSED

TEST 2: Request with Tool Calls
✓ Connected to backend
✓ Sent message: List the files in the current directory
✓ Received 18 events in 3.12s
✓ No duplicates found (1 unique tool events)
✓ Correct order: User → Assistant → 1 tools
✅ TEST 2 PASSED

Passed: 2/2
✅ All integration tests passed!
```

## Issues These Tests Verify

### Issue 1: Duplicate Tool Events ✅ Fixed
**Symptom:** Tool results appeared 3 times in cli-run-7.txt

**Test:** `test_ui_integration.py` → `verify_no_duplicates()`

**Verification:**
```python
tool_ids = set()
for tool_event in self.tool_events:
    tool_id = tool_event.get('id')
    if tool_id in tool_ids:
        # FAIL: Duplicate found!
```

### Issue 2: Wrong Chronological Order ✅ Fixed
**Symptom:** Tool events appeared BEFORE the message that invoked them

**Test:** `test_ui_timeline.py` → `test_responses_api_flow()`

**Verification:**
```python
# Expected: User → Assistant → Tools
# T0: User message (timestamp captured here)
# T1: Tool executes
# T0: Assistant message (uses stream start timestamp, not first token)
# Result: T0 < T1 ✓
```

### Issue 3: "Unknown event type: tool" Warnings ✅ Fixed
**Symptom:** Backend logs showed warnings for tool events

**Test:** `test_ui_integration.py` → Check logs for warnings

**Fix:** Added tool event handler in:
- `penguin/cli/ui.py` lines 246-249
- `penguin/cli/events.py` line 51 (EventType.TOOL)
- Frontend: `penguin-cli/src/ui/components/ChatSession.tsx`

## Reproducing Issues from Logs

The logs you provided showed specific patterns. Here's how to reproduce them:

### Pattern 1: Multiple finalize_streaming_message calls

From your logs:
```
[DEBUG] finalize_streaming_message() adding message. has_reasoning=True, content_length=11754
[DEBUG] finalize_streaming_message() adding message. has_reasoning=False, content_length=1278
[DEBUG] finalize_streaming_message() adding message. has_reasoning=False, content_length=2834
...
```

**Reproduce:**
```bash
# Send a complex request that triggers many iterations
python tests/test_ui_integration.py  # Test 3
```

### Pattern 2: Tool event warnings

From your logs:
```
WARNING:penguin.cli.events:Unknown event type: tool
```

**Check if fixed:**
```bash
# Terminal 1
uv run penguin-web

# Terminal 2
python tests/test_ui_integration.py

# Check Terminal 1 logs - should see NO warnings
```

## Manual Testing

For manual verification with the Ink CLI:

```bash
# Terminal 1: Start backend with debug logging
DEBUG=1 uv run penguin-web

# Terminal 2: Start Ink CLI
cd penguin-cli
npm run dev

# Terminal 2: Send test messages
# 1. Simple: "Hello, introduce yourself"
# 2. With tools: "List files in current directory"
# 3. Many tools: "Create 5 test files"

# Verify in UI:
# - Tool results appear once (not 3 times)
# - Tool results appear AFTER Penguin message
# - No "Unknown event type" in Terminal 1 logs
```

## Expected Timeline Format

Correct timeline order (from EventTimeline.tsx):

```
[1] You: create a whiteboarding app
[2] Penguin: I'll create a whiteboarding app...
  ✓ using execute — Created directory
  ✓ using execute — Created package.json
  ✓ using execute — Created index.html
[3] Penguin: Perfect! I've created Penguin Board
```

**Key points:**
- Messages numbered sequentially [1], [2], [3]
- Tool results indented under triggering message
- Tool results appear AFTER message [2], not before
- Each tool result appears exactly ONCE

## Troubleshooting

### Tests fail with connection error

```
❌ TEST 1 ERROR: Cannot connect to ws://localhost:8000
```

**Solution:** Start backend first
```bash
uv run penguin-web
```

### "Unknown event type" warnings still appear

**Check:** Make sure you have the latest code
```bash
# Backend fix
grep -A 3 "elif event_type == \"tool\":" penguin/cli/ui.py

# Should show:
# elif event_type == "tool":
#     # Tool events are handled by the Ink CLI EventTimeline component
#     logger.debug(f"Tool event received: {data.get('action', 'unknown')}")
```

### Tool events still duplicated

**Check:** Frontend callbacks
```typescript
// ChatSession.tsx - onComplete should NOT create tool events
client.callbacks.onComplete = (actionResults: any) => {
  completeProgress();
  complete(); // Only finalize streaming message
  setTimeout(() => resetProgress(), 1000);
};
```

## Related Documentation

- [context/bug_fixes_keyboard_and_tool_events.md](../context/bug_fixes_keyboard_and_tool_events.md) - All 6 issues fixed
- [context/ui_performance_fix_static_component.md](../context/ui_performance_fix_static_component.md) - Static component pattern
- [context/input_improvements.md](../context/input_improvements.md) - Input handling fixes
