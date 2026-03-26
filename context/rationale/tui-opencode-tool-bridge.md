# Tool Display Bridge: Penguin -> OpenCode TUI

## Goal
Render Penguin tool execution in the OpenCode TUI using OpenCode's `tool` parts,
interleaved with assistant streaming, and respecting OpenCode user settings.

## Source Events (Penguin)
Penguin already emits tool lifecycle events from `ActionExecutor` in
`penguin/utils/parser.py` using the UI callback:

- `action` (start)
- `action_result` (completion)

These events are emitted via `PenguinCore.emit_ui_event` and can be observed by
the TUI adapter.

## Target Events (OpenCode)
Emit OpenCode-compatible events:

- `message.part.updated` with `part.type = "tool"`

## Mapping (Exact)

### action -> tool part (running)
Input (Penguin):
```
event_type: "action"
data: {
  "id": "<action_id>",
  "type": "<action_type>",
  "params": "<action_params>"
}
```

Output (OpenCode):
```
type: "message.part.updated"
properties: {
  part: {
    id: "part_<monotonic>",
    messageID: "msg_<current>",
    sessionID: "<session_id>",
    type: "tool",
    callID: "<action_id>",
    tool: "<action_type>",
    input: "<action_params>",
    state: "running",
    output: null
  }
}
```

### action_result -> tool part (completed/error)
Input (Penguin):
```
event_type: "action_result"
data: {
  "id": "<action_id>",
  "status": "completed" | "error",
  "result": "<stringified result>",
  "action": "<action_type>"
}
```

Output (OpenCode):
```
type: "message.part.updated"
properties: {
  part: {
    id: "<same part id as start>",
    messageID: "<same message id>",
    sessionID: "<session_id>",
    type: "tool",
    callID: "<action_id>",
    tool: "<action_type>",
    state: "completed" | "error",
    output: "<result>",
    error: "<error_message>" (only when status=error)
  }
}
```

## Correlation Rules
- Use `action.id` as the stable correlation key.
- Maintain an in-memory map: `action_id -> part_id`.
- Reuse the same `part_id` for updates from `action_result`.

## Message Association Rules
- If a streaming assistant message is active, attach tool parts to it.
- If no assistant message is active, create a new assistant message
  (`message.updated`) and attach tool parts to that message.

## Ordering Rules
- Tool parts are emitted in the same order as their source events.
- Tool parts should be interleaved with assistant text streaming.

## Rendering Behavior
- OpenCode controls display via its existing settings. Do not override or hide
  tool output at the adapter level.

## Notes
- Tool output can be large; consider truncation when persisting to history.
- If tools are triggered outside a response stream, the adapter should still
  emit a tool-only assistant message to keep UI consistent.
