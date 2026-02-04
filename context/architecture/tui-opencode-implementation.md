# Penguin x OpenCode TUI Compatibility

## Purpose
Deliver a feature-complete OpenCode TUI experience backed by Penguin, using a
near OpenCode-compatible HTTP + SSE API surface (Option A).

This document includes:
1) A concrete audit of what the TUI expects.
2) A gap map vs current Penguin APIs.
3) A staged implementation plan focused first on streaming quality.

## Decision
**Option A:** Implement an OpenCode-compatible API surface in Penguin.

Rationale:
- Keeps the TUI fork closer to upstream OpenCode.
- Centralizes integration logic in Penguin’s web API.
- Enables incremental parity without reworking UI components.

## Current Status (2026-02-02)
- SSE streaming works end-to-end for chat.
- Minimal chat mode is wired in TUI (custom Penguin mode).
- Session list is partially populated, but parity is incomplete.

## Audit: TUI Expectations (from `penguin-tui`)

### API calls used by the TUI
The TUI relies on these SDK calls (OpenCode API surface). This is the minimum
set to support a fully functional UI.

#### Session APIs
- `session.list({ start, search, limit })`
- `session.create({})`
- `session.get({ sessionID })`
- `session.messages({ sessionID, limit })`
- `session.todo({ sessionID })`
- `session.diff({ sessionID })`
- `session.status()`
- `session.update({ sessionID, title })`
- `session.delete({ sessionID })`
- `session.abort({ sessionID })`
- `session.summarize({ sessionID })`
- `session.revert({ sessionID, messageID })`
- `session.unrevert({ sessionID })`
- `session.fork({ sessionID, messageID })`
- `session.shell({ sessionID, agent, model, command })`
- `session.command({ sessionID, command, arguments, agent, model, messageID, variant, parts })`
- `session.prompt({ sessionID, agent, model, messageID, variant, parts })`

#### Provider + Config APIs
- `config.get()`
- `config.providers()`
- `provider.list()`
- `provider.auth()`
- `provider.oauth.authorize()`
- `provider.oauth.callback()`
- `auth.set()`

#### App/Agent/Command APIs
- `app.agents()`
- `command.list()`

#### MCP/LSP/Formatter/Path/VCS
- `mcp.status()`
- `mcp.connect({ name })`
- `mcp.disconnect({ name })`
- `lsp.status()`
- `formatter.status()`
- `path.get()`
- `vcs.get()`

#### Find / Experimental
- `find.files({ query, limit, directory })`
- `experimental.resource.list()`

#### Permissions / Questions
- `permission.reply({ requestID, reply })`
- `question.reply({ requestID, reply })`
- `question.reject({ requestID })`

### Event types used by the TUI
The TUI expects these events to drive UI state:

#### Message + Parts
- `message.updated` (info payload)
- `message.removed`
- `message.part.updated` (part + delta)
- `message.part.removed`

#### Session lifecycle
- `session.created`
- `session.updated`
- `session.deleted`
- `session.status`
- `session.idle`
- `session.compacted`
- `session.diff`
- `session.error`

#### Permissions / Questions
- `permission.asked`
- `permission.replied`
- `question.asked`
- `question.replied`
- `question.rejected`

#### Todo + Tools
- `todo.updated`
- `tool`

#### MCP / LSP
- `mcp.tools.changed`
- `mcp.browser.open.failed`
- `lsp.updated`
- `lsp.client.diagnostics`

## Gap Map: Penguin vs OpenCode

### Already in Penguin (usable)
- `GET /api/v1/events/sse` (SSE stream)
- `POST /api/v1/chat/message` (basic chat)
- `GET /api/v1/conversations` (list)
- `GET /api/v1/conversations/{id}`
- `GET /api/v1/conversations/{id}/history`
- `POST /api/v1/conversations/create`
- Conversation/session metadata via `ConversationManager`

### Missing or incompatible for OpenCode parity

#### Session APIs
- OpenCode expects `/session.*` endpoints with rich message/part history
  (including tool parts, diffs, todos, and revert/fork support).
- Penguin currently returns history as simple message lists, without OpenCode
  message/part envelopes.

#### Provider + Config
- OpenCode expects provider list, model metadata, and provider auth
  endpoints that match its SDK schema.
- Penguin has model config but not an OpenCode-shaped provider API.

#### Tool execution UI
- OpenCode expects tool parts with lifecycle states (pending/running/completed).
- Penguin emits `stream_chunk` and tool events but does not persist tool parts
  in OpenCode message history.

#### Permissions / Questions
- OpenCode expects explicit approval/deny flows with events and reply endpoints.
- Penguin has a permissions system but no OpenCode API surface.

#### MCP/LSP
- OpenCode expects MCP/LSP status + events.
- Penguin does not yet expose MCP/LSP status or tooling in OpenCode schema.

## Implementation Plan (Option A)

### Phase 0: Streaming + Animation Parity (highest priority)
Goal: streaming feels correct and stable in the TUI.

- Ensure consistent `message.updated` with `time.completed` on stream end.
- Emit `message.part.updated` with stable part IDs per stream.
- Ensure `delta` updates are ordered and coalesced for smooth animation.
- Emit `session.status` transitions (busy → idle) during streaming.
- Ensure tool events can stream as `part.type=tool` with state transitions.
- Filter internal markers (`<finish_response>`) at source.
- Reconcile optimistic user messages with server events using a client message id.

**Architecture Decision (Phase 0)**
- Emit OpenCode-compatible streaming events directly from Penguin’s core.
- Keep streaming state and coalescing in Penguin, not in the TUI.
- SSE remains the primary delivery channel; WS remains unchanged.
- Keep optimistic client-side user messages; server echoes the same message id.

### Phase 1: Session list + metadata
Goal: session picker works fully and loads complete history.

- Implement `/session.list`, `/session.get`, `/session.messages` using Penguin
  session metadata and message logs.
- Add OpenCode message envelopes (`info` + `parts`) to history output.
- Emit `session.created`, `session.updated`, `session.deleted` events.

**Architecture Decision (Phase 1)**
- Add `/session.*` endpoints in Penguin web API backed by `ConversationManager`.
- Return OpenCode-shaped messages/parts from persisted session data.

### Phase 2: Provider/model picker
Goal: model selection and provider UI works.

- Implement `/provider.list` and `/config.providers` with OpenCode schema.
- Implement `/config.get` for config controls.
- Add `/provider.auth` (no-op or mapped to Penguin credential status).

**Architecture Decision (Phase 2)**
- Map Penguin model configs into OpenCode provider + model schemas.
- Keep auth endpoints as stubs until provider credential workflows exist.

### Phase 3: Tool execution UI
Goal: tool events render and persist in history.

- Emit tool lifecycle events as `message.part.updated` with `type=tool`.
- Store tool parts in session history for reload.
- Implement `/session.diff`, `/session.todo` to feed diff/todo widgets.
- Tool display respects OpenCode user settings (no custom UI overrides).
- Emit tool parts for all tools, interleaved with assistant streaming.

**Architecture Decision (Phase 3)**
- Persist tool parts alongside message parts in session history.
- Translate Penguin tool lifecycle events into OpenCode tool parts.
- Use `action` + `action_result` events as the canonical tool lifecycle.
- Tool output rendering is controlled by OpenCode settings.

**Tool Display Bridging (Summary)**
- Map `action` events to tool parts with `state=running`.
- Map `action_result` events to the same tool part with `state=completed/error`.
- Use `action.id` as `callID` and as the tool part correlation key.
- Attach tool parts to the current assistant message; if none, create one.
- Interleave tool parts with the streaming message that triggered them.

For the exact mapping, see `context/architecture/tui-opencode-tool-bridge.md`.

### Phase 4: Permissions + questions
Goal: approvals and user questions behave like OpenCode.

- Implement `/permission.reply`, `/question.reply`, `/question.reject`.
- Emit `permission.asked/replied`, `question.asked/replied/rejected`.

**Architecture Decision (Phase 4)**
- Wrap Penguin’s permission system with OpenCode-compatible endpoints/events.
- Treat OpenCode question flow as a thin layer over Penguin prompts.

### Phase 5: MCP/LSP + misc widgets
Goal: the remaining system widgets populate correctly.

- Implement `/mcp.status`, `/mcp.connect`, `/mcp.disconnect`.
- Implement `/lsp.status`, `/formatter.status`, `/path.get`, `/vcs.get`.
- Emit `mcp.tools.changed`, `lsp.updated`, diagnostics events.

**Architecture Decision (Phase 5)**
- Expose MCP/LSP status as read-only endpoints first; add control later.
- Return empty sets when services are not configured.

## Backend Work Items (Penguin)

1) **OpenCode compatibility router**
   - Create a new router under `penguin/web/opencode_routes.py`.
   - Expose OpenCode-compatible endpoints (`/session`, `/provider`, `/config`, etc.).

2) **Event mapping layer**
   - Extend `tui_adapter` to emit full OpenCode event set.
   - Add session lifecycle events, tool parts, and permission/question events.

3) **Persistent message/part model**
   - Store OpenCode `Message` + `Part` data in session history.
   - Ensure replays are identical to live events.

4) **Streaming behavior audit**
   - Tune stream manager cadence and `is_final` handling.
   - Ensure UI receives clean deltas and final completion signals.

## TUI Work Items (temporary)

- Keep minimal Penguin mode for early testing only.
- As OpenCode endpoints are implemented in Penguin, remove the TUI shims and
  point the TUI back to the standard SDK flow.

## Validation

For each phase, validate with:
- Local TUI run + SSE stream
- Session reload + history replay
- Tool event rendering
- Permissions/approval flow
- MCP/LSP status indicators
