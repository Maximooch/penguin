# Penguin TUI OpenCode 2 Sync

## Goal

Adopt OpenCode 2's TUI as a parallel Penguin client without replacing Penguin's
runtime, provider execution, session storage, permission model, or canonical
runtime-event ledger. Ship the migration as reversible vertical slices, then
retire the current OpenCode 1-derived TUI only after parity is proven.

## Pinned Upstream

- Repository: `https://github.com/anomalyco/opencode`
- Branch: `v2`
- Commit: `b35c5fc98577b77d8d67d298c6254e0cd138c9d5`
- Commit date: `2026-08-11T21:05:36Z`
- CLI source manifest: `1.18.4` (`opencode2`)
- Immutable binary artifact: `@opencode-ai/cli@0.0.0-next-17220`
- Bun: `1.3.14`
- OpenTUI: `0.0.0-20260808-9ecf7c0a`

The pin moves only after its contract fixtures and smoke checks pass. The beta
branch is not merged or rebased directly into `penguin-tui/`.

OpenCode documents V2 as a beta with three intentional migration breaks: the
plugin API, server/client contracts, and TUI configuration. It installs as the
parallel `opencode2` binary. Penguin therefore treats every upstream refresh as
a protocol migration, never as a routine dependency bump.

The move from the initial audit pin `2b7bd848…` to `b35c5fc…` changed only
OpenCode core provider/configuration code, skills, and documentation; no TUI,
generated client, schema, protocol, or CLI contract file changed. The final pin
is also the source commit for the successful `next-17220` package publish. The
captured wire fixtures therefore remain the pin gate for Penguin's
compatibility boundary.

The similarly numbered stable platform package
`@opencode-ai/cli-<platform>@1.18.4` is not the V2 artifact: registry inspection
shows it contains `lildax`, not `opencode2`. Release automation must use the
exact `0.0.0-next-17220` wrapper/platform dependency set and must execute the
extracted binary's `--version` check before packaging.

### Moving-head observation

The `v2` branch was rechecked on 2026-08-11 at
`57b636df00d8ff81973f9406df655afea3cc91ab`; this is an observation, not the
tested artifact pin. The range from `b35c5fc…` changes three adoption contracts:

- the TUI plugin API replaces `ui.slot(name, render)` with a hierarchical slot
  claim (`prepend`, `append`, `before`, `after`, or `replace`);
- generated project-copy client paths move from `/experimental/project/*` to
  `/api/experimental/project/*`; and
- session interruption gains an optional `continue=true` query that resumes
  durable pending work after the active execution stops.

Neither change is silently absorbed. Penguin does not expose project-copy in
the first supported slice, and its plugin remains compiled for `next-17220`.
The next immutable artifact refresh must port the Penguin slot claim and
refresh the generated-client fixture before advancing the pin. It must not
accept `continue=true` until Penguin has the durable queued-work semantics that
flag promises. Directory autocomplete and experimental per-tab prompt drafts
are upstream-owned TUI UX that Penguin should adopt unchanged at that refresh.
Other observed changes in the range (embedded web UI, pair-screen labeling,
and core import normalization) stay outside Penguin's compatibility boundary.

## Upstream Capability Ledger

The pinned V2 client is a service-driven rewrite, not an incremental update to
the current OpenCode 1-derived fork. Its useful adoption surface is:

| Capability | V2 surface | Penguin sync decision |
| --- | --- | --- |
| Home, project, and session navigation | Location, project, VCS, session catalogs | Adopt through read-only projections |
| Streaming transcript and composer | Prompt admission plus native session events | Phase 2 tracer bullet |
| Agent, model, and variant selection | Location catalogs and session-scoped selection | Project Penguin choices; keep execution in Penguin |
| Permissions, questions, and forms | Session request resources and event updates | Adapt existing approvals/questions; add forms only for real producers |
| Child, queued, and background sessions | Session families, pending inputs, tabs | Parent/child CRUD first; defer queued/background UX until durable inbox tests |
| Diffs, snapshots, undo, and redo | Session change/snapshot resources | Defer until Penguin has truthful reversible state |
| Commands, skills, references, MCP, and integrations | Boot-time capability catalogs | Return valid empty catalogs first; expose only implemented capabilities |
| Shell and terminal surfaces | Shell catalog and PTY lifecycle | Reuse Penguin PTY ownership after platform smoke tests |
| Themes, keymaps, editor, clipboard, notifications | OpenTUI-native client features | Keep upstream unless Penguin branding needs a narrow override |
| TUI plugins, routes, tabs, commands, and slots | V2 plugin ABI | Preferred Phase 4 Penguin extension seam |
| Mini, debug log, simulations, and story surfaces | Optional development packages | Explicitly outside the first production closure |

The initial source closure, if a branded source build becomes necessary, is the
TUI, generated promise client, schemas, protocol, theme, and thin TUI plugin
ABI. OpenCode core, server, database, providers, AI runtime, simulations, and
browser UI remain outside Penguin.

## Protocol Support Ledger

| Contract group | First supported slice | Later work |
| --- | --- | --- |
| Health and connection | `/api/health`; `server.connected` first on `/api/event` | Diagnostics only |
| Location and project | location, filesystem list, project/current, VCS | Multiple worktrees/workspaces |
| Sessions | create (including parent), list, active, get, rename, agent/model selection, recursive delete | Fork/share/revert/summarize |
| Messages and prompt | history and single-flight text admission; reject queue/busy steer | Durable queued input, attachments, and richer input types |
| Native events | admitted/promoted, execution, step, text, and tool lifecycle | Reasoning, compaction, shell, and snapshot events |
| Interrupt | Existing Penguin session abort | No second cancellation path |
| Permissions and forms | Manager-backed approval/question resources, replies, cancellation, and reconnect hydration | Producers beyond Penguin's existing managers |
| Boot catalogs | Usable agent/model/provider; exact empty envelopes elsewhere | Enable each catalog only with truthful data |
| Durable replay | Penguin ledger remains canonical; reconnect rehydrates REST | Experimental V2 aggregate log only if the TUI requires it |

Unsupported fields are rejected or omitted; they are never silently accepted.

## Upstream Refresh Procedure

1. Fetch `origin/v2` and record its full commit, CLI version, Bun version, and
   OpenTUI pin.
2. Classify the commit range before changing Penguin. Review changes under
   `packages/tui`, `client`, `schema`, `protocol`, `theme`, the TUI plugin ABI,
   and the CLI server-connection/argument code. Core-only changes do not enter
   Penguin's compatibility layer.
3. Refresh protocol fixtures and run the Python contract suite against both
   Python 3.9 and 3.12. A schema or generated-client change blocks the pin move
   until the projector is updated.
4. Run the pinned `opencode2` artifact against a fake-provider Penguin backend:
   Home boot, session create, prompt lifecycle, reconnect, interrupt, and reopen.
5. Publish a separately named, checksummed V2 sidecar. Never overwrite a V1
   asset or cache marker, and never let the upstream binary auto-update itself.
6. Land Penguin adapters separately from a mechanical source refresh. If source
   vendoring becomes necessary, preserve the upstream commit as a distinct
   commit so the overlay remains reviewable.

Every refresh retains the current V1 launcher as the rollback path.

## Ownership Boundary

| Surface | Owner | Strategy |
| --- | --- | --- |
| Reasoning loop, providers, tools, CWM | Penguin | Keep |
| Sessions, permissions, questions, runtime ledger | Penguin | Keep |
| `/api/*` OpenCode 2 protocol | Penguin compatibility layer | Project |
| TUI rendering, navigation, themes, diff UI | OpenCode 2 | Adopt |
| Penguin commands, themes, task/goal UX | Penguin extension | Isolate |
| OpenCode core, database, provider runtime | OpenCode | Do not import |

OpenCode payloads are compatibility projections. They are not Penguin's
internal event or persistence vocabulary.

## Phases

### 1. Pin and classify

- [x] Create an isolated worktree and branch.
- [x] Pin the current OpenCode 2 commit and dependency baseline.
- [x] Record the ownership boundary and adoption order.
- [x] Capture a focused first compatibility fixture manifest from the pin.

Gate status: partially met. The immutable pin, support ledger, and focused
health/location/session/handshake fixture are in this PR. That fixture is not a
complete generated-client schema snapshot, so a future pin move still requires
a fuller decoder fixture and the packaged-client smoke below.

### 2. Backend compatibility slice

- [x] Add thin `/api/health`, `/api/location`, `/api/session`, and `/api/event`
      routes backed by existing Penguin services.
- [x] Project V2 session envelopes without changing stored Penguin sessions.
- [x] Support create, list, get, message history, prompt, and interrupt.
- [x] Project permission/question requests; add generalized forms only where the
      V2 TUI requires them.
- [x] Preserve auth, directory scoping, and structured errors.
- [x] Rehydrate pending approval/form state from Penguin's existing managers
      across a new HTTP/SSE connection; do not add a replay ledger.

Gate status: deterministic route/projector tests cover create, successful and
early-failing prompts, stream terminals, active/idle interrupt, late tool
terminals, interaction reconnect hydration, and reopenable persisted sessions.
The single packaged-client create -> prompt -> interrupt -> backend restart ->
reopen scenario remains a manual pre-release gate.

### 3. Parallel V2 client

- [x] Add an explicit V2 launcher selection without changing the default path.
- [x] Prefer a pinned upstream binary/build over copying the V2 monorepo.
- [x] Pass Penguin auth and server endpoint through the narrow launcher boundary.
- [x] Keep the current TUI as an immediate fallback.

Gate status: the exact pinned packaged binary reaches Home against Penguin and
loads the typed `/penguin` command from the archive layout. Prompt execution and
backend-restart reconnect remain required in the extracted-artifact release
smoke; default V1 behavior is unchanged.

### 4. Penguin extension boundary

- [x] Keep transport/event translation in Penguin's server seam and auth
      credential bridging in the launcher; add no plugin transport.
- [x] Put the first Penguin product command in the smallest supported V2
      plugin/slot surface.
- [x] Do not fork upstream components for features a plugin can supply.

Gate status: met for the pinned artifact. The plugin is strictly typechecked,
built, dynamically imported, and packaged against the pinned ABI. A future
upstream slot-claim API refresh is an explicit port, not a silent update.

### 5. UX adoption

Adopt in dependency order:

1. [x] transcript and single-flight text composer
2. [x] permissions, questions, and forms backed by existing managers
3. [x] agent/model/variant selection backed by session metadata
4. [ ] child/background session UX (parent CRUD and cascade deletion are ready)
5. [ ] diff and undo/redo
6. [x] project/session picker boot resources
7. [ ] session tabs and prefetch
8. [ ] optional mini/debug/storybook surfaces

Gate: each surface has truthful backend data and a deterministic check before
the next dependent surface is enabled.

### 6. Verification

- [x] Contract fixtures for supported V2 endpoints and events.
- [x] Fake-provider create, prompt, stream, and terminal lifecycle tests.
- [x] Native tool lifecycle, failure, and late-terminal adjacency tests.
- [x] Duplicate, late, out-of-order, failure, and interleaved-session event tests.
- [x] REST reconnect hydration from Penguin's canonical session and interaction
      managers; no event replay identity is claimed.
- [x] Permission/question reply, cancellation, and new-adapter hydration tests.
- [x] Connection-local session isolation tests.
- [ ] Multi-tab hydration and restart tests.
- [ ] Native tool replay adjacency and CWM category-priority tests.
- [ ] PTY smoke tests on supported sidecar platforms.

Gate status: Python 3.9/Pydantic 1 and Python 3.12/Pydantic 2 deterministic
matrices are the proof for the supported slice. Multi-tab restart, native PTY,
and CWM category-priority coverage remain deferred and are not implied by the
V2 beta. Live providers remain opt-in smoke tests.

### 7. Rollout

- [x] Put the client behind an explicit opt-in selector; keep V1 as default.
- [x] Add an isolated workflow that assembles a pinned, checksummed V2 sidecar
      set for the same Penguin release.
- [x] Make cache identity include Penguin version, protocol generation, platform,
      and upstream pin.
- [x] Document fallback and collect actionable compatibility diagnostics.
- [x] Keep the default unchanged until packaged-install and upgrade/downgrade
      checks justify a separate default-switch decision.

Gate status: rollback is one environment change and does not migrate or delete
user data. Actual release attachment, checksum verification, clean-wheel
bootstrap, prompt/restart smoke, and cross-platform workflow success remain
release-time gates; this PR prepares them but does not publish a release.

## Milestone PRs

1. Protocol pin and backend vertical slice (Phases 1-2).
2. Parallel launcher and first TUI session (Phase 3).
3. Penguin extensions and prioritized UX (Phases 4-5).
4. Verification, packaging, and opt-in rollout (Phases 6-7).

PRs may combine adjacent milestones when the smaller split would leave an
unrunnable intermediate state.

## Explicit Deferrals

- Do not import OpenCode's core/database/provider runtime.
- Do not promise full API parity before the TUI calls an endpoint.
- Do not build a second event ledger.
- Do not switch the default TUI during OpenCode 2 beta.
- Do not describe Penguin's current CWM trimming as compaction.
