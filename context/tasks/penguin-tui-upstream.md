# Penguin TUI Upstream Plan

## Context

Penguin's TypeScript TUI lives in `penguin-tui/` and started as a fork of
OpenCode's TUI. The fork now carries Penguin-specific backend integration,
local auth, session scoping, project/task commands, model/provider behavior,
and branding.

The original reason for forking OpenCode's TUI was leverage: avoid building a
terminal UI from scratch while Penguin focuses on backend/runtime capability.
The tradeoff is maintenance against upstream OpenCode/OpenTUI, but that should
still be cheaper than recreating the depth of OpenCode's terminal interface,
event rendering, provider/model UX, session navigation, permission surfaces, and
OpenTUI rendering stack independently.

The goal of this track is to move Penguin's TUI closer to upstream OpenCode
without losing Penguin-specific runtime behavior. The target shape is not a
generic TUI with no Penguin behavior. The target is a smaller, easier-to-review
fork where Penguin differences are isolated near transport, SDK, adapter, or
backend compatibility boundaries.

Related planning docs:

- `context/tasks/tui-opencode-fork-alignment-plan.md`
- `context/tasks/tui-opencode-implementation.md`
- `context/rationale/tui-opencode-tool-bridge.md`
- Link context:
  - `/Users/maximusputnam/Code/Link/Link/context/vision.md`
  - `/Users/maximusputnam/Code/Link/Link/architecture.md`
  - `/Users/maximusputnam/Code/Link/Link/context/timelines/production-v1-tracks.md`

Current local comparison notes:

- The local OpenCode reference is at `reference/opencode`. Its checked-out
  `dev` branch is stale and has local commits, but `origin/dev` was refreshed
  on 2026-05-23 and should be used for comparisons unless the local branch is
  intentionally reset.
- Penguin's fork landed locally on January 31, 2026, around embedded OpenCode
  package version `1.1.48`.
- Upstream OpenCode was at `v1.15.10` on May 23, 2026, so the upstream
  delta is substantial and includes backend/API/event-model changes, not just
  TUI polish.
- The largest Penguin TUI divergence appears concentrated in:
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sync.tsx`
  - `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sdk.tsx`
- A previous local comparison showed broad TUI changes across dozens of files,
  but much of that is likely separable into branding, themes, command additions,
  transport/auth, and session protocol compatibility.

## Link Product Context

Penguin is only one half of the broader product direction. Link is the
AI-native team workspace: humans and agents share channels, tasks, files,
permissions, workspace boundaries, and audit trails. Penguin is the first
registered agent/runtime in that system, not the whole product.

Important Link context:

- Link treats agents as first-class accounts with capabilities, roles,
  permissions, and audit trails.
- Link's PM/orchestration layer is intentionally Penguin-shaped: blueprints,
  ITUV phases, evidence, typed dependencies, and the `DONE != COMPLETED` review
  rule are core semantics.
- Link's runtime stream direction is Link-native. Penguin, A2A, OpenCode, Codex,
  Claude SDK, and future agents should project into Link-owned
  `RuntimeEvent`/`SessionEvent` types rather than leaking their native event
  vocabulary into the frontend.
- The active Link frontend (`apps/web`) is an Agentboard first: sessions,
  artifacts, tool UI, file selection, project worktrees, settings, and Penguin
  integration. Chat/Discord-style channels come after Agentboard stabilizes.
- Link's execution tracks explicitly call out runtime/session rendering as a core
  product surface, not polish: reasoning summaries, grouped tool calls/results,
  approval panels, terminal context, context-window meters, diffs/work-log rows,
  and proposed-plan cards.

This changes how to think about Penguin TUI upstreaming. The TUI is not only a
standalone Penguin interface. It is also a reference implementation for the
runtime surface Link needs: streaming events, session history, tool cards,
permissions/questions, model/provider controls, diff review, and subagent/task
navigation.

## Upstream OpenCode Delta

Since Penguin forked OpenCode's TUI, upstream OpenCode has moved quickly in a
direction that is broadly good for Penguin and Link:

- OpenCode doubled down on client/server architecture. The TUI is one client of
  a server/API, which matches Penguin's compatibility direction and Link's
  runtime-adapter direction.
- OpenCode `v1.2.0` moved session data to SQLite and introduced incremental
  `message.part.delta` events, reducing repeated full-part updates.
- OpenCode has formalized more SDK/API behavior, including v2 session APIs,
  structured public errors, OpenAPI fixes, safer unknown-error responses, and
  global event-stream fixes.
- OpenCode's provider/auth surface has grown: Copilot, GitLab Agent Platform,
  Grok/xAI OAuth, OpenAI/Codex OAuth fixes, model reasoning controls, and many
  provider-specific compatibility repairs.
- The TUI has gained or improved session review, full-session fork flows,
  session picker sorting, local-project defaults, imported-session path refresh,
  PDF drag/drop, prompt duplicate-submit prevention, question UI fixes, and
  malformed tool-input crash handling.
- The TUI now has a diff viewer for reviewing changes, including file-tree
  affordances.
- Upstream has updated OpenTUI dependencies beyond Penguin's embedded
  `@opentui/*` `0.1.75` baseline; a recent release note mentions `0.2.15`.

This is potentially very good news for Penguin. Upstream appears to have solved
or improved several areas Penguin cares about: event delivery, smoothness,
structured errors, diff review, session workflows, provider/model controls, and
runtime UI reliability. The upstreaming question should therefore be framed as:
how do we adopt those improvements while keeping Penguin's backend semantics and
Link's larger runtime-event direction intact?

## Working Goal

Make upstreaming and future rebases easier by reducing UI-layer protocol drift.
Penguin-specific behavior should be retained, but placed behind narrow
interfaces where possible.

Success looks like:

- TUI components remain close to upstream OpenCode structure.
- Penguin transport and auth behavior are localized.
- Session/message/bootstrap compatibility is handled by typed helpers or backend
  API parity, not scattered ad hoc UI code.
- Branding and product features remain explicit and easy to review.
- Future OpenCode syncs require fewer conflict-heavy edits.
- Penguin gets reliability/smoothness gains from upstream OpenCode/OpenTUI
  instead of rebuilding them locally.
- Link can reuse Penguin/OpenCode runtime lessons for its own Agentboard event
  and tool UI surfaces.

## Checklist

### 1. Refresh and baseline upstream

- [x] Fetch latest OpenCode into `reference/opencode`.
- [x] Record the exact upstream commit used for comparison.
- [x] Confirm whether OpenCode's active branch is still `dev` for TUI work.
- [x] Generate a fresh diff/stat for `packages/opencode/src/cli/cmd/tui`.
- [x] Identify files added only by Penguin versus files modified from upstream.
- [x] Record upstream versions for important dependencies, especially
      `@opentui/core`, `@opentui/solid`, `@opencode-ai/sdk`, and the AI SDK.
- [x] Identify upstream changes that are backend/API contract changes versus
      pure TUI changes.

### 1.5. Map upstream gains to Penguin and Link

- [x] Inventory upstream improvements since `v1.1.48` that Penguin should
      preserve or adopt:
  - incremental part deltas
  - v2 session API shapes/errors
  - event replay/projector behavior
  - diff viewer
  - full-session fork/session review
  - provider/model/reasoning UX
  - permission/question UI fixes
  - OpenTUI dependency updates
- [x] Mark each upstream improvement as:
  - adopt directly in TUI
  - adopt by changing Penguin backend compatibility
  - defer because Link will own the surface differently
  - avoid because it conflicts with Penguin/Link semantics
- [x] Compare upstream runtime/session UI concepts against Link Agentboard needs
      from `production-v1-tracks.md`.
- [x] Capture reusable lessons for Link's `RuntimeEvent`/`SessionEvent`
      projection model.


### Phase 1/1.5 Audit Results - 2026-05-23

Branch baseline:

- Worktree branch: `penguin-tui-opencode-upstream`.
- Merged latest `origin/main` into the branch on 2026-05-23. Resulting local
  merge commit: `97691bac8135602813da427d1d02b1667b3d2c60`.
- The branch is ahead of `origin/penguin-tui-opencode-upstream`; this audit has
  not been pushed.

Upstream baseline:

- OpenCode reference repo: `reference/opencode`.
- `origin/HEAD` resolves to `origin/dev`, so `dev` is still the active upstream
  branch to watch for TUI work.
- Comparison commit: `origin/dev` at
  `7fe7b9f258e36ad9f9acded20c5a9df201da19d5`
  (`2026-05-23 16:42:22 +0000`, `chore: update nix node_modules hashes`).
- Clean comparison worktree: `/private/tmp/opencode-origin-dev-audit-7fe7b9f`.
- Latest GitHub release observed during the audit: `v1.15.10`, published
  `2026-05-23T01:04:24Z`; tag commit
  `d74d166acf40e51146f8547216913a4e787a4bc1`.
- Release range loaded for notes: `v1.1.48` through `v1.15.10`, 120 releases.
- Fetch note: `origin/dev` refreshed successfully. Tag fetch reported local tag
  clobber rejections for pre-existing tags such as `latest` and `v1.1.45`; this
  does not affect the `origin/dev` TUI comparison.

TUI diff/stat against upstream `origin/dev`:

- Compared upstream
  `packages/opencode/src/cli/cmd/tui` to Penguin
  `penguin-tui/packages/opencode/src/cli/cmd/tui`.
- `git diff --no-index --shortstat`: 178 files changed, 9,970 insertions,
  18,646 deletions.
- Upstream TUI files: 160. Penguin TUI files: 117.
- Common files: 91. Unchanged common files: 8. Modified common files: 83.
- Penguin-only files: 26. Upstream-only files missing in Penguin: 69.

Penguin-only files:

- `component/dialog-command.tsx`
- `component/dialog-settings.tsx`
- `component/dialog-skills.tsx`
- `component/prompt/penguin-local-command-runtime.ts`
- `component/prompt/penguin-local-command.ts`
- `component/prompt/penguin-send.ts`
- `component/textarea-keybindings.ts`
- `component/tips.tsx`
- `context/keybind.tsx`
- `context/penguin-auth.ts`
- `context/session-hydration.ts`
- `context/sync-bootstrap.ts`
- `context/theme/emperor.json`
- `context/theme/glacier-high-contrast.json`
- `context/theme/krill.json`
- `context/theme/midnight-terminal.json`
- `context/theme/penguin-classic.json`
- `context/theme/polar-night.json`
- `context/theme/research-lab.json`
- `context/theme/solar-ice.json`
- `context/theme/tux.json`
- `routes/session/header.tsx`
- `util/api-error.ts`
- `util/exit.ts`
- `util/session-family.ts`
- `util/terminal.ts`

Major upstream-only areas missing in Penguin:

- TUI plugin/runtime system: `plugin/*`, `feature-plugins/*`, `keymap.tsx`,
  `layer.ts`, and `component/command-palette.tsx`.
- Diff viewer implementation: `feature-plugins/system/diff-viewer*`.
- Upstream config/keybind migration files: `config/*`, `context/tui-config.tsx`,
  `context/thinking.ts`.
- Workspace/project dialogs and route helpers: `dialog-workspace-*`,
  `context/project.tsx`, `workspace-label.tsx`.
- Upstream utility helpers: `util/audio.ts`, `util/revert-diff.ts`,
  `util/selection.ts`, `util/scroll.ts`, `validate-session.ts`, `win32.ts`.

Highest-risk modified common files:

- `component/prompt/index.tsx`
- `context/sync.tsx`
- `context/sdk.tsx`
- `routes/session/index.tsx`
- `routes/session/permission.tsx`
- `routes/session/question.tsx`
- `routes/session/sidebar.tsx`
- `app.tsx`
- `thread.ts`
- `component/dialog-provider.tsx`
- `component/dialog-model.tsx`

Dependency delta:

| Package | Penguin embedded `1.1.48` | Upstream `1.15.10` / `origin/dev` | Notes |
| --- | --- | --- | --- |
| `opencode` package | `1.1.48` | `1.15.10` | Confirms fork baseline is far behind. |
| `@opentui/core` | `0.1.75` | `0.2.15` | Needs separate OpenTUI risk track. |
| `@opentui/solid` | `0.1.75` | `0.2.15` | Same OpenTUI upgrade track. |
| `@opentui/keymap` | not present | `0.2.15` | Upstream split keymap support. |
| `@opencode-ai/sdk` | `workspace:*` | `workspace:*` | Contract changed inside workspace SDK. |
| `ai` | `5.0.124` | `6.0.168` | Major AI SDK jump; likely backend/provider impact. |
| `@ai-sdk/anthropic` | `2.0.58` | `3.0.71` | Provider compatibility impact. |
| `@ai-sdk/openai` | `2.0.89` | `3.0.53` | Provider compatibility impact. |
| `@ai-sdk/provider` | `2.0.1` | `3.0.8` | Provider interface impact. |
| `typescript` | `5.8.2` | `5.8.2` | No meaningful delta. |
| `solid-js` | `1.9.10` | `1.9.10` | No meaningful delta. |
| `zod` | `4.1.8` | `4.1.8` | No meaningful delta. |

Backend/API contract changes to account for before or during upstreaming:

- `v1.2.0` introduced incremental `message.part.delta` events. Penguin should
  support this in backend persistence/replay before relying on the TUI to smooth
  over full-part churn.
- `v1.3.0` added git-backed session review, multistep auth, duplicate-submit
  prevention, terminal recovery, attachment preservation, and provider/model
  fixes. Several are UI-visible but depend on backend session and auth truth.
- `v1.4.0` included SDK breaking changes around diff metadata and user message
  model variant shape. This is a compatibility boundary, not just a TUI change.
- `v1.14.42` added HTTP compression, structured validation errors, typed `401`
  auth challenges, permission/question ID validation, retry dialogs, reasoning
  controls, sidebar/session picker improvements, and flat keybind config.
- `v1.15.0` added an Effect-based core event system, better event delivery, and
  fixed event-projector replay lookup behavior. This is directly relevant to
  Penguin and Link runtime projection.
- `v1.15.6` added structured public v2 API error schemas, OpenAPI endpoint error
  preservation, permission JSON startup hardening, OpenTUI `0.2.15`, and the
  TUI diff viewer.
- `v1.15.7` added safe unknown API errors with log IDs, typed session missing and
  unavailable-mutation errors, friendlier tool schema failures, restored OpenAI
  reasoning streams, local-project session defaults, and question UI fixes.
- `v1.15.9` enabled the diff viewer by default, improved diff-viewer empty
  states/context handling, and returned clearer HTTP API errors for project,
  PTY, MCP, and session-busy failures.
- `v1.15.10` restored legacy production desktop flows for opening projects and
  starting sessions; low direct TUI risk, but evidence that upstream still moves
  quickly across client entry flows.

Pure or mostly TUI changes to consider adopting directly:

- Diff viewer UI and file tree.
- Full-session fork option and session review affordances.
- Session picker sorting, sidebar session ID display, and local-project defaults.
- Prompt duplicate-submit prevention and prompt history behavior.
- Permission/question label and checkmark fixes.
- Retry dialogs that name provider and failure reason.
- Flat keybind config and OpenTUI keymap extraction.
- Malformed tool-input crash handling.

Phase 1.5 mapping:

| Upstream improvement | Recommendation | Link implication |
| --- | --- | --- |
| Incremental `message.part.delta` events | Adopt by changing Penguin backend compatibility first, then consume in TUI. | Link should project deltas into Link-owned `RuntimeEvent`/`SessionEvent` updates instead of exposing raw OpenCode events. |
| V2 session API shapes and structured errors | Adopt by backend/API parity where feasible. | Link adapters should preserve typed error categories and log reference IDs. |
| Event replay/projector behavior | Adopt conceptually in backend and adapter layers before UI refactors. | Strong reference for Link runtime event replay and projector versioning. |
| Diff viewer | Adopt directly in Penguin TUI after isolating Penguin diff/session semantics. | Link Agentboard likely needs the same pattern, adapted to tasks, artifacts, and review state. |
| Full-session fork/session review | Adopt with Penguin-specific mapping to conversation/task IDs. | Map to Link review flows and `PENDING_REVIEW` semantics, not raw OpenCode fork vocabulary. |
| Provider/model/reasoning UX | Adopt selectively; backend must provide truthful model/provider capability metadata. | Link should treat this as runtime capability UI, not just settings. |
| Permission/question UI fixes | Adopt directly where route shapes already align; otherwise fix backend shape first. | Link approval panels can copy the UX, but must use Link permission/audit records. |
| OpenTUI dependency updates | Evaluate as a separate upgrade track before mixing with API/event upstreaming. | Rendering smoothness helps both products, but upgrade risk should not block event-contract work. |
| Plugin/runtime system | Defer for now; evaluate after adapter cleanup. | Interesting for Link extensibility, but too large to mix into first upstreaming pass. |
| Desktop/project entry flows | Avoid for Penguin TUI unless a specific terminal workflow needs them. | Link owns project/session entry differently. |

Initial conclusions for Phases 1 and 1.5:

- The fork is no longer a small styling/product delta from OpenCode `v1.1.48`;
  it is missing a substantial upstream TUI architecture layer, especially the
  plugin/runtime system and diff viewer.
- The next implementation step should not be a broad rebase. First shrink
  Penguin-specific protocol drift in `context/sdk.tsx`, `context/sync.tsx`, and
  `component/prompt/index.tsx`.
- Backend/API parity work is likely higher leverage than more TUI-side probing,
  especially for events, sessions, errors, permission/question flows, and
  provider/model metadata.
- Link should borrow upstream runtime UI ideas, but not raw OpenCode event or ID
  vocabulary. Keep Link-native projection as the long-term contract.

### 2. Classify TUI divergence

- [x] Inventory all `sdk.penguin` branches under
      `penguin-tui/packages/opencode/src/cli/cmd/tui/`.
- [x] Classify each branch as one of:
  - branding/docs/theme
  - auth/transport
  - backend compatibility
  - session/message reconciliation
  - optimistic UI
  - local command surface
  - settings/skills/project/task Penguin feature
  - temporary workaround
- [x] Mark each branch as keep, move lower, replace with backend parity, or
      delete after compatibility work.

### Phase 2 Divergence Map - 2026-05-23

Scope:

- This was an audit-only pass. No runtime behavior was changed.
- Direct `sdk.penguin` usage under
  `penguin-tui/packages/opencode/src/cli/cmd/tui` appears 81 times across 10
  files.
- The direct branch count is concentrated in `component/prompt/index.tsx` (52),
  `context/sync.tsx` (11), and `app.tsx` (7). The remaining direct branches are
  small branding/provider/onboarding differences.

Direct `sdk.penguin` branches:

| Area | Classification | Disposition | Notes |
| --- | --- | --- | --- |
| `app.tsx:227`, `app.tsx:228`, `app.tsx:560`, `app.tsx:742` | branding/docs/theme | Keep, but move toward product config. | Terminal title, docs URL, and update copy are valid Penguin identity differences. |
| `app.tsx:430` | settings/skills/project/task Penguin feature | Keep. | Skills are a Penguin feature. Long term, register this through a command/plugin surface rather than inline app command wiring. |
| `app.tsx:463` and `component/prompt/index.tsx:956` | local command surface | Keep, but move lower. | Fast mode is useful, but `/fast` handling should live in one Penguin command registry instead of both app command registration and prompt submission logic. |
| `app.tsx:674` and `component/dialog-provider.tsx:274` | backend compatibility | Move lower. | Provider-specific Penguin copy and OpenCode Zen suppression should come from product/provider metadata or a provider policy helper. |
| `routes/home.tsx:101`, `routes/session/sidebar.tsx:327`, `component/dialog-status.tsx:50`, `routes/session/permission.tsx:141`, `routes/session/permission.tsx:306` | branding/docs/theme | Keep, but move toward product config. | App name/logo/copy branches are low-risk but noisy during upstream syncs. |
| `routes/session/sidebar.tsx:307` and `component/dialog-status.tsx:81` | auth/transport | Keep near auth/provider UX. | Penguin auth wording is legitimate because local auth differs from upstream OpenCode CLI auth. |
| `routes/session/index.tsx:245` and `component/prompt/index.tsx:570`, `component/prompt/index.tsx:581`, `component/prompt/index.tsx:1525` | optimistic UI | Replace with backend status truth where possible. | Interrupt handling uses local pending/busy state because backend status/event truth is not yet sufficient. |
| `routes/session/index.tsx:1195` | session/message reconciliation | Move lower into a session list/message helper. | Queued-message ordering differs because Penguin synthetic IDs and optimistic messages do not sort like upstream IDs. |
| `context/sync.tsx:282`, `context/sync.tsx:493` | backend compatibility | Replace with backend API/event parity. | Usage refresh on idle exists because session usage is not reliably delivered with status/session updates. |
| `context/sync.tsx:309`, `context/sync.tsx:315`, `context/sync.tsx:326`, `context/sync.tsx:524`, `context/sync.tsx:1131` | session/message reconciliation | Move lower into a Penguin sync adapter. | Snapshot hydration, message merge/upsert, and unsorted session lookup compensate for Penguin response/event shapes. |
| `context/sync.tsx:340`, `context/sync.tsx:640` | backend compatibility | Move lower, then replace with backend scoping where feasible. | Directory/session filtering in the TUI is a protocol boundary leak. Backend events should carry enough project/session scope to avoid scattered UI filters. |
| `context/sync.tsx:671` | backend compatibility | Move lower into a bootstrap adapter, then replace with route parity. | The Penguin bootstrap path builds providers, agents, sessions, usage, path, LSP, formatter, and VCS state from mixed Penguin and OpenCode-shaped endpoints. |
| `component/prompt/index.tsx:203`, `component/prompt/index.tsx:206` | optimistic UI | Replace with backend event/status truth. | `store.pending` and `pendingSeenBusy` are client-side reconciliation state for the send gap. |
| `component/prompt/index.tsx:307`, `component/prompt/index.tsx:318`, `component/prompt/index.tsx:1747`, `component/prompt/index.tsx:1891` | settings/skills/project/task Penguin feature | Keep, but move lower. | Agent build/plan mode is a Penguin product feature. Keep it, but isolate session persistence and labels behind Penguin session helpers. |
| `component/prompt/index.tsx:328` through `component/prompt/index.tsx:537` | local command surface | Keep, but move lower. | Project/task command suggestions are useful, but they should be produced by a Penguin command catalog/helper rather than embedded in the prompt component. |
| `component/prompt/index.tsx:892`, `component/prompt/index.tsx:1763` | backend compatibility | Move lower into model/provider capability helpers. | `service_tier`/fast mode should be represented as provider/model capability metadata. |
| `component/prompt/index.tsx:964` | backend compatibility | Replace with backend API parity or isolate in a send adapter. | Session creation still uses `POST /session` with Penguin-specific payload fields. |
| `component/prompt/index.tsx:1013` | local command surface | Keep, but keep below prompt UI. | HTTP local command execution is already partially extracted; the prompt should only dispatch to it. |
| `component/prompt/index.tsx:1076`, `component/prompt/index.tsx:1084`, `component/prompt/index.tsx:1113`, `component/prompt/index.tsx:1129`, `component/prompt/index.tsx:1185` | optimistic UI | Replace with backend echo/persistence when possible. | Synthetic IDs, optimistic user message/part/status events, navigation, and pending state are the highest-risk TUI-side truth shims. |
| `component/prompt/index.tsx:1103` | backend compatibility | Replace with route parity or an attachment adapter. | Image virtual-part stripping is a client workaround for Penguin attachment handling. |
| `component/prompt/index.tsx:1197` | backend compatibility | Move lower into a Penguin send adapter, then converge on OpenCode-compatible send/session APIs where feasible. | Direct `POST /api/v1/chat/message` is the central Penguin send divergence. |
| `component/prompt/index.tsx:1873`, `component/prompt/index.tsx:1875`, `component/prompt/index.tsx:1876` | optimistic UI | Keep until backend status truth is stronger. | Interrupt copy differs because Penguin allows single-key interrupt semantics while local pending is active. |
| `component/tips.tsx:60` | branding/docs/theme | Keep, but move toward product config. | Penguin-specific tips are valid product copy; keep them isolated. |

Penguin-only file classification:

| File | Classification | Disposition |
| --- | --- | --- |
| `component/dialog-command.tsx` | local command surface | Keep short term; evaluate against upstream command palette/plugin runtime before rebasing. |
| `component/dialog-settings.tsx` | settings/skills/project/task Penguin feature | Keep; it is a read-only Penguin settings panel backed by `/api/v1/system/settings`. |
| `component/dialog-skills.tsx` | settings/skills/project/task Penguin feature | Keep; move skill actions behind typed backend responses and command registration. |
| `component/prompt/penguin-local-command.ts` | local command surface | Keep; this is the right kind of extraction, but command definitions should eventually come from one catalog. |
| `component/prompt/penguin-local-command-runtime.ts` | local command surface | Keep, but avoid expanding it inside prompt flow; backend should provide typed command errors. |
| `component/prompt/penguin-send.ts` | optimistic UI | Keep as a helper for now; delete or shrink after backend status/error parity. |
| `component/textarea-keybindings.ts` | temporary workaround | Move toward upstream `@opentui/keymap` / flat keybind handling during the OpenTUI upgrade track. |
| `component/tips.tsx` | branding/docs/theme | Keep as product copy, but avoid inline OpenCode filtering by moving tips into product config. |
| `context/keybind.tsx` | temporary workaround | Replace with upstream flat keybind/keymap path when adopting newer OpenCode/OpenTUI. |
| `context/penguin-auth.ts` | auth/transport | Keep at the SDK boundary. |
| `context/session-hydration.ts` | session/message reconciliation | Keep as an adapter helper; replace parts with backend replay parity and tested event projection. |
| `context/sync-bootstrap.ts` | backend compatibility | Keep as a helper; expand into a typed Penguin bootstrap adapter or remove after route parity. |
| `context/theme/*.json` Penguin themes | branding/docs/theme | Keep. |
| `routes/session/header.tsx` | session/message reconciliation | Keep if Penguin wants this layout, but compare against upstream session header/plugin surfaces before rebasing. |
| `util/api-error.ts` | backend compatibility | Keep until Penguin/OpenCode structured error shapes converge. |
| `util/exit.ts` | optimistic UI | Keep until abort/status transitions are backend-truthful and consistently replayed. |
| `util/session-family.ts` | session/message reconciliation | Keep; map to upstream full-session fork/session review semantics before deleting. |
| `util/terminal.ts` | temporary workaround | Appears unused in current TUI search; verify before deleting during cleanup. |

High-risk modified file conclusions:

- `context/sdk.tsx` should remain the transport boundary. Keep auth header
  injection there, but move custom Penguin SSE parsing, finish-response cleanup,
  and reconnect/session scoping into a named event adapter. Long term, prefer a
  backend event stream that matches OpenCode SDK event semantics.
- `context/sync.tsx` is carrying too many compatibility responsibilities:
  bootstrap shape probing, directory filtering, usage refresh, session mapping,
  message ordering, hydration, and provider/agent defaults. Phase 5 should split
  these into a typed Penguin bootstrap/sync adapter before any upstream rebase.
- `component/prompt/index.tsx` is the largest drift source. The prompt owns
  project/task command registration, local command dispatch, Penguin session
  creation, optimistic message emission, send recovery, fast mode, agent mode,
  attachment stripping, and interrupt behavior. Phase 4 should make the prompt
  call a small Penguin send/command service instead of owning protocol details.
- `routes/session/index.tsx` depends on local pending state and Penguin message
  ordering. This should be revisited after backend status and replay parity.
- `routes/session/sidebar.tsx`, `routes/session/permission.tsx`,
  `component/dialog-status.tsx`, `routes/home.tsx`, `component/dialog-provider.tsx`,
  and `component/tips.tsx` are mostly product copy/branding/provider UX. They
  are not the first upstreaming risk, but product config would reduce merge
  noise.

Recommended next work from Phase 2:

- Phase 3: Treat `context/sdk.tsx` as the first real refactor. Keep
  `context/penguin-auth.ts`, extract `streamPenguin`, `parseEvent`, event
  cleanup, and route/session stream selection into a tested adapter.
- Phase 4: Extract Penguin prompt submit into a `sendPenguinPrompt` helper that
  owns session creation, optimistic emission, `/api/v1/chat/message`, failure
  recovery, and navigation decisions.
- Phase 4: Move project/task command registration into the existing
  `penguin-local-command` catalog so the prompt component only renders and
  dispatches.
- Phase 5: Convert the Penguin bootstrap block in `context/sync.tsx` into a
  typed mapper with explicit input/output shapes and tests for session, usage,
  provider, agent, path, LSP, formatter, and VCS data.
- Phase 6: Prefer backend parity for session create/list/get/messages, event
  replay, status, usage, provider/model metadata, permission/question IDs, and
  attachment handling. Those are the causes of the highest-risk TUI shims.
- Link guardrail: any extracted Penguin event/send/bootstrap adapter should
  expose normalized local types and should not become Link's frontend contract.
  Link should project Penguin/OpenCode/A2A/Codex/Claude runtime streams into
  Link-owned `RuntimeEvent` and `SessionEvent` types.

### 3. Shrink SDK-layer drift

- [x] Review `context/sdk.tsx` against upstream.
- [x] Keep Penguin auth header injection near the SDK boundary.
- [x] Decide whether Penguin SSE should use OpenCode's SDK event subscription
      path, a custom adapter, or backend route parity.
- [x] Move event cleaning and Penguin SSE parsing into a named helper if it
      remains client-side.
- [x] Avoid leaking transport-specific behavior into route and prompt
      components.

### Phase 3 SDK-Layer Results - 2026-05-24

Scope:

- This phase was intentionally narrow: shrink SDK-layer drift without changing
  prompt, sync/bootstrap, OpenTUI, or backend behavior.
- Penguin SSE remains client-side for now, but behind a named adapter. Backend
  route/event parity remains a Phase 6 target.

Changes made:

- Added `penguin-tui/packages/opencode/src/cli/cmd/tui/context/penguin-event-stream.ts`.
- Kept local auth header loading in
  `penguin-tui/packages/opencode/src/cli/cmd/tui/context/penguin-auth.ts`.
- Updated `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sdk.tsx` so it:
  - still constructs the OpenCode SDK client and event emitter
  - still injects Penguin auth headers at the SDK/fetch boundary
  - still chooses Penguin SSE versus upstream SDK event subscription
  - delegates Penguin SSE URL construction, parsing, unauthorized handling hook,
    session-scope cancellation, and `finish_response` cleanup to the new adapter
- Added focused adapter tests in
  `penguin-tui/packages/opencode/test/tui/penguin-event-stream.test.ts`.

Adapter responsibilities now isolated:

- `cleanPenguinText`: removes `finish_response` markers from streamed text.
- `cleanPenguinEvent`: normalizes Penguin `message.part.updated` text/delta
  payloads before they enter the TUI event queue.
- `parsePenguinSSEEvent`: parses `data:` lines from an SSE frame into an event.
- `streamPenguinEvents`: opens `/api/v1/events/sse`, applies `session_id` and
  `directory` query parameters, forwards parsed events, reports `401`
  unauthorized responses, and cancels when the active route/session changes.

Decision recorded:

- Keep the custom Penguin SSE adapter for now. It is the correct short-term
  boundary because Penguin's event route is still `/api/v1/events/sse`, not the
  upstream OpenCode SDK subscription route.
- Do not push this deeper into route/prompt components. `sdk.tsx` remains the
  only TUI component that decides between Penguin SSE and upstream OpenCode SDK
  event subscription.
- Long term, prefer backend event parity so the Penguin branch can collapse back
  toward upstream `sdk.event.subscribe`.

Verification:

- Manual Bun sanity checks passed from `/private/tmp` for:
  - `cleanPenguinText`
  - `parsePenguinSSEEvent`
  - `streamPenguinEvents`
- `bun install` was run in `penguin-tui` after storage was freed. The Husky
  install hook printed `.git can't be found`, but the install completed.
- `bun test test/tui/penguin-event-stream.test.ts` now passes from
  `penguin-tui/packages/opencode`.
- `bun run typecheck` now passes from `penguin-tui/packages/opencode`.

Follow-up suggestion:

- Keep `node_modules` untracked/ignored. If disk pressure returns, it can be
  removed without affecting the source changes.

### 4. Shrink prompt-layer drift

- [x] Review `component/prompt/index.tsx` against upstream.
- [x] Extract Penguin session creation and send flow into a helper/service.
- [x] Decide whether optimistic user-message emission should remain in the TUI.
- [x] If optimistic emission remains, isolate it behind one helper with tests.
- [x] Preserve Penguin `/fast` mode as a first-class command, while keeping its
      parsing/toggle/status handling out of the main prompt submission path.
- [x] Make failure recovery explicit and testable.

### Phase 4 Prompt-Layer Results - 2026-05-24

Scope:

- This phase shrank prompt-layer protocol drift without changing backend routes,
  broad-rebasing, upgrading OpenTUI, or changing local command behavior.
- Optimistic user-message emission remains in the TUI for now because Penguin's
  backend does not yet provide an immediate OpenCode-shaped user-message echo,
  durable replay, and status transition that fully replace it.
- Project/task commands, settings, and local command dispatch remain in
  `component/prompt/index.tsx` as a later command-surface follow-up. They are
  already partially separated through `penguin-local-command.ts` and
  `penguin-local-command-runtime.ts`, but the prompt still owns command
  registration/dispatch decisions.

Changes made:

- Expanded `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-send.ts`
  so it now owns:
  - `resolveSessionID`
  - `createPenguinSession`
  - `shouldStripPenguinVirtualPart`
  - `emitPenguinOptimisticPrompt`
  - `sendPenguinPrompt`
  - `recoverPenguinPromptFailure`
  - `formatPenguinPromptFailure`
- Updated `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx`
  so the main submit flow calls the helper for Penguin session creation,
  optimistic event emission, image virtual-part stripping, `/api/v1/chat/message`
  sending, and failure formatting.
- Added `penguin-tui/packages/opencode/test/tui/penguin-send.test.ts` for the
  extracted prompt helper.
- Adjusted `penguin-tui/packages/opencode/test/tui/penguin-event-stream.test.ts`
  test doubles so the package TypeScript check accepts Bun's extended `fetch`
  type.

OpenCode-compatible backend route sketch:

- Current Penguin prompt send is a single custom route:
  `POST /api/v1/chat/message` with body fields such as `text`, string
  `provider/model`, `session_id`, `agent_id`, `agent_mode`, `directory`,
  `streaming`, `variant`, `service_tier`, `client_message_id`, and `parts`.
- OpenCode-compatible legacy route parity would split this into session,
  message, status, command, shell, and event routes:
  - `GET /event` returns `text/event-stream` and accepts workspace/directory
    routing query parameters.
  - `GET /session`, `POST /session`, and `GET /session/status`.
  - `GET /session/:sessionID`, `PATCH /session/:sessionID`,
    `DELETE /session/:sessionID`, and `POST /session/:sessionID/abort`.
  - `GET /session/:sessionID/message` returns OpenCode-shaped
    `MessageV2.WithParts[]` history/replay.
  - `GET /session/:sessionID/message/:messageID` returns one OpenCode-shaped
    message.
  - `POST /session/:sessionID/message` sends a prompt with an OpenCode-shaped
    payload: optional `messageID`, optional `model: { providerID, modelID }`,
    optional `agent`, optional `variant`, optional `system`/`format`/`noReply`,
    and `parts` containing text, file, agent, or subtask prompt parts.
  - `POST /session/:sessionID/prompt_async` accepts the same prompt payload but
    returns immediately after queueing work.
  - `POST /session/:sessionID/command` and `POST /session/:sessionID/shell`
    handle slash-command and shell-mode execution.
- OpenCode's newer v2 route direction is also worth tracking:
  - `GET /api/session` returns `{ items, cursor }` for paged sessions.
  - `POST /api/session/:sessionID/prompt` accepts `{ prompt, delivery? }`,
    where `delivery` is `immediate` or `deferred`.
  - `GET /api/session/:sessionID/message` returns `{ items, cursor }` for paged
    projected messages.
  - `POST /api/session/:sessionID/wait`, `POST /api/session/:sessionID/compact`,
    and `GET /api/session/:sessionID/context` provide explicit runtime/session
    operations.

Backend route conclusion:

- The OpenCode-compatible shape is cleaner than Penguin's current chat route for
  TUI maintenance because session identity is path-scoped, prompt/message
  payloads use OpenCode SDK types, replay is a first-class message route, status
  is independent of prompt send, and generated SDK clients can call the backend
  without custom `sdk.penguin` prompt code.
- Penguin should not rewrite everything immediately in Phase 4. The better path
  is to implement a backend compatibility layer in Phase 6, then collapse
  `sendPenguinPrompt` toward ordinary `sdk.client.session.prompt` or v2 prompt
  calls once the backend emits and replays OpenCode-shaped message/status events.
- If Penguin keeps product-specific fields such as `agent_mode`, `service_tier`,
  project/task IDs, or Link/Penguin runtime metadata, keep them as explicit
  Penguin extensions at the backend boundary. Do not make those fields Link's
  long-term frontend contract.

Verification:

- `bun test test/tui/penguin-event-stream.test.ts test/tui/penguin-send.test.ts`
  passed from `penguin-tui/packages/opencode`.
- `bun test test/cli/tui/prompt-penguin-send.test.ts test/tui/penguin-send.test.ts test/tui/penguin-event-stream.test.ts`
  passed from `penguin-tui/packages/opencode`.
- `bun run typecheck` passed from `penguin-tui/packages/opencode`.
- `git diff --check` passed from the worktree root.

Risks and follow-ups:

- The prompt still synthesizes optimistic `message.updated`,
  `message.part.updated`, and `session.status` events. This should disappear
  only after backend route/event/replay parity is strong enough.
- Penguin currently generates TUI-side synthetic IDs for optimistic messages and
  parts. Backend compatibility work should decide whether the backend accepts
  those IDs, replaces them deterministically, or echoes a canonical mapping.
- `sendPenguinPrompt` still posts to `/api/v1/chat/message`. That is now
  isolated, but it remains the central route to delete after compatibility work.
- Move project/task/settings command registration behind one Penguin command
  catalog or upstream plugin/command-palette style before a broad OpenCode
  rebase.
- Phase 4.5 should address runtime-confidence UX before the larger
  sync/bootstrap extraction: spinner reliability, elapsed wall-clock timing, and
  stale/reconnecting state.
- Phase 5 should then focus on `context/sync.tsx` bootstrap/hydration mapping.
  Phase 6 should prioritize backend route parity for sessions, messages, status,
  event replay, provider/model metadata, and attachments.

Follow-up correction - 2026-05-27:

- Clarified that `/fast` is a Penguin feature to preserve, not generic prompt
  cleanup debt.
- Added `component/prompt/penguin-fast-command.ts` so `/fast [on|off|status]`
  parsing and status formatting live outside the main submit body while
  retaining the command palette toggle, footer indicator, and `service_tier`
  propagation through `penguin-send.ts`.
- Added `test/tui/penguin-fast-command.test.ts` for no-match, toggle,
  explicit on/off, status, invalid argument, and visible status formatting.
- Phase 4 is now considered complete. Remaining command-surface cleanup should
  happen under the later command/plugin/keymap track, not block Phase 5.

### 4.5. Runtime confidence UX

- [x] Review upstream OpenCode's current spinner/activity/timer behavior and
      identify the smallest useful pieces to copy.
- [x] Make Penguin's active-run spinner continue while local prompt send is
      pending or backend session status is busy, even if no text chunks arrive.
- [x] Add an elapsed wall-clock timer for the active response/run, similar to
      OpenCode's response timer.
- [x] Distinguish at least these visible states in the TUI state model:
      `pending`, `running`, `reconnecting`, `stale`, and `idle`.
- [x] Track last-event time from the SDK/event adapter so stream stalls do not
      look identical to a clean idle state.
- [x] Keep the implementation TUI-scoped unless a backend timestamp/status gap
      blocks correctness.
- [x] Update this plan with the UX decision, files changed, tests, and any
      backend follow-up needed for better run-state truth.

### Phase 4.5 Runtime Confidence Results - 2026-05-24

Problem statement:

- The current spinner is not a reliable active-run signal. It can stop while the
  agent is still running, which makes it hard to tell whether Penguin is still
  working, the event stream is quiet, the backend is slow, or something broke.
- Penguin also lacks a wall-clock elapsed timer between prompt submission and
  response completion. Upstream OpenCode has this pattern and it should be a
  relatively small TUI improvement.

Target behavior:

- The spinner should be driven by derived run state, not only by chunk activity.
  At minimum, it should remain active while:
  - the TUI has submitted a prompt and is waiting for backend echo/status
  - backend session status is busy
  - a known active response has not yet received an idle/completion transition
- The TUI should show elapsed wall-clock time for the active run/response and
  settle to a final duration once idle.
- If the event stream reconnects or goes stale while a run is active, the UI
  should show that distinction instead of silently presenting a stopped spinner.

Recommended implementation shape:

- Prefer a small helper or derived state object that combines:
  - local pending state from prompt submission
  - backend session status from sync
  - last event timestamp from the SDK/event adapter
  - active session/message timestamps where available
- Use upstream OpenCode's timer/spinner behavior as the first reference. Copy the
  pattern where it maps cleanly; adapt through a Penguin helper where backend
  status/event truth differs.
- Avoid new backend routes in this phase. If backend timestamps, busy/idle
  transitions, or event replay are insufficient, document the required backend
  follow-up under Phase 6.
- Keep Link alignment explicit: `running`, `stale`, and `reconnecting` are useful
  runtime-state concepts, but Link should still expose them through Link-owned
  runtime/session event types rather than raw Penguin/OpenCode stream events.

Upstream reference:

- Upstream OpenCode now has a reusable `component/spinner.tsx`, richer active
  message/tool spinners, and duration display on assistant/reasoning/tool rows.
- Penguin did not copy the newer plugin/runtime route structure in this phase.
  The useful small pieces were the active-state framing and duration display
  pattern, adapted to Penguin's current prompt footer and event adapter.

Changes made:

- Added
  `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/penguin-run-state.ts`.
  This pure helper derives `idle`, `pending`, `running`, `reconnecting`, and
  `stale` from:
  - local prompt pending state
  - backend `session.status`
  - open assistant message/active part state
  - SDK stream status and last-event timestamp
  - local/user/assistant start timestamps
- Updated
  `penguin-tui/packages/opencode/src/cli/cmd/tui/context/penguin-event-stream.ts`
  with an `onOpen` hook so the SDK can distinguish a connected stream from a
  reconnect loop.
- Updated `penguin-tui/packages/opencode/src/cli/cmd/tui/context/sdk.tsx` so the
  SDK context exposes Penguin stream health:
  - `connecting`
  - `connected`
  - `reconnecting`
  - `denied`
  - `lastEventAt`
- Updated
  `penguin-tui/packages/opencode/src/cli/cmd/tui/component/prompt/index.tsx` so
  the prompt footer:
  - stays active for Penguin while the derived run state is not `idle`
  - keeps the spinner active for pending, running, reconnecting, and stale states
  - shows elapsed wall-clock time as `starting`, `running`, `reconnecting`, or
    `still running`
  - treats an open assistant message or active tool/reasoning part as running
    even if `session.status` has already returned idle
- Added
  `penguin-tui/packages/opencode/test/tui/penguin-run-state.test.ts` for the
  derived run-state helper.

Verification:

- `bun test test/tui/penguin-run-state.test.ts test/tui/penguin-event-stream.test.ts test/tui/penguin-send.test.ts test/cli/tui/prompt-penguin-send.test.ts`
  passed from `penguin-tui/packages/opencode`.
- `bun run typecheck` passed from `penguin-tui/packages/opencode`.
- `git diff --check` passed from the worktree root.

Backend follow-ups for Phase 6:

- Prefer backend-provided canonical run start/end timestamps for reload/replay
  correctness. The TUI now uses local/user/assistant timestamps as a short-term
  fallback.
- Ensure Penguin emits durable busy/idle transitions after the actual agent loop
  state changes, not just after request handling or response dispatch.
- Ensure event replay can reconstruct active assistant/tool state after reconnect
  so the TUI does not need to infer too much from local state.
- Keep the UI-facing states useful for Link, but project them into Link-owned
  runtime/session event types instead of exposing Penguin/OpenCode stream words
  as Link's frontend contract.

Follow-up correction - 2026-05-25:

- The first Phase 4.5 pass added a live footer elapsed timer, but OpenCode's
  reference screenshot also shows the settled wall-clock duration on the
  assistant message metadata row.
- Penguin's backend already returned `time.completed` for the assistant message
  in the tested session, but omitted `finish`. The old TUI duration code required
  both an OpenCode-style final `finish` and a parent user lookup, so it hid the
  completed duration.
- Added a settled assistant-message duration helper that treats
  `time.completed` as completion, preserves OpenCode `finish` semantics, and
  falls back to the previous user message if `parentID` is unavailable or `root`.
- Verification for the correction:
  `bun test test/tui/message-duration.test.ts test/tui/penguin-run-state.test.ts test/tui/penguin-event-stream.test.ts test/tui/penguin-send.test.ts test/cli/tui/prompt-penguin-send.test.ts`
  and `bun run typecheck` from `penguin-tui/packages/opencode`.

### 5. Shrink sync/bootstrap drift

- [x] Review `context/sync.tsx` against upstream.
- [x] Extract bootstrap response mapping into a dedicated Penguin adapter.
- [x] Extract directory/session filtering into a helper.
- [x] Revisit usage refresh and session snapshot hydration responsibilities.
- [ ] Prefer backend-provided OpenCode-shaped session records over client-side
      response probing.
- [x] Keep `sync.tsx` focused on store orchestration.

### Phase 5 Sync/Bootstrap Results - 2026-05-27

Scope:

- This phase intentionally kept backend route shapes unchanged. The goal was to
  move Penguin response probing and directory scoping out of `sync.tsx` without
  changing runtime behavior.
- `context/sync.tsx` was reduced from 1,159 lines to 771 lines. It still owns
  fetch orchestration, store writes, and upstream OpenCode bootstrap flow, but
  no longer owns the largest Penguin-only mapping and filtering blocks.

Changes made:

- Added `context/sync-scope.ts` for Penguin directory/session event scoping:
  - directory normalization
  - session ID extraction from direct, `info`, and `part` event shapes
  - directory extraction from direct, `info.path.cwd`, `path.cwd`, and `part`
    event shapes
  - active-session and project-directory event filtering
- Expanded `context/sync-bootstrap.ts` into the Penguin bootstrap adapter:
  - `unwrapBootstrapData`
  - `parsePenguinUsage`
  - `mapPenguinBootstrap`
  - fallback provider/model/provider-list/auth/config/agent/command state
  - session, usage, and initial idle status mapping
- Updated `context/sync.tsx` so the Penguin branch now:
  - asks `sync-scope.ts` whether an event belongs to the current session or
    directory before applying it
  - delegates provider/config/session/usage/agent/command bootstrap mapping to
    `mapPenguinBootstrap`
  - keeps `refreshSessionUsage` and `syncSessionSnapshot` as local orchestration
    functions because they still depend on live store state and backend route
    timing
- Existing `context/session-hydration.ts` remains the right home for snapshot
  hydration and optimistic-message reconciliation. No new hydration abstraction
  was needed in this phase.

Verification:

- `bun test test/cli/tui/sync-scope.test.ts test/cli/tui/sync-bootstrap.test.ts test/cli/tui/sync-hydration.test.ts`
  passed after the event-scope extraction.
- `bun test test/cli/tui/sync-bootstrap.test.ts test/cli/tui/sync-scope.test.ts test/cli/tui/sync-hydration.test.ts`
  passed after the bootstrap-mapping extraction.
- `bun run typecheck` passed after both extraction commits.
- `git diff --check` passed before each commit.

Deferred to Phase 6:

- Backend-provided OpenCode-shaped session records are still the correct long
  term fix. Phase 5 only isolated the current TUI-side mapping so it is easier
  to delete later.
- Usage refresh is still a TUI-side follow-up request after idle/completed
  transitions. Backend status/session events should eventually carry durable
  usage truth.
- Session-scoped context-window stats now refresh through
  `GET /api/v1/sessions/{session_id}/token-usage` after hydration/status
  transitions. Remaining follow-up: backend status/session events should
  eventually carry durable usage truth so the TUI does not need a follow-up
  request.
- Session snapshot hydration still compensates for replay and optimistic-message
  gaps. Backend message/part replay parity should eventually shrink this helper.

Follow-up investigation - 2026-05-30:

- A session-loading/config quirk can surface as an empty session with
  `Model openai/GPT-5.5 is not valid` while the footer still shows the valid
  lower-case `gpt-5.5` model. The observed cases were metadata-light sessions
  such as `session_20260530_183131_df9d5e0e` and `recovery_20260530_183141`.
- The likely cause is backend session listing treating runtime/cwd directory
  fallback as authoritative before applying an explicit `directory` filter, so
  legacy/recovery sessions with no stored directory can leak into the current
  worktree session list.
- Those sessions also lack model metadata, so session info falls back to global
  config. A config value like `model.default: GPT-5.5` then reaches the TUI as
  `openai/GPT-5.5`; the TUI validates model IDs by exact provider-catalog key,
  where the valid OpenAI entry is lower-case `gpt-5.5`.
- Short-term config workaround: keep OpenAI model defaults lower-case
  (`gpt-5.5`). Proper Phase 6 fix: filter unknown-directory sessions out of
  explicit directory-scoped lists and canonicalize provider/model IDs at the
  backend compatibility boundary.

Follow-up investigation - 2026-06-04, addressed in Phase 6.1:

- Context-window stats should be session scoped in the TUI. The backend exposes
  `GET /api/v1/token-usage?session_id=...` and
  `GET /api/v1/sessions/{session_id}/token-usage`; `refreshSessionUsage` now
  uses the session-specific route instead of rehydrating `/session/{id}`.
- The compatibility boundary makes session-specific token/CWM usage
  authoritative: compute from the located session and owning session/agent
  context window on the backend, then have the TUI update `session_usage` from
  the session token-usage route after hydration and idle/completed transitions.
- Keep `_opencode_usage_v1` in `/session/{id}` as a fast bootstrap/fallback
  snapshot, not the source of truth for session context-window meters.

### 6. Push compatibility toward Penguin backend

- [ ] Identify client workarounds that exist because Penguin endpoints are not
      OpenCode-shaped enough.
- [ ] For each workaround, decide whether backend parity is better than TUI
      adaptation.
- [ ] When OpenCode has a clearly better backend contract or runtime behavior,
      plan to recreate that shape in Penguin rather than preserving weaker
      Penguin-only routes by default.
- [ ] Prioritize backend parity for:
  - session create/list/get/messages
  - message/part event persistence and replay
  - busy/idle status truth
  - provider/model metadata
  - unknown-directory legacy/recovery session filtering
  - paginated/cursor-backed session list loading so the TUI can replace the
    temporary deep fixed fetch used by the Penguin session dialog
  - provider/model ID canonicalization before TUI validation
  - session-scoped token/CWM usage from session-specific token-usage routes
  - permission/question flows
  - path/vcs/lsp/formatter route shapes
- [ ] Keep Penguin-only product features behind explicit Penguin endpoints.

### 6.5. TUI startup performance

Investigation snapshot - 2026-06-08:

- The 5-10s perceived TUI startup delay is primarily in launch/runtime
  initialization, not in the Penguin HTTP bootstrap. API bootstrap requests are
  visible after the process is already up.
- Python startup currently imports more than the launcher needs:
  `penguin/__init__.py` eagerly imports core/config/engine paths, and
  `penguin/cli/__init__.py` imports the full Typer CLI before the OpenCode TUI
  launcher path can run.
- The launcher prefers local source execution when
  `penguin-tui/packages/opencode` exists, so development worktrees commonly run
  `bun run --conditions=browser ./src/index.ts` instead of a built binary or
  lighter sidecar path.
- The TUI also waits on terminal background-color probing and starts the
  OpenCode worker/server/config machinery even when running as a Penguin
  web-backed client.
- Measured local examples during investigation:
  - `uv run penguin-tui --help`: about 2.5s
  - local Bun source help path: about 4.3s warm and 11.5s cold
  - built arm64 OpenCode binary help path: about 2.4s

Planned work:

- [x] Lazy-load Python package and CLI imports so `penguin-tui` reaches the
      launcher without importing PenguinCore/config/engine.
- [x] Make `--use-global-opencode` bypass local source preference.
- [ ] Make launch-mode selection fully explicit with a future env/flag that
      chooses source, built dist, sidecar, or global binary deliberately.
- [x] Move terminal background-color probing after first paint or cap its wait
      more aggressively.
- [x] Audit whether Penguin web-backed mode can defer or skip OpenCode worker
      initialization until a feature actually needs it.
- [x] Add lightweight startup timing instrumentation around Python launcher,
      Bun/binary spawn, first render, and Penguin bootstrap completion.
- [ ] Investigate Bun/source-mode module load cost before `thread.handler.start`;
      this is now the largest remaining measured pre-render startup segment.

Progress - 2026-06-08:

- First fix lazy-loads `penguin.__init__` core/config/engine/agent exports and
  `penguin.cli.__init__` CLI exports so the TUI launcher import no longer pays
  for `PenguinCore`, tool manager, IPython/notebook helpers, or Rich/Typer CLI
  setup.
- Local timing improved from roughly `2.1s` to `0.28-0.45s` for
  `uv run python -c 'import penguin.cli.opencode_launcher'`, and from roughly
  `2.1s` to `0.54s` for `uv run penguin-tui --help`.
- `--use-global-opencode` now prefers the global `opencode` binary before
  considering local Bun/source execution.

Progress - 2026-06-09:

- Added env-gated startup profiling via `PENGUIN_TUI_PROFILE=1` /
  `OPENCODE_TUI_PROFILE=1` across the Python launcher, TUI thread handler,
  first render path, theme initialization, and Penguin bootstrap.
- Penguin `SyncProvider` now starts in `partial` mode so first paint is not
  blocked by `/config`, `/provider`, `/session`, `/lsp`, `/vcs`, or related
  bootstrap fetches. `LocalProvider` now tolerates the temporarily empty agent
  list during that early render.
- Capped Penguin-mode terminal background-color probing at `150ms` instead of
  allowing the full `1000ms` timeout on terminals that do not answer the color
  query.
- Deferred the OpenCode worker creation in Penguin web-backed mode until the
  delayed upgrade check or reload/shutdown path needs it.
- Live profile against local Penguin web on `127.0.0.1:8080`:
  - launcher reaches Bun spawn at about `255ms`
  - Bun/source mode reaches `thread.handler.start` at about `2.54s`
  - terminal color probing now adds about `156ms`
  - first render starts at about `2.69s`
- Current conclusion: the original 10s blank was partly a readiness gate, but
  the largest remaining cold-start target is Bun/source-mode module loading
  before the TUI thread handler. A built/sidecar/global runtime path is likely
  the next meaningful optimization after this surgical pass.
- Follow-up note: starting in `partial` mode needs seeded fallback
  provider/model/config state. Without that, the TUI can first paint quickly but
  leave the prompt/footer config blank until async bootstrap finishes. Phase 7
  covers that regression.

### 7. Testing and verification

- [x] Add focused tests for extracted helpers before behavior changes.
- [ ] Cover event parsing/filtering, session hydration, message ordering, and
      optimistic reconciliation.
- [ ] Run TUI regression tests after each extraction.
- [ ] Run backend API tests when moving compatibility into Penguin web routes.
- [ ] Keep live-provider testing optional; use deterministic fake-provider
      coverage for correctness.
- [ ] Follow `context/tasks/testing-pyramid.md`: use deterministic unit,
      state-machine, contract, and hermetic integration tests as the correctness
      proof; reserve live TUI/provider checks for smoke validation.

Progress - 2026-06-09:

- The Phase 6.5 partial-render optimization exposed a startup regression where
  the TUI could render before provider/model/config state existed, leaving the
  prompt/footer config blank until async bootstrap completed. Phase 7 now seeds
  Penguin partial startup from the same fallback bootstrap mapper used for
  sparse backend responses, so first paint has a usable provider, default model,
  agent, commands, config, and directory while real bootstrap data loads.
- Added a pure `session-dialog-list` helper seam for the Penguin `/sessions`
  dialog so filtering and active-session retention can be tested without
  rendering the TUI.
- Covered blank fallback sessions with no display messages, meaningful titled
  sessions, active blank sessions, current-session retention after a refresh,
  and search mode avoiding accidental current-session injection.
- Added a pure session-event reducer for `session.created`, `session.updated`,
  and `session.deleted` so the cached session list mutation path is covered
  without mounting the full sync provider. This locks in the behavior needed for
  newly created sessions to become visible without a TUI restart.
- Added run-state coverage for the final-response case where the assistant
  message is completed, backend status is idle, and the event stream has gone
  quiet. This locks the spinner/status behavior to `idle` instead of a stale
  running state.
- Added session-scoped usage parsing coverage for active tokens, percentage,
  context-window max, truncation count, removed messages, and freed tokens.
  Missing truncation telemetry now has explicit default coverage so the sidebar
  does not lose the usage snapshot when truncation fields are absent.
- Added TUI route-builder coverage proving usage refreshes target
  `/api/v1/sessions/{session_id}/token-usage` with encoded session IDs, not the
  legacy global `/api/v1/token-usage` route.
- Added fallback-bootstrap coverage for partial startup render so future
  startup optimizations cannot reintroduce an empty provider/model surface.
- Manual startup smoke against an already-running Penguin web server on
  `127.0.0.1:8080` showed first render at about `6.1s` in local Bun/source
  mode on the latest run. First paint now shows a nonblank fallback config
  (`Penguin Default (penguin-default) Penguin`) and upgrades to the real
  provider/model config (`GPT-5.5 (gpt-5.5) OpenAI`, with `fast` and `xhigh`)
  once async bootstrap completes. The dominant remaining startup cost is still
  before `thread.handler.start`, so it is Bun/source-mode module loading rather
  than async Penguin config bootstrap.
- Manual session smoke confirmed `Ctrl+X L` opens `/sessions` without restart,
  the newest Today session appears at the top of the list, and an older
  `Greeting Penguin` session can be loaded from the dialog with messages,
  settled duration, real model config, and session-scoped sidebar stats
  (`12,144 6% ($0.00)`).
- The full focused TUI helper/compatibility slice passed:
  `bun test test/cli/tui`.
- Focused TUI tests passed:
  `bun test test/cli/tui/sync-session-usage.test.ts test/cli/tui/session-dialog-list.test.ts test/tui/penguin-run-state.test.ts test/cli/tui/sync-bootstrap.test.ts`.
- Targeted backend tests passed for OpenAI model canonicalization and
  session-scoped usage:
  `uv run pytest -q tests/api/test_session_view_service.py::test_get_session_info_canonicalizes_openai_model_metadata tests/api/test_session_view_service.py::test_get_session_info_canonicalizes_global_model_fallback tests/api/test_token_usage_routes.py`.
- `bun run typecheck` passed after extracting the helper seam.

Remaining Phase 7 coverage targets:

- Add a higher-level hermetic sync-provider event harness once the sync store can
  be driven without mounting the full TUI provider. Pure session list mutation
  for `session.created`, `session.updated`, and `session.deleted` is now
  covered; the remaining gap is listener dispatch plus Solid store wiring.
- Add focused provider/model canonicalization tests at the backend
  compatibility boundary if another casing regression appears.
- Keep the final Layer 6 smoke manual: create a session, open `/sessions`
  without restart, load an older session, verify session-scoped sidebar stats,
  send one prompt, and confirm spinner/status stop after the final response.

### 8. Keep Link alignment explicit

- [x] Treat Penguin TUI as both a user-facing interface and a reference runtime
      UI for Link's Agentboard.
- [x] Keep ID boundaries clear:
  - Link task/session IDs
  - Penguin conversation/task IDs
  - OpenCode session/message/part IDs
  - A2A task/message IDs
- [x] Do not make Penguin-specific frontend streams the long-term Link contract.
      Link should consume Link-native runtime events projected from Penguin,
      OpenCode, A2A, Claude SDK, Codex, and future runtimes.
- [x] When upstream OpenCode has a better runtime UI pattern, decide whether it
      belongs in Penguin TUI, Link Agentboard, or both.
- [x] Document any Penguin TUI behavior that Link should copy before refactoring
      it away.

Phase 8 clarification - 2026-06-27:

- Treat Phase 8 as a plan-only alignment checkpoint. It decides boundaries and
  sequencing; it should not implement the unified event envelope or pull broad
  upstream UI changes.
- Penguin TUI remains both a shipping terminal UI and a useful reference for
  Link Agentboard runtime UX. That means Link may copy interaction patterns
  such as tool cards, progress/status treatment, session switching, retry
  affordances, and diff/file review, but not Penguin's current transport or
  event names as-is.
- Preserve runtime identity boundaries. Penguin conversation/task IDs,
  OpenCode session/message/part IDs, Link task/session IDs, and A2A IDs should
  be translated at adapter boundaries instead of treated as interchangeable.
- Defer the canonical `RuntimeEvent`/`SessionEvent` envelope to Phase 10. The
  current Penguin surface still includes multiple practical event shapes:
  local event bus `event_type + data`, OpenCode-shaped `{ type, properties }`
  events, RunMode status dictionaries, and message-bus protocol messages. Phase
  10 should define the backend contract that projects those into a durable
  runtime-event model.
- Use the core ACBRA refactor branch as the backend-contract prerequisite, not
  as part of Phase 8. Once that branch is merged, Phase 10 can build on
  `penguin.core_runtime`, `penguin.web.services`, provider/session/token
  services, and the deterministic default suite instead of adding new contract
  logic to `PenguinCore` or route handlers.
- Sequence after this clarification:
  1. Phase 9 rebaselines against current upstream OpenCode, imports direct TUI
     feature wins that do not require new backend truth, and inventories the
     backend-dependent features for Phase 10 instead of mixing contract work into
     the UI pass.
  2. Phase 10 moves backend-first upstream contracts into Penguin: replay,
     session records, status truth, provider/model metadata, structured errors,
     permission/question IDs, and message/part persistence.
  3. Later reliability/observability work can harden the final contract with
     runtime traces, replay fixtures, metrics, and broader fault/property tests.

### 9. Import direct upstream TUI feature wins

Phase 9 is now a rebaseline-and-import phase, not a narrow "copy a few widgets"
phase. The previous upstream comparison was anchored at OpenCode `v1.15.10`
from May 23, 2026. A fresh comparison against upstream `origin/dev` shows the
reference is materially stale: OpenCode is at
`dfeb1b5051a05b359bd4af711b204d2c0342c5f4`
(`feat(client): generate complete protocol client (#34164)`, 2026-06-27), and
the latest release observed in this audit is `v1.17.11` from 2026-06-25. The
release window to mine is therefore `v1.15.11` through `v1.17.11`, with roughly
1,210 commits since the old baseline.

Implementation rule: Phase 9 may adapt frontend/runtime UX and hardening that
Penguin's current backend can support. If an upstream feature depends on new
server contracts, generated protocol clients, durable session history, public
event definitions, or snapshot/revert semantics, Phase 9 should document the
shape and leave implementation to Phase 10.

#### 9.0 Rebaseline current upstream before implementation

- [x] Record the new OpenCode upstream baseline:
      `dfeb1b5051a05b359bd4af711b204d2c0342c5f4` on `origin/dev`.
- [x] Record the release range now in scope: `v1.15.11` through `v1.17.11`.
- [x] Treat the local OpenCode checkout as a reference checkout only; compare
      against `origin/dev` or a clean worktree because local `dev` may be dirty
      and far behind.
- [x] Update file-path references: the old CLI TUI surface under
      `packages/opencode/src/cli/cmd/tui` has been substantially deleted or
      replaced. Current terminal runtime references live mostly under
      `packages/opencode/src/cli/cmd/run/*`.
- [x] Mine desktop/app-only ideas from `packages/app/src/*`, but do not assume
      those components can be copied into Penguin's terminal TUI.
- [x] Classify each upstream item as one of:
      direct Phase 9 import, Penguin-specific adaptation, Phase 10 backend
      contract, desktop/app reference only, or out of scope.

#### 9.1 Prompt, composer, drafts, and submit safety

- [x] Review upstream responsive prompt sizing and prompt-size config from
      `v1.15.11`; adapt only if it improves Penguin terminal ergonomics.
      - [x] Audited. No direct prompt-size config import was needed for Phase 9;
            Penguin should keep terminal sizing behavior local unless a focused
            prompt-resize regression appears.
- [x] Import prompt duplicate-submit prevention, submit state handling, and
      shortcut gating where Penguin's current prompt flow can support it.
      - [x] Added a Penguin prompt submit gate so rapid repeated submits cannot
            create duplicate sessions or duplicate optimistic sends while the
            first send/local-command path is still settling.
      - [x] Hardened the gate against active Penguin runs: submits are now
            blocked while the current session is busy or still streaming, so a
            later prompt cannot be posted into an in-flight assistant turn.
      - [x] Continue reviewing upstream prompt submit state for shortcut gating,
            restore-on-failure behavior, and prompt draft preservation that does
            not require backend-owned draft contracts.
      - [x] Kept the Phase 9 import to frontend-safe submit gating. Prompt draft
            ownership and generated request-part contracts remain Phase 10
            backend/protocol work.
- [x] Review prompt history behavior, mode navigation, and slash/model command
      autocomplete fixes, including `/mo` preferring the models command.
      - [x] Moved prompt history browsing into a pure helper, matching the
            current upstream direction, so Penguin now filters blank entries,
            skips adjacent duplicates, browses newest-to-oldest reliably, and
            restores the user's draft prompt after leaving history browse mode.
      - [x] Added deterministic slash command ranking so command names and
            aliases sort ahead of display-label fuzziness, including `/mo`
            preferring the `/models` command when available.
      - [x] Continue reviewing mode navigation and prompt autocomplete behavior
            against the current upstream `cmd/run` prompt runtime.
      - [x] Imported only the local autocomplete/history pieces. Deeper mode
            navigation remains tied to session/draft truth and should follow
            Phase 10 backend contracts.
- [x] Preserve prompt text around tab/session/workspace switches where Penguin
      has enough session identity to do so safely.
      - [x] Classified as Phase 10 unless Penguin exposes backend-owned draft
            identity across sessions/workspaces. Avoid TUI-only draft inference.
- [x] Review upstream handling for paste/wide-character corruption and prompt
      editor edge cases; add deterministic tests before changing key handling.
      - [x] Audited. No reproducible Penguin corruption case was identified in
            Phase 9, so key handling was left unchanged rather than churned.
- [x] Inventory desktop prompt features for later UI tracks: per-tab draft
      prompt state, scoped drafts from Home, project/server-bound prompt drafts,
      prompt rollback scoping, async attachment scoping, thinking-level selector,
      mobile composer controls, and new-session progress indicator.
- [x] Defer any prompt behavior that requires backend-owned session drafts or
      generated protocol request parts to Phase 10.

#### 9.2 Session navigation, lists, tabs, and switchers

- [x] Review upstream experimental session switcher improvements and adapt the
      pieces that fit Penguin's current session/conversation model.
      - [x] Adapted the parts that are safe with current Penguin session
            records: directory labels and blank-title fallbacks. Server-aware
            switcher behavior remains Phase 10.
- [x] Bring over session picker sorting, local-project defaults, long-path
      truncation, sidebar/session ID display, and stable navigation polish where
      it reduces Penguin TUI drift.
      - [x] Adapted upstream's project-copy/session-list cue using Penguin's
            existing session `directory` field: the session dialog now shows a
            truncated directory basename for sessions outside the current
            directory, without adding new backend project/worktree contracts.
- [x] Review session list directory filters, workspace filters, hidden/blank
      session handling, empty-state behavior, and recent-session scrolling.
      - [x] Hardened blank-title rendering so meaningful or active sessions
            never appear as empty rows; the dialog falls back to the session ID
            while keeping child-session indentation.
- [x] Import low-risk missing-session cleanup behavior where Penguin can detect
      a session no longer exists without adding new backend contracts.
      - [x] Classified as Phase 10/session-service work. Penguin TUI should not
            delete or hide sessions based on local inference without a backend
            missing-session signal.
- [x] Inventory desktop tab ideas for later: draggable tabs, fixed tab widths,
      tab overflow scrolling/fade, Chrome-style `mod+1` through `mod+9` tab
      cycling, help button in tab bar, viewed-session notification clearing, and
      closing tabs for deleted sessions.
- [x] Defer server-aware session routes, tab-scoped servers, and same-session
      navigation across servers to Phase 10 unless Penguin already exposes a
      safe route-compatible equivalent.

#### 9.3 Workspaces, project copies, and session moves

- [x] Review upstream workspace management dialog and decide whether Penguin TUI
      needs a terminal equivalent or only web/TUI-service support.
      - [x] Classified as backend/service-first work. Phase 9 kept terminal
            affordances limited to labels and reminders backed by current
            session fields.
- [x] Adapt project-copy/session-move affordances that map cleanly to Penguin:
      highlighting project copies, preserving the current location, deleting
      working copies from the move dialog, and injecting a working-directory
      reminder after moving a session.
      - [x] Adapted project-copy visibility through session-directory labels.
            Move/delete semantics require stronger backend workspace ownership.
- [x] Review managed workspace cloning, moving sessions between workspaces and
      directories, and stable remote-backed project identity as Phase 10 backend
      contract inputs.
- [x] Bring over editor-open fixes where safe: open external editors from the
      worktree directory, support non-Git project paths, and fall back to local
      cwd for attach-mode sessions when the original project path is unavailable.
      - [x] Audited as later workspace/session service work. No direct Phase 9
            editor-open code change was made without a focused Penguin bug.
- [x] Inventory desktop project/workspace selectors, project avatars, directory
      picker v2, WSL server management, and active-project attachment behavior
      for later UI work.
- [x] Defer default worktree/session isolation semantics until Penguin's backend
      task/session ledger is explicit enough to avoid data loss.

#### 9.4 Diff, review, file tree, and file search affordances

- [x] Import or adapt upstream diff viewer improvements: accelerated scrolling,
      next/previous hunk navigation, configurable keybind to open the diff
      viewer, and compare-against-main mode.
      - [x] Audited. No direct diff viewer import was made in Phase 9; richer
            diff/review behavior should follow Penguin route and file-service
            contracts rather than terminal-only inference.
- [x] Preserve Penguin route and permission semantics while adding malformed
      path/diff metadata guards in permission and session views.
      - [x] Malformed runtime/tool metadata guards were added where current
            Penguin routes expose data. Permission/diff path contracts remain
            backend-owned.
- [x] Review file-tree throttling, directory tree loading, file/folder picker
      improvements, and session-directory scoping for direct Penguin usefulness.
      - [x] Classified as later file-service/review work unless Penguin exposes
            safe directory-tree and picker contracts.
- [x] Review upstream review-line-comment restoration and session review
      refresh/VCS diff caching as later API/service work.
- [x] Inventory `fff`-backed file search tools and unified filesystem search as
      backend/service ideas; do not treat them as a Phase 9 terminal-only import
      unless Penguin's current tools can expose the same behavior safely.
- [x] Add focused tests around any imported diff/file review behavior, especially
      malformed metadata and path normalization.
      - [x] No standalone diff viewer behavior was imported in Phase 9. The
            malformed metadata guards that were adapted are covered by focused
            runtime/session rendering tests.

#### 9.5 Runtime rendering, tools, permissions, and errors

- [x] Import low-risk runtime rendering hardening: duplicate renderable ID
      prevention, worker rejection handling, inline tool row alignment, failed
      inline tool error expansion, and malformed tool-input crash handling.
      - [x] Added shared malformed tool-input guards for transcript export and
            session tool summaries. Non-record tool inputs now coerce to a
            display record, primitive summaries do not assume object inputs, and
            transcript export handles circular/non-JSON values without crashing.
      - [x] Keep upstream inline-tool row alignment and expandable failed-tool
            errors as a follow-up UI rendering slice; Penguin's route has a
            different OpenTUI/layout baseline, so this should be adapted behind
            focused render tests instead of copied wholesale.
      - [x] Adapted the inline-tool row behavior behind a tested row-state
            helper: wrapped completed rows use a fixed icon column, denied
            permission errors remain struck through, and real tool failures are
            expandable instead of always dumping error text inline.
      - [x] Adapted upstream duplicate renderable ID prevention for text and
            reasoning parts by including `messageID` in renderable IDs.
      - [x] Audited upstream worker rejection handling. Penguin's TUI worker
            already logs `unhandledRejection` and `uncaughtException`; later
            lifecycle cleanup can remove handlers on shutdown if the worker
            becomes reusable in-process.
- [x] Review subagent runtime UI fixes: background subagent shortcut gating,
      subagent retry status, backgrounding synchronous/running subagents, and
      spinner unsticking.
      - [x] Adapted the low-risk display portion: subagent task labels now keep
            the background marker attached to the subagent label, and toolcall
            count text is centralized behind tests.
      - [x] Defer backgrounding synchronous/running subagents and retry-dialog
            navigation until Penguin's backend/session status contracts expose
            enough truth to avoid TUI inference.
- [x] Bring over permission/question UI polish where Penguin route shapes
      already align, especially replies routed through the correct session
      directory.
      - [x] Audited upstream directory-aware permission/question reply fixes
            (`3cf1cef7fe`, `f4851e3bd9`). Penguin's current local
            permission/question routes do not accept or apply per-reply
            directory context, so this remains a Phase 10 backend/API contract
            item instead of a TUI-only field.
- [x] Review auth headers on RunCommand fetches and command `$ARGUMENTS` file
      injection fixes for Penguin command execution.
      - [x] Adapted upstream RunCommand authorization-header preservation for
            Penguin's in-process CLI fetch path and shared it with the TUI
            worker auth helper.
- [x] Surface structured failures where Penguin already has provider/tool error
      categories; defer richer retry dialogs until backend error shape is stable.
      - [x] Phase 9 surfaced only frontend-safe tool/runtime failures: malformed
            tool inputs, expanded inline tool failures, and readable MCP
            resource labels. Rich retry dialogs remain Phase 10/error-contract
            work.
- [x] Add tests for runtime display hardening rather than relying on manual TUI
      checks.
      - [x] Added focused Bun tests for malformed tool input, inline tool row
            state, subagent labels, duplicate renderable IDs, RunCommand auth,
            MCP autocomplete, reasoning summaries, and notification policy.

#### 9.6 Provider, model, reasoning, and auth UX

- [x] Review model/reasoning UI changes that can be frontend-only: thinking
      spinner restoration, variant hotkey toast when no variants exist,
      reasoning summary display blocks, and provider-gated reasoning summaries.
      - [x] Adapted upstream variant-key feedback for Penguin's actual
            `variant.cycle` command: models with no variants now produce an
            informational toast instead of silently no-oping, with pure tests
            for the selection contract.
      - [x] Adapted frontend-safe thinking spinner restoration for Penguin's
            simpler reasoning renderer: unfinished reasoning blocks now show a
            spinner label, completed blocks show a static `Thought` label, and
            no provider capability is inferred in the TUI.
      - [x] Adapted the frontend-only reasoning summary display behavior:
            reasoning blocks that begin with a bold summary title now render and
            export the title separately from the markdown body, while ordinary
            reasoning text keeps the existing display/export shape.
      - [x] Adapted release-date model ordering for provider-scoped model
            dialogs while preserving Penguin's existing free-first alphabetical
            ordering in the regular picker.
      - [x] Merged warmed provider catalogs into sparse configured provider
            catalogs for Penguin's model picker and local model validation.
            This keeps configured aliases available while allowing OpenRouter
            and other discovered provider models to appear once backend catalog
            discovery has warmed.
- [x] Inventory provider/model capability changes for Phase 10: OpenAI
      WebSocket transport, custom WebSocket base URLs, sticky `X-Session-Id`
      proxy headers, stored provider credentials, connector-based auth,
      provider integration IDs, and SDK refresh after credential changes.
      - [x] Upstream items identified so far include OpenAI WebSocket
            transport, custom WebSocket base URLs, sticky session proxy
            headers, stored provider credentials, connector auth, and SDK
            refresh after credentials change; keep these in Phase 10 unless the
            Penguin backend exposes stable contracts first.
- [x] Review new provider support only as UI/catalog implications unless Penguin
      backend already supports it: Snowflake Cortex, Cohere North, GLM-5.2
      high/max thinking variants, MiniMax M3 thinking toggle, vLLM interleaved
      reasoning field, Bedrock OpenAI/Mantle/SAP AI Core variants, Cloudflare AI
      Gateway API key handling, Devstral casing, and Copilot custom headers.
      - [x] Classified as Phase 10/backend contract work. Penguin should adopt
            these through provider/model services and generated SDK contracts,
            not by hard-coding inferred capability truth in the terminal UI.
- [x] Track auth/logout/search and expired remote-config auth recovery as
      backend/API work, not a Phase 9 UI-only import.
      - [x] Deferred to Phase 10 provider/auth work; no provider capability
            metadata or OpenCode naming was adopted in this Phase 9.6 TUI pass.
- [x] Preserve Penguin's existing provider contract tests before adopting any
      OpenCode naming or capability metadata.
      - [x] No provider contract behavior changed in this section. Existing
            provider tests remain the proof point for any later backend/provider
            adoption.

#### 9.7 MCP, plugins, commands, and extension surfaces

- [x] Inventory MCP UI/runtime changes: log notifications, debug protocol
      version, server status messages, progress timeout resets, readable
      structured tool output, resource templates, resource read tools, server
      instructions in context, server cwd/root support, and denied-access hiding.
      - [x] Adapted the frontend-safe MCP autocomplete noise fix: resource
            suggestions now display and fuzzy-match on resource name only, while
            preserving URI/client metadata in the selected prompt part.
      - [x] Keep the remaining MCP runtime/protocol items as backend/service
            inventory unless a stable Penguin endpoint already exposes the
            required status, resource-template, progress, log, or capability
            data.
- [x] Review MCP OAuth/error UX: manual OAuth URL printing, callback shutdown,
      escaped OAuth errors, IPv4 loopback binding, expired session recovery, and
      clearing closed clients.
      - [x] Deferred to Phase 10/backend service work. Upstream fixes include
            manual OAuth URL printing, surfaced/escaped callback errors, IPv4
            loopback binding, idle callback shutdown, scoped auth status, closed
            client cleanup, and credential refresh on reauthentication.
- [x] Review command palette/registry/plugin ideas as later architecture work:
      command registry, namespaced hook API, V2 plugin API, plugin dispose hook,
      plugin client active-server reuse, plugin PTY environment, and plugin
      readiness before reference-backed config.
      - [x] Classified as later architecture work. Penguin should map these
            through its own plugin/command runtime boundaries instead of copying
            OpenCode's host API directly.
- [x] Keep plugin/runtime adoption out of Phase 9 unless a specific TUI feature
      needs a small compatibility hook.
      - [x] No plugin runtime adoption was needed for Phase 9.7.
- [x] Defer MCP server capability negotiation, catalog pagination, abort
      signals, and generated SDK protocol changes to Phase 10/backend contracts
      unless Penguin already exposes equivalent data.
      - [x] Deferred. These require server/client capability truth and generated
            protocol contracts, not terminal-side guessing.

#### 9.8 Desktop/app UX ideas to mine without copying blindly

- [x] Review desktop v2 home/session layout ideas for Penguin or Link: empty
      home state, home tab toggle, archived sessions, jump-to-latest restyle,
      sessions list improvements, server sections, settings v2, status popover,
      titlebar/session controls, and debug bar.
      - [x] Mined as Link/Penguin UX references. Terminal-safe session-list
            improvements such as project-copy labels and blank-title fallbacks
            were already adapted earlier in Phase 9; desktop home tabs,
            archived sessions, server sections, titlebar controls, and status
            popovers should stay in the app/Link track.
- [x] Review session timeline improvements: faster timeline rendering, no
      flicker/scroll jumps, rejected stale timeline ranges, virtualized
      measurement, and shared synced session data.
      - [x] Classified as Phase 10/session-event-contract work for Penguin TUI.
            The terminal route already has direct scroll/jump commands; deeper
            timeline virtualization and stale-range rejection require backend
            replay/history/session-event truth.
- [x] Review notification and session ownership ideas: late notification cleanup,
      viewed-session clearing, todo docks preserved across sessions, provider
      dialogs tied to the starting session, and concurrent event reconciliation.
      - [x] Mapped notification ownership into Phase 9.9 terminal notification
            policy. Viewed-session clearing, provider-dialog session ownership,
            and concurrent reconciliation should follow Phase 10 runtime/session
            event contracts.
- [x] Treat mobile bottom navigation, WSL management, update UI, color themes,
      safe-area insets, and Electron-specific changes as design references, not
      immediate Penguin terminal TUI work.
      - [x] Reference only. These are desktop/mobile runtime concerns and should
            not be copied into terminal TUI behavior.
- [x] Keep Link Agentboard needs in mind, but translate through Penguin's
      adapters instead of copying OpenCode app contracts directly.
      - [x] Keep this as a Link/Penguin adapter input after Phase 10 backend
            contracts are stable.

#### 9.9 Terminal notifications and attention routing

- [x] Design terminal notifications as a configurable user preference, not a
      hard-coded sound effect. Suggested modes: off, visual only, terminal bell,
      OS notification, terminal-specific notification, sound, or combined.
      - [x] Added a pure notification policy helper with modes `off`, `visual`,
            `bell`, `osc`, `os`, `terminal`, `sound`, and `combined`. Delivery
            adapters are intentionally not invoked in Phase 9.
- [x] Treat sound packs as a themeable layer. Start with generic sounds and
      optional novelty packs such as train-station or penguin/NOOT-NOOT sounds,
      but keep them disabled by default and easy to mute.
      - [x] Added sound-pack selection metadata for generic, train-station, and
            penguin/NOOT-NOOT-style payloads, disabled unless `sound` mode is
            selected.
- [x] Support attention events with clear categories: run complete, run failed,
      approval/question waiting, provider/auth needs action, background
      subagent update, long-running tool finished, and reconnect/replay failed.
      - [x] Captured these as explicit `AttentionCategory` values in the policy
            helper.
- [x] Prefer portable terminal mechanisms first: BEL for bell-compatible
      terminals and OSC notification escape sequences where supported.
      - [x] Captured as channels only. Actual BEL/OSC emission remains a future
            delivery adapter behind explicit settings.
- [x] Add OS-specific adapters only behind capability detection and explicit
      settings: macOS notification/sound command, Linux desktop notification,
      and Windows notification path.
      - [x] Captured as `os` channel payloads only; no OS command execution in
            default TUI behavior.
- [x] Add terminal-specific integrations as optional adapters, especially for
      CMUX and Ghostty. Do not require either terminal for Penguin TUI behavior.
      - [x] Captured as `terminal` channel payloads only; CMUX/Ghostty adapters
            should be optional later.
- [x] Make notification text privacy-aware. Never include raw prompt text,
      secrets, file contents, or provider credentials in desktop banners or
      terminal sidebars by default.
      - [x] Payloads default to safe category titles/bodies and only include
            caller-provided details when explicitly requested, with simple
            secret/token redaction.
- [x] Add quiet-hours, focus, per-project, and per-event-category controls if
      notifications become noisy during long multi-agent runs.
      - [x] Added quiet-hours and per-category filtering to the pure policy.
            Focus/per-project controls can layer on the same helper later.
- [x] Add tests around notification policy selection and emitted notification
      payloads; keep actual OS/terminal notification delivery as an opt-in
      manual or integration check.
      - [x] Added deterministic Bun tests for disabled mode, combined visual+bell
            payloads, novelty sound-pack selection, quiet hours, category
            filters, privacy redaction, and channel mapping.
- [x] Keep this separate from the canonical runtime event envelope. Phase 9 can
      map existing Penguin events to notifications; Phase 10 can later feed the
      same policy from backend-owned runtime events.
      - [x] The helper accepts local `AttentionEvent` values only. It does not
            define or require the future canonical runtime event envelope.

#### 9.10 Replay, snapshots, history, and event-contract inventory

- [x] Inventory upstream `run --replay`, ACP/session replay fixes, session
      metadata API/SDK support, durable session history pages, generated
      protocol client, extracted public event definitions, and server contracts
      as Phase 10 prerequisites.
      - [x] Phase 10 ownership: run/replay belongs in Penguin run/session
            services; durable history and metadata belong in web/session
            services and conversation/session storage; generated protocol
            clients and public events belong in future protocol modules.
- [x] Inventory upstream session snapshot/revert controls, snapshot performance
      fixes, subdirectory snapshot path fixes, and file-change rollback UI for
      Penguin's checkpoint/fork/revert track.
      - [x] Phase 10 ownership: checkpoint/fork/revert services should own
            source session lineage, subdirectory path handling, snapshot
            performance, and rollback payloads before the TUI adds richer
            controls.
- [x] Do not implement the canonical `RuntimeEvent`/`SessionEvent` envelope in
      Phase 9. Current Penguin event shapes remain practical adapters until
      Phase 10 defines backend-owned replay and event projection.
      - [x] Preserved. Phase 9 added only local notification/UX helper payloads,
            not a canonical runtime event envelope.
- [x] Add notes linking each backend-dependent upstream feature to the Penguin
      service/module that should eventually own it: `web.services`,
      `core_runtime`, `run_mode`, `conversation_manager`, checkpoint services,
      provider/auth services, or future protocol modules.
      - [x] Links captured in the bullets above and in Phase 10. Provider/auth
            capability truth remains provider/auth service work; session status,
            replay, and event projection remain backend-owned.
- [x] Avoid describing Penguin's current context-window behavior as compaction;
      upstream "context overflow" and "compact v2 session context" concepts
      should be translated carefully against Penguin's category-priority and
      recency trimming model.
      - [x] Recorded explicitly: Penguin's current CWM trims by category
            priority and recency. Upstream compaction/session-context concepts
            should be translated only as future design work.

#### 9.11 Phase 9 execution and verification record

- [x] Start with small PR-sized slices, ordered by least backend dependency:
      prompt/submit safety, runtime rendering hardening, diff viewer affordances,
      session picker/list polish, then workspace/project move affordances.
- [x] For each slice, write or repair focused Bun/Python tests before importing
      behavior.
- [x] Use upstream file paths as references, but keep Penguin naming, Penguin
      route shapes, and Penguin backend truth.
- [x] After each slice, classify anything blocked by missing backend truth and
      move it to Phase 10 rather than adding local TUI inference.
- [x] Run targeted TUI tests for changed components and any affected backend
      contract tests.
- [x] Periodically run the Penguin default Python suite when backend adapters or
      shared services are touched.
- [x] Before closing Phase 9, produce a short adoption matrix showing:
      imported now, adapted for Penguin, deferred to Phase 10, desktop/reference
      only, and intentionally skipped.

Phase 9 adoption matrix:

| Classification | Upstream items | Penguin decision |
| --- | --- | --- |
| Direct import | Duplicate-submit prevention, local prompt history behavior, slash-command ranking, auth-header preservation for run-command fetches | Imported as focused helpers/tests where current Penguin state already supports the behavior. |
| Penguin adaptation | Session directory labels, blank-title fallback, malformed tool-input guards, inline tool failure expansion, duplicate renderable IDs, subagent task labels, reasoning spinner/title display, provider-scoped release-date model sorting, warmed provider/model catalog merging, MCP autocomplete labels, notification policy | Adapted to Penguin route shapes, OpenTUI rendering, current session records, and terminal constraints instead of copying OpenCode code directly. |
| Deferred to Phase 10 | Backend-owned drafts, generated request parts, server-aware sessions/tabs, missing-session cleanup, managed workspaces, session moves, workspace isolation, richer diff/review/file-tree/search, permission directory replies, retry dialogs, provider/auth capability truth, MCP protocol/catalog/OAuth, replay/history/snapshots, canonical `RuntimeEvent`/`SessionEvent` | Requires backend/service/protocol truth. Do not infer these in the TUI. |
| Desktop/reference only | Home tabs, draggable tab bars, status popovers, mobile controls, WSL/server management UI, update UI, settings v2, Link Agentboard references | Keep as product/design inputs for Link/Penguin adapter work after backend contracts stabilize. |
| Intentionally skipped | Direct copy of OpenCode app/Electron/mobile code, direct adoption of OpenCode provider naming/capability metadata, TUI-side compaction semantics, OS/terminal notification delivery by default | Skipped to preserve Penguin backend truth, terminal portability, opt-in notification behavior, and CWM terminology. |

Final Phase 9 verification targets:

- Focused Bun tests for each changed helper/component.
- `bun run typecheck` for TUI package changes.
- Targeted formatting checks on touched TypeScript/TSX/Markdown files.
- Python/Responses tool surface coverage for `penguin/tools/tool_manager.py`
  when default tool exposure changes.
- `git diff --check`.
- Python/default Penguin suites only when backend adapters or shared services are
  modified; Phase 9 code changes stayed mostly inside the TUI package and plan
  docs, with narrow Python tool allowlist patches verified separately.

### 10. Move backend-first upstream contracts into Penguin

Phase 10 is the backend-contract and real-wiring phase for the Phase 9 TUI
work. Phase 9 imported or adapted frontend/runtime UX where Penguin's current
backend could support it. Phase 10 should remove the remaining TUI-side guesses
by making Penguin's backend authoritative for the data the TUI renders.

Implementation rule: every section should follow
Audit -> define contract -> add/repair tests -> implement backend
service/route -> implement TUI schema/state/render wiring -> run focused tests
-> commit. Live provider or live terminal checks are smoke validation only; the
correctness proof should be deterministic backend contract tests and Bun tests.

Out of scope for Phase 10:

- Multi-agent execution fixes from `context/tasks/resolve-multi-agents.md`.
  That is a follow-up PR outside the Penguin TUI upstream track.
- The full Link-style unified runtime event envelope. Phase 10 stabilizes the
  current TUI/SSE contracts and keeps enough correlation fields to make a later
  envelope migration straightforward.
- Route bloat or new `PenguinCore` business logic. Backend payload shaping
  belongs in `penguin/web/services/*` or smaller runtime/domain modules.

#### 10.1 Baseline contract audit

- [x] Map Phase 9 UI surfaces to backend truth sources:
  - provider/model catalog -> `penguin.web.services.provider_catalog`,
    `opencode_provider`, provider auth/credential services,
    `component/dialog-model.tsx`, `util/model-*`.
  - session hydration -> `session_view`, token-usage routes,
    `context/sync.tsx`, `context/session-hydration.ts`,
    `context/sync-session-usage.ts`.
  - prompt source/file references -> file/find/upload routes,
    `component/prompt/autocomplete.tsx`, `history-state.ts`,
    `paste-policy.ts`, `file-url.ts`, `prompt/index.tsx`.
  - diffs/modified files -> `session_view.get_session_diff`,
    VCS/path routes, sidebar modified-file rendering, upstream diff-viewer
    reference code.
  - commands -> `component/dialog-command.tsx`,
    `penguin-local-command.ts`, `penguin-local-command-runtime.ts`,
    backend project/task/skills/settings routes.
  - notifications -> `notification-policy.ts`, current TUI event/status hooks,
    future backend notification settings service.
  - events/SSE -> `context/penguin-event-stream.ts`, `sync-scope.ts`,
    `sync-session-events.ts`, web SSE event projection helpers.
- [x] Identify remaining local guesses:
  - sparse provider refresh and alias canonicalization still need backend-owned
    capability metadata and stable connected/disconnected provider truth.
  - session hydration still retries around catalog warmup and partial snapshots.
  - prompt source restoration still depends on TUI-side guards for malformed or
    ambiguous source payloads.
  - modified-file summaries exist in TUI/sidebar form before a complete
    backend diff contract and file-tree diff viewer are wired together.
  - commands are still split between local prompt helpers and backend routes
    rather than one backend-declared command registry.
  - notifications are currently local policy/render helpers, not a backend-owned
    configurable policy.
  - SSE events are practical OpenCode-shaped projections, not a single canonical
    runtime envelope.

#### 10.2 Provider/model catalog

- [ ] Make backend catalog payloads authoritative for provider IDs, connected
      status, sparse catalogs, canonical provider/model IDs, aliases, display
      names, recents, favorites, reasoning options, and provider capability
      flags.
- [ ] Fix OpenRouter/OpenAI/user-config catalog regressions at the backend
      compatibility boundary instead of adding display-name workarounds in the
      TUI.
- [ ] Ensure the TUI refreshes sparse active providers and resolves session
      models after catalog warmup.
- [ ] Add backend tests for provider connection state, sparse/full catalog
      metadata, alias canonicalization, favorites/recents shapes, disconnected
      providers, and user-configured model entries.
- [ ] Add Bun tests for canonical selection keys, favorites/recents de-duping,
      sparse refresh, aliases, disconnected providers, and active-session model
      hydration.

#### 10.3 Session hydration

- [ ] Make session hydration reliable for model/provider, title, cwd/workspace,
      token/context stats, active run state, selected agent/session, and
      session-scoped usage.
- [ ] Retry hydration only while data is legitimately pending. Do not overwrite
      good local state with stale, partial, or wrong-directory payloads.
- [ ] Add backend tests for cold start, session switch, catalog-late hydration,
      explicit directory scoping, and stale-session protection.
- [ ] Add Bun tests for TUI hydration retry, status preservation, model
      restoration after catalog warmup, and session-scoped usage refresh.

#### 10.4 Prompt source/file references

- [ ] Make `@file`, paste, image/SVG, upload, and prompt-history source payloads
      explicit end-to-end.
- [ ] Backend and TUI should agree on whether content is embedded, referenced by
      path, summarized, or omitted.
- [ ] Validate prompt history/source schemas before editor/extmark restoration.
- [ ] Add tests for root-relative files, scoped session directories, duplicate
      filenames, malformed sources, paste thresholds, image/SVG plus surrounding
      text, and exact file URL/path construction.

#### 10.5 Diffs/modified files

- [x] Make backend services authoritative for modified files, file stats, diff
      summaries, per-file diff payloads, and session-scoped changed-file state.
- [x] Keep local git probing as an explicit fallback only when backend state is
      unavailable, not as the primary TUI truth.
- [x] Normalize and merge TUI `session.diff` payloads from hydration and live
      events before they reach sidebar state.
- [x] Add fake-git backend tests and TUI schema tests for empty/malformed diffs,
      duplicate file rows, changed files, and untracked files.
- [x] Defer the full upstream diff viewer UI until after the backend contract is
      stable; keep the current sidebar list as the Phase 10 baseline.

Follow-up before enabling the full interactive diff viewer:

- Add broader coverage for renamed files, binary files, deleted files, large
  diffs, and per-file diff drilldown.
- Add TUI render tests for empty diffs, changed files, renamed files, binary
  files, deleted files, large diffs, and session/project scoping.

#### 10.6 Commands

- [x] Wire a backend command registry contract.
- [x] Backend declares available commands, labels, descriptions, shortcuts,
      enablement, required context, and execution route/payload metadata.
- [x] TUI command bootstrap consumes that contract and handles disabled or
      unavailable commands cleanly.
- [x] Add backend registry tests and TUI command-list/selection/execution tests.

#### 10.7 Notifications

- [x] Implement real notification policy wiring across backend settings and TUI
      delivery hooks.
- [x] Support configurable notification modes without overcommitting to every
      OS or terminal adapter in this PR.
- [x] Include config-ready options for generic sounds, OS/terminal hooks, train
      station sounds, and future Penguin/NOOT NOOT sounds.
- [x] Sanitize notification text consistently.
- [x] Add tests for policy selection, redaction, disabled mode, needs-input
      events, terminal capability fallbacks, and unsupported adapter behavior.

Completed in Phase 10: the backend exposes `/api/v1/notifications/config`;
bootstrap stores the normalized policy; the TUI maps approval/question/error
events to terminal notification payloads with duplicate suppression. Portable
delivery supports visual/log, bell, and OSC payloads. OS/terminal/sound adapters
are represented as policy capabilities and remain opt-in no-ops until a specific
terminal integration is selected.

#### 10.8 Event/SSE stabilization

- [ ] Stabilize current TUI-facing event payloads without introducing the full
      unified runtime envelope.
- [ ] Ensure SSE/OpenCode-projected events have schemas, stable ordering, stable
      IDs where available, session/project correlation, and replay/reconnect
      behavior that does not duplicate or reorder messages.
- [ ] Add tests for stream chunks, tool results, action results, token/context
      updates, session lifecycle events, errors, reconnect/replay, and
      wrong-session filtering.

#### 10.9 Route/service cleanup

- [ ] Keep routes thin while Phase 10 adds backend truth.
- [ ] Move payload shaping and business logic into `penguin/web/services/*`.
- [ ] Put TUI compatibility in services/adapters rather than route handlers or
      `PenguinCore`.
- [ ] Add service-level tests for every extracted backend behavior.

#### 10.10 Verification/docs/PR readiness

- [ ] Run focused tests after each section.
- [ ] Periodically run:
  - `uv run --group dev pytest tests -q`
  - touched Bun TUI test packs
  - `bun run typecheck`
  - Prettier/format checks for touched TypeScript/TSX/Markdown files
  - Ruff/compileall for touched Python files
  - `git diff --check`
- [ ] Run one local smoke path before review:
  - `HOST=127.0.0.1 PORT=8080 uv run penguin-web`
  - `uv run penguin --url http://127.0.0.1:8080 --no-web-autostart`
- [ ] Update this plan with completed Phase 10 work and deferred follow-ups.
- [ ] Leave the branch ready for user review; do not open the PR automatically.

### 11. Evaluate OpenTUI, keymap, and plugin-runtime upgrades

- [ ] Evaluate the OpenTUI dependency jump from Penguin's embedded `0.1.75`
      baseline toward upstream's `0.2.15` track separately from protocol work.
- [ ] Review upstream flat keybind config and `@opentui/keymap` extraction.
- [ ] Decide whether Penguin's local command/settings/skills surfaces should map
      to upstream command palette, keymap, or plugin-runtime concepts.
- [ ] Keep plugin/runtime adoption out of the first upstreaming pass unless a
      specific direct feature depends on it.

## Open Questions

- Should Penguin aim for full OpenCode API parity, or a documented compatible
  subset plus Penguin extensions?
- Should the TUI ever synthesize `message.updated`, `message.part.updated`, or
  `session.status`, or should those always come from the backend?
- Can Penguin's backend provide enough immediate session truth to eliminate most
  optimistic prompt logic?
- What is the right TUI-visible threshold for an active stream becoming
  `stale`, and should that threshold be configurable?
- Should project/task commands be first-class OpenCode-compatible commands, or
  stay as Penguin-only local commands?
- Should settings and skills panels be upstreamable abstractions, or Penguin-only
  UI additions?
- How much branding should remain inline versus isolated behind product config?
- Is `reference/opencode` intended to remain a vendored comparison checkout, or
  should this track use a clean external clone/worktree for upstream syncs?
- What is the desired release coupling between `penguin-ai[tui]` and OpenCode
  TUI source snapshots?
- Should Penguin's TUI track upstream OpenCode more aggressively now that
  upstream is improving exactly the surfaces Penguin/Link care about?
- Which upstream OpenCode API/event changes should Penguin match directly, and
  which should be translated into Link-native runtime events only at the Link
  adapter boundary?
- Is OpenCode's latest diff viewer good enough to reuse as Penguin's primary
  change-review surface, and should Link Agentboard mirror the same UX?
- Should Penguin keep maintaining a standalone TUI long term, or eventually
  treat the standalone TUI as a developer/power-user surface while Link becomes
  the main collaborative interface?
- How should OpenCode subagent/session review semantics map onto Penguin ITUV
  and Link's `PENDING_REVIEW` / approval model?

## Suggestions

- Start with an audit-only commit that produces a divergence map. Do not mix the
  first pass with refactors.
- Treat `prompt/index.tsx` and `sync.tsx` as the first extraction targets because
  they carry the largest and riskiest divergence.
- Move protocol adaptation down before rebasing against newer OpenCode. Rebasing
  first will likely create conflict churn without reducing the root problem.
- Prefer small helpers with narrow inputs and outputs over a large
  "Penguin mode" abstraction.
- Preserve deliberate Penguin UX differences, but make them look like product
  configuration or clearly named Penguin features.
- When possible, fix Penguin's backend OpenCode-compatible surface instead of
  adding another TUI-side shape probe.
- Keep temporary compatibility branches annotated with an issue or checklist item
  so they do not become permanent drift.
- Treat upstream OpenCode changes as a source of leverage, not only as merge
  pressure. Every reliability/smoothness fix adopted upstream is one less custom
  terminal problem for Penguin to own.
- Prefer upstream-compatible backend/API fixes when they also strengthen Link's
  runtime adapter story.
- Treat spinner reliability and wall-clock elapsed time as runtime trust
  signals, not cosmetic polish. They should be fixed before a broad rebase if
  they are isolated enough to do safely.
- When OpenCode does something materially better on the backend, recreate or
  adapt the better contract in Penguin in a later backend phase instead of
  cementing current Penguin route shapes.
- Use Link's `RuntimeEvent`/`SessionEvent` direction as a guardrail: do not let
  Penguin/OpenCode/A2A-specific vocabulary become the long-term Link frontend
  contract.
- Mine upstream OpenCode's TUI for UI patterns Link needs: tool cards, diff
  review, session review, model/provider controls, approval/question surfaces,
  and runtime activity state.

## Concerns

- The current local OpenCode reference is stale, so any diff against it may
  overstate or understate real upstream divergence.
- TUI-side optimistic events can mask backend truth problems and create ordering
  bugs after reload or across sessions.
- A stopped spinner during an active backend run is a high-trust UX failure:
  users cannot distinguish slow work from event-stream stalls or bugs.
- A wall-clock timer implemented only from local prompt timestamps may be good
  enough short term, but backend-provided run start/end times are preferable for
  reload/replay correctness.
- Directory/session scoping is subtle. Moving it too aggressively could regress
  multi-worktree or subagent behavior.
- Provider/model defaults may be carrying implicit assumptions about Penguin's
  backend and auth state.
- Local project/task commands are useful, but if they remain embedded in prompt
  submission they will continue to increase conflict risk.
- Backend API parity work can easily spill into route bloat; keep business logic
  in `penguin/web/services/`.
- A large rebase against current OpenCode should wait until the fork-specific
  behavior is better isolated.
- Upstream has moved enough that blindly rebasing could conflate three separate
  concerns: OpenTUI/runtime dependency upgrades, OpenCode API/event changes, and
  Penguin-specific backend compatibility.
- Link's frontend should not accidentally inherit Penguin TUI's temporary
  compatibility shims as product architecture.
- Some upstream OpenCode concepts may be excellent for a single-runtime TUI but
  still need translation before they fit Link's multi-agent, workspace-scoped,
  cross-org model.
- If Penguin falls too far behind upstream OpenCode/OpenTUI, the fork stops
  delivering the original leverage benefit and starts becoming a bespoke TUI
  anyway.

## General Thoughts

The key principle is separation of product identity from protocol adaptation.
Penguin should keep its identity, settings, local commands, and backend features.
The part to reduce is protocol compensation inside generic OpenCode TUI
components.

For upstreamability, the best unit of progress is not "make the UI identical."
It is "make each difference explainable." A reviewer should be able to look at a
diff and quickly tell whether a change is product branding, transport/auth,
backend compatibility, or a deliberate Penguin feature.

The highest-leverage refactor is likely a Penguin TUI adapter layer that owns:

- auth headers
- SSE subscription differences
- bootstrap response mapping
- session creation/send behavior
- local command dispatch
- failure recovery and optimistic reconciliation

Once those are explicit, most of the remaining TUI can either stay close to
OpenCode or carry small, intentional product differences.

The larger product principle is separation of runtime semantics from UI
mechanics. Penguin owns agent/runtime semantics. OpenCode/OpenTUI can provide a
large share of terminal UI mechanics. Link owns the collaborative team layer and
should consume normalized runtime events rather than raw Penguin or OpenCode
events.

That makes upstream OpenCode progress encouraging rather than threatening. If
OpenCode is improving event reliability, session review, diff review, provider
auth, model controls, and OpenTUI smoothness, Penguin can focus more on backend
truth and compatibility while Link focuses on team/workspace orchestration. The
maintenance cost of tracking upstream is real, but it is probably still lower
than building and sustaining an equivalent TUI from scratch.
