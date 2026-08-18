# DeepSeek Harness + Cordis — Comparative Memo for Penguin

> Audience: Penguin maintainers. Purpose: what Penguin should *consider* borrowing
> from the DeepSeek Harness (dsh) and its underlying Cordis plugin framework.
> This is a design/architecture review, not a mandate. Every suggestion is
> weighed against Penguin's current runtime truth and the risk of churn.
>
> Reviewed: `reference/deepseek-harness/docs` (architecture, capability-seams,
> tool-execution-pipeline, agent-lifecycle, event-producer-consumer,
> persistence-catalog, tool-catalog, defensive-patterns, subsystems/*) and
> `reference/cordis/packages/core/src` (context, events, fiber, registry,
> reflect, service, utils).
>
> Status: analysis memo. No code changed.

## TL;DR

dsh/Cordis is not a runtime Penguin should copy. It is a *composition model* —
a plugin-universe philosophy with two properties Penguin lacks in a coherent
form today:

1. **Every part of the product is a replaceable plugin** mounted on a shared
   service context, with no privileged core to patch.
2. **The session is an append-only, typed event log** — the single source of
   truth from which LLM history, replay, fork, resume, telemetry, and
   persistence are all *derived*, never stored separately.

Penguin already has strong kernels: a good reasoning engine, SQLite project
state, pluggable memory, checkpoints, and a context-window manager. What
dsh/Cordis models better is the **userland**: a service-seam boundary, a
typed-event surface contract, an event-sourced session log, and reversible
registrations. The five ideas below are the highest-leverage borrowings, in
rough priority order.

---

## 1. The event-sourced session log (highest leverage, biggest lift)

### What dsh does

A `Session` is an **append-only log of typed `SessionEvent`s** — the single
source of truth for an agent's whole interaction. LLM message history is
*derived* from the log (a `deriveMessages()` projection), never stored
separately. Replay is re-derivation from the same events. Fork, resume,
transcripts, telemetry, and persistence all derive from this one stream.

Key properties:

- **Model-visible means logged.** Anything that reaches a model request must be
  reconstructable from the log, and a runtime invariant asserts it. A new
  model-visible input requires a new session event type.
- **Surface vs. log-only.** Only `user/message`, `assistant/message`, and
  `tool/result` are *surface* events (they produce LLM messages). Everything
  else — `turn/start`, `step/start`, `assistant/chunk`, `tool/call`, `todo/*`,
  `approval/*`, `hook/*` — is a durable, replayable record with no
  derived-history contribution.
- **Merge-extensible vocabulary.** Plugins add event types via TS declaration
  merging (e.g. compaction adds `compaction/*`, hook bridges add `hook/*`).
- **Lossless JSON + monotonic seq.** Every event is JSON-serializable (enforced
  at append) with contiguous sequence numbers, so persistence can store the
  canonical log verbatim.
- **`sourceEventSeqs` / `surfaceOp`.** A surface event cites the seqs it was
  built from (e.g. the `assistant/chunk` seqs that built an `assistant/message`,
  or the nodes shadowed by a compaction replace). Compaction replaces surface
  nodes via `{op:'replace', start, end}` rather than mutating history.
- **`ignorable` marker.** A reader meeting an unknown event type must refuse to
  reconstruct *unless* the event is marked `ignorable` (purely informational).
  A forgotten marker over-refuses (safe); a missing one silently resumes a
  gutted session (unsafe).

### What Penguin has today

Penguin persists conversations as message transcripts (messages.json plus
metadata) with separate checkpoints, and has a separate durable runtime-event
ledger for web/TUI clients. The model history is stored as the conversation,
not *derived* from an append-only event log. Compaction/truncation rewrites the
stored history rather than layering surface-replacement nodes over an immutable
log.

### What Penguin should consider

This is the single most consequential architectural idea in the reference, and
the hardest to retrofit. Penguin should **not** try to become a full event-sourced
log overnight. But three sub-ideas are cheap and high-value:

1. **Adopt a typed, versioned event envelope as the canonical conversation
   record** — a discriminated union over `type`, with `seq`, `time`, `data`,
   and conditional `sourceEventSeqs`/`surfaceOp`. Penguin already has a
   `RuntimeEvent` envelope for web/TUI; the gap is that the *conversation
   transcript* is not expressed in the same canonical, replayable shape.
2. **Separate "surface" events from "log-only" events** explicitly. Today
   Penguin mixes tool results, system output, and dialog into one message
   store. Naming which events produce model-visible history vs. which are
   durable-but-not-derived is a cheap clarity win that makes compaction and
   replay far more predictable.
3. **Model compaction as surface replacement, not history mutation.** Penguin's
   CWM already truncates by category. Expressing that as a `replace` operation
   over immutable nodes (with `sourceEventSeqs` recording what was shadowed)
   would make truncation auditable and replay-faithful — "what the model saw"
   stays reconstructable even after compaction.

**Cost/risk:** high retrofit effort; touches ConversationManager, persistence,
checkpoints, and CWM. Do this as a *shape* adoption (typed envelope + surface
distinction) before any full event-sourcing rewrite. The invariant "model-visible
means logged/reconstructable" is worth stating as a rule even before the storage
fully honors it.

---

## 2. The guarded tool-execution pipeline (high value, moderate lift)

### What dsh does

Tool calls flow through a **staged pipeline with distinct, composable
waterfalls** rather than a monolithic executor. The stages are explicit and
reorderable by design:

```
model tool-call
  -> tool/call logged (before execution)
  -> tools/pre-execute  waterfall  (hooks, permission, sandbox)
  -> monotonic guards             (deny or abstain; identity protected)
  -> ctx.approval one-shot prompt  (absent/unanswerable => deny)
  -> tools/execute      waterfall  (timeout, retry, metrics — around dispatch)
  -> tool body execute()
  -> fs/* intent gates             (tool-fs mutations only)
  -> tools/post-execute waterfall  (accept, block, replace, add context)
  -> registry normalization        (snapshot failures => isError)
  -> ToolDefinition.finalizeContent (last content-only invariant)
  -> tools/result synchronous notify (frozen authoritative outcome)
  -> tool/result logged (single model-facing outcome)
```

Three properties stand out:

- **Policy is a waterfall, not a patch.** Hooks span tool families without
  coupling tools to one policy service. Pre/post waterfalls can *transform* a
  call (accept, block, replace, inject context). Around-dispatch concerns such
  as timeouts wrap `tools/execute`.
- **Monotonic guards protect identity.** Owner policy that must not be reordered
  (e.g. sandbox confinement) registers as a guard, distinct from generic
  pre/post hooks. Approval resolves *before* guards.
- **Call/result adjacency is preserved.** `tool/call` is logged before
  execution; `tool/result` is the single model-facing outcome. Nested Code-Mode
  sub-calls carry the parent token, log their own dispatch, and omit context
  injection to preserve adjacency.
- **Result normalization is lossless and snapshot-protected.** The registry
  snapshots the candidate result; a snapshot failure becomes `isError` rather
  than corrupting the pipeline. `finalizeContent` runs exactly once on every
  normalized outcome, including pipeline failures.

### What Penguin has today

Penguin's `ActionExecutor` owns a large action-to-handler map; the tool-call
runtime doc already notes the coupling between prompting, parsing, tool
routing, result persistence, UI events, and loop control. Permission checks
exist but are not uniformly a runtime-stage concern across all tool families.
Tool output truncation is handled via the model-output policy (good), but is not
a universal, explicit stage like dsh's spill/prune.

### What Penguin should consider

Penguin's own `tool-call-runtime-architecture.md` already recommends much of
this (stable call ids, durable tool-call objects, permission in the runtime
path, universal truncation). The dsh pipeline adds the **ordering discipline**:

1. **Adopt explicit pre-execute / execute / post-execute stages** as a first-class
   runtime concept, even if Python doesn't have TS waterfalls. The key win is
   that policy (sandbox, approval, truncation, spill) becomes *additive* —
   a new policy doesn't require editing every tool.
2. **Make truncation/spill a universal post-execute stage**, not a per-tool
   concern. dsh's `spillStore` + `toolResultPruner` save oversized output to a
   private file and return a model-facing locator. Penguin already has artifact
   backing; formalizing a spill stage would let any tool's large output degrade
   gracefully.
3. **Preserve call/result adjacency and log `tool/call` before execution.**
   This is cheap and makes replay, UI pending cards, and failure attribution
   reliable.

**Cost/risk:** moderate. Penguin's tool loop is already being refactored toward
a provider-neutral runtime; folding in explicit pre/post stages now is
well-timed. The main caution is not to over-abstract — keep serial execution as
the default and only parallelize explicitly safe tools (Penguin's own doc says
the same).

---

## 3. The Cordis plugin/service model (medium value, structural)

### What Cordis does

Cordis is a *meta-framework*: the runtime itself is built out of plugins mounted
on a shared `Context`. The core (`context.ts`, `events.ts`, `fiber.ts`,
`registry.ts`, `reflect.ts`, `service.ts`) provides four primitives:

- **`Context`** — a tree of scopes. `root` is the app; `extend()`/`isolate()`/
  `intercept()` create child scopes (per-agents, sub-contexts) that inherit
  parent services and can override or isolate them. A `Proxy` routes property
  access so service resolution is lazy and traceable (`reflect`).
- **`plugin()` / Fiber lifecycle** — every plugin is a function/class with a
  declared `Config` (Standard Schema), an optional `inject` (declared service
  dependencies), optional `provide` (services it publishes), and a body that
  registers listeners/effects. A **Fiber** tracks each plugin instance's
  lifecycle with explicit `PENDING → LOADING → ACTIVE → FAILED → DISPOSED →
  UNLOADING` states and *declarative lifespan*: the plugin's body returns a
  disposer, and teardown is reverse-order, awaited to quiescence on unload,
  reload, or dependency change. When an injected service changes, Cordis
  **automatically reloads dependent fibers** (epoch-based) — dependency-driven
  hot reload.
- **`EventsService`** — five dispatch modes: `emit` (fire-and-forget),
  `parallel`, `serial` (stop on first non-undefined), `bail` (first truthy),
  and `waterfall` (composable pass-through with a trailing `next`). This single
  multi-mode event system is how hooks, guards, and policy layers compose.
- **`RegistryService`** — dedupes plugins by resolved callback (a plugin mounted
  N times = one runtime with N fibers), so repeated mounts share state cleanly.

The deep-shallow boundary (from the doc):
- **`seam`** = an interface + one or more named *providers* (e.g. `ctx.shell`
  backed by `bash-local` / `bash-sandbox` / `pwsh-local`). Consumers depend on
  the seam; swapping the backend doesn't touch them.
- **`core`** = a single concrete service (e.g. `ctx.tools`, `ctx.systemPrompt`)
  that plugin modules register into.
- **`bundle`** = a product-assembling composition (e.g. `agent-loop`) — the one
  concrete loop; extension packages depend on events and services, not on the
  bundle.

### What Penguin has today

Penguin has a plugin system (`penguin/plugins/`: `BasePlugin`, `PluginManager`,
decorators, discovery) that registers tools/actions and a `MessageBus`/
`EventBus`. But it is primarily **tool/action registration**, not a
service-composition framework. There is no automatic dependency-driven reload,
no fiber lifecycle with awaited-teardown-to-quiescence, and the event dispatch
modes are not as rich (no native `waterfall`/`serial`/`bail` semantics across
hooks). Penguin's `PenguinCore` is a thin facade over `core_runtime` modules —
a step in the extensibility direction, but the plugin seams are not the same
class of mechanism as Cordis's service context.

### What Penguin should consider

Penguin should **not** adopt Cordis's proxy-based DI and epoch reload wholesale —
that is a large, invasive rewrite and Python can't mirror TS declaration
merging. But these are worth considering:

1. **The seam/provider split is the right boundary for backend swaps.** Penguin
   already swaps LLM adapters, memory providers, and browser backends. Naming
   these as "seams with named providers" (interface + a registry of replaceable
   impls) would make the swap boundary explicit and testable, without needing a
   proxy DI system.
2. **Dependency-driven reload is a useful *concept* even if not implemented
   fully.** At minimum, Penguin's plugin manager should have a declared
   `provides`/`requires` interface so enabling/disabling or reconfiguring a
   service can invalidate dependents predictably instead of silently breaking
   them.
3. **Event dispatch modes are a cheap, high-value primitive.** Adding
   `waterfall`-style semantics to Penguin's EventBus — where listeners can
   transform the payload and pass to `next()` — would make hook layers (e.g.
   tool pre/post, request construction) composable. This dovetails directly
   with section 2's pipeline stages.

**Cost/risk:** medium-to-high if over-applied. Recommend the *concepts* (seams,
declared provides/requires, waterfall events) over the *mechanism* (proxy DI,
epoch reload). Penguin's plugin system can become a real service-composition
framework gradually without a rewrite.

---

## 4. Lifecycle, teardown, and defensive discipline (high value, low lift)

### What dsh/Cordis does

Both projects treat **lifecycle and teardown as a first-class correctness
concern**, with rules that read like bug-class scar tissue (they explicitly
document "defects that actually shipped or nearly shipped here"):

- **Dispose must reach quiescence, not just request it.** A teardown that
  issues kills/aborts but returns before the work stops leaves orphans. Cleanup
  is async and awaits child exit (`kill → await done`); listener/notification
  registries close BEFORE killing so late completions stay silent.
- **Report orthogonal outcomes independently.** A process can time out AND exit
  0 (it trapped the signal). Surface `timedOut`, `signal`, `exitCode` on their
  own — never nest one flag's report inside another's branch, or a caller reads
  a cut-short run as a clean success.
- **Honor public contracts on BOTH sides.** Normalize several representations
  of one outcome before returning through a public API (e.g. `LlmAdapter.stream()`
  may throw or emit `finish{kind:'error'|'aborted'}`, but the runtime exposes
  model-request failures only as terminal finish chunks). Consumers shouldn't
  guess whether an exception came from the provider, a wrapper, chunk logging,
  or their own assembly.
- **Async state is not synchronous state.** `agent.followup()` has no per-message
  completion; a background job's completion races turn boundaries. Never treat
  `agent/status` or `whenIdle()` as the result of one follow-up. An automation
  caller that owns a run must define its interval explicitly.
- **Contain callback exceptions in the dispatcher.** One bad subscriber never
  breaks core lifecycle — wrap the dispatch loop in try/catch and log.
- **Never hand untrusted output the ambient environment or predictable paths.**
  Spawned commands get a scrubbed env (drop `*KEY*`/`*SECRET*`/`*TOKEN*`/
  `*PASSWORD*`); temp/spill files use a private (0700) dir, random names, and
  exclusive owner-only opens (`'wx'`, `0o600`) to avoid symlink races and
  disclosure.

### What Penguin has today

Penguin's docs already carry some of this spirit (message-loop reliability,
retry preserving original request options, abort routing resolving explicit
session/conversation IDs first, redacting sensitive fields from edit
diagnostics, tool-call failures as structured results). The multi-agent-v2 brief
explicitly calls out muddled pause/cancel/resume/restart semantics and
best-effort push-only MessageBus delivery — exactly the class of lifecycle
ambiguity dsh guards against.

### What Penguin should consider

These are **cheap, high-value rules** Penguin can adopt regardless of any larger
refactor:

1. **Adopt a "teardown reaches quiescence" invariant** for subagents, background
   jobs, and process tools. Penguin's `stop_sub_agent`/`resume_sub_agent` and
   background executor are the exact spots this bites. Await child exit before
   returning; close registries before killing.
2. **Report orthogonal outcomes independently** in process/shell tools — expose
   `timedOut`, `signal`, `exitCode` separately, never fold one into another's
   branch. Penguin's process runtime should adopt this explicitly.
3. **Normalize multi-source outcomes at the public boundary** for LLM streaming
   and tool execution, so consumers don't guess at the source of a failure.
4. **Scrub env for spawned commands** and use private, random, owner-only temp
   files for any spill/artifact output. This is a concrete security hardening
   Penguin can apply to its shell/process and artifact paths today.
5. **Contain callback exceptions in the dispatcher** so one bad listener can't
   break the engine loop.

**Cost/risk:** low. These are discipline rules + targeted fixes, not a rewrite.
They align with what Penguin's own task briefs (multi-agent-v2, message-loop
reliability) already identify as gaps.

---

## 5. Turn/step lifecycle and inbox model (medium value, low lift)

### What dsh does

The agent loop is structured around an explicit **turn/step lifecycle** with a
durable inbox, and it separates two concerns Penguin often conflates:

- **Durable replay facts live on `session/event`; live control/status live on
  `agent/*`.** `session/event` is the replayable transcript source (turn/start,
  step/start, user/message, assistant/chunk, assistant/message, tool/call,
  tool/result, step/end, turn/end). `agent/*` is the live coordination API
  (inbox claimed/inserted/spliced, status, steering, continuation, errors).
  This is a clean split: one stream is immutable history, the other is live
  state.
- **A turn is one unit of user-facing work; a step is one model call + its
  tools.** `turn/start` opens, then one or more `step/start→step/end` pairs run.
  A turn with no entered step (rejected input, cancellation) is legal and logs
  no step. The loop can claim "pending next-step input" across turns, so a
  follow-up can continue a turn without a fresh user turn.
- **Durable inbox.** User messages go into a durable pending-message list
  (`agent/inbox/*`), claimed at step boundaries. This makes follow-up,
  steering, and injected context first-class, and gives automation a
  message-level receipt (claimed/inserted) rather than best-effort push.

### What Penguin has today

Penguin has a conversation/engine loop and a `run_task`/`run_response`
termination model (explicit `finish_task`/`finish_response` terminators), plus
clarification `waiting_input` states. But "turn" vs. "step" is not an explicit
first-class vocabulary, and the durable transcript vs. live-coordination split
is not as cleanly drawn. The multi-agent-v2 brief notes MessageBus delivery is
best-effort push with no receipt — no durable inbox equivalent.

### What Penguin should consider

1. **Adopt turn/step vocabulary explicitly.** Naming "turn" (user-facing unit)
   vs. "step" (model call + tools) makes the loop's boundaries testable and
   makes clarification/`waiting_input` states sit naturally at a turn boundary.
   Penguin's `run_mode` and clarification flows already gesture at this; making
   it explicit would tighten them.
2. **Separate durable transcript from live control state.** Penguin already has
   a `RuntimeEvent` ledger for web/TUI and a conversation transcript. Drawing
   the same line dsh does — immutable replayable events vs. live status — would
   reduce the risk of conflating them (a concern Penguin's own docs flag around
   telemetry scoping and "documentation-shaped lies").
3. **A durable inbox with receipts** would fix the multi-agent-v2 complaint that
   delegation "can look successful even when no recipient is truly listening."
   A claimed/inserted receipt per message is a moderate lift but directly
   addresses a known gap.

**Cost/risk:** low-to-moderate. Vocabulary and boundary discipline are cheap;
a durable inbox is a real but bounded feature. Strongly aligned with Penguin's
existing multi-agent-v2 and runmode briefs.

---

## 6. What NOT to copy (and why)

A few things in dsh/Cordis are elegant but wrong-shaped for Penguin:

- **Cordis's proxy-based dependency injection + epoch-based auto-reload.** It is
  a beautiful mechanism, but it is a large, invasive rewrite for Penguin and
  doesn't map cleanly to Python. The *concepts* (seams, provides/requires,
  waterfall events) transfer; the *mechanism* does not.
- **The `run_code` Code-Mode transport as a primary interface.** dsh's whole
  model-facing surface can collapse into one `run_code` tool that calls other
  tools via generated SDK bindings. That is a powerful trick but a very different
  UX philosophy from Penguin's explicit ActionXML/native tool calls, and it
  couples the model surface to the host language. Not for Penguin's core.
- **Full TS declaration-merging extensibility.** dsh lets any plugin add event
  types and service fields via type merging. Python has no equivalent; trying to
  emulate it with dynamic attributes would erode type safety Penguin doesn't
  have in the first place. Prefer explicit registration over magic.
- **The sheer package granularity.** dsh splits into dozens of `@deepseek-ai/*`
  packages (tool-fs, tool-bash, tool-terminal, tool-lsp, tool-jobs, …). That is
  right for an npm monorepo; Penguin is a Python package and should not mirror
  that fragmentation. Keep Penguin's module boundaries coarse enough to be
  navigable.

---

## Synthesis and recommended next steps

dsh/Cordis is best read as a **checklist of composition and correctness
discipline**, not a blueprint. Penguin's kernel is already competitive; the gaps
are in userland boundaries. Ranked by (value / effort * fit):

| # | Idea | Value | Lift | Fit |
|---|------|-------|------|-----|
| 1 | Typed event envelope + surface/log-only split (section 1) | High | High | High |
| 2 | Explicit tool pre/execute/post stages + universal spill (section 2) | High | Mod | High |
| 3 | Lifecycle/teardown-to-quiescence + defensive rules (section 4) | High | Low | High |
| 4 | Turn/step vocabulary + durable transcript/live-state split (section 5) | Med | Low-Mod | High |
| 5 | Seam/provider boundaries + provides/requires + waterfall events (section 3) | Med | Mod | Med |
| 6 | Durable inbox with receipts (section 5) | Med | Mod | Med |

**Concrete next moves (cheap, do first):**

1. Adopt the defensive rules in section 4 as engineering invariants — they cost
   nothing and fix real gaps Penguin's own briefs already name.
2. Draw the durable-transcript vs. live-state line explicitly (section 5.2),
   given Penguin already has a `RuntimeEvent` ledger and a transcript.
3. Fold explicit pre/post tool stages into the in-flight
   `tool-call-runtime-architecture` refactor (section 2) rather than layering
   them on later.
4. Treat the event-envelope/surface split (section 1) as a *shape* adoption that
   informs how ConversationManager, persistence, and CWM evolve — even without a
   full event-sourcing rewrite.

**Do NOT** start a Cordis-style service-composition rewrite or a full
event-sourced session log as a headline effort. Both are high-risk churn with
payoffs Penguin can capture incrementally through the shape and discipline
changes above.

---

*Memo generated from a review of `reference/deepseek-harness/docs` and
`reference/cordis/packages/core/src`. No code was changed; this is analysis
only.*
