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

### 7. Testing and verification

- [ ] Add focused tests for extracted helpers before behavior changes.
- [ ] Cover event parsing/filtering, session hydration, message ordering, and
      optimistic reconciliation.
- [ ] Run TUI regression tests after each extraction.
- [ ] Run backend API tests when moving compatibility into Penguin web routes.
- [ ] Keep live-provider testing optional; use deterministic fake-provider
      coverage for correctness.

### 8. Keep Link alignment explicit

- [ ] Treat Penguin TUI as both a user-facing interface and a reference runtime
      UI for Link's Agentboard.
- [ ] Keep ID boundaries clear:
  - Link task/session IDs
  - Penguin conversation/task IDs
  - OpenCode session/message/part IDs
  - A2A task/message IDs
- [ ] Do not make Penguin-specific frontend streams the long-term Link contract.
      Link should consume Link-native runtime events projected from Penguin,
      OpenCode, A2A, Claude SDK, Codex, and future runtimes.
- [ ] When upstream OpenCode has a better runtime UI pattern, decide whether it
      belongs in Penguin TUI, Link Agentboard, or both.
- [ ] Document any Penguin TUI behavior that Link should copy before refactoring
      it away.

### 9. Import direct upstream TUI feature wins

- [ ] Import or adapt upstream's diff viewer UI and file-tree affordances.
- [ ] Import or adapt full-session fork and session review affordances, mapped
      to Penguin conversation/task semantics.
- [ ] Bring over session picker sorting, sidebar session ID display, and
      local-project default behavior where it fits Penguin.
- [ ] Review upstream prompt duplicate-submit prevention and prompt history
      behavior against Penguin's current prompt flow.
- [ ] Bring over permission/question UI polish where Penguin route shapes
      already align.
- [ ] Add retry dialogs that show provider and failure reason once backend error
      shapes are reliable enough.
- [ ] Bring over malformed tool-input crash handling and other low-risk runtime
      rendering hardening.

### 10. Move backend-first upstream contracts into Penguin

- [ ] Support or translate incremental `message.part.delta` events before
      relying on TUI-side smoothing.
- [ ] Move toward OpenCode-compatible v2 session API shapes and structured
      public errors where they reduce TUI drift.
- [ ] Recreate upstream's stronger event replay/projector behavior in Penguin's
      backend or adapter layer.
- [ ] Make busy/idle status truth durable enough that the TUI can stop
      inferring active runs from local state.
- [ ] Provide backend-owned provider/model/reasoning capability metadata.
- [ ] Align permission/question IDs, validation, and route responses with the
      upstream-compatible surface where feasible.
- [ ] Ensure message/part persistence and replay can reconstruct active and
      completed tool/reasoning/assistant state after reload or reconnect.

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
