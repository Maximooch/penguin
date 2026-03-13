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

## Current Status (2026-03-07)
- SSE streaming works end-to-end for chat in Penguin mode.
- Session filtering by `session_id` works in SSE.
- OpenCode-style message/part streaming is active via `opencode_event` bridge.
- Reasoning is emitted as a dedicated part before text.
- Tool lifecycle is bridged from `action` + `action_result` into tool parts.
- Action-to-tool mapping is in place for key tools (`execute`/`execute_command` -> `bash`, `apply_diff` -> `edit`, etc.).
- Tool parts now emit OpenCode-style ToolState objects (running/completed/error with time/input/output/metadata).
- Chunk-safe action-tag filtering is implemented to prevent tag leakage in streamed text.
- Minimal Penguin TUI command parity added (`/settings`, `/tool_details`, `/thinking`).
- Real OpenCode-compatible endpoints added in core routes for `/path`, `/vcs`, `/formatter`, `/lsp` (plus `/api/v1/*` aliases).
- Added shared web service module for system status (`penguin/web/services/system_status.py`) to keep routes thin.
- `vcs.get` now includes real branch + dirty + ahead/behind fields.
- `vcs.branch.updated` now emits via event bus on branch changes detected during VCS status reads.
- Background VCS watcher is enabled in web app lifespan to emit branch updates proactively.
- File-modifying action paths now emit `lsp.updated` and `lsp.client.diagnostics` refresh events.
- SSE session filtering now passes global VCS/LSP events so TUI subscribers with `session_id` still receive them.
- Penguin-mode TUI bootstrap now fetches and hydrates `/path`, `/vcs`, `/formatter`, and `/lsp` data.
- `path/vcs/formatter/lsp` now support directory/session scoped queries (`directory`, `session_id`) for multi-worktree workflows.
- VCS branch watcher now checks default scope and session-scoped directories for proactive multi-session updates.
- SSE session filtering now only forwards global VCS/LSP events cross-session when no session is attached.
- Added automated VCS hardening tests covering non-git, dirty/clean, no-upstream, detached HEAD, and linked worktrees.
- Request-scoped execution context now drives tool/file root resolution for concurrent session safety.
- Engine initialization-order bug was fixed so web mode no longer silently falls back to legacy processing.
- Streaming scope/finalization now carries explicit session hints (`session_id:agent_id`) across chunk + finalize paths.
- Manual two-session Cadence/Tuxford runs on one server now complete multi-turn prompts with substantially improved isolation.
- Session list/history parity is still incomplete vs full OpenCode API.
- Added OpenCode-compatible permission/question route surface (`/permission`, `/question`, reply/reject variants, plus `/api/v1/*` aliases).
- Approval callbacks now bridge to OpenCode SSE events (`permission.asked`, `permission.replied`) via `opencode_event` payloads.
- Added question event callback bridge (`question.asked`, `question.replied`, `question.rejected`) with a dedicated question manager backing store.
- Added blocking `<question>` action execution in parser/engine flow backed by `QuestionManager.wait_for_resolution`, so runs pause until user reply/reject (OpenCode-style).
- Agent mode (`build`/`plan`) now persists at session level and is exposed through session payloads.
- Mode is propagated into request execution context for policy decisions.
- Plan mode is now hard-enforced at policy layer: non-read tool operations are denied by `AgentModePolicy`.
- `<execute>` action now routes through permission-gated `code_execution` tool checks (closing direct IPython bypass path in plan mode).
- Engine now appends a transient plan-mode system notice to LLM request messages when `agent_mode=plan`, so the model is explicitly informed of read-only constraints.
- Part-event action-tag filtering now treats backtick/escaped tag literals as display text, preventing response truncation when assistants mention examples like ``<spawn_sub_agent>`` inline.
- OpenAI OAuth subscription routing now works end-to-end against the ChatGPT Codex backend with explicit diagnostics (`diag_id` + upstream trace headers), requested-model preservation (for example `gpt-5.4`), and no silent fallback downgrade.

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
- Progress (2026-03-09): implemented `/find/file` + `/api/v1/find/file` route parity (OpenCode-style `query/dirs/type/limit`), directory+file results with hidden-path ordering, per-directory in-memory index caching for autocomplete bursts, and scoped-directory fallback when explicit `directory` is omitted.
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

**Refactor strategy (agreed)**
- Prefer direct refactors in core Penguin modules and existing web routes when the work is broadly useful.
- Keep OpenCode compatibility as schema/adapter logic in shared services, not as a separate product surface by default.
- Introduce a dedicated compatibility router only for truly OpenCode-only endpoint semantics that do not improve Penguin’s native API.
- System status endpoints (`path/vcs/formatter/lsp`) are directory-scoped per request/session for multi-worktree and agent workflows.

## Progress Snapshot (Phases)
- Phase 0 (Streaming + animation parity): **mostly complete**.
- Phase 1 (Session list + metadata): **partial**.
- Phase 2 (Provider/model picker): **partial**.
- Phase 3 (Tool execution UI + persistence): **partial** (live rendering is strong; persistence/replay still incomplete).
- Phase 4 (Permissions + questions): **partial**.
- Phase 5 (LSP/Formatter/Path/VCS real implementations, MCP deferred): **partial**.

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
- Progress (2026-03-07): added OpenCode-compatible `/permission` and `/question` listing/reply routes (and `/api/v1/*` aliases), plus SSE bridge events for permission/question ask/reply/reject flows.
- Progress (2026-03-07): parser now supports `<question>` tool calls with OpenCode-shaped payloads and blocks execution until `question.reply`/`question.reject` resolves the request.

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

1) **Route + service refactor (preferred)**
   - Refactor existing `penguin/web/routes.py` into focused service modules.
   - Add OpenCode-compatible payload adapters in shared service layer.
   - Keep endpoint aliases only where naming compatibility is required.

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

### Immediate execution order (2026-03-06)
1. Close `B2` session discoverability/scoping in TUI bootstrap and session list APIs.
   - Policy decision: show sessions from the exact requested directory plus sessions in the same git/worktree project root.
2. Close `E6` mode parity with explicit security-mode review (`read_only`/`workspace`/`full` + approval semantics).
3. Close `E3` + `E7` sub-agent/event consistency (`agent_id` on message/tool envelopes + reliable sub-agent session lifecycle).
4. Add response timing telemetry surface (time per response) in backend payloads + TUI display.
5. Execute Track I stability/ergonomics items.
6. Expand provider coverage (OpenAI + Anthropic) before OAuth closeout.
   - Scope: OpenRouter already in place; defer OpenCode Zen/ZenMux and wider catalog expansion for now.
   - Execution: Track C4 (provider coverage) -> Track C3 (OAuth closeout).
7. Run Track J bridge extraction and cleanup last.

## VCS Hardening Matrix (Worktrees First)

### Target VCS payload contract
- `vcs.get` returns:
  - `vcs`: `"git" | "none"`
  - `root`: shared git root path
  - `worktree`: active worktree root path
  - `branch`: current branch (empty when detached)
  - `detached`: boolean
  - `head`: short commit SHA
  - `upstream`: tracking branch (empty if missing)
  - `dirty`: boolean
  - `ahead`: integer
  - `behind`: integer
  - `error`: empty string on success, message when unavailable

### Target `vcs.branch.updated` event payload
- `branch`, `detached`, `head`, `worktree`
- Emit only on effective branch/head identity change.

### Scenario matrix (must pass)
1. Normal git repo on tracked branch.
2. Linked git worktree.
3. Detached HEAD.
4. Branch with no upstream.
5. Dirty worktree (tracked + untracked changes).
6. Clean worktree.
7. Non-git directory.
8. Branch switch in current worktree emits one update event.
9. Branch switch in linked worktree emits update with correct worktree.
10. Ahead/behind divergence with upstream.
11. Git command/transient failure still returns stable schema.
12. Endpoint remains responsive in large repos.

### Track A: Stabilize Existing Work
- [x] A1. Persist tool parts in session history and replay them in `/session.messages`.
  - Owner: `penguin/tui_adapter/part_events.py`, `penguin/web/routes.py` + new `penguin/web/services/session_view.py`, `ConversationManager` storage adapters.
  - Acceptance: reload shows identical tool cards/order as live run.
  - Progress (2026-02-28): added persistence/replay regression coverage for live `message.*` + `message.part.*` tool events and transcript order replay.
- [x] A2. Extend action-to-tool mapping coverage for remaining common actions.
  - Owner: `penguin/core.py` mapping helpers.
  - Acceptance: no major action appears as generic white inline text in TUI.
  - Progress (2026-02-28): expanded coding-workflow action mapping (`enhanced_write`, `multiedit`, `insert_lines`, `delete_lines`, `enhanced_diff`, `workspace_search`) to OpenCode tool cards.
- [x] A3. Add diff metadata generation for `replace_lines` and `edit_with_pattern`.
  - Owner: `penguin/core.py` mapper + `penguin/tools/core/support.py` helpers.
  - Acceptance: these actions render block diff views in OpenCode TUI.
  - Progress (2026-02-28): `replace_lines` now returns unified diff output, `edit_with_pattern` emits workspace-relative diff headers, and action-result metadata extraction now persists `metadata.diff` for replay/session diff.

### Track B: API/Service Refactor (No dedicated compatibility router by default)
- [ ] B1. Split `penguin/web/routes.py` by concern (session/config/system/status) with shared service modules.
  - Owner: `penguin/web/routes.py`, `penguin/web/app.py`, `penguin/web/services/*`.
  - Acceptance: route handlers are thin and business logic is testable in services.
- [~] B2. Implement `session.list`, `session.get`, `session.messages` with OpenCode-shaped payloads.
  - Owner: `ConversationManager` + `penguin/web/services/session_view.py` adapters.
  - Acceptance: TUI loads sessions and history without Penguin-mode-only shims.
  - Decision (2026-03-06): session visibility should include exact directory matches plus sessions sharing the same git/worktree project root; unrelated directories should be hidden.
  - Progress (2026-03-06): `session.list` directory filtering now validates/normalizes requested directories and includes sessions from the exact directory plus same git/worktree project identity (git common dir), with exact-directory-only fallback outside git; Penguin-mode bootstrap no longer falls back to unscoped `/api/v1/conversations` when `/session` returns empty.
- [x] B3. Implement `session.status`, `session.update`, `session.delete`, `session.create`.
  - Owner: web routes + `ConversationManager` + service adapters.
  - Acceptance: create/rename/delete session flows work from TUI.
  - Progress (2026-02-21): added `/session/status`, `POST /session`, `PATCH /session/{id}`, `DELETE /session/{id}` and `/api/v1/*` aliases, backed by `session_view` service helpers with route/service coverage in `tests/api/test_opencode_session_routes.py` and `tests/api/test_session_view_service.py`.
- [~] B4. Implement `session.summarize` as Penguin-native title generation (no OpenCode compaction semantics).
  - Owner: web routes + `session_view` service + lightweight title generation service.
  - Acceptance: resumed sessions show generated titles in picker/tab/header without manual rename.
  - Contract:
    - `POST /session/{id}/summarize` (+ `/api/v1/session/{id}/summarize` alias) returns `boolean` for SDK compatibility.
    - Accept OpenCode-shaped body `{ providerID, modelID, auto? }`; `auto` is accepted as a compatibility field and ignored in v1.
    - Execute one backend title-generation call (provider/model override when supplied, runtime model fallback otherwise), then apply deterministic heuristic fallback if model generation fails.
    - Preserve Penguin context-window strategy (no compaction/truncation side effects).
    - Emit `session.updated` when title changes so TUI session list/header refresh immediately.
  - Progress (2026-03-03): added `POST /session/{id}/summarize` + `/api/v1` alias; body now accepts OpenCode-compatible `{providerID, modelID, auto?}` (`auto` ignored in v1). Implemented lightweight title-generation service with provider/model override support and deterministic fallback; route now emits OpenCode-shaped `session.updated` on title changes. Added non-blocking auto title refresh after `/api/v1/chat/message` using explicit-metadata-title detection (so inferred first-user titles can still be upgraded), retry-on-empty-snippet handling, request-text fallback snippets, placeholder/empty-content title rejection, and explicit `session.summarize` / `session.title.auto_refresh` server logs for observability.
- [~] B5. Implement `session.abort` and wire cancel semantics for active stream/tool runs.
  - Owner: web routes + stream manager/session state in `core.py`.
  - Acceptance: pressing cancel key in TUI reliably stops in-flight assistant output.
  - Progress (2026-03-01): `session.abort` now cancels active + queued `/api/v1/chat/message` tasks, force-finalizes active stream/tool parts as aborted errors, clears per-session in-flight tool tracking, and emits deterministic `session.status=idle` events; deep subprocess hard-kill remains deferred.
- [ ] B6. Add standalone session summary snapshot service (separate from context-window compaction).
  - Owner: `penguin/web/services/session_view.py` + summary service module + route adapters.
  - Acceptance: users can request/read concise session summaries without mutating runtime context trimming behavior.

### Track C: Settings / Provider / Model UX
- [x] C1. Implement `config.get` with runtime config + reasoning + active model metadata.
  - Owner: `penguin/web/routes.py`, `core.runtime_config`, model config adapters.
  - Acceptance: settings panel reflects current values and capabilities.
  - Progress (2026-02-22): `config.get` now merges resolved config settings with runtime state, includes richer reasoning metadata (`enabled/effort/max_tokens/exclude/supported`), and emits active model/runtime capability metadata via the `penguin` block.
- [x] C2. Implement `config.providers` and `provider.list` mapped from Penguin model configs.
  - Owner: `penguin/config`, `penguin/llm/model_config.py`, route adapters.
  - Acceptance: model/provider picker loads valid options.
  - Progress (2026-02-22): provider/model IDs now use provider-local model IDs with provider-qualified selector strings for `config.model`; `config.providers.default` uses local model IDs; provider sets include env-connected providers and `list_available_models()` runtime sources so picker defaults and connected-state are consistent.
  - Progress (2026-02-22): OpenRouter-authenticated sessions now merge live OpenRouter catalog models into provider payloads (`config.providers` and `provider.list`) with cached fetches, so the TUI picker can surface broader gateway model options beyond static config entries.
- [~] C3. Implement provider auth contract (`provider.auth`, `auth.set/remove`, OAuth authorize/callback).
  - Owner: web routes + provider auth store service.
  - Acceptance: endpoint set supports OpenRouter API-key auth and OpenAI/ChatGPT Pro OAuth handshake flow with stable payloads.
  - Finalization note: current OpenAI device OAuth uses a compatibility client id mirrored from OpenCode; one of the last Phase C steps is to make client id fully Penguin-owned/configurable (env override first, then first-party registration when available).
  - C3 closeout checklist:
    - [x] Decision (2026-03-11): immediately match OpenCode method ordering for OpenAI auth methods (`0=browser`, `1=headless`, `2=api`) even though prior Penguin behavior used `0=headless`.
    - [x] Refactor provider auth flow shape to OpenCode-style authorize/pending/callback orchestration with provider+method validation.
    - [x] Add loud stage-tagged OAuth diagnostics/errors (no implicit fallback behavior that hides method/order bugs).
    - [x] Add env override for OAuth client id (`PENGUIN_OPENAI_OAUTH_CLIENT_ID`).
    - [ ] Register Penguin first-party OpenAI OAuth client id and switch default to Penguin-owned id.
    - [ ] Keep compatibility fallback id only as an explicit fallback path (not the default) after rollout validation.
  - Progress (2026-02-19): starting Phase C implementation with a dedicated Penguin provider-auth store and OpenCode-compatible config/provider endpoints.
    - Progress (2026-02-20): wired `/config`, `/config/providers`, `/provider`, `/provider/auth`, `/auth/{providerID}`, and `/provider/{providerID}/oauth/*` in `penguin/web/routes.py`; added `/api/v1/*` aliases; added route + service tests (`tests/api/test_opencode_provider_routes.py`, `tests/api/test_opencode_provider_service.py`); switched Penguin-mode TUI bootstrap to consume backend config/provider/auth endpoints first with fallback.
    - Progress (2026-02-21): refactored provider/auth backend into general-purpose services (`provider_catalog.py`, `provider_credentials.py`, `provider_auth.py`) and reduced `opencode_provider.py` to compatibility mapping wrappers; credentials default to user-global `~/.config/penguin/providers/credentials.json` (0600, atomic writes) with legacy-path compatibility.
  - Progress (2026-02-21): OpenAI device OAuth client id is now overridable via `PENGUIN_OPENAI_OAUTH_CLIENT_ID` with compatibility fallback to current OpenCode/Codex client id while first-party Penguin registration is pending.
  - Progress (2026-03-11): queued auth-contract alignment refactor before additional OpenAI OAuth subscription routing work so method ordering and diagnostics are stabilized first.
  - Progress (2026-03-11): auth methods now follow OpenCode ordering (`browser`, `headless`, `api`), OAuth route payloads require explicit `method`, and provider auth emits stage-rich errors for authorize/poll/token/callback failures.
  - Progress (2026-03-11): OAuth callback now applies credentials to runtime immediately; OpenAI OAuth requests now route through the Codex backend with required payload contract updates (system prompt to top-level `instructions`, no `system` role in `input`, assistant history mapped as `output_text`, stream transport on this path, and `max_output_tokens` omitted for Codex-compatibility).
  - Progress (2026-03-11): OpenAI OAuth diagnostics now include per-request IDs (`oaoc_*`), normalized failure categories, and upstream trace headers; user-visible failures stay concise with a diagnostic ID while server logs retain full details.
- [~] C4. Expand provider coverage parity beyond OpenRouter (scoped first pass: OpenAI + Anthropic).
  - Owner: `penguin/web/services/provider_catalog.py`, `penguin/web/services/opencode_provider.py`, model-loading path in `core.py`/`model_config.py`.
  - Acceptance:
    - `config.providers` and `provider.list` reliably include OpenAI + Anthropic with OpenCode-compatible metadata even when not explicitly defined in local `model_configs`.
    - model/provider selection for those entries resolves runtime provider/client wiring correctly.
  - Scope decision (2026-03-09): do not add OpenCode Zen (`opencode`) or ZenMux in this pass; keep focus on OpenAI + Anthropic because OpenRouter coverage is already implemented.
  - Progress (2026-03-09): provider payload builders now merge cached `models.dev` catalogs for OpenAI + Anthropic into both `config.providers` and `provider.list` (provider-local model IDs, capability/cost/limit metadata, release dates), while preserving OpenRouter catalog expansion and local-config precedence.
  - Progress (2026-03-09): provider visibility filters (`enabled_providers`, `disabled_providers`) are now applied consistently to provider/model payload outputs so picker contents match config policy.
  - Progress (2026-03-09): model switch provider inference now defaults OpenAI/Anthropic selections to native runtime wiring (instead of inheriting OpenRouter from the currently active model), while preserving explicit `openrouter/...` gateway routing.
  - Progress (2026-03-09): `core.load_model` now resolves provider/client before model-spec lookup, only requires OpenRouter catalog specs for OpenRouter-routed models, and records explicit `_last_model_load_error` reasons for route-level 400 responses.
  - Progress (2026-03-09): runtime model canonicalization now strips provider prefixes for native OpenAI/Anthropic adapters (e.g. `openai/gpt-5` -> `gpt-5`) and strips `openrouter/` wrapper prefixes for OpenRouter runtime model IDs.
  - Progress (2026-03-09): Anthropic native adapter streaming now awaits async callbacks and preserves `(chunk, message_type)` semantics (including `thinking_delta -> reasoning`); this fixes dropped stream delivery in async callback pipelines.
  - Progress (2026-03-09): OpenCode stream bridge now synthesizes a final assistant part delta from finalize payload content when a provider emits no assistant chunk deltas, preventing blank Penguin-mode SSE turns on otherwise successful responses.
  - Progress (2026-03-09): web startup now rehydrates persisted provider credentials into runtime state so Anthropic/OpenAI API keys from the provider auth store are available immediately after server restart.
  - Progress (2026-03-10): OpenAI native adapter now accepts `OPENAI_OAUTH_ACCESS_TOKEN` (with optional `OPENAI_ACCOUNT_ID` header) as credential fallback, enabling OpenCode OAuth-connected OpenAI usage in native mode when `OPENAI_API_KEY` is absent.
  - Progress (2026-03-10): OpenAI streaming now emits a synthetic assistant callback chunk from final response text when delta events are absent (`responses.stream`/SSE done/completed cases), preventing blank OpenAI turns in Penguin-mode SSE clients.
  - Progress (2026-03-10): OpenAI streaming now maps Responses reasoning-summary event families (`response.reasoning_summary_text.delta`, `response.reasoning_summary_part.*`, and related reasoning deltas) into `reasoning` chunks, and requests concise streamed summaries (`reasoning.summary=concise`) for reasoning-enabled calls so Penguin-mode reasoning parts render for GPT-5.x flows with lower added latency.

### Track D: Diffs, Files Sidebar, VCS
- [x] D1. Implement `vcs.get` with real git-backed branch + dirty status.
  - Owner: `penguin/web/routes.py` + lightweight git adapter utility.
  - Acceptance: sidebar shows branch and updates after branch switch.
- [x] D2. Implement `session.diff` using persisted snapshots/tool outputs and/or git diff.
  - Owner: conversation persistence + route adapters.
  - Acceptance: diff sidebar/widget populates with changed files + patch data.
  - Progress (2026-02-21): `/session/{id}/diff` and `/api/v1/session/{id}/diff` now return FileDiff entries sourced primarily from persisted transcript tool metadata, with git diff fallback when transcript diffs are unavailable.
- [x] D3. Emit `vcs.branch.updated` when branch changes are detected.
  - Owner: event bus + vcs poll/trigger hook.
  - Acceptance: TUI updates branch without restart.

**VCS Hardening status**
- Stable foundation implemented for directory/session-scoped multi-worktree usage.
- Scenario matrix core cases validated manually + automated service tests in `tests/api/test_vcs_status_service.py`.
- Added OpenCode-shaped `/session`, `/session/{id}`, and `/session/{id}/message` adapters backed by session view services.
- Added persisted OpenCode transcript storage (`_opencode_transcript_v1`) from live `message.*` and `message.part.*` events.
- Session->directory binding is now immutable by default (rebind attempts return 409).
- Web request execution now uses request-scoped execution context plumbing instead of route-level root mutation.
- Tool execution root resolution is now context-driven (`directory/project_root/workspace_root`) for parallel session safety.

### Track H: Concurrent Session Isolation
- [x] H1. Introduce request-scoped execution context across web request -> tool execution.
  - Owner: `penguin/system/execution_context.py`, `penguin/web/routes.py`, `penguin/tools/tool_manager.py`, `penguin/utils/parser.py`.
  - Acceptance: concurrent sessions in different repos resolve `pwd`, file tools, and command tools to the correct bound directory.
- [~] H2. Remove remaining implicit global root dependencies (`os.getcwd`, env-root assumptions) from tool and parser paths.
  - Owner: tool helpers and security/path enforcement integration.
  - Acceptance: no request path requires global `PENGUIN_CWD` mutation for correctness.
  - Progress: Engine component resolution now uses agent-scoped conversation manager views (no `set_current_agent` mutation in Engine request path); core request path now prefers scoped managers and context-based event/session tagging.
  - Progress: OpenCode event translation now uses session-scoped TUI adapters/tool-part keys and per-session stream state tracking in `core.py` to prevent cross-session part/message state collisions.
  - Progress: Engine wallet-guard loop state moved to per-run state (`EngineRunState.loop_state`) to avoid concurrent iteration cross-talk.
  - Progress: core streaming manager keys now resolve to request scope (`session_id:agent_id`) instead of agent-only identity in `_handle_stream_chunk` / `finalize_streaming_message`.
  - Progress: stream callback and finalize paths now forward explicit `session_id`/`conversation_id` hints to avoid fallback-to-global session labeling.
  - Progress: Engine finalize call sites pass session-derived scope hints for deterministic message completion routing.
  - Progress: `PartEventAdapter` now balances session `busy`/`idle` lifecycle for both stream and tool-only flows and finalizes tool-created assistant messages.
  - Progress (2026-02-21): `PartEventAdapter` path metadata now prefers session/runtime/execution-context directory via `set_directory`, and core adapter acquisition propagates session-resolved directory hints so event paths no longer rely on global cwd in normal request flow.
- [x] H3. Add explicit parallel multi-session API tests (two sessions, two repos, concurrent prompts/actions).
  - Owner: `tests/api/*`.
  - Acceptance: no cross-session directory bleed under concurrent execution.
  - Progress: added `tests/api/test_concurrent_session_isolation.py` validating parallel `execute_command (pwd)` and file write/read isolation across two repo roots.
- [~] H4. Run a focused mutable-state isolation audit before production-safe declaration.
  - Owner: `penguin/core.py`, `penguin/engine.py`, `penguin/system/conversation_manager.py`, web routes/SSE adapters.
  - Acceptance: all request-dependent fields are either request-scoped (`contextvars`) or local variables; no cross-request reliance on shared mutable pointers.
  - Audit checklist:
    - Verify no request path mutates shared active conversation/session pointers without scoping.
    - Verify event/session identifiers are sourced from request context, not process-global fields.
    - Verify concurrent same-process requests across different repos/sessions do not cross-write files/messages.
    - Verify fallback (legacy/no-engine) path behavior is documented and gated if not fully isolated.
  - Progress (2026-02-19): fixed Engine construction ordering to prevent accidental legacy fallback in web runtime; remaining work is sustained concurrency soak coverage and final checklist sign-off.
  - Progress (2026-02-21): targeted parity/concurrency regression pack passed (`33 passed`) including `tests/api/test_concurrent_session_isolation.py`, `tests/api/test_session_directory_binding.py`, and `tests/api/test_sse_and_status_scoping.py`; keep track open until extended soak + manual gate repeats are complete.

#### Concurrent hardening execution mirror (from `tui-opencode-port.md`)
- Objective: production-safe concurrent OpenCode web sessions for same-agent (`default`) multi-turn usage across repos, without queued/stuck UI.
- Root cause hypothesis: stream lifecycle was keyed by `agent_id` (`default`) instead of session scope, causing shared-state collisions.
- Additional finding: single-session stuck states can occur when tool fallback opens `session.status=busy` without a guaranteed idle transition.
- Ordered implementation tracks:
  1) Add deterministic stream scope key (`session_id:agent_id`) through core stream handling and `AgentStreamingStateManager`.
  2) Remove ambiguous/double finalize paths so each iteration finalizes exactly once with explicit scope.
  3) Ensure default-agent request paths use scoped conversation handles (no shared mutable pointer reliance).
  4) Guarantee completion ordering (critical final events awaited or flush-barriered before REST return).
  5) Harden TUI adapter lifecycle: session-scoped adapters, namespaced tool keys, bounded adapter cleanup, and balanced busy/idle transitions.
  6) Publish formal audit artifact + docs invariants (`stream scope key`, immutable binding, completion ordering).
- Test matrix mirror:
  - Unit stream scope isolation (`tests/llm/test_stream_scope_isolation.py`).
  - Unit core routing (`tests/test_core_stream_scope.py`).
  - API parallel multi-turn default-agent isolation (`tests/api/test_concurrent_session_isolation.py`).
  - API SSE filtering/final completion correctness (`tests/api/test_sse_and_status_scoping.py`).
  - Regression keeps: binding + execution-context + multi-agent smoke.
  - Manual gates: two-session Cadence/Tuxford (5 prompts each) + single-session 5-prompt no-stuck regression.
  - Latest manual signal (2026-02-19): two-session same-server runs are now mostly stable; keep this track open until repeated long-run stress passes complete.

### Track E: Plan/TODO + Agent Features
- [x] E1. Implement `session.todo` with standalone session-scoped todo storage (OpenCode parity first; decoupled from `ProjectManager` task graph).
  - Owner: `penguin/web/services/session_view.py`, `penguin/web/routes.py`, parser/core todo handlers.
  - Acceptance: todo panel shows stable list with statuses.
  - Progress (2026-02-28): added `GET /session/{id}/todo` (+ `/api/v1` alias) backed by persisted `_opencode_todo_v1` session metadata.
- [x] E2. Emit `todo.updated` for `todowrite`/todo mutation flows.
  - Owner: parser/core event emission + SSE bridge.
  - Acceptance: todo panel updates live.
  - Progress (2026-02-28): `todowrite` now persists normalized todos and emits `todo.updated`; core bridges event to OpenCode-shaped `opencode_event` payload.
- [~] E3. Implement `app.agents` and ensure message/tool events carry `agent_id` consistently.
  - Owner: `core.py` agent roster + event adapter.
  - Acceptance: multi/sub-agent UI and filtering behave correctly.
  - Progress (2026-03-07): enriched agent roster payloads with mode/permission/options metadata for OpenCode TUI parity; full sub-agent lifecycle consistency remains open.
- [~] E4. Implement variant/mode + reasoning effort plumbing in `session.prompt`/config.
  - Owner: route adapter + `core.process` parameter mapping.
  - Acceptance: toggling mode/effort affects runtime behavior and is reflected in metadata.
- [x] E5. Complete command palette parity (`Ctrl+P`) including settings/workflow commands in Penguin mode.
  - Owner: TUI command registry + route parity adapters.
  - Acceptance: settings and session/model/agent actions are discoverable from the palette.
  - Progress (2026-03-05): Penguin keybind defaults now hydrate when server config omits `keybinds`, restoring working `Ctrl+P` in Penguin mode; command palette now includes Configuration inspector flow (`/config`, with `/settings` alias) and opens a read-only runtime/config-path dialog.
- [~] E6. Implement agent mode parity (`plan`/`build`/default) and mode-aware routing.
  - Owner: TUI agent context + backend prompt/command dispatch metadata.
  - Acceptance: mode switch changes runtime behavior and is preserved in message metadata.
  - Policy decision (2026-03-07): plan mode is hard-blocked at policy layer (not prompt-only).
  - Progress (2026-03-07): mode now flows from TUI prompt/session update into backend request context, persists on session metadata, and is enforced by `AgentModePolicy` to allow read operations while denying non-read actions in `plan` mode.
- [~] E7. Complete sub-agent lifecycle parity.
  - Owner: agent roster API, message routing, session hierarchy handling.
  - Acceptance: sub-agent tasks appear as first-class sessions with reliable replay/navigation.
  - Progress (2026-03-07): isolated sub-agent sessions now inherit explicit parent linkage metadata (`parentID`, `parent_agent_id`) at creation time, parser `spawn_sub_agent` now emits `session.created` OpenCode events for live TUI discovery, and Penguin-mode sync now handles `session.created` events in the session store path.
  - Progress (2026-03-07): conversation manager edits were minimized to focused linkage logic (no broad formatting churn), with parity regression pack passing (`62 passed`).
  - Progress (2026-03-08): ActionXML parser now supports sub-agent status/context lifecycle tags (`get_agent_status`, `wait_for_agents`, `get_context_info`, `sync_context`) with compatibility aliases (`agent_id`, `agent_ids`, `parent_agent_id`, `child_agent_id`) mapped to canonical tool inputs.
- [~] E8. Context/tokens/cost telemetry parity in sidebar/header.
  - Owner: backend usage accounting + TUI metadata rendering.
  - Acceptance: token usage, context %, and spend reflect real provider usage (including OpenRouter).
  - Progress (2026-03-05): OpenRouter gateway now captures normalized request usage (`prompt/completion/reasoning/cache`) and reported cost when available, and `core.process` propagates that metadata to the latest assistant `message.updated` envelope so sidebar/header spend + token counters can render non-zero values.
  - Progress (2026-03-05): Engine now returns per-turn usage from the active resolved API client (including agent-scoped clients), and `core.process` now prefers that engine-returned usage before fallback handler reads to avoid missing cost metadata in multi-agent/session-scoped runs.
  - Progress (2026-03-05): Usage application now falls back to session-scoped adapter message tracking when stream-state keys are absent, adapter usage updates can upsert missing assistant message state, and OpenRouter/core usage-application logs are mirrored through `uvicorn.error` for runtime observability during live web sessions.
  - Progress (2026-03-06): direct OpenRouter streaming now attempts low-latency usage recovery via `GET /generation?id=...` when streams are intentionally interrupted early (action/tool interrupt path), reducing `No usage data captured (direct-stream)` gaps without waiting for full stream completion.
- [ ] E9. Context-window/truncation visualization parity (no compaction assumptions).
  - Owner: session metadata payloads + TUI context widgets.
  - Acceptance: users can see context pressure/truncation behavior even when compaction is not used.
- [~] E10. Reasoning variants parity (`Ctrl+T` effort/options) in Penguin mode.
  - Owner: config endpoints + prompt payload schema + TUI variant UI.
  - Acceptance: reasoning variant controls are available and affect model requests.
  - Progress (2026-03-05): `config.providers`/`provider.list` model payloads now expose reasoning variants (`low/medium/high`) for reasoning-capable models (OpenRouter-first), Penguin prompt submit now includes `variant` in `/api/v1/chat/message`, and backend routes apply per-request reasoning-effort overrides without mutating persistent model defaults.
  - Progress (2026-03-06): `ModelConfig.get_reasoning_config()` now prioritizes explicit `reasoning_effort` overrides before provider-style defaults, so `variant=low|medium|high` reliably changes emitted OpenRouter reasoning payloads for reasoning-capable models (including Anthropic/Gemini-family routing where effort can be mapped upstream).
  - Progress (2026-03-09): OpenRouter model variant payloads now expose a closer OpenCode effort surface (`none/minimal/low/medium/high/xhigh` for GPT/Gemini-3 families, plus Grok-3-mini low/high), route-level variant overrides now accept expanded effort values (plus `max`/`off` semantics), explicit per-request variants force reasoning payload emission even when capability heuristics are conservative, and OpenRouter gateway logs the resolved reasoning payload/config state for every request.
  - Progress (2026-03-10): native provider variant handling is now provider/model-aware for OpenAI + Anthropic with conservative exposure (to avoid unsupported effort submissions), route-level overrides validate against those provider/model effort sets, and Anthropic native requests now map accepted effort variants through `output_config.effort` (`extra_body`) to match current Claude API guidance.

### Track I: Penguin-mode UX and Runtime Ergonomics
- [ ] I1. Resolve occasional queued/stuck turn behavior under streaming-heavy runs.
  - Owner: stream lifecycle ordering + event flush/completion audit (`core.py`, TUI sync state).
  - Acceptance: turns consistently move busy -> idle without stranded queued prompts.
- [ ] I2. Ensure TUI/server directory coherence when launched from different working dirs.
  - Owner: launcher/runtime directory handshake + immutable session directory binding.
  - Acceptance: tool execution roots match active project immediately, without corrective follow-up commands.
  - Decision (2026-03-11): use a command dispatcher surface where `penguin` defaults to Penguin TUI, `ptui` is a direct TUI alias, and `penguin-cli` is the explicit headless entrypoint for scripts/automation.
  - Decision (2026-03-11): TUI runtime is opt-in via `pip install "penguin-ai[tui]"`; base installs remain headless/container-friendly.
  - Decision (2026-03-11): phase-1 behavior is fail-fast when TUI runtime is unavailable (clear install hint + non-zero exit); automatic fallback to headless CLI is deferred until after startup reliability validation.
  - Scope guard (2026-03-11): keep `litellm` and `ollama` in base dependencies for now; dependency slimming is tracked separately and is not a blocker for I2 startup work.
  - I2 execution checklist (planned):
    - [x] I2.a Add a `penguin` dispatcher entrypoint with deterministic routing (`tui` default, known headless commands/flags pass through to CLI).
    - [x] I2.b Add script surface updates in `pyproject.toml` (`penguin-cli`, `ptui`) and retire `penguin-opencode` naming in user-facing docs/entrypoints.
    - [x] I2.c Add a `tui` optional dependency group and runtime preflight checks for TUI launcher prerequisites.
    - [x] I2.d Implement fail-fast UX for missing TUI runtime with actionable remediation (`pip install "penguin-ai[tui]"`) and explicit `penguin-cli` alternative.
    - [~] I2.e Preserve developer override path (`PENGUIN_OPENCODE_DIR`) while introducing sidecar bootstrap/cache/checksum flow for non-dev installs.
      - Progress (2026-03-11): launcher now keeps local-source override behavior and adds sidecar bootstrap with cache + checksum verification (`~/.cache/penguin/tui` by default, release URL overridable via env), enabling non-dev TUI runs without Bun/global OpenCode.
      - Progress (2026-03-11): sidecar default release source now points to Penguin repo releases (not upstream OpenCode), launcher enforces Penguin compatibility for sidecar binaries (`--url` support required), and global `opencode` fallback remains attach-mode only when explicitly requested.
      - Follow-up (post-merge cleanup): remove temporary branch-specific trigger from `.github/workflows/publish-tui.yml` (`refactor-penguin-backend-tui`) after mainline validation is complete.
    - [~] I2.f Add startup/directory coherence regression tests covering dispatcher routing, web autostart health checks, and session-bound execution roots.
      - Progress (2026-03-11): added dispatcher routing tests (`tests/test_cli_entrypoint_dispatcher.py`) and launcher startup regressions (`tests/test_opencode_launcher.py`) for web autostart success/failure and project-directory environment coherence (`PENGUIN_CWD`/`PENGUIN_PROJECT_ROOT`/`PWD`). Session-bound root behavior through full `/session` request flow remains open.
- [ ] I3. Finish Penguin branding pass in Penguin mode.
  - Owner: TUI home/status/footer copy + theme/assets.
  - Acceptance: no confusing OpenCode-specific branding in Penguin mode (logo/footer/help text), while preserving upstream defaults outside Penguin mode.
- [ ] I4. Add explicit exit/cancel keybind guidance and safer default behavior for `Ctrl+C`/interrupt flows.
  - Owner: keybind layer + prompt/session route handlers.
  - Acceptance: users can predictably interrupt or exit without leaving stuck state.

### Track J: Core/TUI Bridge Extraction (Final Cleanup)
- [ ] J1. Extract OpenCode/TUI event subscription + handlers from `core.py` into a dedicated bridge module.
  - Owner: `penguin/core.py`, `penguin/tui_adapter/*`.
  - Acceptance: `core.py` delegates stream/action/todo/lsp event wiring and handler execution without behavior change.
- [ ] J2. Extract action-to-tool mapping + result metadata shaping into a dedicated mapping module.
  - Owner: `penguin/tui_adapter/tool_mapping.py`.
  - Acceptance: `_map_action_to_tool` and `_map_action_result_metadata` logic no longer lives in `core.py`.
- [ ] J3. Extract transcript persistence + session store lookup helpers into a focused persistence module.
  - Owner: `penguin/tui_adapter/transcript_store.py`.
  - Acceptance: `_persist_opencode_event` path is moved behind a focused interface and replay tests remain green.
- [ ] J4. Extract session runtime bookkeeping (`abort`, active request counters, `session.status` emit) into a runtime helper.
  - Owner: `penguin/tui_adapter/session_runtime.py`.
  - Acceptance: request lifecycle semantics are unchanged and concurrency/session-status tests remain green.
- [ ] J5. Make `core.py` a thin orchestrator for TUI compatibility concerns.
  - Owner: `penguin/core.py`.
  - Acceptance: no OpenCode parity regressions and measurable net `core.py` line-count reduction.
  - Note: align sequencing with `context/architecture/core-refactor-plan.md` so extraction work composes with existing refactor phases.

### Track F: LSP / Formatter / Path (Real, not stubbed)
- [x] F1. Implement `path.get` from runtime roots (`directory`, `worktree`, `home`).
  - Owner: route adapter + runtime config.
  - Acceptance: sidebar path info is always populated.
- [x] F2. Implement `formatter.status` from actual formatter availability/config.
  - Owner: tool/config layer + route adapter.
  - Acceptance: formatter panel shows real enabled/disabled state by language.
- [x] F3. Implement `lsp.status` with real language server health/status.
  - Owner: new `penguin/lsp/` integration module + route adapter.
  - Acceptance: TUI no longer sees empty/default LSP forever; status tracks active languages.
- [~] F4. Emit `lsp.updated` and `lsp.client.diagnostics` events from file edits.
  - Owner: edit/apply_diff/write tool paths + event bus adapter.
  - Acceptance: diagnostics refresh in TUI after edits.
  - Progress: events now emit for file-modifying action tools.
  - Progress (2026-03-09): diagnostics payloads now include OpenCode-compatible `serverID`/`path` fields plus `count`, normalized severity/source/range entries, and line/column extraction from common tool error messages and structured JSON outputs.

### Track G: Deferred / Later
- [ ] G1. MCP compatibility (`mcp.status/connect/disconnect`) after core parity is stable.
  - Owner: `penguin/integrations/mcp/*` + route adapters.
  - Acceptance: OpenCode MCP dialog can connect/disconnect providers.

### Session + messages
- `session.list({ start, search, limit, directory? })` -> `penguin/web/routes.py` + `penguin/web/services/session_view.py` using `ConversationManager` for list/metadata.
  - Response: `{ sessions: [{ id, title, time, summary?, agent?, model?, tags? }] }`
  - Directory scoping (decision 2026-03-06): include sessions bound to the exact requested directory and sessions in the same git/worktree project root; if no git/worktree root is available, fall back to exact-directory-only matching.
- `session.get({ sessionID })` -> `ConversationManager.get_session(session_id)`.
  - Response: `{ session: { id, title, time, model, provider, agent, status } }`
- `session.messages({ sessionID, limit })` -> history + OpenCode envelopes.
  - Response: `{ messages: [{ info: Message, parts: Part[] }] }` (use `tui_adapter` shapes).
- `session.create({})` -> `ConversationManager.create_session()`.
- `session.update({ sessionID, title })` -> `ConversationManager.update_session_title()`.
- `session.delete({ sessionID })` -> `ConversationManager.delete_session()`.
- `session.status()` -> `ConversationManager.get_status()` + active tool/stream state.
- `session.summarize({ sessionID, providerID?, modelID?, auto? })` -> Penguin-native title generation endpoint (OpenCode-compatible route shape, non-compaction behavior).
  - Request compatibility: accept `{ providerID, modelID, auto? }`; ignore `auto` in v1.
  - Behavior: one backend title-generation call with provider/model override support; fallback to deterministic heuristic title when generation fails.
  - Response: `boolean`.
  - Events: emit `session.updated` when title changes.

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
- `session.todo({ sessionID })` -> standalone session-scoped todo storage in session metadata (`_opencode_todo_v1`) for OpenCode parity.
  - Response: `Todo[]` (`[{ id, content, status, priority }]`).
- `todo.updated` event -> emit on `todowrite` / todo mutation flows and mirror through OpenCode-shaped SSE events.
- Future extension: optionally bridge standalone todo storage with `ProjectManager` tasks after parity/stability milestones.

### Agent modes + variants
- `session.prompt({ sessionID, agent, model, variant, parts })` -> `core.process()` with mode/variant metadata.
- Progress (2026-03-09): `/api/v1/chat/message` and websocket chat now include an OpenCode-style inline `@path` fallback parser (matching `ConfigMarkdown.files` behavior) that resolves existing files relative to the bound session directory and appends them to `context_files` when structured `parts` references are absent.
- Progress (2026-03-09): chat routes now pass the effective session id as `conversation_id` to `core.process`, ensuring session-scoped context file attachments load into the active session even when clients only send `session_id`.
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

## Router Decision Rules
- Use existing route modules + shared services for improvements that benefit Penguin broadly.
- Add a dedicated compatibility router only if OpenCode-specific endpoint names/shapes would otherwise pollute core Penguin APIs.
- Prefer adapter functions over duplicate business logic.
