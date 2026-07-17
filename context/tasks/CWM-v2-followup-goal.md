# CWM v2 follow-up `/goal`

```text
/goal Implement CWM v2 as a separate PR from the merged runtime-reliability result.

Branch: feat/CWM-v2 (or Penguin-Context-Window-Manager-v2)
Scope: final-packet context selection only. Do not reopen the reliability PR.

Entry criteria
- Runtime-reliability PR is merged and its Phase 0–3.5 gates are green.
- Use the retained fresh, large-session, tool-heavy, native-adjacency, replay,
  attachment, and large-output fixtures as the comparison baseline.
- Keep raw conversation/session/tool artifacts durable and non-lossy outside the
  assembled request packet.
- Confirm the current CWM terminology: category-priority/recency trimming is not
  compaction or summarization.

Phase A — policy and packet contracts
- Add typed ContextPolicy presets: speed, balanced, coherence, archival/debug.
- Define model/request ceilings, section budgets, reserve, and deterministic
  tie-breaking without changing stored history.
- Define ContextPacket and diagnostics for retained, slimmed, summarized,
  retrieved, dropped, and artifact-referenced sections.

Phase B — deterministic tool-output slimming
- Add a cheap pre-pass that replaces old large tool outputs with bounded previews
  and durable artifact references.
- Protect system/head instructions, native tool-call/result units, recent active
  work, sensitive/protected outputs, and explicit user attachments.
- Fail closed on malformed adjacency or artifact loss; never silently drop evidence.

Phase C — optional summarization and retrieval
- Add optional middle-history summarization with a stable schema and visible
  summary provenance.
- On summarizer failure, retain deterministic trimming/slimming with a visible
  warning and no silent data loss.
- Add bounded conversation/project retrieval with session/message provenance.

Phase D — final assembler and migration
- Assemble the final per-call packet after policy, slimming, summary, and retrieval.
- Preserve the runtime-reliability stable instruction prefix and active-turn
  envelope; record cache-boundary and packet diagnostics.
- Add opt-in persisted-session migration with dry-run, backup, rollback, and
  idempotent restart behavior. Do not rewrite source history destructively.

Tests and metrics
- Deterministic policy/property/state-machine tests for budgets and tie-breaking.
- Native adjacency, provider sanitation, replay, attachment, artifact, and
  malformed-summary fault tests.
- Fresh/large/tool-heavy before-vs-after prompt tokens, cache reads, latency,
  retained evidence, artifact bytes, and summary-failure behavior.
- Migration dry-run/rollback/restart tests and an explicit no-data-loss audit.

Rollback
- Keep packet assembly behind an opt-in policy/config flag until all gates pass.
- Disable the policy to restore the post-reliability packet path; retain raw
  history and artifacts untouched. Migration must restore from its backup.

Exit criteria
- Packet section budgets and model ceilings are deterministic and observable.
- Tool outputs are slimmed once, native units remain adjacent, and artifacts are
  readable after restart.
- Summarization/retrieval are optional, provenance-bearing, and fail visibly.
- Persisted sessions migrate only through reviewed dry-run/backup/rollback flows.
- CWM v2 improves prompt size/cache/latency against the retained post-reliability
  baseline without regressing terminal truth, reconnect, or provider safety.
```
