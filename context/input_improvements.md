# Input Improvements - MultiLineInput

Date: 2025-11-02
Status: Implemented

## Problems Fixed

### 1. Pasted Text Mangling

**Problem:** When pasting terminal output or multi-line text, the text would get scrambled/interleaved incorrectly.

**Example of mangled paste:**
```
🚀 ChatCord server starting on localhost:5000 either: (base) maximusputnam@Maximuss-MacBook-Air backend % python app.py
Portess already in useapp'ode for Python 3.12+ compatibility
```

**Root Cause:** The input handler was processing pasted text character-by-character, not recognizing it as a paste operation. Newlines in pasted text weren't being properly inserted as new lines.

**Fix:** Added paste detection and proper multi-line handling (lines 242-275):
```typescript
// Check if input contains newlines (pasted text)
if (input.includes('\n')) {
  const pastedLines = input.split('\n');
  // Insert lines at cursor position
  // Move cursor to end of pasted text
}
```

### 2. Missing Keyboard Shortcuts

**Problem:** No Option/Command shortcuts for faster navigation and editing (standard on macOS terminals).

**Fix:** Added keyboard shortcut support (where supported by Ink):

#### Navigation Shortcuts:
- **Command/Ctrl + Left Arrow** → Jump to start of line
- **Command/Ctrl + Right Arrow** → Jump to end of line

#### Deletion Shortcuts:
- **Command/Ctrl + Backspace** → Delete to start of line

**Note:** Option/Alt key shortcuts are not supported in Ink due to terminal limitations. These keys are used by terminals for special character input (accented characters, etc.).

## Implementation Details

### Key Handler Ordering (Critical Fix)

**Problem:** Initially, keyboard shortcuts didn't work because regular key handlers were checked before modified key handlers.

**Fix:** Reordered key handlers so modified keys (Cmd/Ctrl + key) are checked **before** unmodified keys (lines 122-198):

```typescript
// IMPORTANT: Check modified keys BEFORE unmodified keys

// Command/Ctrl + Backspace: Delete to start of line
if ((key.backspace || key.delete) && (key.meta || key.ctrl)) {
  // ... handle modified key
  return;
}

// Backspace (regular, no modifiers)
if (key.backspace || key.delete) {
  // ... handle regular key
  return;
}
```

This order ensures that `Cmd+Backspace` is detected before the general `Backspace` handler catches it.

### Paste Handling (lines 201-233)

```typescript
if (input.includes('\n')) {
  const pastedLines = input.split('\n');
  setLines(prev => {
    const newLines = [...prev];
    const currentLine = newLines[cursorLine];
    const before = currentLine.substring(0, cursorCol);
    const after = currentLine.substring(cursorCol);

    // Insert first line of paste
    newLines[cursorLine] = before + pastedLines[0];

    // Insert middle lines
    for (let i = 1; i < pastedLines.length - 1; i++) {
      newLines.splice(cursorLine + i, 0, pastedLines[i]);
    }

    // Insert last line + remaining text
    if (pastedLines.length > 1) {
      const lastPasted = pastedLines[pastedLines.length - 1];
      newLines.splice(cursorLine + pastedLines.length - 1, 0, lastPasted + after);
    } else {
      newLines[cursorLine] = before + pastedLines[0] + after;
    }

    return newLines;
  });

  // Move cursor to end of pasted text
  const lastLine = pastedLines[pastedLines.length - 1];
  setCursorLine(cursorLine + pastedLines.length - 1);
  setCursorCol(lastLine.length);
}
```

### Line Start/End Shortcuts (lines 165-174)

```typescript
// Command/Ctrl + Left: Jump to start of line
if (key.leftArrow && (key.meta || key.ctrl)) {
  setCursorCol(0);
  return;
}

// Command/Ctrl + Right: Jump to end of line
if (key.rightArrow && (key.meta || key.ctrl)) {
  setCursorCol(lines[cursorLine].length);
  return;
}
```

### Delete to Start of Line Shortcut (lines 124-136)

```typescript
// Command/Ctrl + Backspace: Delete to start of line
if ((key.backspace || key.delete) && (key.meta || key.ctrl)) {
  if (cursorCol > 0) {
    const currentLine = lines[cursorLine];
    setLines(prev => {
      const newLines = [...prev];
      newLines[cursorLine] = currentLine.substring(cursorCol);
      return newLines;
    });
    setCursorCol(0);
  }
  return;
}
```

## Testing

### Test Paste Handling:
1. Copy multi-line terminal output (with errors, paths, etc.)
2. Paste into Penguin CLI input
3. **Expected:** Text should appear correctly formatted, preserving newlines
4. **Before:** Text would be mangled/scrambled
5. **After:** Text appears exactly as copied

### Test Keyboard Shortcuts:
1. Type a long line with multiple words
2. Try each shortcut:
   - **Cmd+Left/Right** - Should jump to line start/end
   - **Cmd+Backspace** - Should delete to line start
3. **Expected:** All shortcuts work like standard macOS terminal

## Files Modified

**penguin-cli/src/ui/components/MultiLineInput.tsx** (lines 122-233)
- **CRITICAL FIX:** Reordered key handlers so modified keys are checked before unmodified keys
- Added paste detection and handling (lines 201-233)
- Added Cmd/Ctrl navigation shortcuts (lines 165-174)
- Added Cmd/Ctrl deletion shortcut (lines 124-136)

**penguin/cli/ui.py** (lines 246-249)
- Added handler for "tool" events to prevent "Unknown event type" warnings

## Benefits

1. **Paste works correctly** - Users can copy/paste terminal errors, logs, and multi-line text without mangling
2. **Faster editing** - Word jumping and deletion speeds up editing long messages
3. **Standard UX** - Shortcuts match macOS terminal/editor conventions
4. **Better productivity** - Natural muscle memory from other apps works here

## Keyboard Shortcuts Summary

| Shortcut | Action |
|----------|--------|
| **Enter** | New line |
| **Esc** | Send message |
| **Arrow keys** | Move cursor |
| **Cmd/Ctrl + ←** | Jump to line start |
| **Cmd/Ctrl + →** | Jump to line end |
| **Backspace** | Delete character |
| **Cmd/Ctrl + Backspace** | Delete to line start |
| **Tab** | Cycle autocomplete (if showing) |

## Cross-Platform Notes

- **macOS:** Uses `key.meta` (Command key)
- **Linux/Windows:** Uses `key.ctrl` (Control key)
- Implementation checks both `key.meta` and `key.ctrl` for cross-platform compatibility
- **Note:** Option/Alt modifiers are not supported in Ink due to terminal limitations

## Related Files

- **penguin-cli/src/ui/components/ChatSession.tsx** - Uses MultiLineInput
- Reference: Standard macOS terminal keyboard shortcuts
