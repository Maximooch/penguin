# Context Window Manager v2

## Status

- State: draft task brief
- Created: 2026-05-23
- Research revision: 2026-07-29
- Owner: Maximus / Penguin
- Scope: `penguin/system/` conversation context pipeline, with future shared Penguin/Link package path

## Problem

Penguin's current `ContextWindowManager` is mostly a category-budget retention and trimming system. It preserves coherence by carrying a large working set forward until a budget threshold trips. That is now hurting latency and cost, especially with large-context OpenRouter models.

Recent logs showed repeated ~38k-61k input-token calls for a single task, including ~24k tokens of `CONTEXT`, ~12k tokens of `SYSTEM`, and growing `SYSTEM_OUTPUT`. Prompt caching helps after warmup, but the runtime still overfeeds the model by default.

A later Modal/Kimi K3 trace made the cache problem concrete. One eight-step
tool loop repeatedly sent ~95k-97k prompt tokens and cost about $1.46. One
iteration reused almost the entire prefix and was inexpensive; most iterations
only reused ~39k tokens because the assembled prefix changed. CWM therefore has
two related but distinct optimization problems:

1. Send fewer low-utility tokens.
2. Keep the useful repeated prefix byte-for-byte stable so providers can cache
   it.

Optimizing only prompt length can increase cost if it rewrites an already
cached prefix. Optimizing only cache hits can preserve a large, distracting
working set. CWM v2 must account for both.

The core issue is architectural:

> CWM is acting too much like an archive. It should be the final sampler/assembler before an LLM call.

Raw conversation, tool outputs, project docs, and durable memory should be stored/indexed elsewhere. The LLM request should receive a purpose-built context packet sized for the model, task, and user preference.

## Goals

1. Reduce default prompt size without losing task continuity.
2. Make context policy configurable: speed vs balanced vs coherence vs archival/debug.
3. Keep raw conversation and tool evidence non-lossy outside the prompt packet.
4. Add aggressive, cheap tool-output slimming before any LLM summarization.
5. Add optional summarization for older dialogue/tool history.
6. Prepare the boundary for the future Penguin/Link Context Graph and Coherence Layer.
7. Improve telemetry so context behavior is visible and debuggable.
8. Maximize provider prefix-cache reuse within agent tool loops.
9. Support multiple context representations: exact text, deterministic digest,
   semantic summary, optical page, and recoverable artifact reference.
10. Reach a measured long-session target of at least 50% input-token reduction
    while retaining at least 95% of baseline task performance.
11. Reduce cost per accepted task, not merely nominal prompt length.

## Non-Goals

- Do not build the full Context Graph in this task.
- Do not force lossy compaction on every user.
- Do not rewrite all conversation persistence in one PR.
- Do not make sub-agent semantics a special-case design driver. They should inherit policy and have optional per-agent clamps.
- Do not treat optical compression as a replacement for deterministic tool
  slimming, retrieval, summaries, or cache-stable assembly.
- Do not claim a token, cost, latency, or quality improvement without measuring
  the complete agent run.

## Design Principle

Use a pipeline, not one giant manager:

```text
Raw Conversation Store
  -> Conversation Index / future Context Graph
  -> Coherence State
  -> Context Assembler / CWM v2
  -> LLM Request
```

CWM v2 should assemble a per-call prompt packet. It should not be responsible for being long-term memory.

The derived packet should be split into two logical regions:

```text
IMMUTABLE PREFIX EPOCH
  system instructions
  stable tool manifest
  project/coherence snapshot
  prior structured summary
  sealed optical pages

APPEND-ONLY ACTIVE TAIL
  current user request
  recent dialogue
  current assistant/tool exchange
```

A context epoch is created at a user-turn or explicit checkpoint boundary and
frozen for the inner reasoning/tool loop. During that loop, Penguin appends
actions and observations without removing, reordering, reformatting, or
re-retrieving earlier packet content. A new epoch may be built between user
turns, when policy predicts that rebasing will pay for itself, or at a hard
context safety limit.

This makes CWM v2 a cache-aware context compiler:

```text
Append-only Session Event Log
  -> Artifact / Evidence Store
  -> Coherence State
  -> Retrieval Planner
  -> Representation Selector
  -> Cache-Aware Packet Compiler
  -> Provider Adapter
  -> Usage / Cost / Quality Telemetry
```

## Optimization Objective

The primary unit is an accepted task outcome, not an individual request.

For a complete run, track:

```text
run_cost =
    cache_write_cost
  + cache_read_cost
  + uncached_input_cost
  + output_and_reasoning_cost
  + auxiliary_model_cost
  + provider_tool_cost
```

The default balanced policy should minimize expected run cost and latency
subject to a quality constraint:

```text
minimize expected(cost_per_accepted_task, wall_time)
subject to task_score >= 0.95 * baseline_task_score
```

Raw token reduction remains an explicit target, but it is not a safe proxy for
cost. For example, replacing a large discounted cached prefix with a smaller
uncached summary or image can cost more until enough future turns amortize the
new cache write.

## Proposed Components

### 1. `ContextPolicy`

Config object that defines ceilings, budgets, and strategy.

Example config:

```yaml
context:
  strategy: balanced  # speed | balanced | coherence | archival
  ceiling: 0.70       # maximum input fraction of model context
  target_prompt_tokens: 48000  # cost-oriented target, independent of model max

  cache:
    epoch_scope: user_turn     # user_turn | checkpoint | disabled
    freeze_inner_loop: true
    deterministic_serialization: true
    rebase_min_savings: 0.20
    expected_remaining_turns: 4

  summarize:
    enabled: true
    trigger: 0.55     # summarize when prompt estimate exceeds 55%
    target: 0.35      # target prompt size after summarization
    model: null       # optional auxiliary summarizer model

  budgets:
    system: 0.10
    project_context: 0.10
    dialog_recent: 0.35
    dialog_summary: 0.10
    tool_outputs: 0.05
    retrieved_memory: 0.10
    reserve: 0.20

  tool_outputs:
    old_result_policy: summarize  # keep | summarize | placeholder | artifact_only
    protect_recent_tokens: 8000
    max_old_result_chars: 1000

  project_context:
    retrieval: selective  # eager | selective | off
    autoload_budget: 0.10

  optical:
    enabled: false
    eligible_categories: [system_output]
    protect_recent_tokens: 12000
    max_pages: 2
    retrieval: selective
```

Preset sketch:

| Strategy | Ceiling | Behavior |
|---|---:|---|
| `speed` | 0.40-0.50 | aggressive pruning, selective docs only, small recent tail |
| `balanced` | 0.60-0.70 | summarize older turns, preserve meaningful recent tail |
| `coherence` | 0.80-0.90 | larger tail, less pruning, richer recall |
| `archival` | 0.90+ | expensive debug mode, near-full context, explicit opt-in |

The model context-window fraction is a hard-cap policy, not the only trigger.
Large-context models should still have a cost-oriented prompt target. A 1M-token
window must not imply that a 650k-token prompt is acceptable before CWM acts.

Policy resolution should also consume provider capabilities:

```python
class ContextProviderCapabilities(Protocol):
    supports_prompt_cache: bool
    supports_explicit_cache_breakpoints: bool
    supports_prompt_cache_key: bool
    supports_deferred_tools: bool
    supports_tool_namespaces: bool
    supports_tool_choice_subset: bool
    supports_stateful_continuation: bool
    supports_server_compaction: bool
    supports_vision: bool
    supports_vision_prefix_cache: bool
```

Provider adapters should describe capabilities. They should not each implement
an unrelated context policy.

### 2. `ToolResultCompactor`

Cheap deterministic pass before LLM summarization.

Responsibilities:

- Replace old large tool outputs with concise summaries and artifact refs.
- Remove empty tool-only placeholders and exact duplicate observations.
- Preserve recent tool results by token budget, not fixed count.
- Preserve protected/sensitive tools if needed.
- Keep tool-call/tool-result protocol valid.
- Avoid invalid JSON when shortening tool arguments.
- Produce deterministic output for identical inputs.
- Retain exact error strings, file paths, symbols, hashes, and other fields
  needed for later recovery.

Example replacement:

```text
[read_file] read penguin/system/context_window.py lines 1-220 (18,432 chars). Full output stored as artifact: tool-output-call_abc.txt
```

This should happen even when summarization is disabled.

Large results should be stored once and represented compactly:

```text
[execute_command] completed successfully.
Artifact: tool-results/call_abc.txt
Preview: 40 lines, 8 matches.
Files: penguin/system/context_window.py, penguin/engine.py
Recover with: read_tool_artifact(call_abc, lines=...)
```

### 3. `ConversationSummarizer`

Optional LLM summarizer for older conversation slices.

Guidelines:

- Protect head/system instructions and recent tail.
- Summarize the middle.
- Update prior summaries iteratively instead of summarizing summaries blindly.
- Use an auxiliary model/provider when configured.
- Treat summaries as reference, not active instructions.
- Include explicit sections:
  - Active Task
  - User Intent and Preferences
  - Decisions
  - Files Read/Modified
  - Errors and Fixes
  - Current State
  - Remaining Work
  - Required Files
  - Evidence/Artifact References

Important: summary failure must not silently drop content. If the summarizer fails, fall back to deterministic tool-output slimming + recency trimming with a visible warning.

Summaries should be immutable within a context epoch. Do not regenerate a
summary during every tool iteration. Iterative summary updates happen only when
creating a new epoch.

### 4. `ContextAssembler`

Final per-call prompt packet builder.

Inputs:

- current conversation/session
- current user message
- active files/images/context files
- context policy
- model context/input/output limits
- tool schemas/token overhead estimate
- future: context graph/coherence state retrieval results

Outputs:

- formatted messages
- diagnostics:
  - token estimate by section
  - policy used
  - ceiling used
  - summaries included
  - tool outputs compacted
  - dropped/truncated sections
  - artifacts referenced
  - packet/prefix fingerprint
  - context epoch id
  - cacheable prefix tokens estimated
  - tool-schema tokens estimated
  - image tokens estimated
  - representation chosen per context item

This is the replacement mental model for current `process_session()`.

### 5. `CacheAwarePacketCompiler`

Finalizes a provider-neutral packet without mutating the persisted session.

Responsibilities:

- Build and fingerprint an immutable context epoch.
- Canonically serialize maps, tool arguments, and schemas.
- Keep timestamps, request ids, volatile diagnostics, and per-call retrieval
  results out of the stable prefix.
- Freeze project retrieval and the tool manifest during an inner loop.
- Append new model/tool events without rewriting prior packet content.
- Place explicit cache breakpoints when supported.
- Provide stable cache keys scoped to the user/workspace/session trust boundary.
- Detect and report the first byte/token where consecutive prefixes diverge.
- Rebase only at policy boundaries or hard safety limits.

The compiler should expose an amortized rebase decision:

```text
rebase when:
  expected_future_cache_and_token_savings
    > cache_write_cost
    + summary_cost
    + optical_render_and_vision_cost
```

### 6. `RepresentationSelector`

Chooses the least expensive sufficiently faithful representation for each
context item:

| Representation | Best use |
|---|---|
| Exact text | user intent, active code, errors, current decisions |
| Deterministic digest | old tool results with recoverable artifacts |
| Semantic summary | prior decisions, progress, unresolved work |
| Optical page | bulky cold logs, listings, diffs, and read output |
| Artifact reference | evidence not currently relevant |

Selection should consider:

- expected task utility
- recency and active dependencies
- uniqueness versus redundant evidence
- exact-string sensitivity
- recoverability and provenance
- provider token and cache economics
- cache disruption from changing representation

This is a budgeted selection problem, not just oldest-first deletion.

### 7. `OpticalContextEncoder`

Optical context is an optional cold-evidence representation adapted from
AgentOCR. It must remain request-local; the raw textual session and tool
artifacts remain the source of truth.

Requirements:

- Pack a bounded, prioritized subset instead of encoding all candidates or
  falling back unchanged when the whole set does not fit.
- Build pages from immutable message/artifact ranges and seal them by content
  hash.
- Reuse completed pages exactly; append new pages rather than recomposing all
  old history.
- Store a compact textual sidecar containing page id, message range, tool
  names, files, symbols, keywords, and artifact references.
- Prefer old `SYSTEM_OUTPUT`, command logs, listings, prior diffs, and large
  file reads.
- Keep user decisions, current code, active errors, paths, hashes, and other
  exact-string-sensitive content textual.
- Retrieve only relevant optical pages when possible.
- Trigger from projected request cost or eligible cold-evidence size, not only
  a fraction of the model's maximum context window.
- Calibrate page dimensions and compression factors against actual
  provider-reported image tokens and task accuracy.
- Fall back safely to digests, summaries, or artifact references when vision
  is unavailable.

Agent-selected compression factors are a later experiment. Without AgentOCR's
compression-aware training loop, the first production policy should be
deterministic and evaluation-driven.

### 8. `ConversationRetriever`

Small v1 retrieval bridge before the full graph exists.

Capabilities:

- Read current session and previous sessions by id/project.
- Search conversations for task/file/error terms.
- Return compact snippets with provenance/session/message ids.

Possible existing hooks to inspect:

- session read endpoints/tools
- grep/search tools over conversation storage
- `context/journal` and `context/MEMORY.md`

This should later become a thin client over the Context Graph.

### 9. Future `ContextGraphClient`

Not part of first implementation, but the interface should be shaped now.

Target layers from `context/architecture/Penguin-Link-Context-Graph-v1.md`:

- Context Graph: durable bitemporal facts/events/provenance.
- Coherence Layer: per-agent workspace understanding and salience.
- CWM: per-call sampler/assembler.

CWM v2 should depend on an abstraction like:

```python
class ContextSource(Protocol):
    def retrieve_for_turn(self, query: ContextQuery, budget: TokenBudget) -> list[ContextItem]: ...
```

## Reference Notes

### Cache-Aware Agent Harnesses

OpenAI, Anthropic, Gemini, Manus, and vLLM converge on the same operational
rules:

- Cache hits require an exact shared prefix.
- Put stable instructions, examples, tools, and large shared context first.
- Put variable user input and retrieved material later.
- Keep context append-only within a run.
- Serialize deterministically, including JSON key order.
- Keep tool definitions and image content stable when they are part of the
  cached prefix.
- Use explicit cache breakpoints/keys and consistent worker routing when the
  provider supports them.
- Measure cache reads, writes, misses, and the first divergence point.

Manus additionally recommends masking or constraining tools rather than
removing definitions mid-loop, because changing tools both invalidates the
prefix and leaves historical calls referring to absent schemas.

OpenAI's deferred tool search provides another provider-specific option: keep
compact namespace descriptions visible and inject selected schemas at the end
of the context. Penguin should support both strategies through capabilities
rather than forcing one universal tool policy.

vLLM's automatic prefix caching demonstrates the useful local abstraction:
content-addressed immutable prefix blocks, with multimodal hashes included in
the cache identity. Optical pages should follow the same discipline.

### Hermes Agent

Most relevant architecture.

- Pluggable `ContextEngine` interface.
- Config-driven engine selection.
- Tracks token usage and compression thresholds.
- Dual compression: pre-agent safety net and in-loop compressor.
- Cheap tool-output pruning before LLM summarization.
- Protects head and recent tail.
- Iterative summary updates.

Files:

- `reference/hermes-agent/agent/context_engine.py`
- `reference/hermes-agent/agent/context_compressor.py`
- `reference/hermes-agent/website/docs/developer-guide/context-compression-and-caching.md`

Borrow:

- Interface boundaries.
- Threshold/target config.
- Tool-output pre-pass.
- Summary template discipline.

Do not blindly borrow:

- Silent summary failure behavior. Penguin should never drop middle context invisibly.
- Repeated compression passes without anti-thrashing hysteresis.
- Compression triggers based only on a percentage of a very large model window.

### OpenCode

Good operational primitives.

- Auto compaction can be disabled.
- Emits compaction events.
- Prunes old tool outputs by walking backward and protecting recent tool-token budget.
- Has dedicated compaction message/part types.

Files:

- `reference/opencode/packages/opencode/src/session/compaction.ts`
- `reference/opencode/packages/opencode/src/session/processor.ts`
- `reference/opencode/packages/opencode/src/session/summary.ts`

Borrow:

- Eventing.
- Old tool-output pruning.
- Explicit compaction parts/messages.

### Kimi CLI

Simple baseline.

- Preserve last N user/assistant messages.
- Summarize earlier history.
- Insert compacted context as assistant reference message.

Files:

- `reference/kimi-cli/src/kimi_cli/soul/compaction.py`
- `reference/kimi-cli/src/kimi_cli/prompts/compact.md`

Borrow:

- Clear, minimal summary schema.

Do not borrow:

- Fixed last-2-message preservation. Too crude for Penguin.

### Cline

Good user-facing model of auto compact.

- Summarization is visible as a tool call.
- Continuation prompt is explicit.
- Strong summary sections for coding tasks.
- Integrates with task progress/focus chain.

Files:

- `reference/cline/docs/features/auto-compact.mdx`
- `reference/cline/src/core/prompts/contextManagement.ts`

Borrow:

- Summary prompt structure.
- UX visibility.
- Checkpoint/restore framing.

Do not blindly borrow:

- Full conversation replacement as the primary architecture.

### Claude Code / Anthropic

Anthropic describes a hybrid long-horizon strategy:

- compact old history into a high-recall handoff
- clear redundant tool calls/results
- preserve architectural decisions, unresolved bugs, and implementation state
- keep a small set of recently accessed files
- maintain structured notes outside the context window
- retrieve information just in time

Borrow:

- Maximize recall first, then improve summary precision through evaluations.
- Treat structured notes and artifacts as durable state outside the prompt.
- Combine up-front stable context with just-in-time exploration.

### AgentOCR and Prompt Compression Research

AgentOCR reports over 50% token reduction while retaining over 95% of baseline
performance on its evaluated agent tasks. Its segment optical cache supports
the immutable-page direction, but Penguin must not assume those results
transfer directly to coding, Kimi K3, or untrained compression-factor
selection.

LongLLMLingua and related prompt-compression work suggest that higher
information density and improved placement can sometimes improve performance,
not just reduce cost. `Lost in the Middle` provides the complementary warning:
technically supported long context is not uniformly usable attention.

MemGPT's virtual-memory framing maps closely to CWM v2:

- exact recent working set in the model
- structured warm state
- cold summaries/optical pages
- lossless backing store

These references support a hierarchical, recoverable design rather than one
irreversible transcript rewrite.

External sources:

- OpenAI prompt caching:
  <https://developers.openai.com/api/docs/guides/prompt-caching>
- OpenAI tool search:
  <https://developers.openai.com/api/docs/guides/tools-tool-search>
- OpenAI programmatic tool calling:
  <https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling>
- OpenAI compaction:
  <https://developers.openai.com/api/docs/guides/compaction>
- Anthropic prompt caching:
  <https://platform.claude.com/docs/en/build-with-claude/prompt-caching>
- Anthropic context engineering:
  <https://www.anthropic.com/engineering/effective-context-engineering-for-ai-agents>
- Manus context engineering:
  <https://manus.im/blog/Context-Engineering-for-AI-Agents-Lessons-from-Building-Manus>
- vLLM automatic prefix caching:
  <https://docs.vllm.ai/en/stable/design/prefix_caching/>
- AgentOCR: <https://arxiv.org/abs/2601.04786>
- MemGPT: <https://arxiv.org/abs/2310.08560>
- Lost in the Middle: <https://arxiv.org/abs/2307.03172>
- LongLLMLingua: <https://arxiv.org/abs/2310.06839>

## Computer-Science Model

Use these concepts explicitly in design and review:

| Concept | CWM v2 application |
|---|---|
| Working-set model | Keep actively referenced state in exact text |
| Generational garbage collection | Age context from recent text to compact cold evidence |
| Event sourcing | Preserve an append-only session; derive request packets |
| Content-addressable storage | Hash artifacts, summaries, and optical pages |
| Cache locality | Stabilize frequently reused instructions and state |
| Amortized analysis | Rebase only when future savings repay the miss/write |
| Hysteresis | Separate trigger/target thresholds to prevent compaction thrash |
| Rate-distortion | Minimize representation cost under a quality-loss bound |
| Knapsack/submodular selection | Maximize useful, non-redundant evidence per token |
| Critical-path analysis | Reduce sequential model turns before optimizing parallel work |
| Progressive disclosure | Start compact and retrieve details on demand |

## Current Penguin Issues To Address

1. `SYSTEM_OUTPUT` budget appears too large in code relative to architecture docs.
   - Code currently documents/uses 20%.
   - Architecture doc says 5%.
   - Recent logs showed `SYSTEM_OUTPUT` growing past ~18k tokens.

2. Project context autoload can inject ~24k tokens on a fresh task.
   - Need selective retrieval or budgeted autoload.

3. Tool-only turns look like empty responses.
   - Telemetry should distinguish `tool_only=True` from actual empty model text.

4. Large context windows delay discipline.
   - A 272k context should not mean a 272k prompt target.
   - Add configurable ceiling.

5. Current CWM trims only when over budget/category limit.
   - Need proactive slimming/summarization based on policy trigger.

6. Current processing replaces the active session after messages are added.
   - CWM v2 packet assembly must be request-local.
   - The persisted raw transcript must not be destructively trimmed.

7. Category trimming during an inner tool loop can rewrite the historical
   prefix.
   - Freeze a context epoch for the loop and append only.

8. Token counting excludes or inaccurately estimates provider-rendered
   overhead.
   - Include tools, images, reasoning replay, provider wrappers, and actual API
     usage reconciliation.

9. Tool schemas are a large fresh-session cost.
   - Measure schema tokens separately.
   - Use stable manifests, stateful constraints, namespaces, or deferred tools
     according to provider capability.

10. Retrieval can itself break caching.
    - Resolve and freeze project/retrieved context once per user turn.

11. Empty tool-only assistant placeholders pollute history and diagnostics.
    - Preserve native tool protocol records without synthesizing repeated
      model-visible empty messages.

## Implementation Plan

### Phase 0: Instrumentation and Guardrails

- Add context packet diagnostics before every LLM call:
  - model context limit
  - configured ceiling
  - estimated input tokens
  - tool schema overhead estimate
  - section/category breakdown
  - compacted/skipped counts
- Add provider-reported actual token reconciliation:
  - uncached prompt tokens
  - cache-read tokens
  - cache-write tokens
  - tool-schema tokens
  - image tokens
  - output/reasoning tokens
- Add packet, epoch, and stable-prefix fingerprints.
- Compare consecutive requests and report the first prefix divergence.
- Add `tool_only` telemetry in streaming finalization.
- Add warning when prompt exceeds configured ceiling.

Acceptance:

- Logs make it obvious why a prompt is large.
- Tool-only turns no longer look like failed empty responses.
- The dashboard can reconstruct cost per request and complete agent run.
- A cache miss can be traced to the exact changed packet section.

### Phase 1: Policy and Ceiling

- Add `ContextPolicy` config loader with presets.
- Enforce input ceiling separately from model context window.
- Keep existing behavior as `archival` or compatibility mode.
- Default to `balanced` after tests pass.

Acceptance:

- User can set `context.ceiling: 0.50` or `0.70`.
- LLM request assembly targets that ceiling, not full context.
- A cost-oriented absolute target can activate before the context-fraction
  trigger on large-window models.

### Phase 2: Cache-Stable Context Epochs

- Move trimming/representation decisions out of durable session mutation.
- Build a request-local packet from the append-only session.
- Create and fingerprint an immutable epoch at user-turn boundaries.
- Freeze system instructions, project retrieval, summaries, optical pages, and
  tool policy during the inner loop.
- Canonically serialize all stable data.
- Append assistant/tool records without rewriting prior packet content.
- Add provider cache keys and breakpoints when supported.

Acceptance:

- Iteration 2+ of a deterministic fake-provider loop has an identical prefix
  through the prior iteration boundary.
- Adding a tool result changes only the appended suffix.
- Raw persisted sessions retain every original message and artifact pointer.
- Prefix divergence diagnostics identify deliberate epoch rebases.

### Phase 3: Tool Output Compaction

- Add deterministic compactor for old tool results.
- Preserve recent tool outputs by token budget.
- Replace older large outputs with summaries + artifact refs.
- Preserve protocol validity for tool calls/results.
- Remove empty placeholders and exact duplicate observations.
- Cap large outputs at insertion time while storing the complete artifact.

Acceptance:

- A session with large `read_file`/command outputs shrinks significantly before LLM call.
- Raw outputs remain recoverable from artifacts/session storage.
- Identical inputs produce byte-identical digests.
- Compaction does not split or orphan native tool exchanges.

### Phase 4: Selective Project Context

- Make context file autoload budgeted.
- Prefer relevance-ranked snippets over entire docs.
- Keep explicit user-attached files stronger than auto context.
- Resolve retrieval once per user turn and freeze it in the epoch.

Acceptance:

- Fresh task does not inject 24k project docs unless strategy/config allows it.
- Inner-loop requests do not rerun retrieval or change the project-context
  prefix.

### Phase 5: Optional Summarization

- Add `ConversationSummarizer` using configured auxiliary/main model.
- Summarize middle turns when trigger threshold is crossed.
- Preserve system/head and recent tail.
- Iterate previous summary.
- Emit visible summary/compaction event.
- Add hysteresis, minimum-savings, and anti-thrashing rules.
- Update summaries only at epoch boundaries.

Acceptance:

- Long sessions maintain task continuity with much smaller prompt packets.
- Summary failure does not silently drop context.
- Ineffective compression cannot loop repeatedly.

### Phase 6: Optical Cold Evidence

- Add optical encoding as a `RepresentationSelector` option.
- Pack a prioritized bounded subset rather than requiring all candidates to
  fit.
- Seal immutable pages and textual sidecars by content hash.
- Keep exact active state textual and raw evidence recoverable.
- Retrieve pages selectively.
- Calibrate model/provider image-token cost and OCR accuracy.

Acceptance:

- Sealed pages are reused byte-for-byte across inner-loop requests.
- Adding cold history creates a new page without changing completed pages.
- Page limits degrade to digest/summary/artifact representations rather than
  restoring the entire textual history.
- Exact-string-sensitive tasks do not depend solely on OCR recovery.
- Optical mode improves the evaluation Pareto frontier before becoming a
  default.

### Phase 7: Retrieval and Context Graph Bridge

- Add minimal conversation/session retriever.
- Define `ContextSource` abstraction for future Context Graph client.
- Store summary/compaction artifacts with provenance pointers.

Acceptance:

- CWM v2 can pull relevant prior-session snippets without loading whole sessions.
- The interface can later target the shared Penguin/Link context graph package.

### Phase 8: Tool and Orchestration Efficiency

- Measure tool-schema overhead by provider and task.
- Add task-relevant tool bundles/namespaces.
- Support deferred tool loading where the provider preserves the cache.
- Prefer stateful tool constraints over removing schemas mid-loop where
  supported.
- Add orchestration budgets for model iterations, retries, repeated reads, and
  exploration.
- Parallelize independent reads/searches.
- Use deterministic reducers for filtering, deduplication, ranking, joins, and
  aggregation before returning results to the model.
- Route simple auxiliary tasks to evaluated smaller models.

Acceptance:

- Fresh-session schema overhead falls substantially without tool-selection
  regressions.
- Long tool loops make fewer sequential model calls on the replay corpus.
- Completed actions are not repeated without new evidence or an explicit retry.

## Testing Strategy

Unit tests:

- Policy preset resolution.
- Ceiling calculation.
- Canonical packet serialization and fingerprinting.
- Context epoch freeze/rebase behavior.
- Prefix-divergence diagnostics.
- Provider capability resolution.
- Tool-output compaction summaries.
- Protocol validity after tool compaction.
- Artifact recovery.
- Summary insertion and role ordering.
- Summary failure fallback.
- Anti-thrashing hysteresis.
- Project context budget enforcement.
- Optical page packing, sealing, sidecars, and fallback.
- Representation selection under token/cost budgets.

Integration tests:

- Long tool-heavy session stays below ceiling.
- Fresh task with project docs stays below autoload budget.
- Tool-only model responses are persisted/logged as tool-only, not empty failures.
- Config modes produce expected prompt sizes.
- Inner-loop requests preserve a stable prefix while appending tool exchanges.
- Persisted sessions remain lossless after request-local compaction.
- Provider usage is reconciled with estimated packet sections.

Regression tests from recent logs:

- 35 tool schemas + ~40k prompt does not synthesize massive output cap.
- Context packet with growing `SYSTEM_OUTPUT` triggers compaction/slimming before reaching runaway size.
- The Modal/Kimi eight-step replay does not repeatedly send ~96k mostly
  uncached tokens.
- Tool-only responses do not create hundreds of `[Empty response from model]`
  messages.
- Optical compression does not return the full original text merely because
  all eligible candidates exceed the page budget.

Replay evaluation:

- Build a stratified corpus of real, sanitized Penguin sessions:
  - long tool-heavy coding
  - large project context
  - multi-turn debugging
  - exact error/string recovery
  - research
  - vision/optical-eligible history
  - provider failures and retries
- Record or fake tool outputs so CWM variants see identical evidence.
- Compare the current baseline with cumulative ablations:
  1. cache-stable epochs
  2. placeholder cleanup and deterministic tool compaction
  3. selective project retrieval
  4. structured summaries/coherence state
  5. optical cold evidence
  6. tool namespaces/deferred loading
- Repeat stochastic live-model evaluations where needed and report confidence
  intervals rather than a single favorable run.
- Keep live-provider checks opt-in; deterministic fake-provider and contract
  tests remain the correctness proof.

## Metrics

Track per turn:

- `prompt_tokens_estimated`
- `prompt_tokens_actual`
- `prompt_uncached_tokens_actual`
- `cache_read_tokens`
- `cache_write_tokens`
- `cache_hit_fraction`
- `cacheable_prefix_tokens_estimated`
- `tool_schema_tokens_estimated`
- `image_tokens_estimated`
- `reasoning_tokens_actual`
- `context_ceiling_tokens`
- `context_ceiling_fraction`
- `context_target_tokens`
- `context_epoch_id`
- `packet_fingerprint`
- `stable_prefix_fingerprint`
- `prefix_divergence_section`
- `tool_output_tokens_before`
- `tool_output_tokens_after`
- `summary_tokens`
- `optical_candidate_tokens`
- `optical_pages_included`
- `artifact_reference_count`
- `compaction_count`
- `context_assembly_ms`
- `llm_latency_ms`
- `time_to_first_token_ms`
- `model_iterations`
- `tool_calls`
- `request_cost`
- `run_cost`
- `accepted_task`
- `cost_per_accepted_task`

Success targets for balanced mode:

- Fresh coding/research task starts under 20k-30k prompt tokens unless user explicitly attaches more.
- Tool-heavy loop keeps old `SYSTEM_OUTPUT` under ~5-10% of model context or configured ceiling.
- Repeated loops avoid unbounded prompt growth.
- Iteration 2+ stable-prefix cache hit fraction is at least 85% on providers
  with prefix caching.
- Long-session actual input tokens are at most 50% of the current-CWM baseline
  on the replay corpus.
- Task score is at least 95% of the current-CWM baseline.
- Cost per accepted task is at most 50% of baseline.
- No critical user constraint, unresolved blocker, active error, or native tool
  protocol dependency is lost.

Quality scoring must be task-based, not summary-similarity-based. Include:

- final task/test success
- patch correctness and completeness
- user constraint recall
- decision, file, and unresolved-error recall
- evidence restoration success
- tool protocol validity
- unsupported claims or hallucinated actions

Token reduction, cache savings, cost reduction, and latency reduction must be
reported separately. A smaller prompt is not automatically cheaper, and a 50%
input reduction does not guarantee a 50% wall-time reduction.

## Open Questions

1. Should the default strategy be `balanced` or `speed` for OpenRouter models?
2. Should summarization use the same provider/model, or a dedicated fast auxiliary model?
3. Where should summary artifacts live: session messages, context files, or both?
4. How much of project docs should be eager-loaded vs retrieved?
5. What should be the exact compatibility path for existing persisted sessions?
6. Should compaction be visible in the chat transcript by default or only in telemetry?
7. How should user dislike of compaction be represented? Suggested answer: make summarization optional, but always allow deterministic tool-output slimming.
8. What is the provider-neutral representation of cache keys and explicit
   breakpoints?
9. Should the epoch normally rebase every user turn or only when predicted
   savings exceed a threshold?
10. Which tools/results are exact-string-sensitive and therefore ineligible
    for optical-only representation?
11. How should image-token cost and visual recall be calibrated per model?
12. Should tool schemas remain stable and constrained, or be deferred, for each
    provider?
13. What composite task score defines 95% retained performance?

## Suggested First PR

Minimal, high-leverage PR:

1. Add context packet and provider-usage diagnostics.
2. Add packet/epoch/prefix fingerprints and divergence reporting.
3. Add request-local `ContextAssembler` without changing trimming behavior yet.
4. Add deterministic old tool-output slimming with recoverable artifacts.
5. Lower/parameterize `SYSTEM_OUTPUT` budget.
6. Add `tool_only=True` telemetry and stop creating empty model-visible
   placeholders.

Avoid LLM summarization and optical encoding in the first PR. Establish
lossless request-local assembly, stable prefixes, accurate accounting, and
deterministic wins first.

## Strategic Note

The point is not to copy generic compaction. The point is to make Penguin stop resending everything by default while preserving evidence and continuity elsewhere, and to stop invalidating expensive provider caches while doing so.

The durable memory path is the Context Graph. The working-memory path is the Coherence Layer. CWM v2 is only the final model-specific packet assembler.

Optical context is one cold-storage encoding available to that assembler. It
helps CWM v2 reach the 50% token target only after stable caching,
deterministic tool compaction, selective retrieval, and recoverable memory
boundaries are in place.
