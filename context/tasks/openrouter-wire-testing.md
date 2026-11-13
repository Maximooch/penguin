# OpenRouter Wire-Level Testing

Status: proposal (2026-10-21)
Related: `testing-pyramid.md` (Phase 3 "provider fake-contract suite", unchecked), `llm-provider-contract.md`, `llm-testing-suite-overhaul.md`

## Why

Three production failures with open-weight models on OpenRouter (DeepSeek V4.1 Flash) in one day, none caught by tests:

1. Catalog `max_completion_tokens` (393216) sent as per-request `max_tokens` → 402 credit-reservation errors. Fixed: catalog ceiling capped at 64K, per-model config wins (`core_runtime/model_runtime.py`).
2. Mid-stream upstream disconnect raised an httpx error with empty `str()` → text classifier fell to RUNTIME → non-retryable. Fixed on the SDK path only (`OpenRouterGateway._describe_unexpected_error`).
3. Genuine "Insufficient credits" 402 → still classified RUNTIME. Not fixed.
4. Agent deleted a temp screenshot it had viewed. `_process_messages_for_vision` built a text fallback, then discarded it, because the "changed" flag only flipped on a successful encode. The raw `image_path` part reached OpenRouter on every later turn, giving a 400, and the session was wedged. Fixed in the OpenRouter and OpenAI adapters.

Root cause of the test gap: **every OpenRouter test fakes above the HTTP layer.**

- `provider_contract_fixtures.py:465` monkeypatches `AsyncOpenAI` with `SimpleNamespace` chunks; with reasoning on, it replaces `_direct_api_call_with_reasoning` wholesale, so the direct-SSE path never runs.
- `test_runtime_stream_retry.py` hands the runtime pre-classified `LLMError`s, skipping classification.
- `test_streaming_provider_replay.py` replays `{content, type}` dicts into `StreamingStateManager`, with no adapter involved.
- Nothing asserts the `max_tokens` actually sent.
- No respx, cassettes, or fake OpenAI-compatible server exists. `httpx.MockTransport` is used only for Link, whose provider accepts `http_client`.

So the tests prove policy given correct classification. They never prove the classification itself, or the request shape.

## What other harnesses do

| Harness | max_tokens default | Stream failure policy | Test layer |
|---|---|---|---|
| Codex (Rust) | never sent | idle timeout 300s; stream retries 5; retryable = disconnect/timeout/5xx; quota & invalid request fatal; server delay hint wins | 4 layers: byte-stream parser units → fake `HttpTransport` (`FlakyTransport`) → wiremock `mount_sse_sequence` with exact call counts → gated raw-TCP streaming server for mid-stream faults |
| OpenCode | provider default | typed `provider-error.ts`: QuotaExceeded/Auth/InvalidRequest fatal; RateLimit/Internal/Transport/incomplete-stream retryable; `x-should-retry` overrides; backoff 2s→10s, 10 tries, Retry-After clamped | `test/lib/sse.ts` builders (`sseEvents`, `sseRaw`); `http-recorder` JSON cassettes incl. OpenRouter reasoning+tool loop |
| Kilo Code | `min(model output, 32_000)` | (OpenCode) | (OpenCode) |
| Roo Code | ≤20% of context window | in-stream `error` chunk → throw, no retry | — |
| Cline | — | buffers each attempt until first real output; silent retry on empty or pre-content socket death; sums usage across attempts | — |
| Goose | — | 402 → CreditsExhausted (fatal); 429 delay from body `metadata.retry_after_seconds` or header, sanitized | raw HTTP/1.1 bytes from a local socket |
| Hermes | — | `FailoverReason` enum incl. billing; on 402 "can only afford N", clamp `max_tokens` to N−64 (floor 512) and retry **once** | — |
| mistral-vibe | omitted | retries only on HTTP status; no mid-stream retry; replays from scratch (duplicates output) | respx + real captured `data:` lines |

Takeaways: Penguin's 64K cap is in line with peers (Kilo 32K, Roo 20%). Codex and OpenCode both treat quota/credits as a **typed, fatal** category. Hermes' clamp-and-retry-once is the best answer to a reservation 402.

## OpenRouter wire facts to encode as fixtures

Source: openrouter.ai/docs (errors, streaming, parameters, reasoning-tokens, provider-routing).

- Pre-generation errors are a real HTTP status with body `{"error":{"code","message","metadata"}}`. 402 credits, 408 timeout, 429 rate limit, 502 model down/bad upstream, 503 no eligible provider.
- Post-200 errors are a `data:` chunk with top-level `error` (e.g. `server_error`, "Provider disconnected unexpectedly"), `choices[0].finish_reason: "error"`, and then the stream ends. It can be the only event.
- openai-python raises `APIError` (not `APIStatusError`, so no `status_code`) for an in-stream error chunk. Classify from `.body["code"]` and `.body["metadata"]`.
- SDK `max_retries` covers only starting the request, never a stream already in progress.
- Keepalive is SSE comment lines (`: OPENROUTER PROCESSING`). The SDK skips them; the direct path must too.
- 402 metadata `limit_source`: `openrouter_credits`, `openrouter_key_limit`, `openrouter_in_flight_budget`. Only the in-flight budget one, with `Retry-After`, is wait-and-retry.
- Omitted `max_tokens` means the provider default. Reasoning tokens count toward `max_tokens`. `finish_reason: "length"` with empty content: retrying does not help.
- The usage chunk arrives just before `[DONE]` and repeats `finish_reason` with an empty delta. It is accounting only.
- Stream `reasoning_details[]` (text/summary/encrypted, indexed) must be replayed in order on the assistant message with tool results.

## Proposal

### 1. Make the adapter injectable (small refactor)

Accept an optional `http_client: httpx.AsyncClient` in `OpenRouterGateway`. Pass it to `AsyncOpenAI(http_client=...)` and use it on the direct path instead of `ConnectionPoolManager` when given. Copy the Link provider's existing shape (`providers/link/provider.py:113`). Production behaviour is unchanged.

### 2. Wire-level fake: `tests/llm/openrouter_wire/`

- `sse.py`: builders ported from OpenCode `sse.ts`: `chunk_delta`, `chunk_reasoning`, `chunk_reasoning_details`, `chunk_tool_call(index, id, name, args_fragment)`, `chunk_finish(reason, usage)`, `keepalive()`, `error_chunk(code, message, metadata)`, `sse_events(*chunks, done=True)`, `sse_raw(*lines)`.
- `fake_openrouter.py`: `httpx.MockTransport` with:
  - a sequence responder (Nth call → Nth scripted response, exact call-count assertion, like Codex `mount_sse_sequence`);
  - request capture (assert `max_tokens`, headers, `reasoning`, replayed `reasoning_details`);
  - a scripted async byte stream that can yield, raise `httpx.ReadError("")` / `RemoteProtocolError("")`, or wait on an `asyncio.Event` gate (like Codex `StreamingSseChunk`) for idle/watchdog tests without sleeping.
- Run every scenario through **both** the SDK path and the direct-SSE path, which `testing-pyramid.md:491` already requires ("obey the same semantic contract").
- Inject retry budgets, timeouts and the sleep function per test; never use real sleeps.

### 3. Fixture matrix (each row = one regression, red first)

| # | Scenario | Expected |
|---|---|---|
| 1 | Catalog advertises 393216 output, no config | request `max_tokens` == cap (64K) |
| 2 | 402 "can only afford N" before stream | clamp to N−64 (floor 512), retry once; second 402 → fatal BILLING |
| 3 | 402 `openrouter_credits` "Insufficient credits" | fatal, category BILLING, user-facing "add credits" message, no retry |
| 4 | 402 `openrouter_in_flight_budget` + Retry-After | wait (injected sleep) and retry |
| 5 | 429 with Retry-After / body `retry_after_seconds` | retry after the sanitized delay |
| 6 | 502 / 503 | retryable PROVIDER_UNAVAILABLE |
| 7 | 200 whose only event is an error chunk | classified from `error.code`, retryable if `server_error` |
| 8 | 200, reasoning deltas, then `ReadError("")` | NETWORK, retryable, replayed (no visible text streamed) |
| 9 | 200, visible text, then socket reset, no `[DONE]` | not replayed; partial preserved; clear message |
| 10 | keepalives only, then stall | watchdog fires only if a timeout is configured; otherwise waits |
| 11 | `finish_reason: "length"` with empty content and reasoning tokens | not retried; surfaced as truncation |
| 12 | usage chunk repeating `finish_reason` | single terminal event; usage recorded |
| 13 | interleaved `reasoning_details` + split tool-call deltas | tool args reassembled; details replayed in order next turn |
| 14 | non-stream 200 containing only `error` | classified, not treated as empty success |
| 15 | history contains `{"type":"image_url","image_path":X}` where X was deleted | request has a text placeholder, never a raw `image_path` part (was a 400 "image_url ... got undefined" on 2026-10-21; fixed in both adapters) |

### 4. Classification fixes the matrix will force

- Add `ErrorCategory.BILLING` (fatal). Map 402, `insufficient_quota`, and "insufficient credits" to it in `normalize_error_category`, and pass a category from `_parse_openrouter_error`.
- Route the direct path's generic `except` (`openrouter.py:2196-2210`) through `_describe_unexpected_error`; it still uses `"timeout" in str(e)`.
- Classify in-stream `APIError` from `.body`, not message text.
- Honour `Retry-After` / `metadata.retry_after_seconds`, sanitized and clamped (Goose and OpenCode both do this).
- Implement the 402 reservation clamp-and-retry-once (Hermes).

### 5. Recorded cassettes (later, opt-in)

Record happy-path live responses into JSON cassettes with redaction, OpenCode `http-recorder` style, and fail when a cassette is missing in CI. Use them only for happy paths: vcrpy-style replay loses chunk timing and cannot express mid-stream faults. Live provider tests stay opt-in smoke checks, per `testing-pyramid.md`.

## Separate issue spotted: prefix-cache churn

The same session showed repeated `engine.context.prefix reason=source_changed common_items=2|4` followed by `cache_read=0|8704`. Those calls cost about $0.005–0.0076 each, against about $0.0007 on cache hits. That is roughly a 10x cost multiplier, and it drained the credits faster.

`ContextEpoch.select` (`system/context_epoch.py:34-83`) hashes every earlier message. Likely causes:

- `_handle_image_trimming` replacing old images with placeholders after `read_image` (`context_window.py:692`). The churn lines up with `read_image` calls in the log.
- SYSTEM/CONTEXT messages being sorted ahead of dialog (`conversation.py:510-535`), so a new one lands at index 2–4.

This needs its own investigation.
