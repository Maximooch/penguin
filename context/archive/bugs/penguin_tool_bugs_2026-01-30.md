# Bug Report: Tool Usage Failures in Penguin Agent System

**Report Date:** 2026-01-30  
**Session Context:** Debugging Electron app for Cadence Scheduler  
**Severity:** High (Core functionality broken)

---

## Executive Summary

During a 30+ turn debugging session, the `apply_diff` tool failed repeatedly with response truncation errors, forcing fallback to raw Python file manipulation via `execute`. Additionally, async tool result handling and timeout management created friction that slowed resolution.

---

## Bug 1: `apply_diff` Response Truncation (CRITICAL)

### Symptoms
- Tool calls with properly formatted unified diff would execute but response to user was truncated mid-diff
- User had to prompt: *"your message keeps getting cut off, try a different way of applying it"*
- Required fallback to `<execute>` with Python file operations

### Example Failure
```
`apply_diff`electron/preload.js:--- a/electron/preload.js
+++ b/electron/preload.js
@@ -1,4 +1,4 @@
-const { contextBridge, ipcRenderer, app } = require('electron');
+const { contextBridge, ipcRenderer } =
[RESPONSE TRUNCATED HERE]
```

### Root Cause Hypothesis
Unified diff headers (`@@ -start,count +start,count @@`) or boundary markers (`--- a/`, `+++ b/`) may trigger regex parsing in response formatter. Large multi-line diffs especially vulnerable.

### Impact
- **HIGH**: Core editing functionality unreliable
- Forces users to see partial/incomplete responses
- Creates confusion about whether changes were applied

### Recommended Fixes
1. **Add validation layer**: Confirm diff applied by re-reading file hash before returning success
2. **Implement `replace_lines` alternative**: Simpler API - just file_path, start_line, end_line, new_content
3. **Fuzzy matching**: Use `git apply --ignore-space-change` semantics for context lines
4. **Dry-run mode**: Show preview before apply, require explicit confirmation

---

## Bug 2: Async Tool Result Handling Gaps

### Symptoms
- During exploration phase, occasionally didn't properly acknowledge tool results before calling next tool
- User would see empty responses or rapid-fire tool calls without interpretation

### Example
```python
`enhanced_read`electron/electron-todo.md:true:100`enhanced_read`
# [File not found error - no response shown to user]
`list_files_filtered`electron:true:false`list_files_filtered`
```

### Recommended Fixes
1. **Enforce "respond to every result" rule**: Add lint check that each tool call is followed by either another tool call OR text response, not silent continuation
2. **Add pending indicator**: Show "⏳ Waiting for tool result..." in UI when async tools in flight
3. **Minimum tool call enforcement**: Actually enforce "minimum 5-12 tool calls before responding" - I sometimes violated this

---

## Bug 3: Timeout Handling Leaves Zombie Processes

### Symptoms
- `execute_command` with `npm start` would timeout after 60s
- Electron processes left running in background
- Subsequent runs would have port conflicts or multiple instances

### Example
```
`execute_command`cd electron && npm start & sleep 5
[TIMEOUT after 60s]
[Process continues running, user has to manually kill]
```

### Recommended Fixes
1. **Process cleanup on timeout**: Auto-kill spawned processes when timeout hits
2. **Process tracking**: Add `process_list` auto-check on session start to warn about orphaned processes
3. **Detach vs attach modes**: Explicit flag for "run and wait" vs "run and forget"

---

## Bug 4: Diff Context Sensitivity

### Symptoms
- `apply_diff` would fail if context lines had subtle whitespace differences
- Required exact indentation match even for unrelated context

### Recommended Fixes
1. **Relax context matching**: Only require 1-2 lines of context instead of 3
2. **Auto-indent detection**: Show warning if file uses 2-space but diff uses 4-space
3. **Semantic diff mode**: For Python/JS, use AST-aware diffing (big ask, but would be killer feature)

---

## Workarounds Documented for Users

Until fixed, agents should:

1. **When `apply_diff` fails**: Switch to `<execute>` with Python:
   ```python
   with open('file.js', 'r') as f:
       content = f.read()
   content = content.replace('old', 'new')
   with open('file.js', 'w') as f:
       f.write(content)
   ```

2. **Verify all edits**: Always re-read with `enhanced_read` after changes

3. **Process cleanup**: Explicitly kill before restart:
   ```bash
   pkill -f electron; sleep 1; npm start
   ```

---

## Success Patterns to Preserve

- `enhanced_read` with line numbers: Essential for debugging
- `search` across project: Fast way to find symbol usage
- `execute` as escape hatch: Saved the session when structured tools failed
- `list_files_filtered`: Clean directory exploration

---

**Submitted by:** penguin-agent[bot]  
**Session logs:** context/journal/2026-01-30.md