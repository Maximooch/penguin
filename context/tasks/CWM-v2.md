# Context Window Manager v2

## Status

- State: draft task brief
- Created: 2026-05-23
- Owner: Maximus / Penguin
- Scope: `penguin/system/` conversation context pipeline, with future shared Penguin/Link package path

## Problem

Penguin's current `ContextWindowManager` is mostly a category-budget retention and trimming system. It preserves coherence by carrying a large working set forward until a budget threshold trips. That is now hurting latency and cost, especially with large-context OpenRouter models.

Recent logs showed repeated ~38k-61k input-token calls for a single task, including ~24k tokens of `CONTEXT`, ~12k tokens of `SYSTEM`, and growing `SYSTEM_OUTPUT`. Prompt caching helps after warmup, but the runtime still overfeeds the model by default.

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

## Non-Goals

- Do not build the full Context Graph in this task.
- Do not force lossy compaction on every user.
- Do not rewrite all conversation persistence in one PR.
- Do not make sub-agent semantics a special-case design driver. They should inherit policy and have optional per-agent clamps.

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

## Proposed Components

### 1. `ContextPolicy`

Config object that defines ceilings, budgets, and strategy.

Example config:

```yaml
context:
  strategy: balanced  # speed | balanced | coherence | archival
  ceiling: 0.70       # maximum input fraction of model context

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
```

Preset sketch:

| Strategy | Ceiling | Behavior |
|---|---:|---|
| `speed` | 0.40-0.50 | aggressive pruning, selective docs only, small recent tail |
| `balanced` | 0.60-0.70 | summarize older turns, preserve meaningful recent tail |
| `coherence` | 0.80-0.90 | larger tail, less pruning, richer recall |
| `archival` | 0.90+ | expensive debug mode, near-full context, explicit opt-in |

### 2. `ToolResultCompactor`

Cheap deterministic pass before LLM summarization.

Responsibilities:

- Replace old large tool outputs with concise summaries and artifact refs.
- Preserve recent tool results by token budget, not fixed count.
- Preserve protected/sensitive tools if needed.
- Keep tool-call/tool-result protocol valid.
- Avoid invalid JSON when shortening tool arguments.

Example replacement:

```text
[read_file] read penguin/system/context_window.py lines 1-220 (18,432 chars). Full output stored as artifact: tool-output-call_abc.txt
```

This should happen even when summarization is disabled.

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

This is the replacement mental model for current `process_session()`.

### 5. `ConversationRetriever`

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

### 6. Future `ContextGraphClient`

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

## Implementation Plan

### Phase 0: Instrumentation and Guardrails

- Add context packet diagnostics before every LLM call:
  - model context limit
  - configured ceiling
  - estimated input tokens
  - tool schema overhead estimate
  - section/category breakdown
  - compacted/skipped counts
- Add `tool_only` telemetry in streaming finalization.
- Add warning when prompt exceeds configured ceiling.

Acceptance:

- Logs make it obvious why a prompt is large.
- Tool-only turns no longer look like failed empty responses.

### Phase 1: Policy and Ceiling

- Add `ContextPolicy` config loader with presets.
- Enforce input ceiling separately from model context window.
- Keep existing behavior as `archival` or compatibility mode.
- Default to `balanced` after tests pass.

Acceptance:

- User can set `context.ceiling: 0.50` or `0.70`.
- LLM request assembly targets that ceiling, not full context.

### Phase 2: Tool Output Compaction

- Add deterministic compactor for old tool results.
- Preserve recent tool outputs by token budget.
- Replace older large outputs with summaries + artifact refs.
- Preserve protocol validity for tool calls/results.

Acceptance:

- A session with large `read_file`/command outputs shrinks significantly before LLM call.
- Raw outputs remain recoverable from artifacts/session storage.

### Phase 3: Optional Summarization

- Add `ConversationSummarizer` using configured auxiliary/main model.
- Summarize middle turns when trigger threshold is crossed.
- Preserve system/head and recent tail.
- Iterate previous summary.
- Emit visible summary/compaction event.

Acceptance:

- Long sessions maintain task continuity with much smaller prompt packets.
- Summary failure does not silently drop context.

### Phase 4: Selective Project Context

- Make context file autoload budgeted.
- Prefer relevance-ranked snippets over entire docs.
- Keep explicit user-attached files stronger than auto context.

Acceptance:

- Fresh task does not inject 24k project docs unless strategy/config allows it.

### Phase 5: Retrieval and Context Graph Bridge

- Add minimal conversation/session retriever.
- Define `ContextSource` abstraction for future Context Graph client.
- Store summary/compaction artifacts with provenance pointers.

Acceptance:

- CWM v2 can pull relevant prior-session snippets without loading whole sessions.
- The interface can later target the shared Penguin/Link context graph package.

## Testing Strategy

Unit tests:

- Policy preset resolution.
- Ceiling calculation.
- Tool-output compaction summaries.
- Protocol validity after tool compaction.
- Summary insertion and role ordering.
- Summary failure fallback.
- Project context budget enforcement.

Integration tests:

- Long tool-heavy session stays below ceiling.
- Fresh task with project docs stays below autoload budget.
- Tool-only model responses are persisted/logged as tool-only, not empty failures.
- Config modes produce expected prompt sizes.

Regression tests from recent logs:

- 35 tool schemas + ~40k prompt does not synthesize massive output cap.
- Context packet with growing `SYSTEM_OUTPUT` triggers compaction/slimming before reaching runaway size.

## Metrics

Track per turn:

- `prompt_tokens_estimated`
- `prompt_tokens_actual`
- `context_ceiling_tokens`
- `context_ceiling_fraction`
- `cache_read_tokens`
- `tool_output_tokens_before`
- `tool_output_tokens_after`
- `summary_tokens`
- `compaction_count`
- `context_assembly_ms`
- `llm_latency_ms`
- `cost`

Success targets for balanced mode:

- Fresh coding/research task starts under 20k-30k prompt tokens unless user explicitly attaches more.
- Tool-heavy loop keeps old `SYSTEM_OUTPUT` under ~5-10% of model context or configured ceiling.
- Repeated loops avoid unbounded prompt growth.

## Open Questions

1. Should the default strategy be `balanced` or `speed` for OpenRouter models?
2. Should summarization use the same provider/model, or a dedicated fast auxiliary model?
3. Where should summary artifacts live: session messages, context files, or both?
4. How much of project docs should be eager-loaded vs retrieved?
5. What should be the exact compatibility path for existing persisted sessions?
6. Should compaction be visible in the chat transcript by default or only in telemetry?
7. How should user dislike of compaction be represented? Suggested answer: make summarization optional, but always allow deterministic tool-output slimming.

## Suggested First PR

Minimal, high-leverage PR:

1. Add `ContextPolicy` with `ceiling` and strategy presets.
2. Add context packet diagnostics.
3. Add deterministic old tool-output slimming.
4. Lower/parameterize `SYSTEM_OUTPUT` budget.
5. Add `tool_only=True` telemetry.

Avoid LLM summarization in the first PR. It is higher risk. Get the deterministic wins first.

## Strategic Note

The point is not to copy generic compaction. The point is to make Penguin stop resending everything by default while preserving evidence and continuity elsewhere.

The durable memory path is the Context Graph. The working-memory path is the Coherence Layer. CWM v2 is only the final model-specific packet assembler.
