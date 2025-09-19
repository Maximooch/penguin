# Penguin × OpenAI Responses API — Implementation TODOs

This document tracks the concrete work to fully integrate OpenAI’s Responses API as a first‑class provider while preserving Penguin’s model‑agnostic behavior and Context Window Manager (CWM) guarantees.

Legend: [OAI] OpenAI‑specific, [GEN] generic/safe for all providers.

## A) Inside `penguin/llm/adapters/openai.py`

1) Requests and model branching
- [OAI] Add `instructions` param support. Source = Penguin system prompt for the turn.
- [OAI] Reasoning control: include `reasoning: {effort: low|medium|high}` for effort‑style models (e.g., gpt‑5/o*). Omit `temperature` for these; include temperature for classic models. (Already partially implemented.)
- [OAI] Input content parts: when images are present, send as an array of `input_text` + `input_image{ image_url }`. Otherwise use a compact string input. Auto‑detect and choose smallest payload.
- [OAI] Streaming: set `stream_options.include_usage: true` and surface usage in the stream callback.

2) Conversation state
- [OAI] Add Conversations API helpers: `create_conversation(instructions)`, `update_conversation(conversation_id, instructions)`, `delete_conversation(conversation_id)`; return/store ids only (no global state here).
- [OAI] Accept `previous_response_id` on each call and include in Responses requests.
- [OAI] Accept `conversation` id and include when provided.
- [GEN] Do not enable unless provider is OpenAI and feature flag is set.

3) Tools and response shaping
- [OAI] Add optional `tools` and `tool_choice` parameters (web_search, file_search, code_interpreter). Gate behind config flags.
- [OAI] Add optional `response_format` (JSON schema) for structured outputs (actions/tool directives). Provide helper to merge a schema from the caller.

4) Error handling and telemetry
- [GEN] On 4xx/5xx, log a safe param summary: model, has_reasoning, effort_style, has_instructions, input_kind (string|array), has_tools, has_response_format.
- [GEN] Normalize SDK/SSE streaming paths; recover gracefully on SSE parse errors.
- [GEN] Retries/backoff: targeted backoff on 429/5xx (non‑streaming or stream start only); do not retry mid‑stream.
- [GEN] Timeouts: separate connect/read; fail fast on stream start; return actionable error messages.

5) Token counting
- [GEN] Keep tiktoken fallback; if OpenAI exposes usage live via stream, prefer that for the UI and skip expensive client counts on large payloads.

6) Backward compatibility
- [GEN] Cleanly no‑op OAI‑only knobs for other providers to keep APIClient stable.

## B) Cross‑Penguin integration (outside `openai.py`)

1) `APIClient`
- [GEN] Thread optional fields down to adapter: `instructions`, `previous_response_id`, `response_format`, `tools`, `tool_choice`, `stream_options`.
- [GEN] When provider==openai & feature enabled, set `instructions` to Penguin’s system prompt for the turn.

2) `ConversationManager`
- [GEN] Persist per‑session provider metadata:
  - `provider_conversation_id` (str | None)
  - `previous_response_id` (str | None)
- [GEN] Expose getters/setters used by APIClient. Ensure these are persisted in session save/load/snapshot/branch flows.
- [GEN] Defaults remain unchanged for non‑OpenAI: if no provider conversation is set, legacy history packing stays active.
- [OAI] On session start (when `use_server_conversation` and provider==openai): call adapter `create_conversation()` with the core system prompt as `instructions` and store the returned id; on session end/cleanup, call `delete_conversation()`.
- [OAI] When the active system prompt changes (see prompting overhaul), call `update_conversation()` to keep provider instructions in sync.

3) Context Window Manager (CWM)
- [GEN] Add a “delta mode” switch: when a provider conversation is active, CWM sends only the current user turn + targeted fresh context (retrieval/tool outputs), not the entire packed history.
- [GEN] Keep all budgeting: what to include/exclude, summarization, safety truncation. Delta mode only changes the assembled payload size and defers long‑term history to provider.

4) Config (`config.yml` and model configs)
- [GEN] Add flags:
  - `model.use_server_conversation` (default false)
  - `model.stream_include_usage` (default true for OpenAI)
  - `model.enable_oai_tools` (default false)
  - `model.response_format` (none | json_schema)
- [FUTURE] `model.zero_retention_mode` (plan only): route via encrypted reasoning items when supported; defaults off.
- [GEN] Document effort‑style vs classic models and the temperature rule.

5) UI / Token telemetry
- [GEN] When `include_usage` is active, propagate usage deltas from stream to the token UI without recomputing on the client.

6) Tests
- [GEN] Extend `penguin/llm/test_openai_adapter.py`:
  - Instructions present and respected.
  - previous_response_id continuity across two turns.
  - effort‑style (gpt‑5/o*) path omits temperature; classic path includes temperature.
  - response_format json schema round‑trip (simple schema) produces valid JSON.
  - tools gated by config (no crash when disabled).
  - 429/5xx retry/backoff behavior and timeout handling.
  - Performance sanity: measure first token latency and total time.

7) Docs
- [GEN] Add a section to README/docs explaining server conversations vs. CWM delta mode, flags, and tradeoffs.
- [GEN] Add adapter setup page: env/config, examples (instructions, previous_response_id, streaming usage, response_format, tools), troubleshooting.

8) Monitoring & Security
- [GEN] Add structured logs (redacted) for request shapes; expose a minimal local metrics view (tokens, latency, error rates).
- [GEN] Add optional privacy mode (future): redact inputs/outputs in logs; plan zero‑retention flag.

9) Community
- [GEN] Prepare a short guide for contributors: how to run tests, model matrix, where to add schemas/tools, how to file issues.

## C) Guardrails and provider‑specificity

- Defaults must remain identical for non‑OpenAI providers. Only enable server conversation + delta mode when:
  1) provider == `openai` and
  2) `use_server_conversation` is true.
- If the provider toggles mid‑session, reset provider metadata (conversation_id, previous_response_id) and fall back to legacy packing for safety.

## D) Open questions / suggestions / concerns

1) Conversation creation lifecycle
- Adopt explicit provider conversation lifecycle: create at session start (with `instructions`), update on system‑prompt changes, delete at session end. Keep a fallback path that uses only `previous_response_id` when creation fails.

2) Data retention / privacy
- If zero‑retention is required, plan a future flag to use encrypted reasoning/context patterns when available; verify support per model/region and document implications.

3) SDK version pin
- Pin `openai` SDK to a version known to support Responses streaming events (`response.output_text.delta`, reasoning delta) to avoid regressions.

4) Rate limits / retries
- Add tenacity/backoff around 429/5xx with idempotent handling for streaming startup and non‑streaming.

5) Tools surface
- If built‑in tools are enabled, how do we bridge tool events into Penguin’s tool bus? Proposal: treat built‑in tools as “external” and only enable for explicit projects; otherwise prefer Penguin tools for consistent auditability.

6) Cross‑provider parity
- For providers without server conversations, keep CWM full‑history mode. Expose a provider capability flag so callers don’t attempt delta mode where unsupported.

Answers:

1. A "create provider conversation" call and store of the id would be better. I wonder if in terms of modularity when it comes to prompting this may be too fixed? Probably not. At least the core system prompt? @penguin_todo_prompting.md 

2. It's an open source project where we assume they're ran locally. But we can add this as a future consideration in the near term. 

3. Sounds good.

4. Sounds good

5. Yes

6. Sounds good. 

---

## E) Minimal rollout plan

1) Adapter first
- Implement `instructions`, `previous_response_id`, `include_usage`, response_format, content parts, effort/temperature branching, and Conversations helpers (create/update/delete) in `openai.py` (many pieces partially present).

2) Threading
- Add optional params through `APIClient` and pull `instructions` from `system_prompt.py` (see `context/penguin_todo_prompting.md` for core prompt source). Wire ConversationManager metadata into APIClient calls.

3) Session metadata
- Add provider conversation metadata to `ConversationManager`. No behavior change yet.

4) Delta mode
- Toggle CWM delta mode only when provider==openai and `use_server_conversation` true. Keep full behavior for others.

5) Tests + docs
- Extend tests; update docs. Default off; announce flag in changelog.


