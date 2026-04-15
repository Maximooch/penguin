# OpenAI Codex Reasoning Summary Visibility

## Problem

Native OpenAI/Codex runs are reporting non-zero `reasoning_tokens`, but Penguin is often
showing only the fallback note:

`Reasoning effort applied, but provider returned no visible reasoning summary.`

OpenRouter-backed OpenAI models and the OpenCode reference more frequently surface visible
reasoning text in the TUI.

## Evidence

- Native OpenAI/Codex logs show patterns like:
  - `reasoning_tokens=84`
  - `visible_reasoning_chars=0`
  - `summary_returned=False`
- Event traces for native OAuth often include only:
  - `response.created`
  - `response.in_progress`
  - `response.output_item.added`
  - `response.output_item.done`
  - `response.content_part.added`
  - `response.output_text.delta`
  - `response.output_text.done`
  - `response.content_part.done`
  - `response.completed`
- In those cases, no `response.reasoning_summary_text.delta` events are seen.

## Reference Findings

### OpenAI docs

From the Responses reasoning guide:

- Visible reasoning summaries require opting in with `reasoning.summary`.
- Recommended request setting is `reasoning.summary = "auto"`.
- Reasoning summary output is part of the `summary` array on a `reasoning` output item.
- For stateless responses (`store=false`), `include: ["reasoning.encrypted_content"]`
  is needed to retain reasoning items across turns.

### OpenCode reference

- `provider/transform.ts` sets for OpenAI reasoning variants:
  - `reasoningEffort: effort`
  - `reasoningSummary: "auto"`
  - `include: ["reasoning.encrypted_content"]`
- The OpenAI responses stream parser handles reasoning text from:
  - `response.reasoning_summary_text.delta`
  - `response.output_item.added` with `item.type === "reasoning"`
  - `response.output_item.done` with `item.type === "reasoning"`
- Final non-stream response parsing reads reasoning text from `part.summary[]`.

## Current Penguin Gaps

1. Native OAuth request config currently defaults to `reasoning.summary = "concise"`
   instead of the OpenCode/OpenAI-docs `"auto"` setting.
2. Native OAuth request payload does not currently include
   `include: ["reasoning.encrypted_content"]`.
3. Penguin's response-object extractor only reads reasoning text from `content[]` and does
   not parse `summary[]` on reasoning output items.
4. Penguin's SSE reasoning extractor does not read reasoning summaries from
   `response.output_item.added/done` reasoning items.

## Intended Fix

1. Update native OpenAI/Codex request shaping to:
   - prefer `reasoning.summary = "auto"`
   - include `reasoning.encrypted_content` in `include`
2. Expand reasoning extraction to parse reasoning summary arrays from:
   - completed response objects
   - streamed `response.output_item.added/done` reasoning items
3. Preserve current fallback-note behavior only when:
   - reasoning was requested
   - reasoning tokens were billed
   - no visible reasoning text was actually extracted

## Regression Coverage

Add tests for:

- request payload contains `reasoning.summary = "auto"`
- request payload includes `reasoning.encrypted_content`
- completed response object with `output[].summary[]` extracts visible reasoning
- streamed `response.output_item.done` reasoning item with `summary[]` extracts visible reasoning
- fallback note remains active only when visible reasoning is still absent
