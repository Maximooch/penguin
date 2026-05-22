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

- The local OpenCode reference is at `reference/opencode`, but it is stale
  relative to its remote and should be refreshed before treating it as current
  upstream.
- Penguin's fork landed locally on January 31, 2026, around embedded OpenCode
  package version `1.1.48`.
- Upstream OpenCode was at `v1.15.7` on May 21, 2026, so the upstream delta is
  substantial and includes backend/API/event-model changes, not just TUI polish.
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

- [ ] Fetch latest OpenCode into `reference/opencode`.
- [ ] Record the exact upstream commit used for comparison.
- [ ] Confirm whether OpenCode's active branch is still `dev` for TUI work.
- [ ] Generate a fresh diff/stat for `packages/opencode/src/cli/cmd/tui`.
- [ ] Identify files added only by Penguin versus files modified from upstream.
- [ ] Record upstream versions for important dependencies, especially
      `@opentui/core`, `@opentui/solid`, `@opencode-ai/sdk`, and the AI SDK.
- [ ] Identify upstream changes that are backend/API contract changes versus
      pure TUI changes.

### 1.5. Map upstream gains to Penguin and Link

- [ ] Inventory upstream improvements since `v1.1.48` that Penguin should
      preserve or adopt:
  - incremental part deltas
  - v2 session API shapes/errors
  - event replay/projector behavior
  - diff viewer
  - full-session fork/session review
  - provider/model/reasoning UX
  - permission/question UI fixes
  - OpenTUI dependency updates
- [ ] Mark each upstream improvement as:
  - adopt directly in TUI
  - adopt by changing Penguin backend compatibility
  - defer because Link will own the surface differently
  - avoid because it conflicts with Penguin/Link semantics
- [ ] Compare upstream runtime/session UI concepts against Link Agentboard needs
      from `production-v1-tracks.md`.
- [ ] Capture reusable lessons for Link's `RuntimeEvent`/`SessionEvent`
      projection model.

### 2. Classify TUI divergence

- [ ] Inventory all `sdk.penguin` branches under
      `penguin-tui/packages/opencode/src/cli/cmd/tui/`.
- [ ] Classify each branch as one of:
  - branding/docs/theme
  - auth/transport
  - backend compatibility
  - session/message reconciliation
  - optimistic UI
  - local command surface
  - settings/skills/project/task Penguin feature
  - temporary workaround
- [ ] Mark each branch as keep, move lower, replace with backend parity, or
      delete after compatibility work.

### 3. Shrink SDK-layer drift

- [ ] Review `context/sdk.tsx` against upstream.
- [ ] Keep Penguin auth header injection near the SDK boundary.
- [ ] Decide whether Penguin SSE should use OpenCode's SDK event subscription
      path, a custom adapter, or backend route parity.
- [ ] Move event cleaning and Penguin SSE parsing into a named helper if it
      remains client-side.
- [ ] Avoid leaking transport-specific behavior into route and prompt
      components.

### 4. Shrink prompt-layer drift

- [ ] Review `component/prompt/index.tsx` against upstream.
- [ ] Extract Penguin session creation and send flow into a helper/service.
- [ ] Decide whether optimistic user-message emission should remain in the TUI.
- [ ] If optimistic emission remains, isolate it behind one helper with tests.
- [ ] Keep `/fast`, project/task commands, settings, and local commands out of
      the main prompt submission path where possible.
- [ ] Make failure recovery explicit and testable.

### 5. Shrink sync/bootstrap drift

- [ ] Review `context/sync.tsx` against upstream.
- [ ] Extract bootstrap response mapping into a dedicated Penguin adapter.
- [ ] Extract directory/session filtering into a helper.
- [ ] Revisit usage refresh and session snapshot hydration responsibilities.
- [ ] Prefer backend-provided OpenCode-shaped session records over client-side
      response probing.
- [ ] Keep `sync.tsx` focused on store orchestration.

### 6. Push compatibility toward Penguin backend

- [ ] Identify client workarounds that exist because Penguin endpoints are not
      OpenCode-shaped enough.
- [ ] For each workaround, decide whether backend parity is better than TUI
      adaptation.
- [ ] Prioritize backend parity for:
  - session create/list/get/messages
  - message/part event persistence and replay
  - busy/idle status truth
  - provider/model metadata
  - permission/question flows
  - path/vcs/lsp/formatter route shapes
- [ ] Keep Penguin-only product features behind explicit Penguin endpoints.

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

## Open Questions

- Should Penguin aim for full OpenCode API parity, or a documented compatible
  subset plus Penguin extensions?
- Should the TUI ever synthesize `message.updated`, `message.part.updated`, or
  `session.status`, or should those always come from the backend?
- Can Penguin's backend provide enough immediate session truth to eliminate most
  optimistic prompt logic?
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
