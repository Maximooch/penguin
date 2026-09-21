# GPT-6 Astra reasoning visibility diagnosis

Date: 2026-09-04. Scope: onboarding, diagnosis, and offline verification; no runtime changes.

## Conclusion

The supplied Astra runs completed successfully through Penguin's native OpenAI
OAuth Codex route. Their reasoning token counts were nonzero, but no visible
reasoning was extracted and no reasoning-summary events appeared in the event
inventory. The immediate failure boundary is the provider/adapter boundary,
before the terminal renderer.

Separately, deterministic fake-provider replays reproduce three ways Penguin can
lose visible summaries. These can explain intermittent heading-only or missing
text, but the supplied logs do not establish that these patterns occurred in
the two Astra runs.

## Runtime map

- `penguin/web/routes.py`: request handling, session/model/variant selection,
  reasoning diagnostics, and chat response assembly.
- `penguin/llm/runtime.py`: reasoning variant overrides and diagnostic snapshots.
- `penguin/core.py`: orchestration; `penguin/engine.py`: reasoning/tool loop and
  streaming finalization.
- `penguin/llm/api_client.py`: provider dispatch.
- `penguin/llm/model_config.py`: GPT-6 reasoning capability and effort settings.
- `penguin/llm/adapters/openai.py`: native SDK and OAuth Responses transports,
  request shaping, summary extraction, callbacks, and usage accounting.
- `penguin/core_runtime/`: stream events and OpenCode transcript bridge.
- `penguin-tui/packages/opencode/src/cli/cmd/tui/routes/session/index.tsx`:
  reasoning rendering. Its `util/reasoning-summary.ts` helper separates a leading
  bold heading from the remaining body.

## Evidence from the supplied session

Session: `session_20260904_183854_b70a0a4e`.

| Chat request diagnostic ID | Reasoning tokens | Extracted summary characters | Reasoning events |
| --- | ---: | ---: | --- |
| `oaoc_9e66bfe7dd` | 18 | 0 | none |
| `oaoc_23261ce199` | 247 | 0 | none |

Both used `gpt-6-astra`, medium effort, priority service, HTTP 200, and no model
fallback. Title-generation requests are separate and should not be confused
with these chat requests.

The saved conversation exists under `~/penguin_workspace/conversations/` and
contains the corresponding two assistant messages. The attached screenshot
shows a Claude Code session, so it does not establish Penguin's Astra UI state.

The pasted logs show pre-adapter effort and `has_reasoning=True`, not the exact
outbound reasoning object or raw output items. Consequently, they cannot prove
whether the live request opted into summaries or whether an unrecognized nested
payload held text. Current-code replay does verify the expected outbound object.

## Ranked causes and verification

### 1. No visible summary returned on this OAuth route: strongest live evidence

The supplied stream inventory contains no summary events. Current Penguin code
already adds `reasoning.summary = "auto"` and requests
`include: ["reasoning.encrypted_content"]` (adapter lines 2847 and 1507).
A fake GPT-6 Astra request confirms both fields are sent.

Codex reference commit `574a36ff99` dated 2026-09-04 sets Astra's
`default_reasoning_summary` to `none`, while explicitly declaring support for
summaries and the summary parameter in
`reference/codex/codex-rs/models-manager/models.json` (lines 36 and 169).
This is evidence of a client default, not proof Astra cannot return summaries
or that the backend ignores Penguin's explicit opt-in.

The official reasoning guide distinguishes internal reasoning token usage from
visible summaries and demonstrates Astra with `summary: "auto"`:
<https://developers.openai.com/api/docs/guides/reasoning#reasoning-summaries>.
The public API guide does not establish identical behavior for the ChatGPT OAuth
Codex endpoint. Server behavior, account gating, and exact live request shaping
remain unresolved without a targeted capture or comparison.

### 2. Response-wide deduplication discards valid summary text: reproduced

At adapter lines 2015–2020, any prior nonempty reasoning suppresses all text
from subsequent `response.output_item.done` reasoning items. At lines 1995–1997,
the final response summary is also used only when accumulated reasoning is empty.
The SDK stream has analogous guards around lines 2618 and 2649.

Consequences reproduced through `OpenAIAdapter.get_response`, using the existing
fake OAuth transport and GPT-6 Astra configuration:

- A heading delta followed by a completed item containing heading plus body
  yields only the heading, even when the final response includes the full text.
- Two distinct completed reasoning items yield only the first item.

This is a definite adapter bug. Attribution to the user's historical partial
displays remains a hypothesis because those raw streams were not supplied.

### 3. Newer Codex event handling is missing: reproduced, conditional relevance

Penguin ignores `response.reasoning_summary_text.done` in both SSE and SDK
extractors (adapter lines 2912 and 2941). A replay with a summary present only
in this event yields no visible text. Complete text repeated in a final response
can rescue the case only if no earlier reasoning was accumulated.

The reference parser handles this event in
`reference/codex/codex-rs/codex-api/src/sse/responses.rs:391`.
Codex optionally requests
`stream_options.reasoning_summary_delivery = "sequential_cutoff"` and consumes
complete summaries with item IDs and summary indexes in the turn handler.

However, `ConcurrentReasoningSummaries` is under development and defaults off
(`reference/codex/codex-rs/features/src/lib.rs:1486`). It is not a demonstrated
mandatory GPT-6 migration. Enabling the request option alone is not a sound fix.
The reference also handles `response.reasoning_text.delta`, which Penguin's
extractors omit; this was found by inspection, not a separate stream replay.

### 4. Presentation behavior: contributes to symptoms, not the logged root cause

The TUI displays a heading without a body when only a bold heading reaches it.
Its thinking visibility setting defaults to true. The renderer keeps the body
when supplied, so the heading parser itself does not explain the adapter losses.

Both `build_reasoning_visibility_note` and `build_reasoning_fallback_note` in
`penguin/llm/runtime.py` now return `None`. Thus, when a provider returns usage
without visible text, Penguin deliberately shows no explanatory placeholder.
The older reasoning-visibility task document describes obsolete fallback
behavior and lists request-shaping fixes that are already implemented.

## Offline checks

Command:

```sh
uv run --no-sync pytest -q tests/llm/test_openai_oauth_subscription_flow.py tests/test_openai_adapter_streaming.py tests/test_engine_reasoning_fallback.py tests/api/test_reasoning_debug_routes.py
```

Result: **44 passed**, three existing Pydantic deprecation warnings.

An additional temporary in-memory harness used `FakeCodexTransport`, fake OAuth
credentials, and real `OpenAIAdapter.get_response` calls. No provider requests
were sent. The harness compared both callback text and `get_last_reasoning()`.

| Synthetic stream | Result |
| --- | --- |
| No visible provider summary, nonzero reasoning usage | Empty text, as expected |
| Full summary delta plus completed duplicate | Complete text once, as expected |
| Heading delta plus full completed item and response | Body lost |
| Two distinct completed reasoning items plus full response | Second item lost |
| Summary-text done event only | All summary text lost |

These cases reveal missing coverage despite the green existing tests. They are
synthetic protocol replays, not captures of the user's historical streams.

## Recommended next implementation

1. Track summary state by reasoning item ID and summary index, preserving missing
   suffixes and later items while deduplicating repeated completed snapshots.
   Cover both SDK and OAuth streams, complete-summary events, and final fallback.
2. Add the reproduced cases as regression tests before changing the adapter.
3. Capture the sanitized outbound reasoning/stream options and per-item summary
   lengths for an Astra request. The existing session `reasoning-debug` endpoint
   exposes the latest handler configuration while the server remains running;
   it stores snapshots in memory, not durable conversation history.
4. Only then compare summary delivery options on the same OAuth route. Do not
   infer that changing effort, adding encrypted content again, or a broad
   Responses Lite migration will restore visible text.

Existing uncommitted tool-abort/transcript changes were inspected and left
untouched. No runtime implementation or settings were changed during diagnosis.

## Implementation for manual review

Implemented after the diagnosis, at the user's request; not committed.

- `penguin/llm/adapters/responses_reasoning.py` tracks each reasoning item and
  summary/content index for one stream. Completed snapshots add missing suffixes
  without repeating earlier text. Distinct items and parts retain identical text.
- OAuth, SDK streaming, and HTTP fallback use the same tracker and callback path.
  Summary-text done, summary-part done, and reasoning-text events are supported.
- The existing OAuth request log now includes allowlisted reasoning options and
  whether encrypted content was requested. Completion diagnostics include each
  reasoning item's summary lengths, including empty summary arrays. They do not
  log summary text, ciphertext, prompts, or credentials.
- `tests/llm/test_openai_reasoning_stream.py` covers all three transports, repeated
  text, item/index identification, final response recovery, per-request reset,
  and diagnostic privacy. The first pre-fix run had 15 failures in 24 cases.

Verification: 147 targeted tests passed, including provider contracts, lifecycle,
retry, prepared-request, OAuth, SDK, and reasoning-route tests. New files pass
Ruff, all changed Python files pass formatting, and `git diff --check` passes.
The existing adapter has 217 Ruff findings versus 218 at HEAD; no new diagnostics.

No live provider request was made and the server was not restarted. After review
and restart, an Astra request will write the new sanitized diagnostics to its
normal server log. `request_options` and `reasoning_parts` are also available in
the existing session reasoning-debug snapshot. The original provider-side absence
of summaries still requires live verification; these changes cannot create text
the provider does not send.

The callback protocol remains append-only. A completed snapshot that revises
already emitted text rather than extending it produces a warning without logging
the text; replacing such text would require a separate UI update contract.
Experimental summary delivery and Responses Lite remain unchanged.
