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

## Current Status (2026-02-07)
- SSE streaming works end-to-end for chat in Penguin mode.
- Session filtering by `session_id` works in SSE.
- OpenCode-style message/part streaming is active via `opencode_event` bridge.
- Reasoning is emitted as a dedicated part before text.
- Tool lifecycle is bridged from `action` + `action_result` into tool parts.
- Action-to-tool mapping is in place for key tools (`execute`/`execute_command` -> `bash`, `apply_diff` -> `edit`, etc.).
- Tool parts now emit OpenCode-style ToolState objects (running/completed/error with time/input/output/metadata).
- Chunk-safe action-tag filtering is implemented to prevent tag leakage in streamed text.
- Minimal Penguin TUI command parity added (`/settings`, `/tool_details`, `/thinking`).
- Session list/history parity is still incomplete vs full OpenCode API.

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

## Feature Completion Order (OpenCode parity)
1) Session + message/parts history parity (envelopes + parts).
2) Streaming + tool lifecycle polish (interleaving, tool cards, persistence).
3) Settings/config + provider/model picker.
4) Diffs + modified files sidebar (session.diff + VCS snapshot data).
5) Plan + TODO widgets.
6) Agent modes + variants.
7) Reasoning effort/variant configuration.
8) Multi/sub-agents (agent roster + message routing).
9) LSP/Formatter/Path/VCS real implementations.
10) Permissions + questions.
11) MCP (defer; can stub until needed).
12) Experimental resources + session ops (fork/revert/summarize/abort).

**Cross-cutting principle**
- Where OpenCode implements a more reliable or clearer workflow than Penguin, prefer updating Penguin to match OpenCode behavior (e.g., tool metadata shapes, diff rendering, session envelopes).

## Progress Snapshot (Phases)
- Phase 0 (Streaming + animation parity): **mostly complete**.
- Phase 1 (Session list + metadata): **partial**.
- Phase 2 (Provider/model picker): **partial**.
- Phase 3 (Tool execution UI + persistence): **partial** (live rendering is strong; persistence/replay still incomplete).
- Phase 4 (Permissions + questions): **not started**.
- Phase 5 (LSP/Formatter/Path/VCS real implementations, MCP deferred): **not started**.

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

**Action-to-Tool Mapping (Initial)**
- `execute` -> `bash` (temporary; reuse Bash card for IPython output).
- `execute_command` -> `bash`.
- `apply_diff` -> `edit` (diff rendered via `metadata.diff`).
- `replace_lines` -> `edit` (inline until diff generation added).
- `edit_with_pattern` -> `edit` (inline until diff generation added).
- `enhanced_read` -> `read`.
- `list_files_filtered` -> `list`.
- `find_files_enhanced` -> `glob`.
- `search` -> `grep`.

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

- Implement `/lsp.status`, `/formatter.status`, `/path.get`, `/vcs.get` (real implementations).
- Emit `lsp.updated`, diagnostics events (real signal sources).
- Defer MCP endpoints until after the rest is stable.

**Architecture Decision (Phase 5)**
- LSP/Formatter/Path/VCS must be real; avoid stubs.
- MCP endpoints can be deferred or stubbed until needed.

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

## Implementation Checklist (Endpoints, Payloads, Owners)

## Executable Task Backlog

### Track A: Stabilize Existing Work
- [ ] A1. Persist tool parts in session history and replay them in `/session.messages`.
  - Owner: `penguin/tui_adapter/part_events.py`, `penguin/web/opencode_routes.py` (or equivalent session route layer), `ConversationManager` storage adapters.
  - Acceptance: reload shows identical tool cards/order as live run.
- [ ] A2. Extend action-to-tool mapping coverage for remaining common actions.
  - Owner: `penguin/core.py` mapping helpers.
  - Acceptance: no major action appears as generic white inline text in TUI.
- [ ] A3. Add diff metadata generation for `replace_lines` and `edit_with_pattern`.
  - Owner: `penguin/core.py` mapper + `penguin/tools/core/support.py` helpers.
  - Acceptance: these actions render block diff views in OpenCode TUI.

### Track B: OpenCode API Compatibility Router
- [ ] B1. Add compatibility router scaffold for OpenCode operation IDs.
  - Owner: `penguin/web/opencode_routes.py` + `penguin/web/app.py` route registration.
  - Acceptance: route table includes session/config/provider/lsp/formatter/path/vcs endpoints used by TUI.
- [ ] B2. Implement `session.list`, `session.get`, `session.messages` with OpenCode-shaped payloads.
  - Owner: `ConversationManager` + route adapters.
  - Acceptance: TUI loads sessions and history without Penguin-mode-only shims.
- [ ] B3. Implement `session.status`, `session.update`, `session.delete`, `session.create`.
  - Owner: web routes + `ConversationManager`.
  - Acceptance: create/rename/delete session flows work from TUI.

### Track C: Settings / Provider / Model UX
- [ ] C1. Implement `config.get` with runtime config + reasoning + active model metadata.
  - Owner: `penguin/web/opencode_routes.py`, `core.runtime_config`, model config adapters.
  - Acceptance: settings panel reflects current values and capabilities.
- [ ] C2. Implement `config.providers` and `provider.list` mapped from Penguin model configs.
  - Owner: `penguin/config`, `penguin/llm/model_config.py`, route adapters.
  - Acceptance: model/provider picker loads valid options.
- [ ] C3. Implement `provider.auth` placeholder contract.
  - Owner: web routes.
  - Acceptance: endpoint returns stable non-error response with clear unsupported/available state.

### Track D: Diffs, Files Sidebar, VCS
- [ ] D1. Implement `vcs.get` with real git-backed branch + dirty status.
  - Owner: `penguin/web/opencode_routes.py` + lightweight git adapter utility.
  - Acceptance: sidebar shows branch and updates after branch switch.
- [ ] D2. Implement `session.diff` using persisted snapshots/tool outputs and/or git diff.
  - Owner: conversation persistence + route adapters.
  - Acceptance: diff sidebar/widget populates with changed files + patch data.
- [ ] D3. Emit `vcs.branch.updated` when branch changes are detected.
  - Owner: event bus + vcs poll/trigger hook.
  - Acceptance: TUI updates branch without restart.

### Track E: Plan/TODO + Agent Features
- [ ] E1. Implement `session.todo` from `ProjectManager` task graph.
  - Owner: `penguin/project` + route adapter.
  - Acceptance: todo panel shows stable list with statuses.
- [ ] E2. Emit `todo.updated` on task create/update/complete.
  - Owner: project/task layer event emission.
  - Acceptance: todo panel updates live.
- [ ] E3. Implement `app.agents` and ensure message/tool events carry `agent_id` consistently.
  - Owner: `core.py` agent roster + event adapter.
  - Acceptance: multi/sub-agent UI and filtering behave correctly.
- [ ] E4. Implement variant/mode + reasoning effort plumbing in `session.prompt`/config.
  - Owner: route adapter + `core.process` parameter mapping.
  - Acceptance: toggling mode/effort affects runtime behavior and is reflected in metadata.

### Track F: LSP / Formatter / Path (Real, not stubbed)
- [ ] F1. Implement `path.get` from runtime roots (`directory`, `worktree`, `home`).
  - Owner: route adapter + runtime config.
  - Acceptance: sidebar path info is always populated.
- [ ] F2. Implement `formatter.status` from actual formatter availability/config.
  - Owner: tool/config layer + route adapter.
  - Acceptance: formatter panel shows real enabled/disabled state by language.
- [ ] F3. Implement `lsp.status` with real language server health/status.
  - Owner: new `penguin/lsp/` integration module + route adapter.
  - Acceptance: TUI no longer sees empty/default LSP forever; status tracks active languages.
- [ ] F4. Emit `lsp.updated` and `lsp.client.diagnostics` events from file edits.
  - Owner: edit/apply_diff/write tool paths + event bus adapter.
  - Acceptance: diagnostics refresh in TUI after edits.

### Track G: Deferred / Later
- [ ] G1. MCP compatibility (`mcp.status/connect/disconnect`) after core parity is stable.
  - Owner: `penguin/integrations/mcp/*` + route adapters.
  - Acceptance: OpenCode MCP dialog can connect/disconnect providers.

### Session + messages
- `session.list({ start, search, limit })` -> `penguin/web/opencode_routes.py` using `ConversationManager` for list/metadata.
  - Response: `{ sessions: [{ id, title, time, summary?, agent?, model?, tags? }] }`
- `session.get({ sessionID })` -> `ConversationManager.get_session(session_id)`.
  - Response: `{ session: { id, title, time, model, provider, agent, status } }`
- `session.messages({ sessionID, limit })` -> history + OpenCode envelopes.
  - Response: `{ messages: [{ info: Message, parts: Part[] }] }` (use `tui_adapter` shapes).
- `session.create({})` -> `ConversationManager.create_session()`.
- `session.update({ sessionID, title })` -> `ConversationManager.update_session_title()`.
- `session.delete({ sessionID })` -> `ConversationManager.delete_session()`.
- `session.status()` -> `ConversationManager.get_status()` + active tool/stream state.

### Tool lifecycle + diffs
- `session.diff({ sessionID })` -> `ConversationManager` + VCS snapshot (see below).
  - Response: `{ diffs: [{ filePath, diff, additions, deletions, status }] }`
- Tool parts in SSE -> `penguin/core.py` action->tool mapping + `tui_adapter/part_events.py` ToolState.

### Settings / config / provider
- `config.get()` -> `core.runtime_config.to_dict()` plus current model info.
  - Response: `{ config: { ... }, model: { id, provider, temperature, max_output_tokens, reasoning } }`
- `config.providers()` -> map `core.config.model_configs` to OpenCode provider schema.
- `provider.list()` -> list of providers + models; owner: `penguin/config` + `penguin/llm/model_config`.
- `provider.auth()` / OAuth -> stub or no-op until auth workflows exist.

### Plan + TODO
- `session.todo({ sessionID })` -> `ProjectManager` tasks + `ConversationManager` summaries.
  - Response: `{ items: [{ id, title, status, owner?, updatedAt? }] }`
- `todo.updated` event -> emit when tasks change.

### Agent modes + variants
- `session.prompt({ sessionID, agent, model, variant, parts })` -> `core.process()` with mode/variant metadata.
- Embed `variant`/`mode` in message envelopes and SSE metadata.

### Reasoning effort / variant
- `config.get()` should include reasoning settings (e.g., `reasoning.enabled`, `reasoning.effort`).
- `session.prompt()` should accept a `reasoning` override.

### Multi/sub-agents
- `app.agents()` -> `AgentManager` roster (agent id, persona, model override, status).
- `session.command()` -> route to specific agent via `core.send_to_agent()`.
- Include `agent_id` on messages + tool parts for proper TUI grouping.

### LSP (real)
- `lsp.status()` -> integrate a lightweight LSP manager (per language) and return OpenCode schema.
  - Response: `{ data: [{ language, status, server?, diagnostics? }] }`
- `lsp.updated` + `lsp.client.diagnostics` -> emit on file writes/patches.
  - Owner: new `penguin/lsp/` module (or reuse an existing LSP integration if present).

### Formatter (real)
- `formatter.status()` -> expose configured formatters from Penguin (per language).
  - Response: `{ data: [{ language, status, formatter }] }`
  - Owner: `penguin/tools` or new `penguin/formatter` module.

### Path (real)
- `path.get()` -> return workspace/project roots and home.
  - Response: `{ directory, worktree, home }` from `core.runtime_config` + `WORKSPACE_PATH`.

### VCS (real)
- `vcs.get()` -> detect git repo, branch, dirty status.
  - Response: `{ branch, status?, root?, vcs: "git"|"none" }`
  - Emit `vcs.branch.updated` on branch changes (poll or on-demand).

### MCP (defer)
- `mcp.status/connect/disconnect` -> optional; can remain stubbed until LSP/VCS are stable.
